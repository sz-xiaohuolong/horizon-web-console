"""保留原始凭据引用的配置读取、校验与原子更新。"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from filelock import Timeout
from pydantic import ValidationError

from .._file_utils import _atomic_write_text
from ..mcp.service import _redact_config
from ..models import Config
from ..processing import ProfileRegistry
from ..storage.manager import _expand_env_vars
from ..run_lock import run_lock

REDACTED = "<redacted>"
ALLOWED_PATCH = {"collection", "processing", "digest", "sources", "wechat"}
SOURCE_NAMES = {"github": "GitHub", "hackernews": "Hacker News", "rss": "RSS", "reddit": "Reddit", "telegram": "Telegram", "twitter": "X / Twitter", "openbb": "OpenBB", "ossinsight": "OSS Insight", "gdelt": "GDELT", "google_news": "Google News"}


def _has_hidden_value(value: Any) -> bool:
    if isinstance(value, str):
        return REDACTED in value or "%3credacted%3e" in value.lower()
    if isinstance(value, dict):
        return any(_has_hidden_value(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_hidden_value(child) for child in value)
    return False


def _previous_item(proposed: Any, previous: list, index: int, *, fallback: bool = True) -> Any:
    if isinstance(proposed, dict):
        for key in ("url", "id", "name", "username", "channel", "subreddit"):
            value = proposed.get(key)
            if value is None:
                continue
            matches = [item for item in previous if isinstance(item, dict) and key in item and value in (item[key], _redact_config(item[key], key))]
            if len(matches) == 1:
                return matches[0]
    if _has_hidden_value(proposed):
        raise HTTPException(422, "无法唯一识别含隐藏凭据的条目，请先在本地配置中为私有订阅设置不同名称。")
    return previous[index] if fallback and index < len(previous) else None


def _restore_hidden(proposed: Any, previous: Any) -> Any:
    if proposed == REDACTED:
        return deepcopy(previous)
    if isinstance(previous, str) and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", previous) and str(proposed).casefold() == str(_expand_env_vars(previous)).casefold():
        return previous
    if isinstance(proposed, dict):
        return {key: _restore_hidden(value, previous.get(key) if isinstance(previous, dict) else None) for key, value in proposed.items()}
    if isinstance(proposed, list):
        old = previous if isinstance(previous, list) else []
        return [_restore_hidden(value, _previous_item(value, old, index)) for index, value in enumerate(proposed)]
    if isinstance(proposed, str) and isinstance(previous, str):
        if proposed == _redact_config(previous) or proposed == REDACTED:
            return previous
        if REDACTED in proposed or "%3credacted%3e" in proposed.lower():
            try:
                old, new = urlsplit(previous), urlsplit(proposed)
                if old.hostname != new.hostname:
                    raise ValueError
                old_query = dict(parse_qsl(old.query, keep_blank_values=True))
                query = [(key, old_query[key] if value == REDACTED and key in old_query else value) for key, value in parse_qsl(new.query, keep_blank_values=True)]
                netloc = old.netloc if REDACTED in new.netloc else new.netloc
                return urlunsplit(new._replace(netloc=netloc, query=urlencode(query)))
            except ValueError:
                raise HTTPException(422, "隐藏的凭据不能移动到其他地址，请保留原始条目。")
    return proposed


def _merge(previous: Any, patch: Any) -> Any:
    if isinstance(previous, dict) and isinstance(patch, dict):
        result = deepcopy(previous)
        for key, value in patch.items():
            result[key] = _merge(previous.get(key), value)
        return result
    return _restore_hidden(patch, previous)


def _check_secrets(previous: Any, proposed: Any, key: str = "") -> None:
    if proposed == previous:
        return
    if isinstance(proposed, dict):
        for child_key, value in proposed.items():
            old = previous.get(child_key) if isinstance(previous, dict) else None
            _check_secrets(old, value, child_key)
    elif isinstance(proposed, list):
        old = previous if isinstance(previous, list) else []
        for index, value in enumerate(proposed):
            _check_secrets(_previous_item(value, old, index), value, key)
    elif isinstance(proposed, str):
        if REDACTED in proposed or "%3credacted%3e" in proposed.lower() or _redact_config(proposed, key) != proposed:
            raise HTTPException(422, "网页不接受凭据修改；请在本地环境变量中维护密钥。")


def _view_values(raw: Any, effective: Any) -> Any:
    if isinstance(raw, dict) and isinstance(effective, dict):
        result = deepcopy(raw)
        result.update({key: _view_values(raw.get(key), value) if key in raw else value for key, value in effective.items()})
        return result
    if isinstance(raw, list) and isinstance(effective, list):
        return [_view_values(raw[index], value) if index < len(raw) else value for index, value in enumerate(effective)]
    if isinstance(raw, str) and isinstance(effective, str):
        return raw
    return effective


def _carry_unknown(previous: Any, proposed: Any, known: Any) -> Any:
    if isinstance(previous, dict) and isinstance(proposed, dict) and isinstance(known, dict):
        result = deepcopy(proposed)
        for key, value in previous.items():
            if key not in known and key not in result:
                result[key] = deepcopy(value)
            elif key in result and key in known:
                result[key] = _carry_unknown(value, result[key], known[key])
        return result
    if isinstance(previous, list) and isinstance(proposed, list) and isinstance(known, list):
        result = []
        for index, value in enumerate(proposed):
            old = _previous_item(value, previous, index, fallback=False)
            old_index = previous.index(old) if old in previous else index
            normalized = known[old_index] if old_index < len(known) else None
            result.append(_carry_unknown(old, value, normalized))
        return result
    return proposed


class ConfigStore:
    def __init__(self, workspace: Path, data_dir: Path, config_path: Path):
        self.workspace, self.data_dir, self.path = workspace, data_dir, config_path

    def read_raw(self) -> dict:
        if not self.path.exists():
            raise HTTPException(422, "配置文件不存在，请先运行 uv run horizon-wizard 完成配置。")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (OSError, ValueError):
            raise HTTPException(422, "配置文件无法读取，请检查本地 JSON 文件。")

    def validate(self, raw: dict) -> tuple[Config, ProfileRegistry]:
        try:
            config = Config.model_validate(_expand_env_vars(raw))
            if not 1 <= config.collection.time_window_hours <= 168:
                raise ValueError("time_window_hours")
            profiles = ProfileRegistry.load(Path(config.processing.profiles_dir).expanduser(), config.processing.default_profile, base_dir=self.workspace)
            profiles.validate_source_references(config.sources.model_dump(mode="json"))
            profiles.validate_digest_references(config.digest)
            for profile in config.processing.profile_settings:
                profiles.get(profile)
            return config, profiles
        except (ValidationError, ValueError, OSError):
            raise HTTPException(422, "配置校验失败，请检查必填字段、数值范围及分类引用。")

    def revision(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def view(self) -> dict:
        raw = self.read_raw()
        config, profiles = self.validate(raw)
        # 使用未展开的源数据覆盖默认值，避免任何环境变量进入响应。
        merged = _view_values(raw, config.model_dump(mode="json"))
        return {"revision": self.revision(), "config": _redact_config(merged), "profiles": [{"id": profile_id, "name": profile.definition.display_names.get("zh", profile.definition.name), "threshold": config.processing.profile_settings.get(profile_id).threshold if profile_id in config.processing.profile_settings else None, "topic_dedup": config.processing.profile_settings.get(profile_id).topic_dedup if profile_id in config.processing.profile_settings else True} for profile_id, profile in ((loaded.id, loaded) for loaded in profiles.profiles)]}

    def patch(self, revision: str, patch: dict) -> dict:
        if not patch or set(patch) - ALLOWED_PATCH:
            raise HTTPException(422, "只允许修改采集、筛选、信息源与微信开关。")
        if "sources" in patch and (not isinstance(patch["sources"], dict) or set(patch["sources"]) - set(SOURCE_NAMES)):
            raise HTTPException(422, "信息源字段无效。")
        if "processing" in patch and (not isinstance(patch["processing"], dict) or set(patch["processing"]) - {"profile_settings", "default_profile"}):
            raise HTTPException(422, "网页仅允许修改默认分类及分类筛选参数。")
        try:
            with run_lock(self.data_dir):
                raw = self.read_raw()
                if revision != self.revision():
                    raise HTTPException(409, "配置已被其他操作更新，请刷新后重试。")
                known = Config.model_validate(_expand_env_vars(raw)).model_dump(mode="json")
                # 视图会补齐并脱敏模型默认值，还原时也必须使用相同基线。
                baseline = _view_values(raw, known)
                updated = _merge(raw, patch)
                # 来源块与可增删的映射使用替换语义，防止删除操作被深合并恢复。
                for section, field in (("digest", "category_groups"), ("digest", "profile_min_items"), ("processing", "profile_settings")):
                    section_patch = patch.get(section)
                    if isinstance(section_patch, dict) and field in section_patch:
                        updated[section][field] = _restore_hidden(section_patch[field], (raw.get(section) or {}).get(field))
                known_sources = known["sources"]
                for source_id, source_patch in (patch.get("sources") or {}).items():
                    previous_source = baseline["sources"].get(source_id)
                    replacement = _restore_hidden(source_patch, previous_source)
                    updated["sources"][source_id] = _carry_unknown(previous_source, replacement, known_sources.get(source_id))
                _check_secrets(baseline, updated)
                self.validate(updated)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                backup = self.path.with_name(f"{self.path.name}.web-{stamp}-{uuid4().hex[:6]}.bak")
                _atomic_write_text(backup, self.path.read_text(encoding="utf-8"))
                _atomic_write_text(self.path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
                return self.view()
        except Timeout:
            raise HTTPException(409, "流水线正在运行，请结束后再修改配置。")

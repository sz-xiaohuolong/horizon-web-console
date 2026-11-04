"""独占后台任务、阶段状态及可重放的脱敏日志。"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from fastapi import HTTPException
from filelock import Timeout
from rich.console import Console

from .._file_utils import _atomic_write_text
from ..ai.tokens import get_usage_snapshot, reset_usage
from ..mcp.run_store import STAGES, RUN_ID_RE
from ..mcp.service import HorizonPipelineService, _redact_config
from ..run_lock import run_lock
from .config import ConfigStore

MAX_LOGS = 2000
MAX_LOG_BYTES = 1_000_000
VALID_STATUS = {"running", "completed", "failed", "cancelled", "interrupted", "unknown"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_text(value: str, secrets: list[str]) -> str:
    value = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", value)
    for secret in secrets:
        if len(secret) >= 4:
            value = value.replace(secret, "<redacted>")
    value = re.sub(r"(?i)(https?://)[^\s/@]+@", r"\1<redacted>@", value)
    value = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1<redacted>", value)
    value = re.sub(r"(?i)([?&](?:api[_-]?key|token|secret|password|signature|key)=)[^\s&#]+", r"\1<redacted>", value)
    return value[:8000]


def config_secrets(value: Any, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [secret for child_key, child in value.items() for secret in config_secrets(child, str(child_key))]
    if isinstance(value, list):
        return [secret for child in value for secret in config_secrets(child, key)]
    if not isinstance(value, str):
        return []
    found = []
    if not key.lower().endswith("_env") and _redact_config(value, key) != value:
        found.append(value)
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"}:
            found.extend(unquote(part) for part in (url.username, url.password) if part)
            found.extend(part for name, part in parse_qsl(url.query) if _redact_config(part, name) != part)
    except ValueError:
        pass
    for line in value.splitlines():
        name, separator, content = line.partition(":")
        if separator and _redact_config(content, name.strip()) != content:
            found.append(content.strip())
    return found


class LogBuffer(io.TextIOBase, logging.Handler):
    def __init__(self, path: Path, secrets: list[str]):
        io.TextIOBase.__init__(self)
        logging.Handler.__init__(self)
        self.path = path
        self.items: deque[dict] = deque(maxlen=MAX_LOGS)
        self.sequence = 0
        self.pending = ""
        self.secrets = sorted(set(value for value in secrets if len(value) >= 4), key=len, reverse=True)
        self.event = asyncio.Event()
        self.load()

    def sanitize(self, value: str) -> str:
        return sanitize_text(value, self.secrets)

    def load(self) -> None:
        if not self.path.exists() or self.path.is_symlink():
            return
        try:
            # 只读取日志尾部，避免异常大文件占用内存。
            with self.path.open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - MAX_LOG_BYTES))
                raw = stream.read().decode("utf-8", errors="replace")
            for line in raw.splitlines():
                try:
                    record = json.loads(line)
                    if isinstance(record, dict) and isinstance(record.get("id"), int):
                        record["message"] = self.sanitize(str(record.get("message", "")))
                        self.items.append(record)
                        self.sequence = max(self.sequence, record["id"])
                except ValueError:
                    continue
        except OSError:
            return

    def add(self, message: str, level: str = "info") -> None:
        message = self.sanitize(message).strip()
        if not message:
            return
        self.sequence += 1
        record = {"id": self.sequence, "time": now(), "level": level, "message": message}
        self.items.append(record)
        encoded = json.dumps(record, ensure_ascii=False) + "\n"
        if self.path.exists() and self.path.stat().st_size + len(encoded.encode("utf-8")) > MAX_LOG_BYTES:
            lines = [json.dumps(item, ensure_ascii=False) + "\n" for item in self.items]
            size = sum(len(line.encode("utf-8")) for line in lines)
            while lines and size > MAX_LOG_BYTES:
                size -= len(lines.pop(0).encode("utf-8"))
            _atomic_write_text(self.path, "".join(lines))
        else:
            with self.path.open("a", encoding="utf-8") as stream:
                os.chmod(self.path, 0o600)
                stream.write(encoded)
        self.event.set()

    def write(self, value: str) -> int:
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.add(line)
        if len(self.pending) > 8000:
            self.add(self.pending)
            self.pending = ""
        return len(value)

    def flush(self) -> None:
        if self.pending:
            self.add(self.pending)
            self.pending = ""

    def emit(self, record: logging.LogRecord) -> None:
        self.add(record.getMessage(), record.levelname.lower())


class RunManager:
    def __init__(self, service: HorizonPipelineService, configs: ConfigStore):
        self.service, self.configs = service, configs
        self.task: asyncio.Task | None = None
        self.active_id: str | None = None
        self.file_lock = None
        self.buffers: dict[str, LogBuffer] = {}
        self._console = service.console

    def _secrets(self) -> list[str]:
        values = [value for key, value in os.environ.items() if re.search(r"(?i)(token|secret|password|api.?key)", key)]
        try:
            raw_config = self.configs.read_raw()
            values.extend(config_secrets(raw_config))
            raw = json.dumps(raw_config)
            values.extend(os.getenv(key, "") for key in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", raw))
            session_path = self.configs.data_dir / "wechat_session.json"
            if session_path.exists():
                session = json.loads(session_path.read_text())
                values.extend(str(session.get(key, "")) for key in ("bot_token", "context_token"))
        except (OSError, ValueError, HTTPException):
            pass
        return sorted(set(value for value in values if len(value) >= 4), key=len, reverse=True)

    def safe_run(self, run_id: str, artifact: str | None = None) -> Path:
        store = self.service.run_store
        if not RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
            raise HTTPException(404, "运行工件不存在。")
        directory = store.root / run_id
        if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != store.root.resolve():
            raise HTTPException(404, "运行工件不存在或路径不安全。")
        for filename in ("meta.json", artifact):
            if filename is None:
                continue
            target = directory / filename
            if target.is_symlink() or target.resolve().parent != directory.resolve():
                raise HTTPException(404, "运行工件不存在或路径不安全。")
        return directory

    def logs(self, run_id: str) -> LogBuffer:
        directory = self.safe_run(run_id, "web-logs.jsonl")
        if run_id not in self.buffers:
            self.buffers[run_id] = LogBuffer(directory / "web-logs.jsonl", self._secrets())
            # 历史查询不无限积累缓存；活动任务的缓冲始终保留。
            if len(self.buffers) > 16:
                oldest = next(key for key in self.buffers if key not in {self.active_id, run_id})
                self.buffers.pop(oldest)
        return self.buffers[run_id]

    def busy(self) -> bool:
        if self.active_id:
            return True
        try:
            with run_lock(self.configs.data_dir):
                return False
        except Timeout:
            return True

    def _entries(self, limit: int = 10000) -> list[dict]:
        store = self.service.run_store
        entries = []
        for directory in store.root.iterdir():
            if not directory.is_dir() or directory.is_symlink() or not RUN_ID_RE.fullmatch(directory.name) or ".." in directory.name:
                continue
            try:
                self.safe_run(directory.name, "meta.json")
                meta = store.load_meta(directory.name)
                if not isinstance(meta, dict):
                    continue
                entries.append({"run_id": directory.name, "meta": meta})
            except (OSError, ValueError, TypeError, HTTPException):
                continue
        entries.sort(key=lambda entry: str(entry["meta"].get("updated_at") or entry["meta"].get("created_at") or ""), reverse=True)
        return entries[:limit]

    def _scrub(self, value, secrets=None):
        secrets = secrets if secrets is not None else self._secrets()
        if isinstance(value, str):
            return sanitize_text(value, secrets)
        if isinstance(value, dict):
            return {key: self._scrub(item, secrets) for key, item in value.items()}
        if isinstance(value, list):
            return [self._scrub(item, secrets) for item in value]
        return value

    def list_runs(self, limit: int = 100) -> list[dict]:
        entries = self._entries(limit)
        result = []
        for entry in entries:
            try:
                result.append(self.get_run(entry["run_id"]))
            except (ValueError, OSError, TypeError, HTTPException):
                continue
        return result

    def get_run(self, run_id: str) -> dict:
        store = self.service.run_store
        self.safe_run(run_id, "meta.json")
        meta = store.load_meta(run_id)
        if not isinstance(meta, dict):
            raise ValueError("运行元数据无效")
        status = meta.get("status", "unknown")
        if not isinstance(status, str) or status not in VALID_STATUS:
            status = "unknown"
        counts, stages = {}, {}
        for stage in STAGES:
            self.safe_run(run_id, STAGES[stage])
            stages[stage] = store.has_stage(run_id, stage)
            counts[stage] = meta.get(f"{stage}_count")
            if counts[stage] is None and stages[stage]:
                try:
                    payload = store.load_items(run_id, stage)
                    counts[stage] = len(payload) if isinstance(payload, list) else None
                except (OSError, ValueError):
                    counts[stage] = None
        token_info = meta.get("tokens")
        return self._scrub({"run_id": run_id, "status": status, "current_stage": meta.get("current_stage"), "created_at": meta.get("created_at"), "updated_at": meta.get("updated_at", meta.get("created_at")), "duration_seconds": meta.get("duration_seconds"), "tokens": token_info if isinstance(token_info, dict) else None, "counts": counts, "stage_durations": meta.get("stage_durations", {}), "error": meta.get("error"), "meta": _redact_config(meta), "stages": stages})

    def recover(self) -> None:
        # 另一个进程持锁时，不改写它正在维护的状态。
        if self.busy():
            return
        for entry in self._entries(10000):
            meta = entry["meta"]
            if meta.get("web_managed") and meta.get("status") == "running":
                self.service.run_store.update_meta(entry["run_id"], {"status": "interrupted", "error": "服务曾中断，任务未完成。", "current_stage": None})

    async def start(self, hours: int, enrich: bool, languages: list[str] | None) -> dict:
        if self.active_id:
            raise HTTPException(409, "已有流水线正在运行。")
        config, _ = self.configs.validate(self.configs.read_raw())
        self.file_lock = run_lock(self.configs.data_dir)
        try:
            self.file_lock.acquire(timeout=0)
        except Timeout:
            self.file_lock = None
            raise HTTPException(409, "命令行或另一个控制台正在运行流水线。")
        try:
            run_id = self.service.run_store.create_run()
            self.active_id = run_id
            self.service.run_store.update_meta(run_id, {"web_managed": True, "status": "running", "current_stage": "raw", "hours": hours, "stage_durations": {}, "error": None})
            self.task = asyncio.create_task(self._execute(run_id, hours, enrich, languages or list(config.ai.languages)))
            return self.get_run(run_id)
        except BaseException:
            self.active_id = None
            self.file_lock.release()
            self.file_lock = None
            raise

    async def _execute(self, run_id: str, hours: int, enrich: bool, languages: list[str]) -> None:
        store = self.service.run_store
        log = self.logs(run_id)
        self.service.console = Console(file=log, force_terminal=False, color_system=None, width=120)
        app_logger = logging.getLogger("src")
        app_logger.addHandler(log)
        old_level = app_logger.level
        app_logger.setLevel(logging.INFO)
        started = time.monotonic()
        durations = {}
        reset_usage()
        status, error = "completed", None
        kwargs = {"horizon_path": str(self.configs.workspace), "config_path": str(self.configs.path)}

        async def stage(name, operation):
            store.update_meta(run_id, {"current_stage": name})
            log.add({"raw": "开始抓取信息源", "scored": "开始分类与评分", "filtered": "开始筛选与去重", "enriched": "开始深度补充", "summary": "开始生成速递"}[name])
            timer = time.monotonic()
            try:
                return await operation()
            finally:
                durations[name] = round(time.monotonic() - timer, 3)
                store.update_meta(run_id, {"stage_durations": durations})

        try:
            log.add("任务已启动；仅保存摘要，不发送外部通知。")
            fetched = await stage("raw", lambda: self.service.fetch_items(run_id=run_id, hours=hours, **kwargs))
            if fetched.get("fetch_status") == "failure":
                raise RuntimeError("所有信息源抓取失败。")
            if fetched["fetched"]:
                await stage("scored", lambda: self.service.score_items(run_id=run_id, **kwargs))
                filtered = await stage("filtered", lambda: self.service.filter_items(run_id=run_id, **kwargs))
                summary_stage = "filtered"
                if enrich and filtered["kept"] > 0:
                    result = await stage("enriched", lambda: self.service.enrich_items(run_id=run_id, **kwargs))
                    if result.get("status") != "failure":
                        summary_stage = "enriched"
                    else:
                        log.add("深度补充失败，将使用筛选结果生成速递。", "warning")
            else:
                log.add("本次没有抓取到条目，将保存空结果速递。")
                summary_stage = "raw"
            for language in languages:
                await stage("summary", lambda language=language: self.service.generate_summary(run_id=run_id, language=language, source_stage=summary_stage, save_to_horizon_data=True, **kwargs))
            log.add("任务已完成，速递已保存。")
        except asyncio.CancelledError:
            status, error = "cancelled", "任务已取消。"
            log.add(error, "warning")
        except Exception as exc:
            status = "failed"
            error = "任务执行失败，请查看日志并检查信息源或模型配置。"
            log.add(f"{error} {log.sanitize(str(exc))}", "error")
        finally:
            usage = get_usage_snapshot()
            try:
                store.update_meta(run_id, {"status": status, "current_stage": None, "duration_seconds": round(time.monotonic() - started, 3), "tokens": {"input": usage.total_input_tokens, "output": usage.total_output_tokens, "total": usage.total_tokens}, "error": error, "finished_at": now(), "stage_durations": durations})
                log.flush()
            finally:
                log.event.set()
                app_logger.removeHandler(log)
                app_logger.setLevel(old_level)
                self.service.console = self._console
                self.active_id = None
                if self.file_lock:
                    self.file_lock.release()
                    self.file_lock = None

    async def cancel(self, run_id: str) -> dict:
        self.get_run(run_id)
        if run_id != self.active_id or self.task is None:
            raise HTTPException(409, "该任务当前未在此控制台运行。")
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            # 尚未获得执行时隙的任务也必须落盘并释放锁。
            self.service.run_store.update_meta(run_id, {"status": "cancelled", "current_stage": None, "error": "任务已取消。", "finished_at": now()})
            self.active_id = None
            if self.file_lock:
                self.file_lock.release()
                self.file_lock = None
        return self.get_run(run_id)

    async def shutdown(self) -> None:
        if self.active_id and self.task:
            await self.cancel(self.active_id)

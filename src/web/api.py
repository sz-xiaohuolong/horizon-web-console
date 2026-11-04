"""将 Horizon 服务适配为仅供本机使用的 HTTP API。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import html
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..mcp.errors import HorizonMcpError
from ..mcp.horizon_adapter import get_enabled_sources, load_environment
from ..mcp.run_store import STAGES
from ..mcp.service import HorizonPipelineService, _redact_config
from ..models import SOURCE_REGISTRY
from ..services.wechat import WeChatSession, CONTEXT_MESSAGE_BUDGET
from .config import ConfigStore, SOURCE_NAMES
from .runtime import RunManager

SUMMARY_RE = re.compile(r"^horizon-(\d{4}-\d{2}-\d{2})-([A-Za-z0-9_-]+)\.md$")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: int = Field(default=24, ge=1, le=168)
    enrich: bool = True
    languages: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @field_validator("languages")
    @classmethod
    def valid_languages(cls, value):
        if value and any(not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", language) for language in value):
            raise ValueError("语言标识无效")
        return list(dict.fromkeys(value)) if value else value


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1)
    patch: dict[str, Any]


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation: str = Field(pattern=r"^[a-f0-9]{64}$")


def create_app(*, workspace: Path | str | None = None, data_dir: Path | str | None = None, config_path: Path | str | None = None, runs_dir: Path | str | None = None, service: HorizonPipelineService | None = None, wechat_client_factory=None, static_dir: Path | str | None = None) -> FastAPI:
    root = Path(workspace or Path(__file__).resolve().parents[2]).expanduser().resolve()
    data = Path(data_dir or root / "data").expanduser().resolve()
    config_file = Path(config_path or data / "config.json").expanduser().resolve()
    load_environment(root)
    configs = ConfigStore(root, data, config_file)
    pipeline = service or HorizonPipelineService(runs_root=Path(runs_dir or data / "mcp-runs"))
    manager = RunManager(pipeline, configs)
    # 微信模块只在显式操作时访问外部网络。
    from .wechat import WeChatManager
    wechat = WeChatManager(configs, client_factory=wechat_client_factory)

    @asynccontextmanager
    async def lifespan(app):
        manager.recover()
        yield
        await manager.shutdown()
        await wechat.shutdown()

    app = FastAPI(title="Horizon 本地控制台", version="1.0.0", lifespan=lifespan, docs_url=None, openapi_url="/api/openapi.json", redoc_url=None)
    app.state.manager, app.state.configs, app.state.wechat = manager, configs, wechat

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            hostname = urlsplit(f"http://{host}").hostname
        except ValueError:
            hostname = None
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "控制台仅接受本机地址。"}, status_code=400)
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                valid_origin = parsed.scheme in {"http", "https"} and parsed.netloc == host
            except ValueError:
                valid_origin = False
            if not valid_origin:
                return JSONResponse({"detail": "此操作必须来自控制台同源页面。"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (request.headers.get("x-horizon-request") != "1" or not origin):
            return JSONResponse({"detail": "写操作需要同源控制台请求。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "请求参数无效，请检查必填项、数值范围与字段格式。"}, status_code=422)

    @app.exception_handler(HorizonMcpError)
    async def horizon_error(request, exc):
        missing = exc.code in {"HZ_RUN_NOT_FOUND", "HZ_STAGE_NOT_FOUND", "HZ_SUMMARY_NOT_FOUND"}
        return JSONResponse({"detail": "所选工件尚未生成或已不存在。" if missing else "Horizon 操作失败，请检查本地配置。", "code": exc.code}, status_code=404 if missing else 422)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request, exc):
        return JSONResponse({"detail": "所选工件尚未生成或已不存在。"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid_identifier(request, exc):
        return JSONResponse({"detail": "标识或工件内容无效。"}, status_code=422)

    def summary_files():
        directory = (data / "summaries").resolve()
        if not directory.is_dir():
            return []
        return sorted([path for path in directory.glob("horizon-*.md") if SUMMARY_RE.fullmatch(path.name) and not path.is_symlink() and path.resolve().parent == directory], reverse=True)

    def read_summary(summary_id: str):
        match = SUMMARY_RE.fullmatch(summary_id)
        path = data / "summaries" / summary_id
        if not match or path not in summary_files():
            raise HTTPException(404, "速递不存在。")
        content = path.read_bytes()
        return {
            "id": summary_id, "date": match[1], "language": match[2],
            "markdown": content.decode("utf-8"), "size": len(content),
            "revision": hashlib.sha256(content).hexdigest(),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }

    def get_wechat_status():
        enabled = False
        try:
            raw = configs.read_raw()
            enabled = bool((raw.get("wechat") or {}).get("enabled", False))
        except HTTPException:
            pass
        try:
            session = WeChatSession.load(data / "wechat_session.json")
            return {"enabled": enabled, "connected": session is not None, "ready": bool(session and session.ready), "remaining_budget": session.remaining_budget if session else None, "budget_limit": CONTEXT_MESSAGE_BUDGET, "estimated": True, "context_updated_at": session.context_updated_at if session else None, "logged_in_at": session.logged_in_at if session else None, "message": "额度为本地估算。" if session else "尚未连接，请扫码登录。"}
        except (ValueError, TypeError, OSError):
            return {"enabled": enabled, "connected": False, "ready": False, "remaining_budget": None, "budget_limit": CONTEXT_MESSAGE_BUDGET, "estimated": True, "message": "微信会话无法读取，请重新扫码登录。"}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/overview")
    async def overview():
        runs = manager.list_runs(10000)
        warnings = []
        sources, ai = [], {"provider": "", "model": "", "configured": False}
        try:
            config, _ = configs.validate(configs.read_raw())
            enabled = get_enabled_sources(config)
            for source_id, definition in SOURCE_REGISTRY.items():
                source_config = getattr(config.sources, definition.config_field, None)
                if definition.config_is_list:
                    count = len(source_config or [])
                elif definition.item_fields:
                    count = sum(len(getattr(source_config, field, []) or []) for field in definition.item_fields) if source_config else 0
                else:
                    count = 1 if source_config else 0
                sources.append({"id": source_id, "name": SOURCE_NAMES[source_id], "enabled": source_id in enabled, "count": count})
            configured = config.ai.provider.value == "ollama" or bool(os.getenv(config.ai.api_key_env))
            if config.ai.provider.value == "openai-chatgpt":
                from ..ai.chatgpt_auth import ChatGPTAuth
                try:
                    configured = bool(ChatGPTAuth().status(config.ai.chatgpt_account).get("plan_usage"))
                except (ValueError, OSError):
                    configured = False
            ai = {"provider": config.ai.provider.value, "model": config.ai.model, "configured": configured}
            if not configured:
                warnings.append("模型凭据尚未就绪，请在本地环境中完成配置。")
        except HTTPException as exc:
            warnings.append(str(exc.detail))
        active = manager.get_run(manager.active_id) if manager.active_id else None
        busy = manager.busy()
        if busy and not active:
            warnings.append("另一个进程正在运行流水线，暂时无法启动任务或保存配置。")
        return {"active_run": active, "latest_run": runs[0] if runs else None, "run_count": len(runs), "summary_count": len(summary_files()), "sources": sources, "ai": ai, "wechat": get_wechat_status(), "scheduler": {"managed": False, "message": "外部调度由系统管理，控制台不接管定时任务。"}, "warnings": warnings, "busy": busy}

    @app.get("/api/runs")
    async def list_runs(limit: int = Query(100, ge=1, le=1000)):
        items = manager.list_runs(limit)
        return {"items": items, "count": len(items)}

    @app.post("/api/runs", status_code=202)
    async def start_run(body: RunRequest):
        return await manager.start(body.hours, body.enrich, body.languages)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return manager.get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        return await manager.cancel(run_id)

    @app.get("/api/runs/{run_id}/stages/{stage}")
    async def stage_items(run_id: str, stage: Literal["raw", "scored", "filtered", "enriched"], offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), q: str = Query("", max_length=200), source: str = "", disposition: Literal["all", "kept", "removed"] = "all", min_score: float | None = Query(None, ge=0, le=10)):
        store = pipeline.run_store
        manager.safe_run(run_id, STAGES[stage])
        items = store.load_items(run_id, stage)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise HTTPException(422, "阶段工件内容无效，请检查本地文件。")
        manager.safe_run(run_id, STAGES["filtered"])
        filtered_ids = {item["id"] for item in store.load_items(run_id, "filtered")} if store.has_stage(run_id, "filtered") else None
        source_counts = dict(Counter(item.get("source_type", "unknown") for item in items))
        enriched = []
        for item in items:
            item = dict(item)
            retained = item.get("id") in filtered_ids if filtered_ids is not None else None
            item["retained"] = retained
            item["exclusion_reason"] = "推断：该条目未出现在筛选工件中，可能因评分、去重或分类配额被移除。" if retained is False else None
            score = ((item.get("processing") or {}).get("analysis") or {}).get("score")
            if min_score is not None and (not isinstance(score, (int, float)) or score < min_score):
                continue
            if source and item.get("source_type") != source:
                continue
            if q and q.casefold() not in json.dumps(item, ensure_ascii=False).casefold():
                continue
            if disposition == "kept" and retained is not True or disposition == "removed" and retained is not False:
                continue
            enriched.append(item)
        distribution = {"0-2": 0, "3-4": 0, "5-6": 0, "7-8": 0, "9-10": 0, "unscored": 0}
        for item in enriched:
            analysis = (item.get("processing") or {}).get("analysis") or {}
            score = analysis.get("score")
            if not isinstance(score, (int, float)):
                bucket = "unscored"
            else:
                bucket = "0-2" if score < 3 else "3-4" if score < 5 else "5-6" if score < 7 else "7-8" if score < 9 else "9-10"
            distribution[bucket] += 1
        return {"items": _redact_config(enriched[offset:offset + limit]), "total": len(enriched), "offset": offset, "limit": limit, "score_distribution": distribution, "source_counts": source_counts}

    @app.get("/api/runs/{run_id}/summary")
    async def run_summary(run_id: str, language: str = Query("zh", pattern=r"^[A-Za-z0-9_-]{1,20}$")):
        manager.safe_run(run_id, f"summary-{language}.md")
        return {"run_id": run_id, "language": language, "markdown": pipeline.run_store.load_summary(run_id, language)}

    @app.get("/api/runs/{run_id}/logs")
    async def run_logs(run_id: str):
        return {"items": list(manager.logs(run_id).items)}

    @app.get("/api/runs/{run_id}/logs/stream")
    async def stream_logs(run_id: str, request: Request):
        log = manager.logs(run_id)
        try:
            after = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(422, "日志游标无效。")

        async def events():
            cursor = after
            while True:
                log.event.clear()
                for record in list(log.items):
                    if record["id"] > cursor:
                        cursor = record["id"]
                        yield f"id: {cursor}\nevent: log\ndata: {json.dumps(record, ensure_ascii=False)}\n\n"
                if manager.get_run(run_id)["status"] != "running":
                    yield 'event: done\ndata: {}\n\n'
                    break
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(log.event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})

    @app.get("/api/summaries")
    async def summaries():
        items = []
        for path in summary_files():
            item = read_summary(path.name)
            markdown = item.pop("markdown")
            item["title"] = next((line.lstrip("# ").strip() for line in markdown.splitlines() if line.strip()), "Horizon 速递")[:160]
            items.append(item)
        items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        return {"items": items, "count": len(items)}

    @app.get("/api/summaries/{summary_id}")
    async def summary(summary_id: str):
        return read_summary(summary_id)

    @app.get("/api/summaries/{summary_id}/wechat")
    async def preview_delivery(summary_id: str):
        return wechat.preview_delivery(read_summary(summary_id))

    @app.post("/api/summaries/{summary_id}/wechat")
    async def send_delivery(summary_id: str, body: DeliveryRequest):
        return await wechat.send_summary(lambda: read_summary(summary_id), body.revision, body.confirmation)

    @app.get("/api/config")
    async def config_view():
        return configs.view()

    @app.patch("/api/config")
    async def config_patch(body: ConfigPatch):
        if manager.active_id:
            raise HTTPException(409, "流水线正在运行，请结束后再保存配置。")
        return configs.patch(body.revision, body.patch)

    @app.get("/api/wechat")
    async def wechat_status():
        return get_wechat_status()

    @app.post("/api/wechat/login")
    async def wechat_login():
        if manager.busy():
            raise HTTPException(409, "流水线正在运行，请结束后再更改微信连接。")
        return await wechat.start()

    @app.get("/api/wechat/login/{login_id}")
    async def wechat_login_status(login_id: str):
        return wechat.get(login_id)

    @app.post("/api/wechat/login/{login_id}/cancel")
    async def wechat_login_cancel(login_id: str):
        return await wechat.cancel(login_id)

    @app.post("/api/wechat/login/{login_id}/verify")
    async def wechat_verify(login_id: str, body: VerificationRequest):
        return wechat.verify(login_id, body.code)

    @app.post("/api/wechat/refresh")
    async def wechat_refresh():
        if manager.busy():
            raise HTTPException(409, "流水线正在运行，请结束后再刷新微信会话。")
        await wechat.refresh()
        return get_wechat_status()

    @app.get("/api/docs", response_class=HTMLResponse, include_in_schema=False)
    async def api_docs():
        paths = app.openapi()["paths"]
        rows = "".join(f"<tr><td>{html.escape(method.upper())}</td><td><code>{html.escape(path)}</code></td></tr>" for path, methods in paths.items() if path.startswith("/api/") for method in methods if method in {"get", "post", "patch"})
        return HTMLResponse("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Horizon 接口目录</title><style>:root{--font:system-ui,sans-serif;--line:#ddd;--accent:#087b50}body{font:16px var(--font);max-width:1000px;margin:48px auto;padding:0 24px;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid var(--line)}code{overflow-wrap:anywhere}a{color:var(--accent)}</style><h1>Horizon 本地接口目录</h1><p>写操作需要同源 Origin 和 X-Horizon-Request: 1。凭据始终由本地配置维护。</p><p><a href='/api/openapi.json'>查看完整 OpenAPI 契约</a>　<a href='/'>返回控制台</a></p><table><thead><tr><th>方法</th><th>接口路径</th></tr></thead><tbody>" + rows + "</tbody></table></html>")

    directory = Path(static_dir or root / "web/dist").resolve()
    if (directory / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=directory / "assets"), name="assets")

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "接口不存在。")
        target = (directory / path).resolve()
        if path and target.is_relative_to(directory) and target.is_file():
            return FileResponse(target)
        if (directory / "index.html").is_file():
            return FileResponse(directory / "index.html")
        return JSONResponse({"detail": "前端尚未构建，请运行 npm --prefix web ci && npm --prefix web run build。"}, status_code=503)

    return app

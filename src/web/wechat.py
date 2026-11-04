"""微信扫码状态机与用户确认后的报告投递。"""

from __future__ import annotations

import asyncio
import base64
import io
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from filelock import Timeout

from ..run_lock import run_lock
from ..services.wechat import ILinkClient, ILINK_BASE_URL, WeChatSession, WeChatNotifier, plan_chunks
from ..models import WeChatConfig
from ..storage.manager import StorageManager, _expand_env_vars
from .._file_utils import _atomic_write_text
from .config import ConfigStore


class WeChatManager:
    def __init__(self, configs: ConfigStore, client_factory=None):
        self.configs = configs
        self.factory = client_factory or ILinkClient
        self.sessions: dict[str, dict] = {}
        self.active_id: str | None = None
        self.task: asyncio.Task | None = None
        self.file_lock = None
        self.verification: str | None = None

    def get(self, login_id: str) -> dict:
        if login_id not in self.sessions:
            raise HTTPException(404, "扫码会话不存在，请重新获取二维码。")
        return dict(self.sessions[login_id])

    def _update(self, login_id: str, status: str, message: str, **extra):
        self.sessions[login_id].update(status=status, message=message, **extra)

    def _acquire(self):
        lock = run_lock(self.configs.data_dir)
        try:
            lock.acquire(timeout=0)
        except Timeout:
            raise HTTPException(409, "其他任务正在使用本地数据，请稍后重试。")
        return lock

    async def start(self) -> dict:
        if self.active_id:
            return self.get(self.active_id)
        self.file_lock = self._acquire()
        try:
            client = self.factory()
            qr = await client.get_bot_qrcode([])
            if not qr.get("qrcode") or not qr.get("qrcode_img_content"):
                raise ValueError
            import qrcode
            from qrcode.image.svg import SvgPathImage
            output = io.BytesIO()
            qrcode.make(qr["qrcode_img_content"], image_factory=SvgPathImage, border=2).save(output)
            data_url = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii")
            login_id = uuid4().hex
            self.active_id = login_id
            self.verification = None
            self.sessions[login_id] = {"login_id": login_id, "status": "waiting", "qr_data_url": data_url, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=480)).isoformat(), "message": "请使用微信扫描二维码，并在手机上确认。", "verify_code": False}
            while len(self.sessions) > 8:
                self.sessions.pop(next(iter(self.sessions)))
            self.task = asyncio.create_task(self._poll(login_id, client, qr["qrcode"]))
            return self.get(login_id)
        except BaseException as exc:
            self.file_lock.release()
            self.file_lock = None
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise HTTPException(502, "无法获取微信二维码，请检查网络后重试。")

    async def _poll(self, login_id: str, client, qrcode: str):
        base_url = ILINK_BASE_URL
        deadline = asyncio.get_running_loop().time() + 480
        try:
            while asyncio.get_running_loop().time() < deadline:
                result = await client.get_qrcode_status(qrcode, verify_code=self.verification, base_url=base_url)
                status = result.get("status", "wait")
                if status in {"confirmed", "binded_redirect"}:
                    self._update(login_id, "confirmed", "手机已确认，正在保存连接。", verify_code=False)
                    session_path = self.configs.data_dir / "wechat_session.json"
                    try:
                        old = WeChatSession.load(session_path)
                    except (OSError, ValueError, TypeError):
                        old = None
                    if status == "binded_redirect" and old and not result.get("bot_token"):
                        session = old
                    else:
                        if not result.get("bot_token"):
                            raise ValueError
                        session = WeChatSession(bot_token=result["bot_token"], base_url=(result.get("baseurl") or ILINK_BASE_URL).rstrip("/"), bot_id=result.get("ilink_bot_id", ""), user_id=result.get("ilink_user_id", ""), logged_in_at=datetime.now(timezone.utc).isoformat())
                        session.save(session_path)
                    if session.ready:
                        self._update(login_id, "ready", "微信已连接，可以接收速递。")
                        return
                    self._update(login_id, "waiting_message", "连接已保存。请先在微信中给机器人发一条消息，以启用推送。", qr_data_url=None)
                    while asyncio.get_running_loop().time() < deadline:
                        session = await self._refresh_unlocked(timeout=3)
                        if session and session.ready:
                            self._update(login_id, "ready", "微信会话已就绪。回复额度为本地估算。")
                            return
                        await asyncio.sleep(1)
                    self._update(login_id, "expired", "等待消息超时。连接已保留，发消息后点击刷新会话即可。")
                    return
                if status == "scaned":
                    self._update(login_id, "scanned", "二维码已扫描，请在手机上确认。")
                elif status == "scaned_but_redirect":
                    host = result.get("redirect_host")
                    if host:
                        base_url = host if host.startswith("http") else f"https://{host}"
                elif status == "need_verifycode":
                    self._update(login_id, "scanned", "请输入微信中显示的验证码。", verify_code=True)
                elif status == "verify_code_blocked":
                    self._update(login_id, "failed", "验证码尝试次数过多，请稍后重新扫码。", verify_code=False)
                    return
                elif status == "expired":
                    self._update(login_id, "expired", "二维码已过期，请重新获取。", qr_data_url=None)
                    return
                await asyncio.sleep(1)
            self._update(login_id, "expired", "扫码已超时，请重新获取二维码。", qr_data_url=None)
        except asyncio.CancelledError:
            self._update(login_id, "cancelled", "扫码已取消。", qr_data_url=None, verify_code=False)
        except Exception:
            self._update(login_id, "failed", "微信连接失败，请检查网络并重新扫码。", qr_data_url=None, verify_code=False)
        finally:
            self.active_id = None
            self.verification = None
            if self.file_lock:
                self.file_lock.release()
                self.file_lock = None

    def verify(self, login_id: str, code: str) -> dict:
        state = self.get(login_id)
        if login_id != self.active_id or not state.get("verify_code"):
            raise HTTPException(409, "当前扫码会话不需要验证码。")
        if not code.strip() or len(code) > 32:
            raise HTTPException(422, "验证码格式无效。")
        self.verification = code.strip()
        self.sessions[login_id]["verify_code"] = False
        self.sessions[login_id]["message"] = "正在验证，请稍候。"
        return self.get(login_id)

    async def cancel(self, login_id: str) -> dict:
        self.get(login_id)
        if login_id == self.active_id and self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self._update(login_id, "cancelled", "扫码已取消。", qr_data_url=None, verify_code=False)
                self.active_id = None
                self.verification = None
                if self.file_lock:
                    self.file_lock.release()
                    self.file_lock = None
        return self.get(login_id)

    async def _refresh_unlocked(self, timeout=3):
        path = self.configs.data_dir / "wechat_session.json"
        session = WeChatSession.load(path)
        if session is None:
            raise HTTPException(409, "请先扫码连接微信。")
        client = self.factory(session.base_url, session.bot_token)
        result = await client.get_updates(session.get_updates_buf, timeout=timeout)
        changed = False
        for message in result.get("msgs", []):
            if isinstance(message, dict) and session.update_from_message(message):
                changed = True
        cursor = result.get("get_updates_buf")
        if cursor and cursor != session.get_updates_buf:
            session.get_updates_buf, changed = cursor, True
        if changed:
            session.save(path)
        return session

    async def refresh(self):
        if self.active_id:
            return
        lock = self._acquire()
        try:
            await self._refresh_unlocked()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "无法刷新微信会话，请检查网络或重新扫码。")
        finally:
            lock.release()

    async def shutdown(self):
        if self.active_id:
            await self.cancel(self.active_id)

    def delivery_plan(self, summary: dict) -> dict:
        config = WeChatConfig.model_validate(_expand_env_vars(self.configs.read_raw().get("wechat") or {}))
        try:
            session = WeChatSession.load(self.configs.data_dir / "wechat_session.json")
        except (OSError, ValueError, TypeError):
            raise HTTPException(409, "微信会话无法读取，请重新扫码连接。")
        remaining = session.remaining_budget if session else 0
        chunks = plan_chunks(summary["markdown"], config.chunk_size, summary["language"], remaining)
        identity = [session.base_url, session.bot_id, session.user_id] if session else []
        key = hashlib.sha256(json.dumps([identity, summary["revision"]]).encode()).hexdigest()
        confirmation = hashlib.sha256(json.dumps([
            key, session.context_token if session else "", remaining, config.model_dump(), chunks,
        ], sort_keys=True).encode()).hexdigest()
        receipt_path = self.configs.data_dir / "wechat-deliveries" / f"{key}.json"
        reason = ""
        if receipt_path.exists():
            reason = "此版本已发起过推送，为避免重复消息不会再次发送。"
        elif not config.enabled:
            reason = "请先在配置 → 服务配置中启用微信推送并保存。"
        elif config.languages and summary["language"] not in config.languages:
            reason = "此报告语言不在微信推送配置范围内，请在本地配置中调整 languages。"
        elif not session or not session.ready:
            reason = "请先到微信连接页扫码，给机器人发送一条消息，再刷新消息上下文。"
        elif not chunks:
            reason = "报告没有可发送的正文。"
        elif len(chunks) > remaining:
            reason = "估算额度不足，请给机器人发一条消息并在微信连接页刷新；超过十段的报告请下载阅读。"
        receipt = None
        if receipt_path.exists():
            try:
                saved = json.loads(receipt_path.read_text())
                receipt = {key: saved[key] for key in ("status", "chunks_sent", "message")}
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(409, "发送记录无法读取，为避免重复消息已暂停推送。")
        return {"revision": summary["revision"], "confirmation": confirmation,
                "chunk_count": len(chunks), "remaining_budget": remaining, "estimated": True,
                "can_send": not reason, "reason": reason, "delivery": receipt,
                "_receipt_path": receipt_path, "_config": config}

    def preview_delivery(self, summary: dict) -> dict:
        return {key: value for key, value in self.delivery_plan(summary).items() if not key.startswith("_")}

    async def send_summary(self, read_summary, revision: str, confirmation: str) -> dict:
        lock = self._acquire()
        try:
            summary = read_summary()
            plan = self.delivery_plan(summary)
            if revision != summary["revision"] or confirmation != plan["confirmation"]:
                raise HTTPException(409, "报告或微信会话已变化，请重新预览后确认发送。")
            if not plan["can_send"]:
                raise HTTPException(409, plan["reason"])
            receipt_path = plan["_receipt_path"]
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt = {"status": "pending", "chunks_sent": 0, "message": "推送已发起，结果尚未确认。请先检查微信，系统不会自动重发。"}
            _atomic_write_text(receipt_path, json.dumps(receipt, ensure_ascii=False))
            notifier = WeChatNotifier(plan["_config"], StorageManager(str(self.configs.data_dir)), client_factory=self.factory)
            # 使用确认时的上下文，发送前不再刷新，以免改变收件人、分段或额度。
            result = await notifier.send_text(summary["markdown"], summary["language"], refresh=False)
            message = (f"已推送到微信，共 {result.chunks_sent} 段。" if result.sent else
                       f"推送未完成，已确认发送 {result.chunks_sent} 段；请检查微信，系统不会自动重发。")
            receipt = {"status": result.status.value, "chunks_sent": result.chunks_sent, "message": message}
            _atomic_write_text(receipt_path, json.dumps(receipt, ensure_ascii=False))
            return receipt
        finally:
            lock.release()

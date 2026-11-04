"""微信登录显式联网、状态转换及凭据隔离。"""

import asyncio
import json
import time

from fastapi.testclient import TestClient

from test_web_api import ROOT, HEADERS, workspace


class WeChatClient:
    def __init__(self, *args):
        pass

    async def get_bot_qrcode(self, tokens=None):
        return {"qrcode": "test-code", "qrcode_img_content": "https://example.org/scan"}

    async def get_qrcode_status(self, code, **kwargs):
        return {"status": "confirmed", "bot_token": "very-private-bot-token", "ilink_user_id": "user-id"}

    async def get_updates(self, cursor, *, timeout):
        return {"msgs": [{"message_type": 1, "from_user_id": "user-id", "context_token": "private-context-token"}], "get_updates_buf": "cursor"}


def test_wechat_login_persists_credentials_but_returns_only_public_state(workspace):
    from src.web.api import create_app
    root, data, _ = workspace
    app = create_app(workspace=root, data_dir=data, wechat_client_factory=WeChatClient)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/wechat").json()["connected"] is False
        login = client.post("/api/wechat/login", headers=HEADERS)
        assert login.status_code == 200, login.text
        state = login.json()
        assert state["qr_data_url"].startswith("data:image/svg+xml;base64,")
        for _ in range(100):
            state = client.get(f'/api/wechat/login/{state["login_id"]}').json()
            if state["status"] == "ready":
                break
            time.sleep(.01)
        assert state["status"] == "ready"
        public = json.dumps(state) + client.get("/api/wechat").text
        assert "very-private-bot-token" not in public
        assert "private-context-token" not in public
        saved = json.loads((data / "wechat_session.json").read_text())
        assert saved["bot_token"] == "very-private-bot-token"
        assert saved["context_token"] == "private-context-token"
        assert client.get("/api/wechat").json()["remaining_budget"] == 10


def test_expired_qrcode_releases_lock_and_allows_a_fresh_successful_login(workspace):
    from filelock import FileLock
    from src.web.api import create_app

    class ExpiringOnceClient(WeChatClient):
        attempts = 0

        async def get_bot_qrcode(self, tokens=None):
            type(self).attempts += 1
            code = "expired-code" if self.attempts == 1 else "fresh-code"
            return {"qrcode": code, "qrcode_img_content": f"https://example.org/{code}"}

        async def get_qrcode_status(self, code, **kwargs):
            if code == "expired-code":
                return {"status": "expired"}
            return await super().get_qrcode_status(code, **kwargs)

    root, data, _ = workspace
    app = create_app(workspace=root, data_dir=data, wechat_client_factory=ExpiringOnceClient)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post("/api/wechat/login", headers=HEADERS)
        assert first.status_code == 200, first.text
        first_id = first.json()["login_id"]
        for _ in range(100):
            expired = client.get(f"/api/wechat/login/{first_id}").json()
            if expired["status"] == "expired":
                break
            time.sleep(.01)
        assert expired["status"] == "expired"
        assert expired["qr_data_url"] is None
        assert not (data / "wechat_session.json").exists()
        assert client.get("/api/wechat").json()["connected"] is False
        with FileLock(data / ".horizon-run.lock", timeout=0):
            pass

        second = client.post("/api/wechat/login", headers=HEADERS)
        assert second.status_code == 200, second.text
        second_id = second.json()["login_id"]
        assert second_id != first_id
        assert second.json()["qr_data_url"].startswith("data:image/svg+xml;base64,")
        for _ in range(100):
            ready = client.get(f"/api/wechat/login/{second_id}").json()
            if ready["status"] == "ready":
                break
            time.sleep(.01)
        assert ready["status"] == "ready"
        assert client.get(f"/api/wechat/login/{first_id}").json()["status"] == "expired"
        assert client.get("/api/wechat").json()["ready"] is True
        saved = json.loads((data / "wechat_session.json").read_text())
        assert saved["bot_token"] == "very-private-bot-token"
        assert saved["context_token"] == "private-context-token"


def test_wechat_cancel_stops_poll_and_keeps_previous_session(workspace):
    from src.web.api import create_app
    class WaitingClient(WeChatClient):
        async def get_qrcode_status(self, *args, **kwargs):
            await asyncio.sleep(5)
            return {"status": "wait"}
    root, data, _ = workspace
    with TestClient(create_app(workspace=root, data_dir=data, wechat_client_factory=WaitingClient), base_url="http://127.0.0.1") as client:
        login = client.post("/api/wechat/login", headers=HEADERS).json()
        cancelled = client.post(f'/api/wechat/login/{login["login_id"]}/cancel', headers=HEADERS)
        assert cancelled.json()["status"] == "cancelled"
        assert not (data / "wechat_session.json").exists()


def test_wechat_status_hides_identity_and_shutdown_cancels_active_login(workspace):
    from src.web.api import create_app
    from src.services.wechat import WeChatSession
    class WaitingClient(WeChatClient):
        async def get_qrcode_status(self, *args, **kwargs):
            await asyncio.sleep(30)
            return {"status": "wait"}
    root, data, _ = workspace
    WeChatSession(bot_token="private-token", user_id="private-user-id", bot_id="private-bot-id", context_token="private-context").save(data / "wechat_session.json")
    app = create_app(workspace=root, data_dir=data, wechat_client_factory=WaitingClient)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        status = client.get("/api/wechat")
        assert status.json()["ready"] is True
        public = status.text + client.get("/api/overview").text
        for secret in ("private-token", "private-user-id", "private-bot-id", "private-context"):
            assert secret not in public
        login = client.post("/api/wechat/login", headers=HEADERS).json()
        assert login["status"] == "waiting"
    assert app.state.wechat.get(login["login_id"])["status"] == "cancelled"
    from filelock import FileLock
    with FileLock(data / ".horizon-run.lock", timeout=0):
        pass


def test_immediate_login_cancel_releases_shared_lock(workspace):
    from src.web.api import create_app
    from filelock import FileLock
    root, data, _ = workspace
    manager = create_app(workspace=root, data_dir=data, wechat_client_factory=WeChatClient).state.wechat
    async def exercise():
        state = await manager.start()
        cancelled = await manager.cancel(state["login_id"])
        assert cancelled["status"] == "cancelled"
    asyncio.run(exercise())
    with FileLock(data / ".horizon-run.lock", timeout=0):
        pass


class SendingClient(WeChatClient):
    sent = []
    fail_after = None

    async def send_text(self, to_user_id, text, *, context_token):
        import httpx
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise httpx.ReadTimeout("private-token 不应进入响应")
        self.sent.append(text)
        return {}


def prepare_delivery(workspace):
    from src.web.api import create_app
    from src.services.wechat import WeChatSession
    root, data, config = workspace
    config['wechat'] = {'enabled': True, 'chunk_size': 100}
    (data / 'config.json').write_text(json.dumps(config))
    WeChatSession(bot_token='private-token', user_id='user-id', context_token='private-context-token').save(data / 'wechat_session.json')
    archive = data / 'summaries'
    archive.mkdir(exist_ok=True)
    (archive / 'horizon-2026-11-04-zh.md').write_text('# 测试报告\n\n' + '新闻正文。' * 30)
    SendingClient.sent = []
    SendingClient.fail_after = None
    return create_app(workspace=root, data_dir=data, wechat_client_factory=SendingClient)


DELIVERY_URL = '/api/summaries/horizon-2026-11-04-zh.md/wechat'


def test_preview_confirm_and_persistent_duplicate_guard(workspace):
    app = prepare_delivery(workspace)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        plan = client.get(DELIVERY_URL).json()
        assert plan['can_send'] is True
        assert plan['chunk_count'] == 3
        assert SendingClient.sent == []
        body = {key: plan[key] for key in ('revision', 'confirmation')}
        assert client.post(DELIVERY_URL, json=body).status_code == 403
        result = client.post(DELIVERY_URL, headers=HEADERS, json=body)
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'success'
        assert result.json()['chunks_sent'] == 3
        assert len(SendingClient.sent) == 3
        assert client.get('/api/wechat').json()['remaining_budget'] == 7
        assert 'private-token' not in result.text
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
    from src.web.api import create_app
    with TestClient(create_app(workspace=workspace[0], data_dir=workspace[1], wechat_client_factory=SendingClient), base_url='http://127.0.0.1') as client:
        assert client.get(DELIVERY_URL).json()['can_send'] is False
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
    assert len(SendingClient.sent) == 3


def test_report_or_recipient_change_invalidates_confirmation(workspace):
    from src.services.wechat import WeChatSession
    app = prepare_delivery(workspace)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        plan = client.get(DELIVERY_URL).json()
        body = {key: plan[key] for key in ('revision', 'confirmation')}
        path = workspace[1] / 'wechat_session.json'
        session = WeChatSession.load(path)
        session.user_id = 'another-user'
        session.save(path)
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
        plan = client.get(DELIVERY_URL).json()
        body = {key: plan[key] for key in ('revision', 'confirmation')}
        (workspace[1] / 'summaries/horizon-2026-11-04-zh.md').write_text('# 新版')
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
        assert SendingClient.sent == []


def test_partial_failure_is_visible_and_never_automatically_retried(workspace, caplog):
    app = prepare_delivery(workspace)
    SendingClient.fail_after = 1
    with TestClient(app, base_url='http://127.0.0.1') as client:
        plan = client.get(DELIVERY_URL).json()
        body = {key: plan[key] for key in ('revision', 'confirmation')}
        result = client.post(DELIVERY_URL, headers=HEADERS, json=body)
        assert result.json()['status'] == 'network_failure'
        assert result.json()['chunks_sent'] == 1
        assert 'private-token' not in result.text
        assert 'private-token' not in caplog.text
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
        assert len(SendingClient.sent) == 1


def test_delivery_rejects_unready_disabled_filtered_or_low_budget(workspace):
    from src.services.wechat import WeChatSession
    app = prepare_delivery(workspace)
    data = workspace[1]
    with TestClient(app, base_url='http://127.0.0.1') as client:
        original = json.loads((data / 'config.json').read_text())
        for changes in ({'enabled': False}, {'languages': ['en']}):
            config = json.loads(json.dumps(original))
            config['wechat'].update(changes)
            (data / 'config.json').write_text(json.dumps(config))
            assert client.get(DELIVERY_URL).json()['can_send'] is False
        (data / 'config.json').write_text(json.dumps(original))
        session = WeChatSession.load(data / 'wechat_session.json')
        session.context_sends = 10
        session.save(data / 'wechat_session.json')
        plan = client.get(DELIVERY_URL).json()
        assert plan['can_send'] is False
        assert client.post(DELIVERY_URL, headers=HEADERS, json={key: plan[key] for key in ('revision', 'confirmation')}).status_code == 409
        (data / 'wechat_session.json').unlink()
        assert client.get(DELIVERY_URL).json()['can_send'] is False
        assert SendingClient.sent == []


def test_sending_holds_shared_lock_and_rejects_arbitrary_payload(workspace):
    from filelock import FileLock, Timeout
    import pytest
    app = prepare_delivery(workspace)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        plan = client.get(DELIVERY_URL).json()
        body = {key: plan[key] for key in ('revision', 'confirmation')}
        assert client.post(DELIVERY_URL, headers=HEADERS, json={**body, 'to_user_id': 'someone'}).status_code == 422
        with FileLock(workspace[1] / '.horizon-run.lock', timeout=0):
            assert client.post(DELIVERY_URL, headers=HEADERS, json=body).status_code == 409
        class CheckingClient(SendingClient):
            async def send_text(self, *args, **kwargs):
                with pytest.raises(Timeout):
                    with FileLock(workspace[1] / '.horizon-run.lock', timeout=0):
                        pass
                return await super().send_text(*args, **kwargs)
        app.state.wechat.factory = CheckingClient
        assert client.post(DELIVERY_URL, headers=HEADERS, json=body).json()['status'] == 'success'

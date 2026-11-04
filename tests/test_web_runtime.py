"""任务生命周期、日志重放与互斥的行为检查。"""

import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from filelock import FileLock

from src.mcp.service import HorizonPipelineService
from test_web_api import ROOT, HEADERS, workspace


class OfflineService(HorizonPipelineService):
    def __init__(self, runs_root, *, fail=False, slow=False):
        super().__init__(runs_root=runs_root)
        self.fail, self.slow = fail, slow

    async def fetch_items(self, *, run_id, **kwargs):
        self.console.print("开始抓取 secret-test-credential")
        await asyncio.sleep(5 if self.slow else .02)
        if self.fail:
            raise RuntimeError("secret-test-credential")
        self.run_store.save_items(run_id, "raw", [])
        self.run_store.update_meta(run_id, {"raw_count": 0, "fetch_status": "success"})
        return {"run_id": run_id, "fetched": 0, "fetch_status": "success"}


def wait_terminal(client, run_id):
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(.01)
    raise AssertionError("任务未完成")


def test_empty_run_finishes_and_log_replay_resumes_after_last_event(workspace, monkeypatch):
    from src.web.api import create_app
    monkeypatch.setenv("TEST_API_TOKEN", "secret-test-credential")
    root, data, _ = workspace
    service = OfflineService(data / "mcp-runs")
    with TestClient(create_app(workspace=root, data_dir=data, service=service), base_url="http://127.0.0.1") as client:
        started = client.post("/api/runs", headers=HEADERS, json={"hours": 12})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        result = wait_terminal(client, run_id)
        assert result["status"] == "completed"
        assert result["counts"]["raw"] == 0
        assert result["duration_seconds"] >= 0
        logs = client.get(f"/api/runs/{run_id}/logs").json()["items"]
        assert logs and "secret-test-credential" not in json.dumps(logs)
        replay = client.get(f"/api/runs/{run_id}/logs/stream", headers={"Last-Event-ID": str(logs[0]["id"])})
        assert f'id: {logs[0]["id"]}\n' not in replay.text
        assert "event: log" in replay.text
        assert client.get("/api/summaries").json()["count"] >= 1


def test_cancel_run_releases_lock_and_records_cancelled_state(workspace):
    from src.web.api import create_app
    root, data, _ = workspace
    service = OfflineService(data / "mcp-runs", slow=True)
    with TestClient(create_app(workspace=root, data_dir=data, service=service), base_url="http://127.0.0.1") as client:
        started = client.post("/api/runs", headers=HEADERS, json={}).json()
        assert client.post("/api/runs", headers=HEADERS, json={}).status_code == 409
        revision = client.get("/api/config").json()["revision"]
        assert client.patch("/api/config", headers=HEADERS, json={"revision": revision, "patch": {"collection": {"time_window_hours": 12}}}).status_code == 409
        cancelled = client.post(f'/api/runs/{started["run_id"]}/cancel', headers=HEADERS)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        with FileLock(data / ".horizon-run.lock", timeout=0):
            pass
        saved = service.run_store.load_meta(started["run_id"])
        assert saved["status"] == "cancelled"


def test_failed_run_is_visible_without_exception_secrets(workspace, monkeypatch):
    from src.web.api import create_app
    monkeypatch.setenv("TEST_API_TOKEN", "secret-test-credential")
    root, data, _ = workspace
    service = OfflineService(data / "mcp-runs", fail=True)
    with TestClient(create_app(workspace=root, data_dir=data, service=service), base_url="http://127.0.0.1") as client:
        run = client.post("/api/runs", headers=HEADERS, json={}).json()
        failed = wait_terminal(client, run["run_id"])
        assert failed["status"] == "failed"
        assert failed["error"]
        assert "secret-test-credential" not in json.dumps(failed)


def test_external_lock_is_reported_and_blocks_web_run(workspace):
    from src.web.api import create_app
    root, data, _ = workspace
    with TestClient(create_app(workspace=root, data_dir=data), base_url="http://127.0.0.1") as client:
        with FileLock(data / ".horizon-run.lock", timeout=0):
            assert client.get("/api/overview").json()["busy"] is True
            assert client.post("/api/runs", headers=HEADERS, json={}).status_code == 409


def test_cli_respects_web_shared_lock(workspace, monkeypatch):
    from types import SimpleNamespace
    from src import main as cli
    from src.models import AIProvider
    root, data, _ = workspace
    called = []
    class Storage:
        def __init__(self, *args, **kwargs):
            pass
        def load_config(self):
            return SimpleNamespace(ai=SimpleNamespace(provider=AIProvider.OLLAMA), display=SimpleNamespace(icon_style="ascii"))
    class Orchestrator:
        def __init__(self, *args, **kwargs):
            pass
        async def run(self, **kwargs):
            called.append(True)
    monkeypatch.setattr(cli, "StorageManager", Storage)
    monkeypatch.setattr(cli, "HorizonOrchestrator", Orchestrator)
    monkeypatch.setattr(cli, "configure_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr("sys.argv", ["horizon", "--data-dir", str(data)])
    with FileLock(data / ".horizon-run.lock", timeout=0):
        import pytest
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
    assert called == []


def test_cancel_immediately_after_start_releases_lock(workspace):
    from src.web.api import create_app
    root, data, _ = workspace
    app = create_app(workspace=root, data_dir=data, service=OfflineService(data / "mcp-runs", slow=True))
    manager = app.state.manager
    async def exercise():
        run = await manager.start(24, True, ["zh"])
        cancelled = await manager.cancel(run["run_id"])
        assert cancelled["status"] == "cancelled"
        assert manager.busy() is False
    asyncio.run(exercise())


def test_full_pipeline_records_stage_counts_and_token_snapshot(workspace):
    from src.web.api import create_app
    from src.ai.tokens import record_usage
    class StagedService(HorizonPipelineService):
        async def fetch_items(self, *, run_id, **kwargs):
            self.run_store.save_items(run_id, "raw", [{"id": "item"}])
            return {"run_id": run_id, "fetched": 1, "fetch_status": "success"}
        async def score_items(self, *, run_id, **kwargs):
            self.run_store.save_items(run_id, "scored", [{"id": "item"}])
            record_usage("test", 100, 20)
        async def filter_items(self, *, run_id, **kwargs):
            self.run_store.save_items(run_id, "filtered", [{"id": "item"}])
            return {"kept": 1}
        async def enrich_items(self, *, run_id, **kwargs):
            self.run_store.save_items(run_id, "enriched", [{"id": "item"}])
            return {"status": "success"}
        async def generate_summary(self, *, run_id, language, source_stage, save_to_horizon_data, **kwargs):
            assert source_stage == "enriched"
            assert save_to_horizon_data is True
            self.run_store.save_summary(run_id, language, "# 本地测试速递")
            return {"run_id": run_id}
    root, data, _ = workspace
    service = StagedService(data / "mcp-runs")
    with TestClient(create_app(workspace=root, data_dir=data, service=service), base_url="http://127.0.0.1") as client:
        started = client.post("/api/runs", headers=HEADERS, json={"languages": ["zh"]}).json()
        completed = wait_terminal(client, started["run_id"])
        assert completed["status"] == "completed"
        assert completed["counts"] == {"raw": 1, "scored": 1, "filtered": 1, "enriched": 1}
        assert completed["tokens"] == {"input": 100, "output": 20, "total": 120}
        assert set(completed["stage_durations"]) == {"raw", "scored", "filtered", "enriched", "summary"}
        assert client.get(f'/api/runs/{started["run_id"]}/summary?language=zh').json()["markdown"] == "# 本地测试速递"


def test_literal_url_credentials_are_redacted_from_runtime_logs(workspace):
    from src.web.api import create_app
    root, data, config = workspace
    config["sources"]["rss"][0]["url"] = "https://private-user:private-password@example.org/feed?key=literal-feed-secret"
    (data / "config.json").write_text(json.dumps(config))
    class LeakingService(OfflineService):
        async def fetch_items(self, **kwargs):
            raise RuntimeError("https://private-user:private-password@example.org/feed?key=literal-feed-secret")
    with TestClient(create_app(workspace=root, data_dir=data, service=LeakingService(data / "mcp-runs")), base_url="http://127.0.0.1") as client:
        started = client.post("/api/runs", headers=HEADERS, json={}).json()
        wait_terminal(client, started["run_id"])
        output = client.get(f'/api/runs/{started["run_id"]}/logs').text
        for secret in ("private-user", "private-password", "literal-feed-secret"):
            assert secret not in output

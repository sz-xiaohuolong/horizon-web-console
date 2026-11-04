"""本地控制台的数据边界与配置事务。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.mcp.service import HorizonPipelineService

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-Horizon-Request": "1", "Origin": "http://127.0.0.1"}


@pytest.fixture
def workspace(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = json.loads((ROOT / "data/config.example.json").read_text())
    config["processing"]["profiles_dir"] = str(ROOT / "profiles")
    config["sources"]["rss"] = [{"name": "私有订阅", "url": "https://example.org/feed?key=${FEED_TOKEN}", "enabled": True}]
    config["ai"]["base_url"] = "https://example.org/${AI_TENANT}"
    (data / "config.json").write_text(json.dumps(config))
    return tmp_path, data, config


@pytest.fixture
def client(workspace, monkeypatch):
    from src.web.api import create_app
    root, data, _ = workspace
    monkeypatch.setenv("FEED_TOKEN", "feed-private-secret")
    monkeypatch.setenv("AI_TENANT", "tenant-private-secret")
    app = create_app(workspace=root, data_dir=data, runs_dir=data / "mcp-runs")
    with TestClient(app, base_url="http://127.0.0.1") as session:
        yield session


def test_configuration_patch_preserves_env_refs_and_detects_stale_writers(client, workspace):
    root, data, _ = workspace
    initial = client.get("/api/config").json()
    assert "feed-private-secret" not in json.dumps(initial)
    assert "tenant-private-secret" not in json.dumps(initial)
    response = client.patch("/api/config", headers=HEADERS, json={"revision": initial["revision"], "patch": {"collection": {"time_window_hours": 12}}})
    assert response.status_code == 200, response.text
    persisted = json.loads((data / "config.json").read_text())
    assert persisted["collection"]["time_window_hours"] == 12
    assert persisted["sources"]["rss"][0]["url"].endswith("${FEED_TOKEN}")
    assert persisted["ai"]["base_url"].endswith("${AI_TENANT}")
    assert list(data.glob("config.json.web-*.bak"))
    stale = client.patch("/api/config", headers=HEADERS, json={"revision": initial["revision"], "patch": {"collection": {"time_window_hours": 6}}})
    assert stale.status_code == 409


def test_archive_exposes_new_revision_when_same_day_report_is_replaced(client, workspace):
    folder = workspace[1] / "summaries"
    folder.mkdir(exist_ok=True)
    path = folder / "horizon-2026-11-04-zh.md"
    path.write_text("# 同一天的报告\n\n旧内容")
    first = client.get("/api/summaries").json()["items"][0]
    path.write_text("# 同一天的报告\n\n新生成的十条新闻")
    second = client.get("/api/summaries").json()["items"][0]
    assert first["id"] == second["id"]
    assert first["revision"] != second["revision"]
    assert second["updated_at"]
    detail = client.get(f'/api/summaries/{second["id"]}').json()
    assert detail["revision"] == second["revision"]
    assert "新生成" in detail["markdown"]


@pytest.mark.parametrize("full_sources", [False, True])
def test_source_patch_restores_redacted_schema_defaults(client, workspace, monkeypatch, full_sources):
    data = workspace[1]
    monkeypatch.setenv("LWN_KEY", "example-private-token")
    config = json.loads((ROOT / "data/config.example.json").read_text())
    config["processing"]["profiles_dir"] = str(ROOT / "profiles")
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config").json()
    sources = view["config"]["sources"]
    sources["rss"][0]["name"] = "保存后的离线订阅"
    source_patch = sources if full_sources else {"rss": sources["rss"]}
    response = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": {"sources": source_patch}})
    assert response.status_code == 200, response.text
    saved = json.loads((data / "config.json").read_text())
    assert saved["sources"]["rss"][0]["name"] == "保存后的离线订阅"
    assert saved["sources"]["rss"][-1]["url"].endswith("${LWN_KEY}")
    if full_sources:
        assert saved["sources"]["twitter"]["cookie_dir"] == "data"
        assert saved["sources"]["twitter"]["cookie_file_pattern"] == "x_cookies_*.json"
    assert "<redacted>" not in json.dumps(saved)
    assert "example-private-token" not in json.dumps(saved)


@pytest.mark.parametrize("section", ["collection", "sources"])
def test_unedited_private_url_keeps_original_spelling_during_saves(client, workspace, section):
    data = workspace[1]
    original_url = "https://review-user:private-value@EXAMPLE.ORG"
    config = json.loads((data / "config.json").read_text())
    config["sources"]["rss"] = [{"name": "保留原始地址", "url": original_url, "enabled": True}]
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config").json()
    if section == "sources":
        sources = view["config"]["sources"]
        sources["rss"][0]["enabled"] = False
        patch = {"sources": sources}
    else:
        patch = {"collection": {"time_window_hours": 12}}
    response = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": patch})
    assert response.status_code == 200, response.text
    saved = json.loads((data / "config.json").read_text())
    assert saved["sources"]["rss"][0]["url"] == original_url
    assert "review-user" not in response.text
    assert "private-value" not in response.text


def test_config_rejects_credential_writes_and_invalid_values_without_changing_file(client, workspace):
    data = workspace[1]
    before = (data / "config.json").read_bytes()
    revision = client.get("/api/config").json()["revision"]
    for patch in [{"ai": {"model": "other"}}, {"collection": {"time_window_hours": 0}}, {"sources": {"rss": [{"name": "secret", "url": "https://example.org/?token=plaintext"}]}}]:
        result = client.patch("/api/config", headers=HEADERS, json={"revision": revision, "patch": patch})
        assert result.status_code == 422, result.text
        assert (data / "config.json").read_bytes() == before


def test_atomic_config_replace_failure_preserves_original_and_allows_retry(workspace, monkeypatch):
    import os
    from src.web.api import create_app
    root, data, _ = workspace
    config_path = data / "config.json"
    before = config_path.read_bytes()
    original_replace = os.replace

    def fail_config_replace(source, destination):
        if Path(destination) == config_path:
            raise OSError("模拟配置原子替换失败")
        return original_replace(source, destination)

    app = create_app(workspace=root, data_dir=data)
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        revision = client.get("/api/config").json()["revision"]
        body = {"revision": revision, "patch": {"collection": {"time_window_hours": 12}}}
        with monkeypatch.context() as patcher:
            patcher.setattr(os, "replace", fail_config_replace)
            response = client.patch("/api/config", headers=HEADERS, json=body)
        assert response.status_code == 500
        assert config_path.read_bytes() == before
        assert client.get("/api/config").json()["revision"] == revision
        backups = list(data.glob("config.json.web-*.bak"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == before
        assert not list(data.glob(".config.json.*.tmp"))
        retry = client.patch("/api/config", headers=HEADERS, json=body)
        assert retry.status_code == 200, retry.text
        assert json.loads(config_path.read_text())["collection"]["time_window_hours"] == 12


def test_host_origin_and_custom_header_protect_local_mutations(client):
    assert client.get("/api/overview", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/runs", json={"hours": 24}).status_code == 403
    assert client.post("/api/runs", headers={"Origin": "https://evil.example", "X-Horizon-Request": "1"}, json={"hours": 24}).status_code == 403


def test_stage_filter_pagination_and_unknown_metrics_are_truthful(client, workspace):
    store = HorizonPipelineService(runs_root=workspace[1] / "mcp-runs").run_store
    run_id = store.create_run("run-old")
    items = [{"id": "a", "title": "模型发布", "source_type": "rss", "url": "https://example.org/a", "processing": {"analysis": {"score": 9, "reason": "技术进展", "summary": "摘要"}}}, {"id": "b", "title": "其他消息", "source_type": "github", "url": "https://example.org/b", "processing": {"analysis": {"score": 3, "reason": "相关性低", "summary": "摘要"}}}]
    store.save_items(run_id, "scored", items)
    store.save_items(run_id, "filtered", items[:1])
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["tokens"] is None
    assert run["duration_seconds"] is None
    result = client.get(f"/api/runs/{run_id}/stages/scored?disposition=removed&limit=1").json()
    assert result["total"] == 1
    assert result["items"][0]["id"] == "b"
    assert result["items"][0]["retained"] is False
    assert "推断" in result["items"][0]["exclusion_reason"]
    assert client.get(f"/api/runs/{run_id}/stages/raw").status_code == 404


def test_summary_paths_are_confined_and_markdown_is_returned_as_text(client, workspace):
    summaries = workspace[1] / "summaries"
    summaries.mkdir(exist_ok=True)
    (summaries / "horizon-2026-11-04-zh.md").write_text("# 实际速递\n\n内容")
    (workspace[0] / "secret.md").write_text("private")
    (summaries / "horizon-2026-11-05-zh.md").symlink_to(workspace[0] / "secret.md")
    listing = client.get("/api/summaries").json()
    assert listing["count"] == 1
    assert listing["items"][0]["id"] == "horizon-2026-11-04-zh.md"
    assert client.get("/api/summaries/horizon-2026-11-04-zh.md").json()["markdown"].startswith("# 实际速递")
    assert client.get("/api/summaries/horizon-2026-11-05-zh.md").status_code == 404


def test_restart_marks_abandoned_web_runs_interrupted(workspace):
    from src.web.api import create_app
    data = workspace[1]
    store = HorizonPipelineService(runs_root=data / "mcp-runs").run_store
    run = store.create_run("run-abandoned")
    store.update_meta(run, {"web_managed": True, "status": "running", "current_stage": "scored"})
    with TestClient(create_app(workspace=workspace[0], data_dir=data), base_url="http://127.0.0.1") as client:
        assert client.get(f"/api/runs/{run}").json()["status"] == "interrupted"


def test_numeric_environment_config_is_readable_and_unchanged_reference_is_preserved(client, workspace, monkeypatch):
    data = workspace[1]
    monkeypatch.setenv("WEB_FETCH_HOURS", "12")
    config = json.loads((data / "config.json").read_text())
    config["collection"]["time_window_hours"] = "${WEB_FETCH_HOURS}"
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config")
    assert view.status_code == 200, view.text
    assert view.json()["config"]["collection"]["time_window_hours"] == 12
    result = client.patch("/api/config", headers=HEADERS, json={"revision": view.json()["revision"], "patch": {"collection": {"time_window_hours": 12}}})
    assert result.status_code == 200
    assert json.loads((data / "config.json").read_text())["collection"]["time_window_hours"] == "${WEB_FETCH_HOURS}"


def test_stage_minimum_score_does_not_hide_other_source_filter_choices(client, workspace):
    store = HorizonPipelineService(runs_root=workspace[1] / "mcp-runs").run_store
    run_id = store.create_run("run-score")
    store.save_items(run_id, "scored", [{"id": "a", "title": "条目A", "source_type": "rss", "processing": {"analysis": {"score": 9}}}, {"id": "b", "title": "条目B", "source_type": "github", "processing": {"analysis": {"score": 3}}}, {"id": "c", "title": "缺少评分", "source_type": "rss"}])
    result = client.get(f"/api/runs/{run_id}/stages/scored?min_score=8&source=rss").json()
    assert result["total"] == 1
    assert result["items"][0]["id"] == "a"
    assert result["source_counts"] == {"rss": 2, "github": 1}


def test_corrupt_run_metadata_does_not_break_overview(client, workspace):
    runs = workspace[1] / "mcp-runs"
    bad = runs / "run-corrupt"
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text("[]")
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/runs").json()["count"] == 0


def test_run_diagnostics_do_not_reveal_environment_secret_values(client, workspace):
    store = HorizonPipelineService(runs_root=workspace[1] / "mcp-runs").run_store
    run_id = store.create_run("run-error")
    store.update_meta(run_id, {"status": "failed", "error": "request failed: feed-private-secret", "fetch_report": {"error": "upstream rejected feed-private-secret"}})
    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert "feed-private-secret" not in response.text


def test_replacement_maps_allow_removing_quota_groups(client, workspace):
    data = workspace[1]
    config = json.loads((data / "config.json").read_text())
    config["digest"]["category_groups"] = {"one": {"name": "第一组", "limit": 2, "categories": ["first"]}, "two": {"name": "第二组", "limit": 2, "categories": ["second"]}}
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config").json()
    result = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": {"digest": {"category_groups": {"two": view["config"]["digest"]["category_groups"]["two"]}}}})
    assert result.status_code == 200, result.text
    assert set(json.loads((data / "config.json").read_text())["digest"]["category_groups"]) == {"two"}


def test_deleting_preceding_private_feed_preserves_remaining_credential_reference(client, workspace, monkeypatch):
    data = workspace[1]
    monkeypatch.setenv("OTHER_FEED_TOKEN", "second-feed-secret")
    config = json.loads((data / "config.json").read_text())
    config["sources"]["rss"].append({"name": "第二个订阅", "url": "https://other.example.org/feed?key=${OTHER_FEED_TOKEN}", "enabled": True})
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config").json()
    remaining = view["config"]["sources"]["rss"][1]
    result = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": {"sources": {"rss": [remaining]}}})
    assert result.status_code == 200, result.text
    saved = json.loads((data / "config.json").read_text())["sources"]["rss"]
    assert len(saved) == 1
    assert saved[0]["url"] == "https://other.example.org/feed?key=${OTHER_FEED_TOKEN}"


def test_ambiguous_private_feed_changes_are_rejected_without_writing(client, workspace):
    data = workspace[1]
    config = json.loads((data / "config.json").read_text())
    config["sources"]["rss"] = [
        {"name": "相同名称", "url": "https://example.org/feed?token=private-first"},
        {"name": "相同名称", "url": "https://example.org/feed?token=private-second"},
    ]
    (data / "config.json").write_text(json.dumps(config))
    before = (data / "config.json").read_bytes()
    view = client.get("/api/config").json()
    remaining = view["config"]["sources"]["rss"][1]
    result = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": {"sources": {"rss": [remaining]}}})
    assert result.status_code == 422, result.text
    assert "不同名称" in result.json()["detail"]
    assert (data / "config.json").read_bytes() == before
    assert not list(data.glob("config.json.web-*.bak"))


@pytest.mark.parametrize(("filename", "route"), [
    ("meta.json", ""),
    ("raw_items.json", "/stages/raw"),
    ("scored_items.json", "/stages/scored"),
    ("filtered_items.json", "/stages/filtered"),
    ("enriched_items.json", "/stages/enriched"),
    ("summary-zh.md", "/summary?language=zh"),
    ("web-logs.jsonl", "/logs"),
    ("web-logs.jsonl", "/logs/stream"),
])
def test_run_artifact_symlinks_are_rejected_without_reading_or_deleting_them(client, workspace, filename, route):
    store = HorizonPipelineService(runs_root=workspace[1] / "mcp-runs").run_store
    run_id = store.create_run("run-symlink")
    outside = workspace[0] / "outside-private.json"
    outside.write_text('[{"id":"outside-sentinel","source_type":"rss","title":"private-sentinel"}]')
    target = store.run_dir(run_id) / filename
    target.unlink(missing_ok=True)
    target.symlink_to(outside)
    result = client.get(f"/api/runs/{run_id}{route}")
    assert result.status_code == 404, result.text
    assert "private-sentinel" not in result.text
    assert target.is_symlink()
    assert outside.read_text().startswith('[{"id":"outside-sentinel"')


def test_run_directory_symlink_is_rejected_even_if_target_is_another_run(client, workspace):
    store = HorizonPipelineService(runs_root=workspace[1] / "mcp-runs").run_store
    run_id = store.create_run("run-real")
    store.save_summary(run_id, "zh", "private-sentinel")
    alias = store.root / "run-alias"
    alias.symlink_to(store.run_dir(run_id), target_is_directory=True)
    response = client.get("/api/runs/run-alias/summary?language=zh")
    assert response.status_code == 404
    assert "private-sentinel" not in response.text
    assert alias.is_symlink()


def test_configuration_view_and_source_toggle_preserve_unknown_user_fields(client, workspace):
    data = workspace[1]
    config = json.loads((data / "config.json").read_text())
    config["sources"]["rss"][0]["user_metadata"] = {"owner": "个人订阅", "rank": 2}
    (data / "config.json").write_text(json.dumps(config))
    view = client.get("/api/config").json()
    assert view["config"]["sources"]["rss"][0]["user_metadata"] == {"owner": "个人订阅", "rank": 2}
    source = view["config"]["sources"]["rss"][0]
    source.pop("user_metadata")
    source["enabled"] = False
    result = client.patch("/api/config", headers=HEADERS, json={"revision": view["revision"], "patch": {"sources": {"rss": [source]}}})
    assert result.status_code == 200, result.text
    saved = json.loads((data / "config.json").read_text())["sources"]["rss"][0]
    assert saved["enabled"] is False
    assert saved["user_metadata"] == {"owner": "个人订阅", "rank": 2}

"""独立浏览器验收服务器：临时目录、固定工件、离线模型和微信伪服务。"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from src.ai.tokens import record_usage
from src.mcp.service import HorizonPipelineService
from src.web.api import create_app
from src.services.wechat import WeChatSession

ROOT = Path(__file__).resolve().parents[1]
ITEMS = [
    {"id": "research", "title": "本地验收：可追溯的模型研究进展", "source_type": "rss", "url": "https://example.org/research", "content": "用于测试的离线内容，没有访问外部信息源。", "published_at": "2026-11-04T10:00:00Z", "profile": "tech-news", "processing": {"analysis": {"score": 9, "reason": "包含可核实的技术细节，符合研究主题。", "summary": "本条只用于离线验收。", "tags": ["研究"]}}},
    {"id": "release", "title": "本地验收：开源工具发布", "source_type": "github", "url": "https://example.org/release", "published_at": "2026-11-04T09:00:00Z", "processing": {"analysis": {"score": 8, "reason": "有明确版本和使用场景。", "summary": "第二条测试信息。"}}},
    {"id": "removed", "title": "本地验收：相关性较低的消息", "source_type": "rss", "url": "https://example.org/low", "published_at": "2026-11-04T08:00:00Z", "processing": {"analysis": {"score": 3, "reason": "缺少与当前主题有关的实质内容。"}}},
]
REPORT = "# Horizon 本地验收速递\n\n此报告由离线伪服务生成。\n\n## 研究进展\n\n- [可追溯的模型研究进展](https://example.org/research)\n\n## 开源发布\n\n- 开源工具发布\n"


class BrowserPipeline(HorizonPipelineService):
    async def fetch_items(self, *, run_id, hours, **kwargs):
        self.console.print("离线验收：开始采集，未访问网络。")
        await asyncio.sleep(30 if hours == 12 else 1)
        self.run_store.save_items(run_id, "raw", [{k: v for k, v in item.items() if k != "processing"} for item in ITEMS])
        return {"fetched": len(ITEMS), "fetch_status": "success"}

    async def score_items(self, *, run_id, **kwargs):
        await asyncio.sleep(1)
        self.run_store.save_items(run_id, "scored", copy.deepcopy(ITEMS))
        record_usage("offline", 120, 30)

    async def filter_items(self, *, run_id, **kwargs):
        await asyncio.sleep(1)
        self.run_store.save_items(run_id, "filtered", copy.deepcopy(ITEMS[:2]))
        return {"kept": 2}

    async def enrich_items(self, *, run_id, **kwargs):
        await asyncio.sleep(1)
        self.run_store.save_items(run_id, "enriched", copy.deepcopy(ITEMS[:2]))
        return {"status": "success"}

    async def generate_summary(self, *, run_id, language, **kwargs):
        self.run_store.save_summary(run_id, language, REPORT)
        self.archive.mkdir(exist_ok=True)
        (self.archive / f"horizon-2026-11-04-{language}.md").write_text(REPORT)
        self.console.print("离线验收：速递已保存。")
        return {"run_id": run_id}


class BrowserWeChat:
    attempts = 0
    sent = []

    def __init__(self, *args):
        pass

    async def get_bot_qrcode(self, tokens=None):
        type(self).attempts += 1
        return {"qrcode": str(self.attempts), "qrcode_img_content": "https://example.org/offline-test-qr"}

    async def get_qrcode_status(self, code, **kwargs):
        if code == "1":
            return {"status": "wait"}
        if kwargs.get("verify_code") != "123456":
            return {"status": "need_verifycode"}
        return {"status": "confirmed", "bot_token": "offline-test-token", "ilink_user_id": "offline-user"}

    async def get_updates(self, cursor, *, timeout):
        return {"msgs": [{"message_type": 1, "from_user_id": "offline-user", "context_token": "offline-test-context"}], "get_updates_buf": "offline-cursor"}

    async def send_text(self, to_user_id, text, *, context_token):
        self.sent.append(text)
        print(f"离线伪发送：第 {len(self.sent)} 段，未访问微信服务。", flush=True)
        return {}


def main():
    parser = argparse.ArgumentParser(description="启动离线浏览器验收夹具；12小时时间窗用于测试取消，其余用于正常完成。")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--ready-wechat", action="store_true", help="使用伪会话验收手动推送")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="horizon-browser-") as temporary:
        root = Path(temporary)
        data = root / "data"
        data.mkdir()
        config = json.loads((ROOT / "data/config.example.json").read_text())
        config["processing"]["profiles_dir"] = str(ROOT / "profiles")
        config["sources"]["rss"] = [{"name": "离线验收订阅", "url": "https://example.org/feed", "enabled": True, "user_metadata": {"note": "必须保留"}}]
        config["ai"]["languages"] = ["zh"]
        if args.ready_wechat:
            config["wechat"] = {"enabled": True, "chunk_size": 100}
            WeChatSession(bot_token="offline-test-token", user_id="offline-user", context_token="offline-test-context").save(data / "wechat_session.json")
        (data / "config.json").write_text(json.dumps(config, ensure_ascii=False))
        service = BrowserPipeline(runs_root=data / "mcp-runs")
        service.archive = data / "summaries"
        run = service.run_store.create_run("offline-seed")
        for stage, values in (("raw", ITEMS), ("scored", ITEMS), ("filtered", ITEMS[:2]), ("enriched", ITEMS[:2])):
            service.run_store.save_items(run, stage, copy.deepcopy(values))
        service.run_store.save_summary(run, "zh", REPORT)
        service.run_store.update_meta(run, {"status": "completed", "duration_seconds": 4.5, "tokens": {"input": 120, "output": 30, "total": 150}, "stage_durations": {"raw": 1, "scored": 1, "filtered": 1, "enriched": 1}})
        service.archive.mkdir()
        (service.archive / "horizon-2026-11-04-zh.md").write_text(REPORT)
        print(f"离线验收数据目录：{data}", flush=True)
        app = create_app(workspace=root, data_dir=data, service=service, wechat_client_factory=BrowserWeChat, static_dir=ROOT / "web/dist")
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

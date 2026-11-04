"""同端口托管 API 与 React 构建产物的本地入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Horizon 本地 Web 控制台")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost", "::1"], help="本机监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="本地数据目录")
    parser.add_argument("--config", type=Path, default=None, help="配置文件，默认 <data-dir>/config.json")
    parser.add_argument("--runs-dir", type=Path, default=None, help="阶段工件目录，默认 <data-dir>/mcp-runs")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须介于 1 与 65535 之间")
    import uvicorn
    app = create_app(data_dir=args.data_dir, config_path=args.config, runs_dir=args.runs_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

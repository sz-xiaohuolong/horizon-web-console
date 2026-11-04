"""命令行与本地控制台共享的流水线互斥锁。"""

from pathlib import Path
from filelock import FileLock


def run_lock(data_dir: Path | str) -> FileLock:
    path = Path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return FileLock(path / ".horizon-run.lock", timeout=0, thread_local=False, mode=0o600)

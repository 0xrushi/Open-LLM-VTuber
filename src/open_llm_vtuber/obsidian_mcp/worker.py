"""RQ worker entry point for background jobs.

Start with:
    uv run python -m open_llm_vtuber.obsidian_mcp.worker
"""
import sys
import os
from pathlib import Path
import platform

_src = str(Path(__file__).resolve().parents[2])
if _src not in sys.path:
    sys.path.insert(0, _src)

from redis import Redis
from rq import Worker, Queue, SimpleWorker


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    conn = Redis.from_url(redis_url)
    queues = [
        Queue("obsidian-tools", connection=conn),
        Queue("web-search", connection=conn),
    ]
    # macOS + forking workers can crash with Objective-C runtime init-after-fork errors.
    # Use SimpleWorker on Darwin to execute jobs in-process safely.
    worker_cls = SimpleWorker if platform.system() == "Darwin" else Worker
    worker_name = getattr(worker_cls, "__name__", str(worker_cls))
    queue_names = ", ".join(q.name for q in queues)
    print(
        f"RQ worker starting with {worker_name} "
        f"(queues: {queue_names}, redis={redis_url}) ..."
    )
    worker_cls(queues, connection=conn).work()


if __name__ == "__main__":
    main()

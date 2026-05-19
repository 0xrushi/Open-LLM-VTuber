"""ObsidianJobQueue — Redis/RQ wrapper for non-blocking Obsidian tool calls."""
from __future__ import annotations

import os
from typing import Tuple, Optional
from loguru import logger


class ObsidianJobQueue:
    """Thin wrapper around rq.Queue for Obsidian tool background jobs.

    Falls back gracefully when Redis is not available.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = os.environ.get("REDIS_URL", redis_url)
        self._redis = None
        self._queue = None
        self._init()

    def _init(self) -> None:
        try:
            from redis import Redis
            from rq import Queue

            self._redis = Redis.from_url(self._redis_url)
            self._queue = Queue("obsidian-tools", connection=self._redis)
        except Exception as exc:
            logger.warning(f"ObsidianJobQueue: Redis unavailable ({exc}). Will fall back to sync.")
            self._redis = None
            self._queue = None

    def is_available(self) -> bool:
        if self._redis is None:
            return False
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

    def enqueue(
        self,
        tool_name: str,
        tool_args: dict,
        vault_path: str,
        embed_base_url: str,
        embed_model: str,
    ) -> str:
        """Enqueue a tool call and return the job_id string."""
        if self._queue is None:
            raise RuntimeError("Redis queue not available")
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        job = self._queue.enqueue(
            run_obsidian_tool,
            tool_name,
            tool_args,
            vault_path,
            embed_base_url,
            embed_model,
            job_timeout=120,
        )
        logger.info(f"Obsidian job enqueued: {job.id} ({tool_name})")
        return job.id

    def get_result(self, job_id: str) -> Tuple[str, Optional[str]]:
        """Return (status, result_or_None).

        Status values: "queued" | "started" | "finished" | "failed"
        """
        from rq.job import Job

        try:
            job = Job.fetch(job_id, connection=self._redis)
        except Exception:
            return ("failed", None)

        raw = job.get_status()
        status = raw.value if hasattr(raw, "value") else str(raw)
        if status == "finished":
            return ("finished", str(job.result) if job.result is not None else "")
        if status in ("failed", "stopped", "canceled", "cancelled"):
            exc_info = getattr(job, "exc_info", None) or ""
            return ("failed", str(exc_info)[:500] if exc_info else None)
        return (status, None)

    def cleanup(self, job_id: str) -> None:
        """Delete a finished or failed job from Redis."""
        from rq.job import Job

        try:
            job = Job.fetch(job_id, connection=self._redis)
            job.delete()
        except Exception:
            pass

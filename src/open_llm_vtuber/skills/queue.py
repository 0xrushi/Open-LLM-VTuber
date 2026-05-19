"""WebSearchJobQueue — Redis/RQ wrapper for non-blocking pi web search calls."""
from __future__ import annotations

import os
from typing import Tuple, Optional
from loguru import logger


class WebSearchJobQueue:
    """Thin wrapper around rq.Queue for web search background jobs.

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
            self._queue = Queue("web-search", connection=self._redis)
        except Exception as exc:
            logger.warning(f"WebSearchJobQueue: Redis unavailable ({exc}). Will fall back to sync.")
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
        query: str,
        max_results: int,
        pi_bin: str,
        skill_name: str,
        provider: str | None,
        model: str | None,
    ) -> str:
        """Enqueue a web search job and return the job_id string."""
        if self._queue is None:
            raise RuntimeError("Redis queue not available")
        from open_llm_vtuber.skills.tasks import run_pi_web_search

        job = self._queue.enqueue(
            run_pi_web_search,
            query,
            max_results,
            pi_bin,
            skill_name,
            provider,
            model,
            job_timeout=300,
        )
        logger.info(f"Web search job enqueued: {job.id} (query={query!r})")
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

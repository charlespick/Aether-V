"""Asynchronous coordination of remote WinRM/PowerShell operations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from ..core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RemoteTaskCategory(str, Enum):
    """High level buckets used for logging and diagnostics."""

    DEPLOYMENT = "deployment"
    INVENTORY = "inventory"
    JOB = "job"
    GENERAL = "general"


class RemoteTaskTimeoutError(TimeoutError):
    """Raised when a remote task exceeds its allotted execution window."""


@dataclass(slots=True)
class _RemoteTask:
    """Internal representation of queued remote work."""

    hostname: str
    func: Callable[..., Any]
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    future: asyncio.Future[Any]
    description: str
    category: RemoteTaskCategory
    timeout: Optional[float]
    queue_name: str
    track_duration: bool
    submitted_at: float = field(default_factory=monotonic)


class RemoteTaskService:
    """Central queue with adaptive concurrency for remote host operations."""

    def __init__(self) -> None:
        self._fast_queue: Optional[asyncio.Queue[Optional[_RemoteTask]]] = None
        self._job_queue: Optional[asyncio.Queue[Optional[_RemoteTask]]] = None
        self._fast_workers: set[asyncio.Task[None]] = set()
        self._job_workers: set[asyncio.Task[None]] = set()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._min_concurrency = 1
        self._max_concurrency = 1
        self._scale_up_backlog = 1
        self._scale_up_duration_threshold = 5.0
        self._idle_seconds = 30.0
        self._job_concurrency = 1
        self._avg_duration = 0.0
        self._completed = 0
        self._fast_inflight = 0
        self._fast_current_workers = 0
        self._job_current_workers = 0
        self._job_inflight = 0

    async def start(self) -> None:
        """Initialise the worker pool if it is not already running."""

        async with self._start_lock:
            if self._started:
                return

            self._fast_queue = asyncio.Queue()
            self._job_queue = asyncio.Queue()
            self._started = True

            self._min_concurrency = max(1, settings.remote_task_min_concurrency)
            self._max_concurrency = max(
                self._min_concurrency, settings.remote_task_max_concurrency
            )
            self._scale_up_backlog = max(1, settings.remote_task_scale_up_backlog)
            self._idle_seconds = max(1.0, float(settings.remote_task_idle_seconds))
            self._scale_up_duration_threshold = max(
                1.0, float(settings.remote_task_scale_up_duration_threshold)
            )
            self._job_concurrency = max(1, settings.remote_task_job_concurrency)
            self._avg_duration = 0.0
            self._completed = 0
            self._fast_inflight = 0
            self._fast_current_workers = 0
            self._job_current_workers = 0
            self._job_inflight = 0

            for _ in range(self._min_concurrency):
                self._spawn_worker("fast")

            for _ in range(self._job_concurrency):
                self._spawn_worker("job")

            logger.info(
                (
                    "Remote task service started "
                    "(fast_min=%d, fast_max=%d, job=%d, idle_timeout=%.1fs)"
                ),
                self._min_concurrency,
                self._max_concurrency,
                self._job_concurrency,
                self._idle_seconds,
            )

    async def stop(self) -> None:
        """Stop all workers and drain the queue."""

        async with self._start_lock:
            if not self._started:
                return

            assert self._fast_queue is not None
            assert self._job_queue is not None
            self._started = False

            fast_workers = self._fast_current_workers
            for _ in range(fast_workers):
                await self._fast_queue.put(None)

            job_workers = self._job_current_workers
            for _ in range(job_workers):
                await self._job_queue.put(None)

        await asyncio.gather(
            *self._fast_workers,
            *self._job_workers,
            return_exceptions=True,
        )
        self._fast_workers.clear()
        self._job_workers.clear()
        self._fast_current_workers = 0
        self._job_current_workers = 0
        self._fast_inflight = 0
        self._fast_queue = None
        self._job_queue = None
        logger.info("Remote task service stopped")

    async def run_blocking(
        self,
        hostname: str,
        func: Callable[..., T],
        *args: Any,
        description: str,
        category: RemoteTaskCategory = RemoteTaskCategory.GENERAL,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> T:
        """Schedule a blocking callable to run under concurrency control."""

        if not self._started:
            await self.start()

        if timeout is not None:
            timeout = max(0.1, float(timeout))

        assert self._fast_queue is not None
        assert self._job_queue is not None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        queue_name = "job" if category is RemoteTaskCategory.JOB else "fast"
        task = _RemoteTask(
            hostname=hostname,
            func=func,
            args=args,
            kwargs=kwargs,
            future=future,
            description=description,
            category=category,
            timeout=timeout,
            queue_name=queue_name,
            track_duration=category is not RemoteTaskCategory.JOB,
        )

        target_queue = self._job_queue if queue_name == "job" else self._fast_queue
        await target_queue.put(task)
        if queue_name == "fast":
            self._maybe_scale_up()

        try:
            return await future
        finally:
            if future.cancelled():
                logger.debug(
                    "Remote task for %s (%s) was cancelled before completion",
                    hostname,
                    description,
                )

    def _spawn_worker(self, queue_name: str) -> None:
        if queue_name == "fast":
            assert self._fast_queue is not None
            worker_set = self._fast_workers
        else:
            assert self._job_queue is not None
            worker_set = self._job_workers

        worker = asyncio.create_task(
            self._worker(queue_name), name=f"remote-task-worker-{queue_name}"
        )
        worker_set.add(worker)
        if queue_name == "fast":
            self._fast_current_workers += 1
        else:
            self._job_current_workers += 1

        def _cleanup(task: asyncio.Task[None]) -> None:
            worker_set.discard(task)

        worker.add_done_callback(_cleanup)

    async def _worker(self, queue_name: str) -> None:
        queue = self._fast_queue if queue_name == "fast" else self._job_queue
        assert queue is not None
        metrics_enabled = queue_name == "fast"
        try:
            while True:
                if queue_name == "fast":
                    try:
                        item = await asyncio.wait_for(
                            queue.get(), timeout=self._idle_seconds
                        )
                    except asyncio.TimeoutError:
                        if self._fast_current_workers > self._min_concurrency:
                            logger.debug(
                                "Remote task worker idle for %.1fs; scaling down",
                                self._idle_seconds,
                            )
                            break
                        continue
                else:
                    item = await queue.get()

                if item is None:
                    queue.task_done()
                    break

                task = item

                if task.future.cancelled():
                    logger.debug(
                        "Discarding cancelled remote task (%s) for %s before execution",
                        task.description,
                        task.hostname,
                    )
                    queue.task_done()
                    continue

                start = monotonic()
                if queue_name == "fast":
                    self._fast_inflight += 1
                else:
                    self._job_inflight += 1
                try:
                    result = await self._execute_task(task)
                except Exception as exc:  # pragma: no cover - defensive logging
                    if not task.future.done():
                        task.future.set_exception(exc)
                else:
                    if not task.future.done():
                        task.future.set_result(result)
                finally:
                    if queue_name == "fast":
                        self._fast_inflight -= 1
                    else:
                        self._job_inflight -= 1
                    duration = monotonic() - start
                    if metrics_enabled and task.track_duration:
                        self._update_metrics(duration)
                    queue.task_done()
        finally:
            if queue_name == "fast":
                self._fast_current_workers -= 1
            else:
                self._job_current_workers -= 1

    async def _execute_task(self, task: _RemoteTask) -> Any:
        logger.debug(
            "Starting remote %s task on %s: %s",
            task.category.value,
            task.hostname,
            task.description,
        )

        run_coro = asyncio.to_thread(task.func, *task.args, **task.kwargs)
        try:
            if task.timeout is not None:
                result = await asyncio.wait_for(run_coro, timeout=task.timeout)
            else:
                result = await run_coro
        except asyncio.TimeoutError as exc:
            message = (
                f"Remote task '{task.description}' on {task.hostname} timed out after "
                f"{task.timeout:.1f}s"
            )
            logger.warning(message)
            raise RemoteTaskTimeoutError(message) from exc
        except Exception:
            logger.exception(
                "Remote task '%s' on %s raised an exception",
                task.description,
                task.hostname,
            )
            raise
        else:
            logger.debug(
                "Remote %s task on %s completed: %s",
                task.category.value,
                task.hostname,
                task.description,
            )
            return result

    def _update_metrics(self, duration: float) -> None:
        self._completed += 1
        if self._avg_duration <= 0.0:
            self._avg_duration = duration
        else:
            self._avg_duration = (self._avg_duration * 0.8) + (duration * 0.2)

    def _maybe_scale_up(self) -> None:
        if not self._started or self._fast_queue is None:
            return

        backlog = self._fast_queue.qsize()
        if backlog < self._scale_up_backlog:
            return

        if self._fast_current_workers >= self._max_concurrency:
            return

        if self._avg_duration > 0.0 and (
            self._avg_duration >= self._scale_up_duration_threshold
        ):
            logger.debug(
                "Skipping fast-pool scale up because average duration %.2fs exceeds threshold %.2fs",
                self._avg_duration,
                self._scale_up_duration_threshold,
            )
            return

        self._spawn_worker("fast")
        logger.debug(
            "Scaled remote task workers to %d (backlog=%d, avg_duration=%.2fs)",
            self._fast_current_workers,
            backlog,
            self._avg_duration,
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of the internal worker pool state."""

        fast_depth = self._fast_queue.qsize() if self._fast_queue else 0
        job_depth = self._job_queue.qsize() if self._job_queue else 0
        return {
            "started": self._started,
            "average_duration_seconds": self._avg_duration,
            "completed_tasks": self._completed,
            "scale_up_backlog_threshold": self._scale_up_backlog,
            "scale_up_duration_threshold_seconds": self._scale_up_duration_threshold,
            "idle_timeout_seconds": self._idle_seconds,
            "fast_pool": {
                "queue_depth": fast_depth,
                "inflight": self._fast_inflight,
                "current_workers": self._fast_current_workers,
                "min_workers": self._min_concurrency,
                "max_workers": self._max_concurrency,
                "configured_workers": None,
            },
            "job_pool": {
                "queue_depth": job_depth,
                "inflight": self._job_inflight,
                "current_workers": self._job_current_workers,
                "min_workers": None,
                "max_workers": None,
                "configured_workers": self._job_concurrency,
            },
        }


remote_task_service = RemoteTaskService()

__all__ = [
    "remote_task_service",
    "RemoteTaskService",
    "RemoteTaskCategory",
    "RemoteTaskTimeoutError",
]

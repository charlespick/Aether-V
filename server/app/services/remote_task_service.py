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
    submitted_at: float = field(default_factory=monotonic)


class RemoteTaskService:
    """Central queue with adaptive concurrency for remote host operations."""

    def __init__(self) -> None:
        self._queue: Optional[asyncio.Queue[Optional[_RemoteTask]]] = None
        self._workers: set[asyncio.Task[None]] = set()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._min_concurrency = 1
        self._max_concurrency = 1
        self._scale_up_backlog = 1
        self._scale_up_duration_threshold = 5.0
        self._idle_seconds = 30.0
        self._avg_duration = 0.0
        self._completed = 0
        self._inflight = 0
        self._current_workers = 0

    async def start(self) -> None:
        """Initialise the worker pool if it is not already running."""

        async with self._start_lock:
            if self._started:
                return

            self._queue = asyncio.Queue()
            self._started = True

            self._min_concurrency = max(1, settings.remote_task_min_concurrency)
            self._max_concurrency = max(
                self._min_concurrency, settings.remote_task_max_concurrency
            )
            self._scale_up_backlog = max(1, settings.remote_task_scale_up_backlog)
            self._idle_seconds = max(1.0, float(settings.remote_task_idle_seconds))
            self._scale_up_duration_threshold = max(
                1.0, float(settings.winrm_operation_timeout) / 2.0
            )
            self._avg_duration = 0.0
            self._completed = 0
            self._inflight = 0
            self._current_workers = 0

            for _ in range(self._min_concurrency):
                self._spawn_worker()

            logger.info(
                "Remote task service started (min=%d, max=%d, idle_timeout=%.1fs)",
                self._min_concurrency,
                self._max_concurrency,
                self._idle_seconds,
            )

    async def stop(self) -> None:
        """Stop all workers and drain the queue."""

        async with self._start_lock:
            if not self._started:
                return

            assert self._queue is not None
            self._started = False

            worker_count = self._current_workers
            for _ in range(worker_count):
                await self._queue.put(None)

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._queue = None
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

        assert self._queue is not None
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        task = _RemoteTask(
            hostname=hostname,
            func=func,
            args=args,
            kwargs=kwargs,
            future=future,
            description=description,
            category=category,
            timeout=timeout,
        )

        await self._queue.put(task)
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

    def _spawn_worker(self) -> None:
        assert self._queue is not None

        worker = asyncio.create_task(self._worker(), name="remote-task-worker")
        self._workers.add(worker)
        self._current_workers += 1

        def _cleanup(task: asyncio.Task[None]) -> None:
            self._workers.discard(task)

        worker.add_done_callback(_cleanup)

    async def _worker(self) -> None:
        assert self._queue is not None
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(), timeout=self._idle_seconds
                    )
                except asyncio.TimeoutError:
                    if self._current_workers > self._min_concurrency:
                        logger.debug(
                            "Remote task worker idle for %.1fs; scaling down",
                            self._idle_seconds,
                        )
                        break
                    continue

                if item is None:
                    self._queue.task_done()
                    break

                task = item

                if task.future.cancelled():
                    logger.debug(
                        "Discarding cancelled remote task (%s) for %s before execution",
                        task.description,
                        task.hostname,
                    )
                    self._queue.task_done()
                    continue

                start = monotonic()
                self._inflight += 1
                try:
                    result = await self._execute_task(task)
                except Exception as exc:  # pragma: no cover - defensive logging
                    if not task.future.done():
                        task.future.set_exception(exc)
                else:
                    if not task.future.done():
                        task.future.set_result(result)
                finally:
                    self._inflight -= 1
                    duration = monotonic() - start
                    self._update_metrics(duration)
                    self._queue.task_done()
        finally:
            self._current_workers -= 1

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
        if not self._started or self._queue is None:
            return

        backlog = self._queue.qsize()
        if backlog < self._scale_up_backlog:
            return

        if self._current_workers >= self._max_concurrency:
            return

        if (
            self._avg_duration > 0.0
            and self._avg_duration > self._scale_up_duration_threshold
        ):
            return

        self._spawn_worker()
        logger.debug(
            "Scaled remote task workers to %d (backlog=%d, avg_duration=%.2fs)",
            self._current_workers,
            backlog,
            self._avg_duration,
        )


remote_task_service = RemoteTaskService()

__all__ = [
    "remote_task_service",
    "RemoteTaskService",
    "RemoteTaskCategory",
    "RemoteTaskTimeoutError",
]

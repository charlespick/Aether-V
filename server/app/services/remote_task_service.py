"""Asynchronous coordination of remote WinRM/PowerShell operations.

This module provides static concurrency control with:
- Global maximum WinRM connections (48 by default)
- Per-host serialization for IO-intensive operations (disk creation, guest init)
- Rate-limited dispatcher for short jobs (1 per second)
- No dynamic scaling - simple, predictable behavior
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Callable, Deque, Dict, Optional, Set, Tuple, TypeVar

from ..core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RemoteTaskCategory(str, Enum):
    """Task categories that determine execution behavior.
    
    IO: IO-intensive operations (disk creation, guest initialization)
        - Per-host serialization (only one IO task per host at a time)
        - Longer timeout (io_job_timeout_seconds)
    
    SHORT: All other operations (inventory, VM actions, CRUD, deployment)
        - Rate-limited dispatch (one per second to prevent spikes)
        - Shorter timeout (short_job_timeout_seconds)
        - No per-host limit
    """

    IO = "io"
    SHORT = "short"
    # Legacy categories mapped to SHORT for backwards compatibility
    DEPLOYMENT = "short"
    INVENTORY = "short"
    JOB = "io"  # Legacy JOB category maps to IO for long-running jobs
    GENERAL = "short"


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
    """Central queue with static concurrency limits for remote host operations.
    
    Architecture:
    - Global semaphore limits total concurrent WinRM connections
    - IO queue: Per-host serialization for disk/guest-init operations
    - Short queue: Rate-limited dispatch (1/second) for everything else
    """

    def __init__(self) -> None:
        # Global connection limit
        self._global_semaphore: Optional[asyncio.Semaphore] = None
        self._max_connections = 48
        
        # Short job queue with rate-limited dispatcher
        self._short_queue: Optional[asyncio.Queue[Optional[_RemoteTask]]] = None
        self._short_dispatcher_task: Optional[asyncio.Task[None]] = None
        self._dispatch_interval = 1.0  # seconds between short job dispatches
        
        # IO job queue with per-host serialization
        self._io_queue: Optional[asyncio.Queue[Optional[_RemoteTask]]] = None
        self._io_worker_task: Optional[asyncio.Task[None]] = None
        self._host_io_locks: Dict[str, asyncio.Lock] = {}
        
        # Service state
        self._started = False
        self._start_lock = asyncio.Lock()
        
        # Metrics
        self._completed_short = 0
        self._completed_io = 0
        self._short_inflight = 0
        self._io_inflight = 0
        self._total_connections = 0  # Current active connections

    async def start(self) -> None:
        """Initialize the task queues and dispatcher."""

        async with self._start_lock:
            if self._started:
                return

            # Load configuration
            self._max_connections = max(1, settings.max_winrm_connections)
            self._dispatch_interval = max(0.1, settings.short_job_dispatch_interval_seconds)
            
            # Initialize global semaphore
            self._global_semaphore = asyncio.Semaphore(self._max_connections)
            
            # Initialize queues
            self._short_queue = asyncio.Queue()
            self._io_queue = asyncio.Queue()
            
            # Reset metrics
            self._completed_short = 0
            self._completed_io = 0
            self._short_inflight = 0
            self._io_inflight = 0
            self._total_connections = 0
            self._host_io_locks.clear()
            
            # Start dispatcher for short jobs (rate-limited)
            self._short_dispatcher_task = asyncio.create_task(
                self._short_job_dispatcher(),
                name="remote-task-short-dispatcher",
            )
            
            # Start worker for IO jobs (per-host serialized)
            self._io_worker_task = asyncio.create_task(
                self._io_job_worker(),
                name="remote-task-io-worker",
            )
            
            self._started = True
            logger.info(
                "Remote task service started (max_connections=%d, dispatch_interval=%.1fs)",
                self._max_connections,
                self._dispatch_interval,
            )

    async def stop(self) -> None:
        """Stop all workers and drain the queues."""

        async with self._start_lock:
            if not self._started:
                return

            self._started = False

            # Signal queues to stop
            if self._short_queue is not None:
                await self._short_queue.put(None)
            if self._io_queue is not None:
                await self._io_queue.put(None)

        # Wait for workers to complete
        if self._short_dispatcher_task is not None:
            try:
                await asyncio.wait_for(self._short_dispatcher_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._short_dispatcher_task.cancel()
                try:
                    await self._short_dispatcher_task
                except asyncio.CancelledError:
                    pass
            self._short_dispatcher_task = None

        if self._io_worker_task is not None:
            try:
                await asyncio.wait_for(self._io_worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._io_worker_task.cancel()
                try:
                    await self._io_worker_task
                except asyncio.CancelledError:
                    pass
            self._io_worker_task = None

        self._short_queue = None
        self._io_queue = None
        self._global_semaphore = None
        self._host_io_locks.clear()
        
        logger.info("Remote task service stopped")

    async def run_blocking(
        self,
        hostname: str,
        func: Callable[..., T],
        *args: Any,
        description: str,
        category: RemoteTaskCategory = RemoteTaskCategory.SHORT,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> T:
        """Schedule a blocking callable to run under concurrency control.
        
        Args:
            hostname: Target host for the operation
            func: Blocking callable to execute
            *args: Positional arguments for func
            description: Human-readable description for logging
            category: Task category (IO or SHORT)
            timeout: Optional timeout in seconds
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func execution
            
        Raises:
            RemoteTaskTimeoutError: If task exceeds timeout
        """

        if not self._started:
            await self.start()

        if timeout is not None:
            timeout = max(0.1, float(timeout))

        assert self._short_queue is not None
        assert self._io_queue is not None

        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        
        # Normalize category for legacy compatibility
        effective_category = self._normalize_category(category)
        
        task = _RemoteTask(
            hostname=hostname,
            func=func,
            args=args,
            kwargs=kwargs,
            future=future,
            description=description,
            category=effective_category,
            timeout=timeout,
        )

        # Route to appropriate queue
        if effective_category == RemoteTaskCategory.IO:
            await self._io_queue.put(task)
        else:
            await self._short_queue.put(task)

        try:
            return await future
        finally:
            if future.cancelled():
                logger.debug(
                    "Remote task for %s (%s) was cancelled before completion",
                    hostname,
                    description,
                )

    def _normalize_category(self, category: RemoteTaskCategory) -> RemoteTaskCategory:
        """Normalize legacy categories to IO or SHORT."""
        # Handle enum value comparison for legacy categories
        if category.value == "io":
            return RemoteTaskCategory.IO
        return RemoteTaskCategory.SHORT

    async def _short_job_dispatcher(self) -> None:
        """Dispatch short jobs at a rate-limited pace (1 per second).
        
        This prevents spikes of load by spreading job execution over time.
        Each job still respects the global connection limit.
        """
        assert self._short_queue is not None
        
        try:
            while self._started:
                task = await self._short_queue.get()
                
                if task is None:
                    self._short_queue.task_done()
                    break
                
                if task.future.cancelled():
                    logger.debug(
                        "Discarding cancelled short task (%s) for %s",
                        task.description,
                        task.hostname,
                    )
                    self._short_queue.task_done()
                    continue
                
                # Execute the task (acquires global semaphore)
                asyncio.create_task(
                    self._execute_short_task(task),
                    name=f"short-task-{task.hostname}",
                )
                
                self._short_queue.task_done()
                
                # Rate limit: wait before dispatching next job
                await asyncio.sleep(self._dispatch_interval)
                
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Short job dispatcher failed")

    async def _execute_short_task(self, task: _RemoteTask) -> None:
        """Execute a short task with global connection limiting."""
        assert self._global_semaphore is not None
        
        async with self._global_semaphore:
            self._total_connections += 1
            self._short_inflight += 1
            try:
                result = await self._execute_task(task)
                if not task.future.done():
                    task.future.set_result(result)
            except Exception as exc:
                if not task.future.done():
                    task.future.set_exception(exc)
            finally:
                self._short_inflight -= 1
                self._total_connections -= 1
                self._completed_short += 1

    async def _io_job_worker(self) -> None:
        """Process IO jobs with per-host serialization.
        
        Only one IO operation (disk creation or guest initialization)
        can run per host at a time to prevent IO overload.
        """
        assert self._io_queue is not None
        
        try:
            while self._started:
                task = await self._io_queue.get()
                
                if task is None:
                    self._io_queue.task_done()
                    break
                
                if task.future.cancelled():
                    logger.debug(
                        "Discarding cancelled IO task (%s) for %s",
                        task.description,
                        task.hostname,
                    )
                    self._io_queue.task_done()
                    continue
                
                # Execute with per-host serialization
                asyncio.create_task(
                    self._execute_io_task(task),
                    name=f"io-task-{task.hostname}",
                )
                
                self._io_queue.task_done()
                
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("IO job worker failed")

    async def _execute_io_task(self, task: _RemoteTask) -> None:
        """Execute an IO task with per-host serialization and global connection limiting."""
        assert self._global_semaphore is not None
        
        # Get or create per-host lock for IO serialization
        host_key = task.hostname.lower().strip()
        if host_key not in self._host_io_locks:
            self._host_io_locks[host_key] = asyncio.Lock()
        host_lock = self._host_io_locks[host_key]
        
        # Acquire host lock first (ensures only one IO op per host)
        async with host_lock:
            # Then acquire global semaphore (ensures total connection limit)
            async with self._global_semaphore:
                self._total_connections += 1
                self._io_inflight += 1
                try:
                    result = await self._execute_task(task)
                    if not task.future.done():
                        task.future.set_result(result)
                except Exception as exc:
                    if not task.future.done():
                        task.future.set_exception(exc)
                finally:
                    self._io_inflight -= 1
                    self._total_connections -= 1
                    self._completed_io += 1

    async def _execute_task(self, task: _RemoteTask) -> Any:
        """Execute a task in a thread pool with timeout handling."""
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

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of the service state for diagnostics."""

        short_depth = self._short_queue.qsize() if self._short_queue else 0
        io_depth = self._io_queue.qsize() if self._io_queue else 0
        
        return {
            "started": self._started,
            "max_connections": self._max_connections,
            "total_connections": self._total_connections,
            "dispatch_interval_seconds": self._dispatch_interval,
            "short_queue": {
                "queue_depth": short_depth,
                "inflight": self._short_inflight,
                "completed": self._completed_short,
            },
            "io_queue": {
                "queue_depth": io_depth,
                "inflight": self._io_inflight,
                "completed": self._completed_io,
                "hosts_with_active_io": len([
                    h for h, lock in self._host_io_locks.items() if lock.locked()
                ]),
            },
        }


remote_task_service = RemoteTaskService()

__all__ = [
    "remote_task_service",
    "RemoteTaskService",
    "RemoteTaskCategory",
    "RemoteTaskTimeoutError",
]

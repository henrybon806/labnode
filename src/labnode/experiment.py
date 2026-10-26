"""The Experiment base class and the state machine every node shares."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from labnode._version import __version__


IDLE = "idle"
BUSY = "busy"
STOPPING = "stopping"
DONE = "done"
STOPPED = "stopped"
ERROR = "error"

# States where a sample is still sitting in the instrument and must be collected.
OCCUPIED_STATES = {BUSY, STOPPING, DONE, STOPPED, ERROR}
COLLECTABLE_STATES = {DONE, STOPPED, ERROR}


class NodeConflict(Exception):
    """The request does not make sense in the node's current state (HTTP 409)."""


class NotSupported(Exception):
    """The node did not implement the requested optional feature (HTTP 501)."""


class Experiment:
    """Subclass this, set ``name`` and implement ``run``. Everything else is optional.

    ``run`` executes in a background thread. Return when the experiment is
    finished; the return value (anything JSON-serialisable) shows up as
    ``result`` in ``/status``. Raise to report an error.

    Long runs should check ``self.stop_requested`` between steps so an
    emergency stop can end them cleanly.
    """

    name = "experiment"

    def run(self, sample_id: str, params: dict[str, Any]) -> Any:
        raise NotImplementedError

    def stop(self) -> None:
        """Halt the instrument right now (emergency stop). Optional."""
        raise NotImplementedError

    def estimate(self, params: dict[str, Any]) -> Optional[float]:
        """Expected run time in seconds, used for ``remaining``. Optional."""
        return None

    def position(self) -> dict[str, float]:
        """Current position, e.g. ``{"x": .., "y": .., "z": ..}``. Gantry nodes only."""
        raise NotImplementedError

    # ------------------------------------------------------------- internals
    # Managed by labnode; subclasses should not need to touch these. Set up in
    # __new__ so subclasses may define __init__ without calling super().

    def __new__(cls, *args: Any, **kwargs: Any) -> "Experiment":
        node = super().__new__(cls)
        node._init_state()
        return node

    def _init_state(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = IDLE
        self._sample_id: Optional[str] = None
        self._params: dict[str, Any] = {}
        self._started_at: Optional[float] = None
        self._started_monotonic: Optional[float] = None
        self._finished_monotonic: Optional[float] = None
        self._estimated: Optional[float] = None
        self._result: Any = None
        self._error: Optional[str] = None

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @classmethod
    def supports(cls, feature: str) -> bool:
        return getattr(cls, feature) is not getattr(Experiment, feature)

    def status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = None
            if self._started_monotonic is not None:
                end = self._finished_monotonic or time.monotonic()
                elapsed = end - self._started_monotonic
            remaining = None
            if self._state in (BUSY, STOPPING) and self._estimated is not None and elapsed is not None:
                remaining = max(0.0, self._estimated - elapsed)
            return {
                "name": self.name,
                "kind": "experiment",
                "labnode": __version__,
                "state": self._state,
                "busy": self._state in (BUSY, STOPPING),
                "occupied": self._state in OCCUPIED_STATES,
                "sample_id": self._sample_id,
                "params": self._params,
                "started_at": self._started_at,
                "elapsed": elapsed,
                "estimated_duration": self._estimated,
                "remaining": remaining,
                "result": self._result,
                "error": self._error,
                "supports": {
                    feature: self.supports(feature) for feature in ("stop", "position")
                },
            }

    def start(self, sample_id: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params = dict(params or {})
        with self._lock:
            if self._state != IDLE:
                raise NodeConflict(
                    f"{self.name} is {self._state} with sample {self._sample_id}; "
                    "it must be idle to start"
                )
            self._stop_event.clear()
            self._state = BUSY
            self._sample_id = sample_id
            self._params = params
            self._started_at = time.time()
            self._started_monotonic = time.monotonic()
            self._finished_monotonic = None
            self._result = None
            self._error = None
            self._estimated = None
            self._thread = threading.Thread(
                target=self._worker, args=(sample_id, params),
                name=f"{self.name}-run", daemon=True,
            )
        try:
            self._estimated = self.estimate(params)
        except Exception:
            self._estimated = None
        self._thread.start()
        return self.status()

    def _worker(self, sample_id: str, params: dict[str, Any]) -> None:
        try:
            result = self.run(sample_id, params)
            error = None
        except Exception as exc:
            result = None
            error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._finished_monotonic = time.monotonic()
            self._result = result
            self._error = error
            if error is not None:
                self._state = ERROR
            elif self._stop_event.is_set():
                self._state = STOPPED
            else:
                self._state = DONE

    def request_stop(self) -> dict[str, Any]:
        if not self.supports("stop"):
            raise NotSupported(f"{self.name} does not implement stop()")
        with self._lock:
            if self._state not in (BUSY, STOPPING):
                raise NodeConflict(f"{self.name} is {self._state}; nothing to stop")
            self._state = STOPPING
            self._stop_event.set()
        self.stop()
        return self.status()

    def mark_taken(self, sample_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            if self._state not in COLLECTABLE_STATES:
                raise NodeConflict(f"{self.name} is {self._state}; nothing to collect")
            if sample_id is not None and sample_id != self._sample_id:
                raise NodeConflict(
                    f"{self.name} holds sample {self._sample_id}, not {sample_id}"
                )
            self._state = IDLE
            self._sample_id = None
            self._params = {}
            self._started_at = None
            self._started_monotonic = None
            self._finished_monotonic = None
            self._estimated = None
            self._result = None
            self._error = None
        return self.status()

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the current run finishes (mainly for tests and scripts)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

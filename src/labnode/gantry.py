"""The Gantry base class: a node that moves, picks up and places samples."""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from labnode._version import __version__
from labnode.experiment import NodeConflict, NotSupported


IDLE = "idle"
BUSY = "busy"
ERROR = "error"

ACTIONS = ("move", "pick", "place", "home")


class Gantry:
    """Subclass this, set ``name`` and implement ``move`` and ``position``.

    ``pick``, ``place``, ``home`` and ``stop`` are optional; the ones you
    implement show up as ``true`` under ``supports`` in ``/status``.

    Every action runs in a background thread: return once it is finished,
    raise to report an error. Long actions should check
    ``self.stop_requested`` so an emergency stop can end them. ``params`` is
    whatever the caller sent (station name, sample id, speed, ...), so new
    needs do not require a protocol change.
    """

    name = "gantry"

    def move(self, x: float, y: float, z: Optional[float], params: dict[str, Any]) -> None:
        """Travel to (x, y), and to ``z`` if given. Return once arrived."""
        raise NotImplementedError

    def position(self) -> dict[str, float]:
        """Current position, e.g. ``{"x": .., "y": .., "z": ..}``."""
        raise NotImplementedError

    def pick(self, params: dict[str, Any]) -> None:
        """Pick up the sample under the head. Optional."""
        raise NotImplementedError

    def place(self, params: dict[str, Any]) -> None:
        """Put down the held sample under the head. Optional."""
        raise NotImplementedError

    def home(self, params: dict[str, Any]) -> None:
        """Run the homing routine. Optional."""
        raise NotImplementedError

    def stop(self) -> None:
        """Halt the gantry right now (emergency stop). Optional."""
        raise NotImplementedError

    # ------------------------------------------------------------- internals
    # Managed by labnode; set up in __new__ so subclasses may define __init__
    # without calling super().

    def __new__(cls, *args: Any, **kwargs: Any) -> "Gantry":
        node = super().__new__(cls)
        node._lock = threading.Lock()
        node._stop_event = threading.Event()
        node._thread: Optional[threading.Thread] = None
        node._state = IDLE
        node._action: Optional[str] = None
        node._target: Optional[dict[str, Any]] = None
        node._error: Optional[str] = None
        return node

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @classmethod
    def supports(cls, feature: str) -> bool:
        return getattr(cls, feature) is not getattr(Gantry, feature)

    def status(self) -> dict[str, Any]:
        try:
            position = self.position()
        except Exception:
            position = None
        with self._lock:
            return {
                "name": self.name,
                "kind": "gantry",
                "labnode": __version__,
                "state": self._state,
                "busy": self._state == BUSY,
                "action": self._action,
                "position": position,
                "target": self._target,
                "error": self._error,
                "supports": {
                    feature: self.supports(feature) for feature in ("pick", "place", "home", "stop")
                },
            }

    def start_move(self, x: float, y: float, z: Optional[float] = None,
                   params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params = dict(params or {})
        target = {"x": x, "y": y} if z is None else {"x": x, "y": y, "z": z}
        return self._start("move", target, lambda: self.move(x, y, z, params))

    def start_action(self, action: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Start ``pick``, ``place`` or ``home``."""
        if action not in ("pick", "place", "home"):
            raise ValueError(f"unknown action {action!r}")
        if not self.supports(action):
            raise NotSupported(f"{self.name} does not implement {action}()")
        params = dict(params or {})
        return self._start(action, None, lambda: getattr(self, action)(params))

    def _start(self, action: str, target: Optional[dict[str, Any]], work: Callable[[], None]) -> dict[str, Any]:
        with self._lock:
            if self._state == BUSY:
                raise NodeConflict(f"{self.name} is busy with {self._action}")
            self._stop_event.clear()
            self._state = BUSY
            self._action = action
            self._target = target
            self._error = None
            self._thread = threading.Thread(
                target=self._worker, args=(work,), name=f"{self.name}-{action}", daemon=True,
            )
        self._thread.start()
        return self.status()

    def _worker(self, work: Callable[[], None]) -> None:
        try:
            work()
            error = None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            if error is None and self._stop_event.is_set():
                error = "stopped"
            self._error = error
            self._state = IDLE if error is None else ERROR

    def request_stop(self) -> dict[str, Any]:
        if not self.supports("stop"):
            raise NotSupported(f"{self.name} does not implement stop()")
        with self._lock:
            if self._state != BUSY:
                raise NodeConflict(f"{self.name} is {self._state}; nothing to stop")
            self._stop_event.set()
        self.stop()
        return self.status()

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the current action finishes (mainly for tests and scripts)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

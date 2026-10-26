"""Watch nodes without waiting on them: one background thread per node.

A NodeListener polls one node (usually its /status) and keeps the latest
answer, so callers read it instantly instead of making a request. Share
listeners through a ListenerPool so each node is polled once however many
parts of a program are watching it.
"""

from __future__ import annotations

import threading
from typing import Any

from labnode.client import NodeClient, NodeError, NodeUnreachable


POLL_INTERVAL = 0.2
REQUEST_TIMEOUT = 0.5
NOT_STARTED = "not started"
UNREADABLE = "unreadable"

# (payload, problem, detail): problem is "" on success, else NOT_STARTED or UNREADABLE.
Reading = tuple[Any, str, str]
NO_ANSWER_YET: Reading = (None, NOT_STARTED, "no answer yet")


def fetch(address: str, path: str, timeout: float = REQUEST_TIMEOUT) -> Reading:
    """GET ``path`` from a node once. A /status that is not a labnode status is UNREADABLE."""
    try:
        payload = NodeClient(address, timeout=timeout).get(path)
    except NodeUnreachable as error:
        return None, NOT_STARTED, str(error)
    except (NodeError, ValueError) as error:
        return None, UNREADABLE, str(error) or type(error).__name__
    if path == "/status" and not (isinstance(payload, dict) and isinstance(payload.get("state"), str)):
        return None, UNREADABLE, "response is not a labnode status"
    return payload, "", ""


class NodeListener:
    """Polls one node path on its own thread and keeps the latest reading."""

    def __init__(self, address: str, path: str = "/status", interval: float = POLL_INTERVAL) -> None:
        self.address = address
        self.path = path
        self.interval = interval
        self._lock = threading.Lock()
        self._reading = NO_ANSWER_YET
        self._generation = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"listen {address}{path}", daemon=True)
        self._thread.start()

    def latest(self) -> Reading:
        with self._lock:
            return self._reading

    def update(self, payload: Any) -> None:
        """Store an answer the caller already has, e.g. the reply to a command.

        A poll that was in flight when this is called is thrown away, so an
        answer from before the command never overwrites it.
        """
        with self._lock:
            self._generation += 1
            self._reading = (payload, "", "")

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                generation = self._generation
            reading = fetch(self.address, self.path)
            with self._lock:
                if generation == self._generation:
                    self._reading = reading
            self._stop.wait(self.interval)


class ListenerPool:
    """Shares one listener per (address, path) between everyone who needs it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[tuple[str, str], NodeListener] = {}
        self._users: dict[tuple[str, str], int] = {}

    def acquire(self, address: str, path: str = "/status") -> NodeListener:
        key = (address, path)
        with self._lock:
            if key not in self._listeners:
                self._listeners[key] = NodeListener(address, path)
                self._users[key] = 0
            self._users[key] += 1
            return self._listeners[key]

    def release(self, listener: NodeListener) -> None:
        key = (listener.address, listener.path)
        with self._lock:
            if key not in self._users:
                return
            self._users[key] -= 1
            if self._users[key] > 0:
                return
            del self._users[key]
            listener = self._listeners.pop(key)
        listener.close()

    def close(self) -> None:
        with self._lock:
            listeners = list(self._listeners.values())
            self._listeners.clear()
            self._users.clear()
        for listener in listeners:
            listener.close()


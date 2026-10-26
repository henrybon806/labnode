"""Small stdlib HTTP client for talking to labnode servers."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


class NodeError(Exception):
    """The node answered with an HTTP error (``status`` holds the code)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class NodeUnreachable(OSError):
    """The node could not be contacted at all."""


def normalize_url(address: str) -> str:
    """Accept ``http://host:port``, ``host:port`` or a bare ``port`` (localhost)."""
    address = address.strip().rstrip("/")
    if not address:
        raise ValueError("empty node address")
    if "://" not in address:
        address = f"http://{address if ':' in address else '127.0.0.1:' + address}"
    parsed = urllib.parse.urlparse(address)
    if not parsed.hostname or parsed.port is None:
        raise ValueError(f"node address needs a host and port: {address}")
    return address


class NodeClient:
    def __init__(self, address: str, token: Optional[str] = None, timeout: float = 2.0) -> None:
        self.url = normalize_url(address)
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None, query: Optional[dict[str, Any]] = None) -> Any:
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except (ValueError, AttributeError):
                detail = raw
            raise NodeError(error.code, str(detail)) from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise NodeUnreachable(f"{self.url}: {reason}") from None

    def get(self, path: str, query: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, query=query)

    def status(self) -> dict[str, Any]:
        return self.get("/status")

    def position(self) -> dict[str, float]:
        return self.get("/position")

    def start(self, sample_id: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", "/start", {"sample_id": sample_id, "params": params or {}})

    def stop(self) -> dict[str, Any]:
        return self._request("POST", "/stop", {})

    def taken(self, sample_id: Optional[str] = None) -> dict[str, Any]:
        return self._request("POST", "/taken", {"sample_id": sample_id})

    # Gantry nodes only. Each starts the action and returns at once; watch
    # /status until "state" is "idle" again (or "error").

    def move(self, x: float, y: float, z: Optional[float] = None,
             params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", "/move", {"x": x, "y": y, "z": z, "params": params or {}})

    def pick(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", "/pick", {"params": params or {}})

    def place(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", "/place", {"params": params or {}})

    def home(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", "/home", {"params": params or {}})

"""FastAPI app that exposes an Experiment over HTTP."""

from __future__ import annotations

import os
import secrets
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from labnode.experiment import Experiment, NodeConflict, NotSupported


TOKEN_ENV = "LABNODE_TOKEN"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class StartRequest(BaseModel):
    sample_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class TakenRequest(BaseModel):
    sample_id: Optional[str] = None


def create_app(node: Experiment, token: Optional[str] = None) -> FastAPI:
    """Build the app. With ``token`` set, POST endpoints need ``Authorization: Bearer <token>``."""
    app = FastAPI(title=f"labnode: {node.name}", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> None:
        if token is None:
            return
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(status_code=401, detail="missing or wrong bearer token")

    def call(action, *args):
        try:
            return action(*args)
        except NodeConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except NotSupported as error:
            raise HTTPException(status_code=501, detail=str(error)) from None

    @app.get("/status", summary="Current state: idle, busy, stopping, done, stopped or error")
    def get_status() -> dict[str, Any]:
        return node.status()

    @app.post("/start", status_code=202, dependencies=[Depends(authorize)],
              summary="Start a run; 409 unless the node is idle")
    def post_start(request: StartRequest) -> dict[str, Any]:
        return call(node.start, request.sample_id, request.params)

    @app.post("/stop", dependencies=[Depends(authorize)],
              summary="Emergency stop; 501 if the node has no stop()")
    def post_stop() -> dict[str, Any]:
        return call(node.request_stop)

    @app.post("/taken", dependencies=[Depends(authorize)],
              summary="The sample was removed; returns a done/stopped/error node to idle")
    def post_taken(request: Optional[TakenRequest] = None) -> dict[str, Any]:
        return call(node.mark_taken, request.sample_id if request else None)

    if node.supports("position"):
        @app.get("/position", summary="Current position reported by the node")
        def get_position() -> dict[str, float]:
            return node.position()

    return app


def serve(
    node: Experiment,
    port: int = 8000,
    host: str = "0.0.0.0",
    token: Optional[str] = None,
    insecure: bool = False,
) -> None:
    """Run the node until interrupted. Open http://<host>:<port>/docs to try it.

    The token comes from ``token`` or the ``LABNODE_TOKEN`` environment
    variable. It is required when listening on a network address unless
    ``insecure=True``.
    """
    import uvicorn

    token = token or os.environ.get(TOKEN_ENV) or None
    if token is None and host not in LOOPBACK_HOSTS and not insecure:
        raise SystemExit(
            f"labnode: refusing to listen on {host} without a token. "
            f"Set {TOKEN_ENV}, pass token=..., or pass insecure=True."
        )
    uvicorn.run(create_app(node, token), host=host, port=port)

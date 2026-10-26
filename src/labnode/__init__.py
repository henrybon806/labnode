"""labnode: wrap a lab instrument in a small REST API."""

from labnode.client import NodeClient, NodeError, NodeUnreachable
from labnode.experiment import Experiment, NodeConflict, NotSupported


def serve(*args, **kwargs):
    from labnode.server import serve as _serve
    return _serve(*args, **kwargs)


def create_app(*args, **kwargs):
    from labnode.server import create_app as _create_app
    return _create_app(*args, **kwargs)


__all__ = [
    "Experiment",
    "NodeClient",
    "NodeConflict",
    "NodeError",
    "NodeUnreachable",
    "NotSupported",
    "create_app",
    "serve",
]
__version__ = "0.1.0"

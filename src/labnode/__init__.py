"""labnode: wrap a lab instrument in a small REST API."""

from labnode._version import __version__
from labnode.client import NodeClient, NodeError, NodeUnreachable
from labnode.experiment import Experiment, NodeConflict, NotSupported
from labnode.gantry import Gantry
from labnode.listen import ListenerPool, NodeListener


def serve(*args, **kwargs):
    from labnode.server import serve as _serve
    return _serve(*args, **kwargs)


def create_app(*args, **kwargs):
    from labnode.server import create_app as _create_app
    return _create_app(*args, **kwargs)


__all__ = [
    "Experiment",
    "Gantry",
    "ListenerPool",
    "NodeClient",
    "NodeConflict",
    "NodeError",
    "NodeListener",
    "NodeUnreachable",
    "NotSupported",
    "create_app",
    "serve",
]

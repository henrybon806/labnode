"""A fake gantry that wanders around so /position has something to show.

    python examples/fake_gantry.py
"""

import math
import time

from labnode import Experiment, serve


class FakeGantry(Experiment):
    name = "gantry"

    def position(self):
        t = time.monotonic() / 4
        return {"x": 50 + 40 * math.cos(t), "y": 30 + 20 * math.sin(2 * t), "z": 0.0}

    def run(self, sample_id, params):
        raise NotImplementedError("moves are not wired up in this example")


if __name__ == "__main__":
    serve(FakeGantry(), host="127.0.0.1", port=8100)

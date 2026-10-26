"""A fake gantry: each move takes MOVE_TIME seconds along a straight line.

    python examples/fake_gantry.py

Then POST /move {"x": .., "y": ..} and watch GET /status or GET /position.
"""

import time

from labnode import Gantry, serve


MOVE_TIME = 1.0


class FakeGantry(Gantry):
    name = "gantry"

    def __init__(self):
        self._from = self._to = (0.0, 0.0)
        self._started = self._arrives = time.monotonic()

    def position(self):
        span = self._arrives - self._started
        progress = 1.0 if span <= 0 else min(1.0, (time.monotonic() - self._started) / span)
        x = self._from[0] + (self._to[0] - self._from[0]) * progress
        y = self._from[1] + (self._to[1] - self._from[1]) * progress
        return {"x": x, "y": y, "z": 0.0}

    def move(self, x, y, z, params):
        here = self.position()
        self._from, self._to = (here["x"], here["y"]), (x, y)
        self._started = time.monotonic()
        self._arrives = self._started + MOVE_TIME
        while time.monotonic() < self._arrives:
            if self.stop_requested:
                return
            time.sleep(0.02)

    def stop(self):
        # Freeze where it is; move() sees stop_requested and returns.
        here = self.position()
        self._from = self._to = (here["x"], here["y"])
        self._started = self._arrives = time.monotonic()


if __name__ == "__main__":
    serve(FakeGantry(), host="127.0.0.1", port=8100)

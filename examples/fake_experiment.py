"""A fake timed experiment. Run it, then open http://127.0.0.1:8000/docs.

    python examples/fake_experiment.py
"""

import time

from labnode import Experiment, serve


class FakeExperiment(Experiment):
    name = "fake"

    def estimate(self, params):
        return float(params.get("seconds", 10))

    def run(self, sample_id, params):
        seconds = float(params.get("seconds", 10))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_requested:
                return {"completed": False}
            time.sleep(0.1)
        return {"completed": True, "measurement": len(sample_id) * 1.5}

    def stop(self):
        # A real instrument would send its abort command here. run() sees
        # stop_requested and returns on its own.
        pass


if __name__ == "__main__":
    serve(FakeExperiment(), host="127.0.0.1", port=8000)

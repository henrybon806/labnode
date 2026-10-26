# labnode

Wrap a lab instrument in a small REST API. You write `run()` (and optionally
`stop()`); labnode handles the HTTP server, the background thread, the
busy/done state and error reporting.

## Install

```bash
pip install -e ./packages/labnode            # from the gantryManager repo
pip install -e "./packages/labnode[test]"    # plus test dependencies
```

## Write a node

```python
from labnode import Experiment, serve

class Keyence(Experiment):
    name = "keyence"

    def run(self, sample_id, params):      # required: return when the run is finished
        ...

    def stop(self):                        # optional: emergency stop
        ...

    def estimate(self, params):            # optional: expected seconds, for "remaining"
        return 120

serve(Keyence(), port=8000)
```

`run()` executes in a background thread. Whatever it returns appears as
`result` in `/status`; if it raises, the node goes to `error` with the message.
Long runs should check `self.stop_requested` between steps.

A gantry node implements `position()` instead and gets `GET /position`.

## Endpoints

| Method | Path        | What it does |
|--------|-------------|--------------|
| GET    | `/status`   | State, sample, elapsed/remaining time, result, error |
| POST   | `/start`    | `{"sample_id": "s1", "params": {...}}`. 409 unless idle |
| POST   | `/stop`     | Emergency stop. 501 if the node has no `stop()` |
| POST   | `/taken`    | `{"sample_id": "s1"}` after removing the sample. Returns the node to idle |
| GET    | `/position` | Only on nodes that implement `position()` |
| GET    | `/docs`     | Interactive page for trying every endpoint in a browser |

States:

```
idle --start--> busy --run returns--> done ----taken--> idle
                  |  --run raises---> error ---taken--> idle
                  '--stop--> stopping --> stopped --taken--> idle
```

`done`, `stopped` and `error` all mean a sample is still in the instrument
(`"occupied": true`), so nothing new can start until the gantry calls `/taken`.

## Security

POST endpoints require `Authorization: Bearer <token>` when a token is set.
`serve()` reads it from `token=` or the `LABNODE_TOKEN` environment variable and
refuses to listen on a network address without one (pass `insecure=True` to
override). Keep tokens, IPs and hostnames out of this package; put them in
each computer's environment or config.

## Talk to nodes

```python
from labnode import NodeClient

keyence = NodeClient("10.0.0.12:8000", token="...")
keyence.start("sample_7", {"magnification": 20})
keyence.status()["state"]     # "busy", later "done"
keyence.taken("sample_7")
```

`NodeClient` uses only the standard library. It raises `NodeError` for HTTP
errors (`.status` has the code) and `NodeUnreachable` when the node can't be
reached.

## Examples

```bash
python examples/fake_experiment.py   # http://127.0.0.1:8000/docs
python examples/fake_gantry.py       # http://127.0.0.1:8100/position
```

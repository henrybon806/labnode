# labnode

Wrap a lab instrument in a small REST API. You write `run()` (and optionally
`stop()`); labnode handles the HTTP server, the background thread, the
busy/done state and error reporting.

## Install

```bash
pip install "labnode @ git+https://github.com/henrybon806/labnode.git@labnode-v0.2.0"
pip install "../labnode[test]"    # from a local clone, plus test dependencies
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

## Write a gantry node

A gantry is a `Gantry` node: implement `move()` and `position()`; `pick()`,
`place()`, `home()` and `stop()` are optional.

```python
from labnode import Gantry, serve

class MyGantry(Gantry):
    name = "gantry"

    def move(self, x, y, z, params):     # z is None unless the caller sent one
        controller.go_to(x, y)           # return once arrived; check self.stop_requested
    def position(self):
        return {"x": controller.x, "y": controller.y, "z": controller.z}
    def pick(self, params):              # optional
        gripper.close()
    def place(self, params):             # optional
        gripper.open()

serve(MyGantry(), port=8100)
```

Each action runs in a background thread, one at a time. `params` is whatever
the caller sent (station, sample id, speed, ...), so a new need is a new key,
not a protocol change. A gantry's `/status` has `state` (`idle`, `busy` or
`error`), `action`, `position`, `target`, and which optional actions it
`supports`. A failed or stopped action leaves it in `error` until the next one.

## Endpoints

| Method | Path        | What it does |
|--------|-------------|--------------|
| GET    | `/status`   | State, sample, elapsed/remaining time, result, error |
| POST   | `/start`    | `{"sample_id": "s1", "params": {...}}`. 409 unless idle |
| POST   | `/stop`     | Emergency stop. 501 if the node has no `stop()` |
| POST   | `/taken`    | `{"sample_id": "s1"}` after removing the sample. Returns the node to idle |
| GET    | `/position` | Gantry nodes (and experiments that implement `position()`) |
| POST   | `/move`     | Gantry: `{"x": 1, "y": 2, "z": null, "params": {}}`. 409 while busy |
| POST   | `/pick`, `/place`, `/home` | Gantry: `{"params": {}}`. 409 while busy, 501 if not implemented |
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

Gantry nodes add `move(x, y, z=None, params=None)`, `pick()`, `place()` and
`home()`; each starts the action and returns at once, so watch `/status`
until it is `idle` again.

`NodeClient` uses only the standard library. It raises `NodeError` for HTTP
errors (`.status` has the code) and `NodeUnreachable` when the node can't be
reached.

## Watch nodes

`NodeListener` polls one node on its own thread and keeps the latest answer,
so reading it never waits on the network. A `ListenerPool` shares one
listener per node between everything in a program that watches it.

```python
from labnode import ListenerPool

pool = ListenerPool()
keyence = pool.acquire("10.0.0.12:8000")     # polls /status every 0.2 s
payload, problem, detail = keyence.latest()  # problem: "", "not started" or "unreadable"
keyence.update(NodeClient("10.0.0.12:8000").start("s1"))  # store a command's reply right away
pool.release(keyence)                        # stops the thread once nobody uses it
```

Every `/status` also carries `kind` (`experiment` or `gantry`) and the
`labnode` version the node runs.

## Examples

```bash
python examples/fake_experiment.py   # http://127.0.0.1:8000/docs
python examples/fake_gantry.py       # http://127.0.0.1:8100/docs
```

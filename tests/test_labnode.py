import threading
import time
import unittest

import uvicorn
from fastapi.testclient import TestClient

from labnode import Experiment, Gantry, ListenerPool, NodeClient, NodeError, NodeUnreachable, create_app
from labnode.client import normalize_url


class Timed(Experiment):
    name = "timed"

    def __init__(self):
        self.release = threading.Event()

    def estimate(self, params):
        return 5.0

    def run(self, sample_id, params):
        while not self.release.wait(0.01):
            if self.stop_requested:
                return None
        if params.get("fail"):
            raise RuntimeError("instrument jammed")
        return {"value": 42}

    def stop(self):
        pass


class NoStop(Experiment):
    name = "nostop"

    def run(self, sample_id, params):
        return None


class PositionNode(Experiment):
    name = "gantry"

    def position(self):
        return {"x": 1.0, "y": 2.0}


class ExperimentStateTests(unittest.TestCase):
    def test_full_cycle_done_then_taken(self):
        node = Timed()
        status = node.start("s1", {"a": 1})
        self.assertEqual(status["state"], "busy")
        self.assertTrue(status["busy"])
        self.assertEqual(status["estimated_duration"], 5.0)

        node.release.set()
        node.wait(2)
        status = node.status()
        self.assertEqual(status["state"], "done")
        self.assertFalse(status["busy"])
        self.assertTrue(status["occupied"])
        self.assertEqual(status["result"], {"value": 42})

        with self.assertRaises(Exception):
            node.start("s2")
        with self.assertRaises(Exception):
            node.mark_taken("wrong_sample")
        self.assertEqual(node.mark_taken("s1")["state"], "idle")

    def test_run_error_is_reported(self):
        node = Timed()
        node.release.set()
        node.start("s1", {"fail": True})
        node.wait(2)
        status = node.status()
        self.assertEqual(status["state"], "error")
        self.assertIn("instrument jammed", status["error"])

    def test_stop_ends_in_stopped(self):
        node = Timed()
        node.start("s1")
        self.assertEqual(node.request_stop()["state"], "stopping")
        node.wait(2)
        self.assertEqual(node.status()["state"], "stopped")

    def test_subclass_init_without_super_still_works(self):
        self.assertEqual(Timed().status()["state"], "idle")


class ServerTests(unittest.TestCase):
    def test_endpoints_and_token(self):
        node = Timed()
        client = TestClient(create_app(node, token="secret"))
        auth = {"Authorization": "Bearer secret"}

        self.assertEqual(client.get("/status").json()["state"], "idle")
        self.assertEqual(client.post("/start", json={"sample_id": "s1"}).status_code, 401)
        self.assertEqual(client.post("/start", json={"sample_id": "s1"}, headers={"Authorization": "Bearer nope"}).status_code, 401)

        response = client.post("/start", json={"sample_id": "s1", "params": {"x": 1}}, headers=auth)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(client.post("/start", json={"sample_id": "s2"}, headers=auth).status_code, 409)
        self.assertEqual(client.post("/taken", json={"sample_id": "s1"}, headers=auth).status_code, 409)

        node.release.set()
        node.wait(2)
        self.assertEqual(client.get("/status").json()["state"], "done")
        self.assertEqual(client.post("/taken", json={"sample_id": "s1"}, headers=auth).json()["state"], "idle")
        self.assertEqual(client.get("/position").status_code, 404)

    def test_optional_features(self):
        client = TestClient(create_app(NoStop()))
        self.assertEqual(client.post("/stop").status_code, 501)
        gantry = TestClient(create_app(PositionNode()))
        self.assertEqual(gantry.get("/position").json(), {"x": 1.0, "y": 2.0})
        self.assertEqual(gantry.get("/status").json()["supports"], {"stop": False, "position": True})


class ClientTests(unittest.TestCase):
    def test_client_against_live_server(self):
        node = Timed()
        config = uvicorn.Config(create_app(node, token="t"), host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        try:
            client = NodeClient(str(port), token="t")
            self.assertEqual(client.start("s1")["state"], "busy")
            with self.assertRaises(NodeError) as caught:
                client.start("s2")
            self.assertEqual(caught.exception.status, 409)
            with self.assertRaises(NodeError) as caught:
                NodeClient(str(port)).stop()
            self.assertEqual(caught.exception.status, 401)
            self.assertEqual(client.stop()["state"], "stopping")
            node.wait(2)
            self.assertEqual(client.taken()["state"], "idle")
        finally:
            server.should_exit = True
            thread.join(5)

        with self.assertRaises(NodeUnreachable):
            NodeClient(str(port), timeout=0.5).status()

    def test_normalize_url(self):
        self.assertEqual(normalize_url("8000"), "http://127.0.0.1:8000")
        self.assertEqual(normalize_url("10.0.0.2:8000/"), "http://10.0.0.2:8000")
        self.assertEqual(normalize_url("http://lab-pc:9000"), "http://lab-pc:9000")
        with self.assertRaises(ValueError):
            normalize_url("lab-pc")


class Stepper(Gantry):
    name = "stepper"

    def __init__(self):
        self.release = threading.Event()
        self.at = {"x": 0.0, "y": 0.0, "z": 0.0}

    def position(self):
        return self.at

    def move(self, x, y, z, params):
        while not self.release.wait(0.01):
            if self.stop_requested:
                return
        if x < 0:
            raise RuntimeError("out of range")
        self.at = {"x": x, "y": y, "z": 0.0 if z is None else z}

    def pick(self, params):
        self.picked = params

    def stop(self):
        pass


class GantryTests(unittest.TestCase):
    def test_move_reports_moving_then_idle_at_target(self):
        node = Stepper()
        client = TestClient(create_app(node))
        response = client.post("/move", json={"x": 3, "y": 4})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["state"], "busy")
        self.assertEqual(response.json()["action"], "move")
        self.assertEqual(response.json()["target"], {"x": 3.0, "y": 4.0})
        self.assertEqual(client.post("/move", json={"x": 1, "y": 1}).status_code, 409)

        node.release.set()
        node.wait(2)
        status = client.get("/status").json()
        self.assertEqual(status["kind"], "gantry")
        self.assertEqual(status["state"], "idle")
        self.assertEqual(status["position"], {"x": 3.0, "y": 4.0, "z": 0.0})
        self.assertEqual(client.get("/position").json()["x"], 3.0)
        self.assertEqual(status["supports"], {"pick": True, "place": False, "home": False, "stop": True})

    def test_pick_passes_params_and_unimplemented_actions_are_501(self):
        node = Stepper()
        client = TestClient(create_app(node))
        response = client.post("/pick", json={"params": {"station": "experiment_a"}})
        self.assertEqual(response.status_code, 202)
        node.wait(2)
        self.assertEqual(node.picked, {"station": "experiment_a"})
        self.assertEqual(node.status()["state"], "idle")
        self.assertEqual(client.post("/place").status_code, 501)
        self.assertEqual(client.post("/home", json={}).status_code, 501)

    def test_move_with_z(self):
        node = Stepper()
        node.release.set()
        node.start_move(1, 2, 5)
        node.wait(2)
        self.assertEqual(node.status()["position"], {"x": 1, "y": 2, "z": 5})

    def test_failed_and_stopped_moves_report_error(self):
        node = Stepper()
        node.release.set()
        node.start_move(-1, 0)
        node.wait(2)
        self.assertEqual(node.status()["state"], "error")
        self.assertIn("out of range", node.status()["error"])

        node.release.clear()
        node.start_move(5, 5)
        node.request_stop()
        node.wait(2)
        self.assertEqual(node.status()["state"], "error")
        self.assertEqual(node.status()["error"], "stopped")

    def test_gantry_has_no_sample_endpoints(self):
        client = TestClient(create_app(Stepper()))
        self.assertEqual(client.post("/start", json={"sample_id": "s1"}).status_code, 404)


class ListenerTests(unittest.TestCase):
    def test_pool_shares_one_listener_per_node_and_tracks_state(self):
        node = Timed()
        server = uvicorn.Server(uvicorn.Config(create_app(node), host="127.0.0.1", port=0, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        pool = ListenerPool()
        try:
            first = pool.acquire(f"127.0.0.1:{port}")
            second = pool.acquire(f"127.0.0.1:{port}")
            self.assertIs(first, second)
            deadline = time.monotonic() + 3
            while first.latest()[1] and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(first.latest()[0]["state"], "idle")

            first.update(NodeClient(f"127.0.0.1:{port}").start("s1"))
            self.assertEqual(first.latest()[0]["state"], "busy")
            pool.release(first)
            self.assertTrue(second._thread.is_alive())
            pool.release(second)
            self.assertFalse(second._thread.is_alive())

            missing = pool.acquire("127.0.0.1:1")
            deadline = time.monotonic() + 3
            while "no answer yet" in missing.latest()[2] and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(missing.latest()[1], "not started")
        finally:
            pool.close()
            node.release.set()
            server.should_exit = True
            thread.join(5)


if __name__ == "__main__":
    unittest.main()

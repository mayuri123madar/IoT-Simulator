"""Sandbox tests: attack scripts must be refused, normal scripts must still work."""
import glob
import json
import time
import unittest

import app as A

ATTACKS = {
    "globals via function":   "x = create_protocol.__globals__['os'].getcwd()\nSensor('s')",
    "globals via class":      "x = IoTDevice.turn_on.__globals__\nSensor('s')",
    "generator frame":        "g = (i for i in [1])\nx = g.gi_frame.f_back.f_globals\nSensor('s')",
    "subclasses":             "x = ().__class__.__base__.__subclasses__()\nSensor('s')",
    "import os":              "import os\nSensor('s')",
    "from import":            "from os import system\nSensor('s')",
    "__import__":             "__import__('os')\nSensor('s')",
    "open file":              "open('/etc/passwd').read()\nSensor('s')",
    "eval":                   "eval('1+1')\nSensor('s')",
    "getattr":                "getattr(network, 'nodes')\nSensor('s')",
    "format string trick":    "x = '{0.__globals__}'.format(create_protocol)\nSensor('s')",
    "traceback":              "try:\n    1/0\nexcept Exception as e:\n    x = e.__traceback__\nSensor('s')",
    "dunder on network":      "x = network.__class__\nSensor('s')",
}

class TestSandbox(unittest.TestCase):
    def test_attacks_are_refused(self):
        for name, script in ATTACKS.items():
            ok, msg = A.validate_python_script(script)
            self.assertFalse(ok, f"attack was NOT blocked: {name}")

    def test_infinite_loop_times_out(self):
        t = time.time()
        ok, msg = A.validate_python_script("while True:\n    pass")
        self.assertFalse(ok)
        self.assertLess(time.time() - t, A.SCRIPT_TIMEOUT_S + 10)

    def test_memory_bomb_is_stopped(self):
        ok, msg = A.validate_python_script("x = [0] * (10 ** 10)\nSensor('s')")
        self.assertFalse(ok)

    def test_recursion_is_caught(self):
        ok, msg = A.validate_python_script("def f():\n    f()\nf()")
        self.assertFalse(ok)

    def test_server_still_alive_after_attacks(self):
        ok, msg = A.validate_python_script("s = Sensor('a')\ns.turn_on()")
        self.assertTrue(ok, msg)

    def test_normal_scripts_work(self):
        scripts = []
        for f in ("editor_industrial_example.py", "editor_smart_city_example.py"):
            scripts.append(open(f, encoding="utf-8").read())
        scripts += [v for v in A.SCRIPT_TEMPLATES.values()] if hasattr(A, "SCRIPT_TEMPLATES") else []
        for f in glob.glob("saved_networks/*.json"):
            scripts.append(json.load(open(f, encoding="utf-8"))["script"])
        self.assertGreater(len(scripts), 3)
        for sc in scripts:
            ok, msg = A.validate_python_script(sc)
            self.assertTrue(ok, f"normal script rejected: {msg}\n{sc[:120]}")

    def test_simulate_route_output(self):
        c = A.app.test_client()
        r = c.post("/simulate", json={"script": "a = Arduino('uno')\ns = Sensor('t')\ns.connect(a)\na.turn_on()\nprint('hi')"})
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertTrue(j["has_devices"])
        self.assertEqual(len([e for e in j["elements"] if "source" in e["data"]]), 1)
        self.assertEqual(j["states"]["uno"], "on")

    def test_simulate_route_rejects_attack(self):
        c = A.app.test_client()
        r = c.post("/simulate", json={"script": ATTACKS["globals via function"]})
        self.assertEqual(r.status_code, 400)

    def test_print_only_script(self):
        c = A.app.test_client()
        j = c.post("/simulate", json={"script": "print('hello')"}).get_json()
        self.assertFalse(j["has_devices"])
        self.assertEqual(j["print_output"], "hello")

    def test_protocol_aliases(self):
        ok, msg = A.validate_python_script("p = LoRaProtocol(spreading_factor=9)\nq = WiFiProtocol()\nSensor('s')")
        self.assertTrue(ok, msg)

if __name__ == "__main__":
    unittest.main()

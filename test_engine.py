"""Tests for the event-driven engine: energy, battery death, rerouting, buffers, duty cycle."""
import json
import unittest

import app as A
from protocols import BLE, LoRa


def sim(script, duration=None):
    ok, msg, res = A.run_script_sandboxed(script, duration)
    assert ok, msg
    return res['simulation']


class TestEnergy(unittest.TestCase):
    SCRIPT = """
g = Gateway("g"); g.turn_on()
s = Sensor("s", battery_mah=1000, protocol=BLEProtocol()); s.turn_on()
s.connect(g, distance_m=5)
s.send_interval(60, 20, to=g)
network.set_duration(600)
"""

    def test_energy_matches_hand_calculation(self):
        r = sim(self.SCRIPT)
        packets = 10                                  # t = 0, 60, ..., 540 (none generated at the very end)
        ble = BLE()
        tx_time = packets * ble.airtime(20)
        expected_tx = packets * 5.3 / 1000 * 3.3 * ble.airtime(20) * 1000       # mJ, I x V x t
        expected_sleep = 0.01 / 1000 * 3.3 * (600 - tx_time) * 1000
        n = r['nodes']['s']
        self.assertEqual(r['flows'][0]['generated'], packets)
        self.assertAlmostEqual(n['energy_mj']['tx'], expected_tx, places=6)
        self.assertAlmostEqual(n['energy_mj']['sleep'], expected_sleep, delta=expected_sleep * 0.01)
        self.assertAlmostEqual(n['tx_time_s'], tx_time, places=9)
        self.assertEqual(r['summary']['delivery_ratio'], 1.0)

    def test_receiver_pays_rx_energy(self):
        r = sim(self.SCRIPT)
        ble = BLE()
        expected_rx = 10 * 5.4 / 1000 * 3.3 * ble.airtime(20) * 1000
        self.assertAlmostEqual(r['nodes']['g']['energy_mj']['rx'], expected_rx, places=6)

    def test_energy_parts_add_up_and_battery_drops(self):
        r = sim(self.SCRIPT)
        for n in r['nodes'].values():
            e = n['energy_mj']
            self.assertAlmostEqual(e['total'], e['tx'] + e['rx'] + e['idle'] + e['sleep'], places=6)
        self.assertLess(r['nodes']['s']['battery_pct'], 100.0)
        self.assertIsNone(r['nodes']['g']['battery_pct'])       # mains powered

    def test_always_on_gateway_uses_idle_current(self):
        r = sim(self.SCRIPT)
        self.assertGreater(r['nodes']['g']['energy_mj']['idle'], 100 * r['nodes']['s']['energy_mj']['sleep'] / 100)
        self.assertEqual(r['nodes']['s']['energy_mj']['idle'], 0.0)

    def test_send_data_uses_one_energy_number(self):
        ok, msg, res = A.run_script_sandboxed(
            "s = Sensor('s', battery_mah=100, protocol=BLEProtocol())\nprint(s.send_data({'a': 1})['energy_mj'])\n"
            "print(s.energy_model.total_energy_mj)")
        self.assertTrue(ok, msg)
        a, b = [float(x) for x in res['print_output']]
        self.assertAlmostEqual(a, b, places=12)


class TestBatteryAndRouting(unittest.TestCase):
    def test_node_dies_at_predicted_time(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", battery_mah=0.001, protocol=BLEProtocol()); s.turn_on()
s.connect(g)
s.send_interval(60, 20, to=g)
network.set_duration(1000)
""")
        died = r['nodes']['s']['died_at_s']
        self.assertIsNotNone(died)
        self.assertTrue(340 < died < 360, died)             # 0.001 mAh / 0.01 mA = 360 s (a little less with TX)
        self.assertEqual(r['nodes']['s']['state'], 'dead')
        self.assertEqual(r['summary']['first_node_death_s'], died)
        self.assertLessEqual(r['flows'][0]['generated'], 7)  # no packets after death

    TWO_PATHS = """
g = Gateway("g"); g.turn_on()
r1 = Router("r1", battery_mah=0.5, protocol=BLEProtocol()); r1.turn_on()
r2 = Router("r2", protocol=BLEProtocol()); r2.turn_on()
s = Sensor("s", protocol=BLEProtocol()); s.turn_on()
s.connect(r1); s.connect(r2); r1.connect(g); r2.connect(g)
s.send_interval(10, 20, to=g)
network.set_duration(600)
"""

    def test_traffic_is_rerouted_when_a_relay_dies(self):
        r = sim(self.TWO_PATHS)
        r1, r2 = r['nodes']['r1'], r['nodes']['r2']
        self.assertTrue(100 < r1['died_at_s'] < 125, r1['died_at_s'])   # 0.5 mAh / 15 mA = 120 s
        self.assertGreater(r1['forwarded'], 0)             # used before it died
        self.assertGreater(r2['forwarded'], 0)             # takes over afterwards
        self.assertIsNone(r['summary']['first_flow_disconnected_s'])
        self.assertGreater(r['summary']['delivery_ratio'], 0.95)
        self.assertTrue(any(t[1] == 'DEAD' and t[2] == 'r1' for t in r['trace']))

    def test_flow_disconnects_when_only_path_dies(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
r1 = Router("r1", battery_mah=0.5, protocol=BLEProtocol()); r1.turn_on()
s = Sensor("s", protocol=BLEProtocol()); s.turn_on()
s.connect(r1); r1.connect(g)
s.send_interval(10, 20, to=g)
network.set_duration(600)
""")
        died = r['nodes']['r1']['died_at_s']
        self.assertIsNotNone(died)
        self.assertEqual(r['summary']['first_flow_disconnected_s'], died)
        self.assertEqual(r['summary']['all_flows_disconnected_s'], died)
        self.assertGreater(r['flows'][0]['drop_reasons'].get('no_route', 0), 0)
        self.assertLess(r['summary']['delivery_ratio'], 0.3)

    def test_projected_lifetime_for_surviving_node(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", battery_mah=1000, protocol=BLEProtocol()); s.turn_on()
s.connect(g)
s.send_interval(60, 20, to=g)
network.set_duration(3600)
""")
        life = r['nodes']['s']['projected_lifetime_s']
        self.assertIsNotNone(life)
        # drain ~ 0.01 mA sleep + small TX share -> roughly 1000 / 0.01 mA = 1e5 h
        self.assertTrue(3.0e8 < life < 3.7e8, life)


class TestResourceLimits(unittest.TestCase):
    def test_small_memory_drops_packets(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=LoRaProtocol(spreading_factor=12), memory_kb=1); s.turn_on()
s.connect(g, distance_m=100)
s.send_interval(1, 50, to=g)
network.set_duration(600)
""")
        self.assertGreater(r['flows'][0]['drop_reasons'].get('buffer_full', 0), 0)

    def test_lora_duty_cycle_limits_send_rate(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=LoRaProtocol(spreading_factor=9), memory_kb=64); s.turn_on()
s.connect(g, distance_m=100)
s.send_interval(1, 20, to=g)
network.set_duration(600)
""")
        lora = LoRa(spreading_factor=9)
        period = lora.airtime(20) + lora.min_off_time(20)          # ~ 18.5 s between packets
        self.assertLessEqual(r['flows'][0]['delivered'], 600 / period + 1)
        self.assertGreater(r['flows'][0]['delivered'], 600 / period - 2)

    def test_lossy_link_retries_then_drops(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=BLEProtocol()); s.turn_on()
s.connect(g, distance_m=80)
s.send_interval(5, 20, to=g)
network.set_duration(600)
""")
        e = r['edges'][0]
        self.assertGreater(e['attempts'], r['flows'][0]['generated'])      # retries happened
        self.assertGreater(e['loss_pct'], 20)
        self.assertGreater(r['flows'][0]['drop_reasons'].get('max_retries', 0), 0)

    def test_wired_link_has_no_loss(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=I2CProtocol()); s.turn_on()
s.connect(g)
s.send_interval(1, 8, to=g)
network.set_duration(60)
""")
        self.assertEqual(r['edges'][0]['lost'], 0)
        self.assertEqual(r['summary']['delivery_ratio'], 1.0)


class TestBehaviour(unittest.TestCase):
    def test_same_seed_same_result(self):
        script = """
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=BLEProtocol()); s.turn_on()
s.connect(g, distance_m=70)
s.send_interval(2, 20, to=g)
network.set_duration(300)
"""
        self.assertEqual(json.dumps(sim(script), sort_keys=True), json.dumps(sim(script), sort_keys=True))

    def test_powered_off_device_takes_no_part(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=BLEProtocol())
s.connect(g)
s.send_interval(10, 20, to=g)
network.set_duration(100)
""")
        self.assertEqual(r['flows'][0]['generated'], 0)
        self.assertTrue(any('is off' in w for w in r['warnings']))

    def test_missing_protocol_is_flagged(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s"); s.turn_on()
s.connect(g)
s.send_interval(10, 20, to=g)
network.set_duration(100)
""")
        self.assertTrue(r['nodes']['s']['protocol_assumed'])
        self.assertEqual(r['nodes']['s']['protocol'], 'WiFi')

    def test_default_sink_is_nearest_gateway(self):
        r = sim("""
g = Gateway("g"); g.turn_on()
s = Sensor("s", protocol=BLEProtocol()); s.turn_on()
s.connect(g)
s.send_interval(10, 20)
network.set_duration(100)
""")
        self.assertEqual(r['summary']['delivery_ratio'], 1.0)

    def test_timeline_has_samples(self):
        r = sim(TestEnergy.SCRIPT)
        self.assertEqual(len(r['timeline']), 100)
        self.assertIn('s', r['timeline'][-1]['battery_pct'])

    def test_scripts_without_traffic_have_no_simulation(self):
        ok, msg, res = A.run_script_sandboxed("a = Arduino('a')\na.turn_on()")
        self.assertTrue(ok, msg)
        self.assertIsNone(res['simulation'])

    def test_simulate_route(self):
        c = A.app.test_client()
        script = TestEnergy.SCRIPT.replace("network.set_duration(600)\n", "")
        j = c.post("/simulate", json={"script": script, "duration_s": 300}).get_json()
        self.assertEqual(j["simulation"]["duration_s"], 300)
        node = [e["data"] for e in j["elements"] if e["data"].get("id") == "s"][0]
        self.assertIn("battery_pct", node)
        edge = [e["data"] for e in j["elements"] if "source" in e["data"]][0]
        self.assertEqual(edge["protocol"], "BLE")
        bad = c.post("/simulate", json={"script": script, "duration_s": "abc"})
        self.assertEqual(bad.status_code, 400)


class TestRecommendBySimulation(unittest.TestCase):
    def script(self, distance):
        return f"""
g = Gateway("g"); g.turn_on()
s = Sensor("s", battery_mah=220); s.turn_on()
s.connect(g, distance_m={distance})
s.send_interval(300, 20, to=g)
network.set_duration(7200)
"""

    def post(self, body):
        return A.app.test_client().post("/recommend_by_simulation", json=body)

    def test_long_distance_only_lora_survives(self):
        j = self.post({"script": self.script(300)}).get_json()
        self.assertTrue(j["best"].startswith("LoRa"), j["best"])
        excluded = {r["name"] for r in j["excluded"]}
        self.assertTrue({"BLE", "WiFi", "Zigbee"} <= excluded)
        self.assertTrue(all("delivery" in r["fails_because"][0] for r in j["excluded"] if r["name"] == "BLE"))

    def test_short_distance_all_work_and_are_ranked_by_lifetime(self):
        j = self.post({"script": self.script(5)}).get_json()
        self.assertEqual(len(j["ranked"]), 6)
        lives = [r["lifetime_s"] for r in j["ranked"]]
        self.assertEqual(lives, sorted(lives, reverse=True))
        self.assertEqual(j["best"], j["ranked"][0]["name"])

    def test_latency_limit_excludes_slow_protocols(self):
        j = self.post({"script": self.script(5), "constraints": {"max_latency_ms": 100}}).get_json()
        excluded = {r["name"]: r for r in j["excluded"]}
        self.assertIn("LoRa SF12", excluded)
        self.assertIn("latency", excluded["LoRa SF12"]["fails_because"][0])
        self.assertNotIn("LoRa SF12", {r["name"] for r in j["ranked"]})

    def test_no_battery_falls_back_to_energy_with_note(self):
        script = self.script(5).replace('Sensor("s", battery_mah=220)', 'Sensor("s")')
        j = self.post({"script": script}).get_json()
        self.assertTrue(any("battery_mah" in n for n in j["notes"]))
        energies = [r["total_energy_mj"] for r in j["ranked"]]
        self.assertEqual(energies, sorted(energies))

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.post({"script": self.script(5), "candidates": ["Nope"]}).status_code, 400)
        self.assertEqual(self.post({"script": self.script(5), "duration_s": "x"}).status_code, 400)
        self.assertEqual(self.post({"script": "a = Arduino('a')"}).status_code, 400)
        self.assertEqual(self.post({"script": "import os"}).status_code, 400)

    def test_forced_protocol_overrides_script(self):
        script = self.script(5).replace('Sensor("s", battery_mah=220)', 'Sensor("s", battery_mah=220, protocol=WiFiProtocol())')
        j = self.post({"script": script, "candidates": ["LoRa SF7"]}).get_json()
        self.assertEqual(j["ranked"][0]["name"], "LoRa SF7")


if __name__ == "__main__":
    unittest.main()

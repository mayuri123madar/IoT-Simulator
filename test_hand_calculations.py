"""
Hand-calculation tests.

Every expected value below was worked out BY HAND from the formula in the comment next to it
(the code is not used to produce the expected numbers). If one of these fails, either the
formula in the code or the hand calculation is wrong - find out which before changing anything.

Parameter values come from protocol_parameters.json. They are still to be checked against the
datasheets (see the "source" fields), so these tests prove the ARITHMETIC is right, not that the
parameters equal the real chips.
"""
import math
import unittest

from protocols import I2C, SPI, UART, CAN, WiFi, BLE, Zigbee, LoRa, MQTT, CoAP


class TestWiredByHand(unittest.TestCase):
    def test_i2c_10_bytes_standard_mode(self):
        # bits = start 1 + address byte (7 bits + R/W) with ACK = 9 + 10 data bytes x 9 + stop 1 = 101
        # time = 101 bits / 100 000 Hz = 1.01 ms
        p = I2C()
        self.assertEqual(p.frame_bits(10), 101)
        self.assertAlmostEqual(p.airtime(10), 1.01e-3, places=12)

    def test_i2c_fast_mode(self):
        # same 101 bits at 400 kHz = 0.2525 ms
        self.assertAlmostEqual(I2C(clock_mode='fast').airtime(10), 0.2525e-3, places=12)

    def test_i2c_energy(self):
        # E = I x V x t = 2.25 mA x 3.3 V x 1.01 ms = 7.49925e-3 mJ
        self.assertAlmostEqual(I2C().tx_energy(10), 2.25e-3 * 3.3 * 1.01e-3 * 1000, places=12)
        self.assertAlmostEqual(I2C().tx_energy(10), 0.00749925, places=9)

    def test_spi_32_bytes(self):
        # bits = 32 x 8 = 256; time = 256 / 10 MHz = 25.6 us
        p = SPI()
        self.assertEqual(p.frame_bits(32), 256)
        self.assertAlmostEqual(p.airtime(32), 25.6e-6, places=12)

    def test_uart_10_bytes_8N1(self):
        # 8N1 = 1 start + 8 data + 1 stop = 10 bits per byte -> 100 bits; 100 / 115200 = 868.0556 us
        p = UART()
        self.assertEqual(p.frame_bits(10), 100)
        self.assertAlmostEqual(p.airtime(10), 100 / 115200, places=12)
        self.assertAlmostEqual(p.airtime(10), 868.0556e-6, places=9)

    def test_can_8_bytes(self):
        # nominal frame = 47 overhead + 8 x 8 = 111 bits. The model adds 20 % for bit stuffing:
        # int(111 x 1.2) = int(133.2) = 133 bits (the spec's worst case is about 135, so this is a close approximation)
        # time = 133 bits / 1 Mbit/s = 133 us
        p = CAN()
        self.assertEqual(p.frame_bits(8), 133)
        self.assertAlmostEqual(p.airtime(8), 133e-6, places=12)

    def test_can_payload_limited_to_8_bytes(self):
        self.assertEqual(CAN().frame_bits(100), CAN().frame_bits(8))


class TestWirelessByHand(unittest.TestCase):
    def test_wifi_128_bytes_54mbps(self):
        # frame = 192 header bits + 128 x 8 = 1216 bits -> 1216 / 54e6 = 22.5185 us
        # + preamble 16 + SIFS 10 + DIFS 34 + average backoff (DIFS/2) 17 us
        # + ACK (192 bits / 54e6 = 3.5556 us) + SIFS 10 = 13.5556 us
        # total = 16 + 22.5185 + 10 + 34 + 17 + 13.5556 = 113.0741 us
        p = WiFi()
        self.assertEqual(p.frame_bits(128), 1216)
        self.assertAlmostEqual(p.airtime(128), 113.0741e-6, places=6)

    def test_wifi_energy(self):
        # 190 mA x 3.3 V x 113.0741 us = 0.0708975 mJ ; RX: 112 mA -> 0.0417937 mJ
        self.assertAlmostEqual(WiFi().tx_energy(128), 0.190 * 3.3 * 113.0741e-6 * 1000, places=6)
        self.assertAlmostEqual(WiFi().tx_energy(128), 0.0708975, places=6)
        self.assertAlmostEqual(WiFi().rx_energy(128), 0.112 * 3.3 * 113.0741e-6 * 1000, places=6)

    def test_ble_20_bytes(self):
        # bits = preamble 8 + access address 32 + header 8 + payload 160 + CRC 24 = 232 -> 232 us at 1 Mbit/s
        # + 150 us inter-frame spacing = 382 us
        p = BLE()
        self.assertEqual(p.frame_bits(20), 232)
        self.assertAlmostEqual(p.airtime(20), 382e-6, places=12)

    def test_ble_energy(self):
        # 5.3 mA x 3.3 V x 382 us = 0.00668118 mJ
        self.assertAlmostEqual(BLE().tx_energy(20), 0.0053 * 3.3 * 382e-6 * 1000, places=12)
        self.assertAlmostEqual(BLE().tx_energy(20), 0.00668118, places=6)

    def test_ble_100_bytes_is_split_into_5_packets(self):
        # ceil(100 / 20) = 5 packets; each has 72 overhead bits (8 + 32 + 8 + 24); payload 800 bits
        # bits = 5 x 72 + 800 = 1160 ; airtime = 1160 us + 5 x 150 us = 1910 us
        p = BLE()
        self.assertEqual(p.frame_bits(100), 1160)
        self.assertAlmostEqual(p.airtime(100), 1910e-6, places=12)

    def test_zigbee_50_bytes(self):
        # bits = 6 + 104 + 400 = 510 -> 510 / 250 000 = 2.04 ms ; + 2 ms backoff = 4.04 ms
        p = Zigbee()
        self.assertEqual(p.frame_bits(50), 510)
        self.assertAlmostEqual(p.airtime(50), 4.04e-3, places=12)


class TestLoRaByHand(unittest.TestCase):
    """Semtech formula; 125 kHz, coding rate 4/5 (CR=1), CRC on, explicit header, 8 preamble symbols"""

    def test_sf7_20_bytes(self):
        # Tsym = 2^7 / 125000 = 1.024 ms ; DE = 0
        # preamble = (8 + 4.25) x 1.024 = 12.544 ms
        # payload symbols = 8 + ceil((8x20 - 4x7 + 28 + 16) / (4 x 7)) x 5 = 8 + ceil(176 / 28 = 6.286) x 5 = 8 + 7 x 5 = 43
        # 43 x 1.024 = 44.032 ms ; total = 56.576 ms
        self.assertAlmostEqual(LoRa(spreading_factor=7).airtime(20), 56.576e-3, places=9)

    def test_sf9_20_bytes(self):
        # Tsym = 512 / 125000 = 4.096 ms ; DE = 0 (4.096 ms < 16 ms)
        # preamble = 12.25 x 4.096 = 50.176 ms
        # payload symbols = 8 + ceil((160 - 36 + 28 + 16) / (4 x 9)) x 5 = 8 + ceil(168 / 36 = 4.667) x 5 = 8 + 25 = 33
        # 33 x 4.096 = 135.168 ms ; total = 185.344 ms
        self.assertAlmostEqual(LoRa(spreading_factor=9).airtime(20), 185.344e-3, places=9)

    def test_sf12_20_bytes_low_data_rate_optimisation(self):
        # Tsym = 4096 / 125000 = 32.768 ms > 16 ms so DE = 1
        # preamble = 12.25 x 32.768 = 401.408 ms
        # payload symbols = 8 + ceil((160 - 48 + 28 + 16) / (4 x (12 - 2))) x 5 = 8 + ceil(156 / 40 = 3.9) x 5 = 8 + 20 = 28
        # 28 x 32.768 = 917.504 ms ; total = 1318.912 ms
        self.assertAlmostEqual(LoRa(spreading_factor=12).airtime(20), 1318.912e-3, places=9)

    def test_duty_cycle_off_time(self):
        # 1 % duty cycle: must stay silent 99 x airtime = 99 x 56.576 ms = 5.601024 s
        self.assertAlmostEqual(LoRa(spreading_factor=7).min_off_time(20), 5.601024, places=9)

    def test_energy_uses_air_time_only(self):
        # 28 mA x 3.3 V x 56.576 ms = 5.2276224 mJ (the duty-cycle waiting time is NOT charged at TX current)
        self.assertAlmostEqual(LoRa(spreading_factor=7).tx_energy(20), 0.028 * 3.3 * 56.576e-3 * 1000, places=9)
        self.assertAlmostEqual(LoRa(spreading_factor=7).tx_energy(20), 5.2276224, places=6)

    def test_frame_bits(self):
        # 20 bytes x 8 = 160 + 16 (CRC) + 20 (explicit header) = 196
        self.assertEqual(LoRa().frame_bits(20), 196)


class TestApplicationByHand(unittest.TestCase):
    wifi = WiFi()

    @staticmethod
    def wifi_airtime(payload_bytes):
        # 16 + (192 + 8 x payload) / 54e6 + 10 + 34 + 17 + (192 / 54e6 + 10), all in microseconds
        return (16 + (192 + 8 * payload_bytes) / 54 + 10 + 34 + 17 + 192 / 54 + 10) * 1e-6

    def test_mqtt_qos0_one_packet(self):
        # PUBLISH = 2 fixed header + 2 topic length + 50 payload + 40 TCP/IP = 94 bytes
        m = MQTT(qos=0, underlying_protocol=self.wifi)
        self.assertAlmostEqual(m.airtime(50), self.wifi_airtime(94), places=12)

    def test_mqtt_qos1_publish_plus_puback(self):
        # PUBLISH with packet id = 96 bytes ; PUBACK = 4 + 40 TCP/IP = 44 bytes
        m = MQTT(qos=1, underlying_protocol=self.wifi)
        self.assertAlmostEqual(m.airtime(50), self.wifi_airtime(96) + self.wifi_airtime(44), places=12)

    def test_mqtt_qos2_four_packets(self):
        m = MQTT(qos=2, underlying_protocol=self.wifi)
        self.assertAlmostEqual(m.airtime(50), self.wifi_airtime(96) + 3 * self.wifi_airtime(44), places=12)
        self.assertEqual(m.extra_packets(50), 3)

    def test_coap_confirmable_message_plus_ack(self):
        # message = 4 header + 4 token + 50 payload + 28 UDP/IP = 86 bytes ; empty ACK = 4 + 28 = 32 bytes
        c = CoAP(confirmable=True, underlying_protocol=self.wifi)
        self.assertAlmostEqual(c.airtime(50), self.wifi_airtime(86) + self.wifi_airtime(32), places=12)

    def test_coap_non_confirmable_one_packet(self):
        c = CoAP(confirmable=False, underlying_protocol=self.wifi)
        self.assertAlmostEqual(c.airtime(50), self.wifi_airtime(86), places=12)
        self.assertEqual(c.extra_packets(50), 0)


class TestLossByHand(unittest.TestCase):
    def test_ble_at_10_m(self):
        # path loss = 40 + 10 x 3.0 x log10(10 / 1) = 70 dB
        # margin = 0 dBm - 70 dB - (-96 dBm) = 26 dB ; loss = 1 / (1 + e^(0.5 x 26)) = 1 / (1 + e^13)
        self.assertAlmostEqual(BLE().path_loss_db(10), 70.0, places=9)
        self.assertAlmostEqual(BLE().loss_probability(10), 1 / (1 + math.exp(13)), places=12)

    def test_loss_is_one_half_when_margin_is_zero(self):
        # find the distance where margin = 0: 0 - (40 + 30 log10 d) + 96 = 0 -> log10 d = 56 / 30 -> d = 10^(1.8667) = 73.6 m
        self.assertAlmostEqual(BLE().loss_probability(10 ** (56 / 30)), 0.5, places=9)

    def test_lora_free_space_reference(self):
        # 868 MHz reference loss 31 dB at 1 m, exponent 3.0: at 1 km PL = 31 + 30 x 3 = 121 dB
        self.assertAlmostEqual(LoRa().path_loss_db(1000), 121.0, places=9)

    def test_wired_never_loses(self):
        self.assertEqual(I2C().loss_probability(1000), 0.0)


class TestBatteryByHand(unittest.TestCase):
    def test_battery_drain_and_death_time(self):
        from energy_model import EnergyModel
        # 1 mAh battery drained at 0.01 mA lasts 1 / 0.01 = 100 h = 360 000 s
        m = EnergyModel("Sensor", battery_mah=1.0)
        m.add_sleep_energy(180000)                       # half of it
        self.assertAlmostEqual(m.get_battery_percentage(), 50.0, places=6)
        m.add_sleep_energy(180000)
        self.assertTrue(m.is_dead)
        # energy in 360 000 s at 0.01 mA x 3.3 V = 0.01e-3 x 3.3 x 360000 J = 11.88 J = 11880 mJ
        self.assertAlmostEqual(m.sleep_energy_mj, 11880.0, places=3)


if __name__ == "__main__":
    unittest.main()


class TestCanCurrent(unittest.TestCase):
    def test_can_average_current(self):
        self.assertAlmostEqual(CAN().tx_current_ma, 42.5, places=6)   # 0.5*75 + 0.5*10
    def test_uart_current(self):
        self.assertAlmostEqual(UART().tx_current_ma, 0.3, places=6)


class TestDeviceParameters(unittest.TestCase):
    def test_every_device_class_has_parameters(self):
        import json, os
        d = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protocol_parameters.json')))['device_parameters']
        for n in ('Sensor', 'Gateway', 'Actuator', 'Camera', 'Switch', 'Router', 'Server', 'Cloud', 'Mobile', 'LED',
                  'Motor', 'Display', 'Arduino', 'ESP32', 'STM32', 'PIC', 'RaspberryPi', 'BeagleBone', 'JetsonNano',
                  'WiFi', 'Bluetooth', 'LoRa', 'Zigbee', 'Battery', 'PowerSupply', 'SolarPanel', 'SDCard', 'EEPROM',
                  'FlashMemory'):
            self.assertIn(n, d)
            self.assertIn('power_v', d[n])
    def test_arduino_is_5v(self):
        from energy_model import EnergyModel
        self.assertEqual(EnergyModel('Arduino').voltage_v, 5)


class TestSensitivityBySF(unittest.TestCase):
    def test_lora_sensitivity_points(self):
        self.assertAlmostEqual(LoRa(spreading_factor=7).sensitivity_dbm, -123.0, places=9)
        self.assertAlmostEqual(LoRa(spreading_factor=12).sensitivity_dbm, -137.0, places=9)
        self.assertAlmostEqual(LoRa(spreading_factor=9).sensitivity_dbm, -123.0 - 14 * 2 / 5, places=9)  # interpolated

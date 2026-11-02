"""
Protocol Validation Tests
Tests all protocol implementations with datasheet-backed formulas
"""

import unittest
from protocols import I2C, SPI, UART, CAN, WiFi, BLE, Zigbee, LoRa, MQTT, CoAP
from energy_model import EnergyModel


class TestWiredProtocols(unittest.TestCase):
    """Test wired protocol implementations"""
    
    def test_i2c_frame_bits(self):
        """Test I2C frame bits calculation"""
        protocol = I2C()
        # I2C: 1 start bit + 8 data bits + 1 ACK bit per byte
        payload_bytes = 10
        expected_bits = 1 + (payload_bytes * 8) + (payload_bytes * 1)  # Start + Data + ACK
        result = protocol.frame_bits(payload_bytes)
        self.assertEqual(result, expected_bits)
    
    def test_i2c_airtime(self):
        """Test I2C airtime calculation"""
        protocol = I2C()
        payload_bytes = 10
        airtime = protocol.airtime(payload_bytes)
        # Airtime should be positive and reasonable
        self.assertGreater(airtime, 0)
        self.assertLess(airtime, 1.0)  # Should be less than 1 second for small payload
    
    def test_i2c_tx_energy(self):
        """Test I2C TX energy calculation"""
        protocol = I2C()
        payload_bytes = 10
        energy = protocol.tx_energy(payload_bytes)
        # Energy should be positive
        self.assertGreater(energy, 0)
    
    def test_i2c_loss_probability(self):
        """Test I2C loss probability (should be 0 for wired)"""
        protocol = I2C()
        loss = protocol.loss_probability(100)
        self.assertEqual(loss, 0.0)
    
    def test_spi_frame_bits(self):
        """Test SPI frame bits calculation"""
        protocol = SPI()
        payload_bytes = 10
        # SPI: 8 bits per byte, no overhead
        expected_bits = payload_bytes * 8
        result = protocol.frame_bits(payload_bytes)
        self.assertEqual(result, expected_bits)
    
    def test_spi_airtime(self):
        """Test SPI airtime calculation"""
        protocol = SPI()
        payload_bytes = 10
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)
        # SPI should be faster than I2C
        i2c = I2C()
        i2c_airtime = i2c.airtime(payload_bytes)
        self.assertLess(airtime, i2c_airtime)
    
    def test_uart_frame_bits(self):
        """Test UART frame bits calculation"""
        protocol = UART()
        payload_bytes = 10
        # UART: 1 start + 8 data + 1 stop = 10 bits per byte
        expected_bits = payload_bytes * 10
        result = protocol.frame_bits(payload_bytes)
        self.assertEqual(result, expected_bits)
    
    def test_can_frame_bits(self):
        """Test CAN frame bits calculation"""
        protocol = CAN()
        payload_bytes = 8
        # CAN has fixed frame structure
        bits = protocol.frame_bits(payload_bytes)
        self.assertGreater(bits, 0)
        # CAN frame should include overhead
        self.assertGreater(bits, payload_bytes * 8)


class TestWirelessProtocols(unittest.TestCase):
    """Test wireless protocol implementations"""
    
    def test_wifi_frame_bits(self):
        """Test WiFi frame bits calculation"""
        protocol = WiFi()
        payload_bytes = 100
        bits = protocol.frame_bits(payload_bytes)
        # WiFi has significant overhead
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_wifi_airtime(self):
        """Test WiFi airtime calculation"""
        protocol = WiFi()
        payload_bytes = 100
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)
        self.assertLess(airtime, 0.1)  # Should be fast for small payload
    
    def test_wifi_loss_probability(self):
        """Test WiFi loss probability (distance-based)"""
        protocol = WiFi()
        loss_10m = protocol.loss_probability(10)
        loss_100m = protocol.loss_probability(100)
        # Loss should increase with distance
        self.assertGreater(loss_100m, loss_10m)
        self.assertGreaterEqual(loss_10m, 0)
        self.assertLessEqual(loss_100m, 1)
    
    def test_ble_frame_bits(self):
        """Test BLE frame bits calculation"""
        protocol = BLE()
        payload_bytes = 20
        bits = protocol.frame_bits(payload_bytes)
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_ble_airtime(self):
        """Test BLE airtime calculation"""
        protocol = BLE()
        payload_bytes = 20
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)
    
    def test_zigbee_frame_bits(self):
        """Test Zigbee frame bits calculation"""
        protocol = Zigbee()
        payload_bytes = 50
        bits = protocol.frame_bits(payload_bytes)
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_lora_frame_bits(self):
        """Test LoRa frame bits calculation"""
        protocol = LoRa()
        payload_bytes = 10
        bits = protocol.frame_bits(payload_bytes)
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_lora_airtime(self):
        """Test LoRa airtime calculation"""
        protocol = LoRa()
        payload_bytes = 10
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)
        # LoRa should be slower than WiFi
        wifi = WiFi()
        wifi_airtime = wifi.airtime(payload_bytes)
        self.assertGreater(airtime, wifi_airtime)
    
    def test_lora_loss_probability(self):
        """Test LoRa loss probability (long range)"""
        protocol = LoRa()
        loss_100m = protocol.loss_probability(100)
        loss_1000m = protocol.loss_probability(1000)
        # LoRa should have low loss even at long range
        self.assertLess(loss_100m, 0.1)
        self.assertLess(loss_1000m, 0.5)


class TestApplicationProtocols(unittest.TestCase):
    """Test application layer protocol implementations"""
    
    def test_mqtt_frame_bits(self):
        """Test MQTT frame bits calculation"""
        wifi = WiFi()
        protocol = MQTT(underlying_protocol=wifi)
        payload_bytes = 50
        bits = protocol.frame_bits(payload_bytes)
        # MQTT adds overhead to underlying protocol
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_mqtt_airtime(self):
        """Test MQTT airtime calculation"""
        wifi = WiFi()
        protocol = MQTT(underlying_protocol=wifi)
        payload_bytes = 50
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)
    
    def test_coap_frame_bits(self):
        """Test CoAP frame bits calculation"""
        wifi = WiFi()
        protocol = CoAP(underlying_protocol=wifi)
        payload_bytes = 30
        bits = protocol.frame_bits(payload_bytes)
        self.assertGreater(bits, payload_bytes * 8)
    
    def test_coap_airtime(self):
        """Test CoAP airtime calculation"""
        wifi = WiFi()
        protocol = CoAP(underlying_protocol=wifi)
        payload_bytes = 30
        airtime = protocol.airtime(payload_bytes)
        self.assertGreater(airtime, 0)


class TestEnergyModel(unittest.TestCase):
    """Test energy model implementation"""
    
    def test_energy_model_initialization(self):
        """Test energy model initialization"""
        model = EnergyModel("ESP32", 2000)
        self.assertEqual(model.device_type, "ESP32")
        self.assertEqual(model.battery_capacity_mah, 2000)
        self.assertEqual(model.battery_current_mah, 2000)
        self.assertFalse(model.is_dead)
    
    def test_add_tx_energy(self):
        """Test adding TX energy"""
        model = EnergyModel("ESP32", 2000)
        model.add_tx_energy(0.001)  # 1ms
        self.assertGreater(model.tx_time_s, 0)
        self.assertLess(model.battery_current_mah, 2000)
    
    def test_add_rx_energy(self):
        """Test adding RX energy"""
        model = EnergyModel("ESP32", 2000)
        model.add_rx_energy(0.001)  # 1ms
        self.assertGreater(model.rx_time_s, 0)
    
    def test_battery_drain(self):
        """Test battery drain"""
        model = EnergyModel("ESP32", 100)  # Small battery
        # Drain battery
        model.add_tx_energy(3600)  # 1 hour at TX current
        # Battery should be depleted
        self.assertLess(model.battery_current_mah, 100)
    
    def test_battery_percentage(self):
        """Test battery percentage calculation"""
        model = EnergyModel("ESP32", 2000)
        percentage = model.get_battery_percentage()
        self.assertEqual(percentage, 100.0)
        
        model.battery_current_mah = 1000
        percentage = model.get_battery_percentage()
        self.assertEqual(percentage, 50.0)
    
    def test_battery_death(self):
        """Test battery death detection"""
        model = EnergyModel("ESP32", 10)  # Very small battery
        # Drain to zero
        model.battery_current_mah = 0
        model._drain_battery(10, 1)  # Should mark as dead
        self.assertTrue(model.is_dead)
        self.assertEqual(model.state, 'dead')


class TestProtocolComparison(unittest.TestCase):
    """Test protocol comparison scenarios"""
    
    def test_wired_vs_wireless_loss(self):
        """Test wired protocols have no loss, wireless do"""
        wired = I2C()
        wireless = WiFi()
        
        wired_loss = wired.loss_probability(50)
        wireless_loss = wireless.loss_probability(50)
        
        self.assertEqual(wired_loss, 0.0)
        self.assertGreater(wireless_loss, 0.0)
    
    def test_high_speed_vs_low_speed(self):
        """Test high-speed vs low-speed protocols"""
        high_speed = SPI()
        low_speed = I2C()
        
        payload = 100
        spi_airtime = high_speed.airtime(payload)
        i2c_airtime = low_speed.airtime(payload)
        
        # SPI should be faster than I2C
        self.assertLess(spi_airtime, i2c_airtime)
    
    def test_long_range_protocols(self):
        """Test long-range protocol capabilities"""
        short_range = BLE()
        long_range = LoRa()
        
        loss_1000m_short = short_range.loss_probability(1000)
        loss_1000m_long = long_range.loss_probability(1000)
        
        # LoRa should have better performance at long range
        self.assertLess(loss_1000m_long, loss_1000m_short)


class TestProtocolParameters(unittest.TestCase):
    """Test protocol parameter validation"""
    
    def test_all_protocols_have_interface(self):
        """Test all protocols implement required interface methods"""
        protocols = [I2C(), SPI(), UART(), CAN(), WiFi(), BLE(), Zigbee(), LoRa()]
        
        for protocol in protocols:
            self.assertTrue(hasattr(protocol, 'frame_bits'))
            self.assertTrue(hasattr(protocol, 'airtime'))
            self.assertTrue(hasattr(protocol, 'tx_energy'))
            self.assertTrue(hasattr(protocol, 'rx_energy'))
            self.assertTrue(hasattr(protocol, 'loss_probability'))
            self.assertTrue(hasattr(protocol, 'extra_packets'))
    
    def test_frame_bits_positive(self):
        """Test all protocols return positive frame bits"""
        protocols = [I2C(), SPI(), UART(), CAN(), WiFi(), BLE(), Zigbee(), LoRa()]
        
        for protocol in protocols:
            bits = protocol.frame_bits(10)
            self.assertGreater(bits, 0)
    
    def test_airtime_positive(self):
        """Test all protocols return positive airtime"""
        protocols = [I2C(), SPI(), UART(), CAN(), WiFi(), BLE(), Zigbee(), LoRa()]
        
        for protocol in protocols:
            airtime = protocol.airtime(10)
            self.assertGreater(airtime, 0)
    
    def test_energy_positive(self):
        """Test all protocols return positive energy values"""
        protocols = [I2C(), SPI(), UART(), CAN(), WiFi(), BLE(), Zigbee(), LoRa()]
        
        for protocol in protocols:
            tx_energy = protocol.tx_energy(10)
            rx_energy = protocol.rx_energy(10)
            self.assertGreater(tx_energy, 0)
            self.assertGreater(rx_energy, 0)
    
    def test_loss_probability_valid_range(self):
        """Test all protocols return valid loss probability (0-1)"""
        protocols = [I2C(), SPI(), UART(), CAN(), WiFi(), BLE(), Zigbee(), LoRa()]
        
        for protocol in protocols:
            loss = protocol.loss_probability(50)
            self.assertGreaterEqual(loss, 0)
            self.assertLessEqual(loss, 1)


if __name__ == '__main__':
    unittest.main()

"""
IoT Protocol Implementations with Datasheet-Based Formulas
Datasheet-based formulas. Parameter values must be checked against the cited documents.
"""

import math
from protocol_interface import WiredProtocol, WirelessProtocol, ApplicationProtocol


class I2C(WiredProtocol):
    """
    I2C Protocol Implementation
    Source: I2C Specification NXP UM10204, Section 3.1
    """
    
    def __init__(self, clock_mode='standard'):
        super().__init__('I2C')
        self.clock_mode = clock_mode
        self.clock = self.parameters.get('clock_standard', 100000) if clock_mode == 'standard' \
                   else self.parameters.get('clock_fast', 400000)
        self.bits_per_byte = self.parameters.get('bits_per_byte', 9)  # 8 data + 1 ACK
        self.start_bits = self.parameters.get('start_bits', 1)
        self.stop_bits = self.parameters.get('stop_bits', 1)
        self.address_bits = self.parameters.get('address_bits', 7)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 2.25)
        self.voltage_v = 3.3  # Typical I2C voltage
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: start + address (7-bit + R/W) + data bytes (9 bits each) + stop
        Source: NXP UM10204, Section 3.1.1
        """
        # Start condition
        bits = self.start_bits
        
        # Address byte (7-bit address + R/W bit) + ACK
        bits += (self.address_bits + 1) + 1
        
        # Data bytes (8 data bits + ACK per byte)
        bits += payload_bytes * self.bits_per_byte
        
        # Stop condition
        bits += self.stop_bits
        
        return bits
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: bits / clock_rate
        Source: NXP UM10204, Section 3.1.1
        """
        bits = self.frame_bits(payload_bytes)
        return bits / self.clock
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        Source: Energy = Power x Time, P = V x I
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000  # Convert to mJ
    
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        I2C is bidirectional, RX energy similar to TX
        """
        return self.tx_energy(payload_bytes)
    
    def loss_probability(self, distance_m):
        """Wired protocol - no distance-based loss"""
        return 0.0
    
    def extra_packets(self, payload_bytes):
        """I2C uses ACK bits, no extra packets"""
        return 0


class SPI(WiredProtocol):
    """
    SPI Protocol Implementation
    Source: SPI Specification Motorola, Section 2.1
    """
    
    def __init__(self, clock_hz=10000000):
        super().__init__('SPI')
        self.clock = clock_hz
        self.bits_per_byte = self.parameters.get('bits_per_byte', 8)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 2.25)
        self.voltage_v = 3.3
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: 8 bits per byte (no ACK, no start/stop)
        Source: Motorola SPI Block Guide, Section 2.1
        """
        return payload_bytes * self.bits_per_byte
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: bits / clock_rate
        Source: Motorola SPI Block Guide, Section 2.1
        """
        bits = self.frame_bits(payload_bytes)
        return bits / self.clock
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """SPI is full-duplex, RX energy similar to TX"""
        return self.tx_energy(payload_bytes)
    
    def loss_probability(self, distance_m):
        """Wired protocol - no distance-based loss"""
        return 0.0
    
    def extra_packets(self, payload_bytes):
        """SPI has no ACK or extra packets"""
        return 0


class UART(WiredProtocol):
    """
    UART Protocol Implementation
    Source: UART 16550 Datasheet, Section 3.2
    """
    
    def __init__(self, baud_rate=115200, config='8N1'):
        super().__init__('UART')
        self.baud_rate = baud_rate
        self.config = config
        self.bits_per_byte = self.parameters.get('bits_per_byte', 10)  # 8N1 = 10 bits
        self.tx_current_ma = self.parameters.get('tx_current_ma', 0.3)
        self.voltage_v = 3.3
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: bytes x (start + data + parity + stop bits)
        8N1 = 1 start + 8 data + 0 parity + 1 stop = 10 bits per byte
        Source: UART 16550 Datasheet, Section 3.2
        """
        return payload_bytes * self.bits_per_byte
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: bits / baud_rate
        Source: UART 16550 Datasheet, Section 3.2
        """
        bits = self.frame_bits(payload_bytes)
        return bits / self.baud_rate
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """UART RX energy similar to TX"""
        return self.tx_energy(payload_bytes)
    
    def loss_probability(self, distance_m):
        """Wired protocol - no distance-based loss"""
        return 0.0
    
    def extra_packets(self, payload_bytes):
        """UART has no ACK or extra packets"""
        return 0


class CAN(WiredProtocol):
    """
    CAN Protocol Implementation
    Source: CAN 2.0 Specification Bosch, Section 4.1
    """
    
    def __init__(self, bit_rate=1000000):
        super().__init__('CAN')
        self.bit_rate = bit_rate
        self.max_data_bytes = self.parameters.get('max_data_bytes', 8)
        self.overhead_bits = self.parameters.get('overhead_bits', 47)  # Standard CAN frame overhead
        self.tx_current_ma = self.parameters.get('tx_current_ma', 42.5)
        # average of dominant and recessive supply current (MCP2551 DC characteristics)
        if 'dominant_current_ma' in self.parameters:
            f = self.parameters.get('dominant_fraction', 0.5)
            self.tx_current_ma = (f * self.parameters['dominant_current_ma']
                                  + (1 - f) * self.parameters['recessive_current_ma'])
        self.voltage_v = 5.0  # Typical CAN voltage
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: overhead + (8 x data bytes) + bit stuffing
        Bit stuffing adds up to 20% overhead
        Source: CAN 2.0 Specification Bosch, Section 4.2.1
        """
        # Limit payload to max CAN frame sizeClassic CAN max 8 bytes
        payload_bytes = min(payload_bytes, self.max_data_bytes)
        
        # Base frame bits
        bits = self.overhead_bits + (payload_bytes * 8)
        
        # Add bit stuffing (up to 20% overhead)
        bits = int(bits * 1.2)
        
        return bits
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: bits / bit_rate
        Source: CAN 2.0 Specification Bosch, Section 4.2.1
        """
        bits = self.frame_bits(payload_bytes)
        return bits / self.bit_rate
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """CAN RX energy similar to TX"""
        return self.tx_energy(payload_bytes)
    
    def loss_probability(self, distance_m):
        """Wired protocol - no distance-based loss"""
        return 0.0
    
    def extra_packets(self, payload_bytes):
        """CAN uses ACK bit, no extra packets"""
        return 0


class WiFi(WirelessProtocol):
    """
    WiFi Protocol Implementation (802.11g)
    Source: ESP32 Datasheet Espressif, Section 2.4
    """
    
    def __init__(self, phy_rate_mbps=54):
        super().__init__('WiFi')
        self.phy_rate_mbps = phy_rate_mbps
        self.phy_rate_bps = phy_rate_mbps * 1000000
        self.header_bits = self.parameters.get('header_bits', 192)
        self.preamble_us = self.parameters.get('preamble_us', 16)
        self.sifs_us = self.parameters.get('sifs_us', 10)
        self.difs_us = self.parameters.get('difs_us', 34)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 240)
        self.rx_current_ma = self.parameters.get('rx_current_ma', 70)
        self.idle_current_ma = self.parameters.get('idle_current_ma', 15)
        self.sleep_current_ma = self.parameters.get('sleep_current_ma', 0.01)
        self.voltage_v = self.parameters.get('voltage_v', 3.3)
        self.retry_limit = self.parameters.get('retry_limit', 7)
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: MAC/PHY header + payload
        Source: IEEE 802.11 Standard, Section 9.3
        """
        return self.header_bits + (payload_bytes * 8)
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: preamble + (bits / PHY rate) + SIFS + DIFS + backoff + ACK
        Simplified: preamble + data transmission + inter-frame spaces
        Source: IEEE 802.11 Standard, Section 9.3
        """
        bits = self.frame_bits(payload_bytes)
        data_time = bits / self.phy_rate_bps
        
        # Convert microseconds to seconds
        preamble_time = self.preamble_us / 1000000.0
        sifs_time = self.sifs_us / 1000000.0
        difs_time = self.difs_us / 1000000.0
        
        # Add average backoff (half of contention window)
        backoff_time = (self.difs_us / 1000000.0) / 2
        
        # ACK time (simplified)
        ack_time = (self.header_bits / self.phy_rate_bps) + sifs_time
        
        total_time = preamble_time + data_time + sifs_time + difs_time + backoff_time + ack_time
        return total_time
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        Formula: I_rx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.rx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def loss_probability(self, distance_m):
        """
        Calculate loss probability using log-distance path loss
        Source: Rappaport, Wireless Communications, Section 4.7
        """
        return super().loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """
        WiFi requires ACK packet.
        NOTE: the ACK time is already inside airtime(); do not add it again.
        Source: IEEE 802.11 Standard, Section 9.3
        """
        return 1  # ACK packet


class BLE(WirelessProtocol):
    """
    BLE Protocol Implementation
    Source: nRF52832 Datasheet Nordic, Section 6.1
    """
    
    def __init__(self):
        super().__init__('BLE')
        self.phy_rate_mbps = self.parameters.get('phy_rate_mbps', 1)
        self.phy_rate_bps = self.phy_rate_mbps * 1000000
        self.preamble_bits = self.parameters.get('preamble_bits', 8)
        self.access_address_bits = self.parameters.get('access_address_bits', 32)
        self.header_bits = self.parameters.get('header_bits', 8)
        self.crc_bits = self.parameters.get('crc_bits', 24)
        self.max_payload_bytes = self.parameters.get('max_payload_bytes', 20)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 15)
        self.rx_current_ma = self.parameters.get('rx_current_ma', 13)
        self.sleep_current_ma = self.parameters.get('sleep_current_ma', 0.01)
        self.voltage_v = self.parameters.get('voltage_v', 3.3)
        self.retry_limit = self.parameters.get('retry_limit', 3)
    
    def frame_bits(self, payload_bytes):
        """
        Total bits on the wire. Payloads larger than max_payload_bytes are split
        into several packets, each with its own preamble/address/header/CRC.
        """
        packets = max(1, math.ceil(payload_bytes / self.max_payload_bytes))
        overhead = self.preamble_bits + self.access_address_bits + self.header_bits + self.crc_bits
        return packets * overhead + payload_bytes * 8
    
    def airtime(self, payload_bytes):
        """bits / PHY rate + 150 us inter-frame spacing after every packet"""
        packets = max(1, math.ceil(payload_bytes / self.max_payload_bytes))
        data_time = self.frame_bits(payload_bytes) / self.phy_rate_bps
        return data_time + packets * (150 / 1000000.0)
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        Formula: I_rx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.rx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def loss_probability(self, distance_m):
        """Calculate loss probability using log-distance path loss"""
        return super().loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """
        BLE may require ACK depending on connection
        Simplified: 1 extra packet for ACK
        Source: Bluetooth Core Specification 5.0, Section 2.1
        """
        return 1


class Zigbee(WirelessProtocol):
    """
    Zigbee Protocol Implementation (IEEE 802.15.4)
    Source: IEEE 802.15.4 Standard, Section 6.2
    """
    
    def __init__(self):
        super().__init__('Zigbee')
        self.phy_rate_kbps = self.parameters.get('phy_rate_kbps', 250)
        self.phy_rate_bps = self.phy_rate_kbps * 1000
        self.phy_header_bits = self.parameters.get('phy_header_bits', 6)
        self.mac_header_bits = self.parameters.get('mac_header_bits', 104)
        self.max_frame_bytes = self.parameters.get('max_frame_bytes', 127)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 25)
        self.rx_current_ma = self.parameters.get('rx_current_ma', 20)
        self.sleep_current_ma = self.parameters.get('sleep_current_ma', 0.001)
        self.voltage_v = self.parameters.get('voltage_v', 3.3)
        self.retry_limit = self.parameters.get('retry_limit', 4)
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: PHY header + MAC header + payload
        Source: IEEE 802.15.4 Standard, Section 6.2
        """
        # Limit payload to max frame size
        payload_bytes = min(payload_bytes, self.max_frame_bytes)
        
        bits = self.phy_header_bits + self.mac_header_bits + (payload_bytes * 8)
        return bits
    
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Formula: bits / PHY rate + CSMA/CA backoff
        Source: IEEE 802.15.4 Standard, Section 6.2
        """
        bits = self.frame_bits(payload_bytes)
        data_time = bits / self.phy_rate_bps
        
        # CSMA/CA backoff (average of contention window)
        backoff_time = 0.002  # 2ms average backoff
        
        return data_time + backoff_time
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        Formula: I_rx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.rx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def loss_probability(self, distance_m):
        """Calculate loss probability using log-distance path loss"""
        return super().loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """
        Zigbee requires ACK
        Source: IEEE 802.15.4 Standard, Section 6.2
        """
        return 1


class LoRa(WirelessProtocol):
    """
    LoRa Protocol Implementation
    Source: SX1276 Datasheet Semtech, Section 4.1.1
    """
    
    def __init__(self, bandwidth_khz=125, spreading_factor=7, coding_rate=1):
        super().__init__('LoRa')
        self.bandwidth_khz = bandwidth_khz
        self.bandwidth_hz = bandwidth_khz * 1000
        self.spreading_factor = spreading_factor
        self.coding_rate = coding_rate
        self.preamble_symbols = self.parameters.get('preamble_symbols', 8)
        self.tx_current_ma = self.parameters.get('tx_current_ma', 28)
        self.rx_current_ma = self.parameters.get('rx_current_ma', 9.9)
        self.sleep_current_ma = self.parameters.get('sleep_current_ma', 0.0002)
        self.voltage_v = self.parameters.get('voltage_v', 3.3)
        self.retry_limit = self.parameters.get('retry_limit', 3)
        self.duty_cycle_percent = self.parameters.get('duty_cycle_percent', 1)
        # Receiver sensitivity depends on the spreading factor: linear interpolation
        # between the two datasheet points (SF7, SF12); outside that range it is clamped.
        pts = self.parameters.get('sensitivity_by_sf')
        if pts:
            lo, hi = float(pts['7']), float(pts['12'])
            sf = min(max(self.spreading_factor, 7), 12)
            self.sensitivity_dbm = lo + (hi - lo) * (sf - 7) / 5.0

    def frame_bits(self, payload_bytes):
        """Payload + 16-bit CRC + 20-bit explicit header (bits carried by the modem)"""
        crc = 16 if self.parameters.get('crc_enabled', 1) else 0
        header = 0 if self.parameters.get('implicit_header', 0) else 20
        return payload_bytes * 8 + crc + header
    
    def airtime(self, payload_bytes):
        """
        Time on air (Semtech SX127x formula). Duty-cycle waiting is NOT included
        here - see min_off_time().
          Tsym = 2^SF / BW
          Tpreamble = (n_preamble + 4.25) * Tsym
          n_payload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH) / (4*(SF - 2*DE))) * (CR + 4), 0)
        """
        sf = self.spreading_factor
        symbol_time = (2 ** sf) / self.bandwidth_hz
        preamble_time = (self.preamble_symbols + 4.25) * symbol_time

        crc = 1 if self.parameters.get('crc_enabled', 1) else 0
        ih = 1 if self.parameters.get('implicit_header', 0) else 0
        de = 1 if symbol_time > 0.016 else 0      # low data rate optimisation (SF11/12 @125 kHz)

        numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * ih
        denominator = 4 * (sf - 2 * de)
        payload_symbols = 8 + max(math.ceil(numerator / denominator) * (self.coding_rate + 4), 0)

        return preamble_time + payload_symbols * symbol_time

    def min_off_time(self, payload_bytes):
        """Time the node must stay silent after a packet to respect the duty cycle (spend it at SLEEP current)"""
        if self.duty_cycle_percent <= 0:
            return 0.0
        return self.airtime(payload_bytes) * (100.0 / self.duty_cycle_percent - 1.0)
    
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.tx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        Formula: I_rx (A) x V (V) x airtime (s) x 1000
        """
        airtime = self.airtime(payload_bytes)
        current_a = self.rx_current_ma / 1000.0
        energy_j = current_a * self.voltage_v * airtime
        return energy_j * 1000
    
    def loss_probability(self, distance_m):
        """Calculate loss probability using log-distance path loss"""
        return super().loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """LoRa typically doesn't use ACK in basic mode"""
        return 0


class MQTT(ApplicationProtocol):
    """
    MQTT Protocol Implementation (Application Layer)
    Source: MQTT 3.1.1 Specification, Section 2.1
    Runs on top of TCP/IP (typically WiFi)
    """
    
    def __init__(self, qos=0, underlying_protocol=None):
        if underlying_protocol is None:
            # Default to WiFi if not specified
            from protocols import WiFi
            underlying_protocol = WiFi()
        super().__init__('MQTT', underlying_protocol)
        self.qos = qos
        self.fixed_header_bytes = self.parameters.get('fixed_header_bytes', 2)
        self.topic_length_bytes = self.parameters.get('topic_length_bytes', 2)
        self.tcp_ip_overhead_bytes = self.parameters.get('tcp_ip_overhead_bytes', 40)
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: MQTT header + topic length + payload + TCP/IP overhead
        Source: MQTT 3.1.1 Specification, Section 2.1
        """
        total_bytes = self.fixed_header_bytes + self.topic_length_bytes
        total_bytes += payload_bytes + self.tcp_ip_overhead_bytes
        return total_bytes * 8
    
    def _packet_sizes(self, payload_bytes):
        """Bytes sent for each packet of the QoS exchange (including TCP/IP overhead)"""
        publish = self.fixed_header_bytes + self.topic_length_bytes + payload_bytes + self.tcp_ip_overhead_bytes
        if self.qos > 0:
            publish += 2                               # packet identifier
        ack = 4 + self.tcp_ip_overhead_bytes           # PUBACK / PUBREC / PUBREL / PUBCOMP = 4 bytes
        return {0: [publish], 1: [publish, ack], 2: [publish, ack, ack, ack]}.get(self.qos, [publish])

    def airtime(self, payload_bytes):
        """Sum of the underlying link's airtime for every packet of the QoS exchange"""
        return sum(self.underlying_protocol.airtime(b) for b in self._packet_sizes(payload_bytes))
    
    def tx_energy(self, payload_bytes):
        return sum(self.underlying_protocol.tx_energy(b) for b in self._packet_sizes(payload_bytes))
    
    def rx_energy(self, payload_bytes):
        return sum(self.underlying_protocol.rx_energy(b) for b in self._packet_sizes(payload_bytes))
    
    def loss_probability(self, distance_m):
        """Use underlying protocol's loss model"""
        return self.underlying_protocol.loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """
        Extra packets based on QoS level
        QoS 0: 0 extra (just PUBLISH)
        QoS 1: 1 extra (PUBACK)
        QoS 2: 3 extra (PUBREC, PUBREL, PUBCOMP)
        Source: MQTT 3.1.1 Specification, Section 4.3
        """
        return {0: 0, 1: 1, 2: 3}.get(self.qos, 0)


class CoAP(ApplicationProtocol):
    """
    CoAP Protocol Implementation (Application Layer)
    Source: RFC 7252, Section 4.2
    Runs on top of UDP/IP (typically WiFi)
    """
    
    def __init__(self, confirmable=True, observe=False, underlying_protocol=None):
        if underlying_protocol is None:
            from protocols import WiFi
            underlying_protocol = WiFi()
        super().__init__('CoAP', underlying_protocol)
        self.confirmable = confirmable
        self.observe = observe
        self.header_bytes = self.parameters.get('header_bytes', 4)
        self.token_bytes = self.parameters.get('token_bytes', 4)
        self.udp_ip_overhead_bytes = self.parameters.get('udp_ip_overhead_bytes', 28)
        self.ack_timeout_s = self.parameters.get('ack_timeout_s', 2)
        self.ack_random_factor = self.parameters.get('ack_random_factor', 1.5)
        self.max_retransmit = self.parameters.get('max_retransmit', 4)
    
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire
        Formula: CoAP header + token + options + payload + UDP/IP overhead
        Source: RFC 7252, Section 3
        """
        total_bytes = self.header_bytes + self.token_bytes
        total_bytes += payload_bytes + self.udp_ip_overhead_bytes
        return total_bytes * 8
    
    def _packet_sizes(self, payload_bytes):
        """Bytes for one exchange without loss: message (+ empty ACK if confirmable)"""
        msg = self.header_bytes + self.token_bytes + payload_bytes + self.udp_ip_overhead_bytes
        ack = self.header_bytes + self.udp_ip_overhead_bytes
        return [msg, ack] if self.confirmable else [msg]

    def airtime(self, payload_bytes):
        """No-loss exchange. Retransmissions (max_retransmit, ack_timeout) are added by the engine when a packet is lost."""
        return sum(self.underlying_protocol.airtime(b) for b in self._packet_sizes(payload_bytes))
    
    def tx_energy(self, payload_bytes):
        return sum(self.underlying_protocol.tx_energy(b) for b in self._packet_sizes(payload_bytes))
    
    def rx_energy(self, payload_bytes):
        return sum(self.underlying_protocol.rx_energy(b) for b in self._packet_sizes(payload_bytes))
    
    def loss_probability(self, distance_m):
        """Use underlying protocol's loss model"""
        return self.underlying_protocol.loss_probability(distance_m)
    
    def extra_packets(self, payload_bytes):
        """Confirmable: 1 ACK. Retransmissions are not counted here (they depend on loss)."""
        return 1 if self.confirmable else 0

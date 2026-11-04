"""
Standard Protocol Interface for IoT Simulator
All protocols must implement these methods with datasheet-based formulas.
"""

from abc import ABC, abstractmethod
import json
import math
import os

PARAMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protocol_parameters.json')


class ProtocolInterface(ABC):
    """Base class for all IoT protocols"""
    
    def __init__(self, name, protocol_type):
        self.name = name
        self.protocol_type = protocol_type  # 'wired', 'wireless', 'application'
        self.parameters = self._load_parameters()
    
    def _load_parameters(self):
        """Load protocol parameters from JSON file"""
        with open(PARAMS_FILE, 'r') as f:
            data = json.load(f)
        return data['protocol_parameters'].get(self.name, {})
    
    @abstractmethod
    def frame_bits(self, payload_bytes):
        """
        Calculate total bits on the wire (payload + overhead)
        Args:
            payload_bytes: Size of payload in bytes
        Returns:
            Total bits transmitted
        """
        pass
    
    @abstractmethod
    def airtime(self, payload_bytes):
        """
        Calculate transmission time in seconds
        Args:
            payload_bytes: Size of payload in bytes
        Returns:
            Airtime in seconds
        """
        pass
    
    @abstractmethod
    def tx_energy(self, payload_bytes):
        """
        Calculate transmission energy in mJ
        Formula: I_tx (A) x V (V) x airtime (s) x 1000
        Args:
            payload_bytes: Size of payload in bytes
        Returns:
            Energy in millijoules
        """
        pass
    
    @abstractmethod
    def rx_energy(self, payload_bytes):
        """
        Calculate reception energy in mJ
        Formula: I_rx (A) x V (V) x airtime (s) x 1000
        Args:
            payload_bytes: Size of payload in bytes
        Returns:
            Energy in millijoules
        """
        pass
    
    @abstractmethod
    def loss_probability(self, distance_m):
        """
        Calculate packet loss probability based on distance
        Args:
            distance_m: Distance in meters
        Returns:
            Loss probability (0.0 to 1.0)
        """
        pass
    
    @abstractmethod
    def extra_packets(self, payload_bytes):
        """
        Calculate additional packets (ACKs, handshakes, etc.)
        Args:
            payload_bytes: Size of payload in bytes
        Returns:
            Number of extra packets
        """
        pass


class WiredProtocol(ProtocolInterface):
    """Base class for wired protocols (no distance-based loss)"""
    
    def __init__(self, name):
        super().__init__(name, 'wired')
    
    def loss_probability(self, distance_m):
        """Wired protocols have no distance-based loss"""
        return 0.0


class WirelessProtocol(ProtocolInterface):
    """Base class for wireless protocols (distance-based loss, link budget)"""

    def __init__(self, name):
        super().__init__(name, 'wireless')
        # Radio / channel values come from protocol_parameters.json.
        # The defaults below are ASSUMPTIONS - verify against the datasheet/standard.
        p = self.parameters
        self.tx_power_dbm = p.get('tx_power_dbm', 0.0)
        self.sensitivity_dbm = p.get('sensitivity_dbm', -90.0)
        self.path_loss_exponent = p.get('path_loss_exponent', 2.7)
        self.reference_distance = p.get('reference_distance_m', 1.0)
        self.reference_loss_db = p.get('reference_loss_db', 40.0)
        self.loss_steepness = p.get('loss_steepness', 0.5)   # 1/dB, logistic slope (modelling choice)

    def path_loss_db(self, distance_m):
        """Log-distance path loss: PL = PL0 + 10*n*log10(d/d0)"""
        d = max(distance_m, self.reference_distance)
        return self.reference_loss_db + 10 * self.path_loss_exponent * math.log10(d / self.reference_distance)

    def loss_probability(self, distance_m):
        """
        Link budget -> packet loss probability.
        margin = TX power - path loss - receiver sensitivity
        loss   = 1 / (1 + exp(k * margin))   (0.5 at zero margin, ->0 for large margin)
        """
        if distance_m <= 0:
            return 0.0
        margin_db = self.tx_power_dbm - self.path_loss_db(distance_m) - self.sensitivity_dbm
        x = self.loss_steepness * margin_db
        if x > 50:
            return 0.0
        if x < -50:
            return 1.0
        return 1.0 / (1.0 + math.exp(x))


class ApplicationProtocol(ProtocolInterface):
    """Base class for application layer protocols (run on top of link layer)"""
    
    def __init__(self, name, underlying_protocol):
        super().__init__(name, 'application')
        self.underlying_protocol = underlying_protocol
    
    def loss_probability(self, distance_m):
        """Use underlying protocol's loss model"""
        return self.underlying_protocol.loss_probability(distance_m)

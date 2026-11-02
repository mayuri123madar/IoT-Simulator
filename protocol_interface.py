"""
Standard Protocol Interface for IoT Simulator
All protocols must implement these methods with datasheet-based formulas.
"""

from abc import ABC, abstractmethod
import json
import os


class ProtocolInterface(ABC):
    """Base class for all IoT protocols"""
    
    def __init__(self, name, protocol_type):
        self.name = name
        self.protocol_type = protocol_type  # 'wired', 'wireless', 'application'
        self.parameters = self._load_parameters()
    
    def _load_parameters(self):
        """Load protocol parameters from JSON file"""
        try:
            with open('protocol_parameters.json', 'r') as f:
                data = json.load(f)
                return data['protocol_parameters'].get(self.name, {})
        except:
            return {}
    
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
    """Base class for wireless protocols (distance-based loss)"""
    
    def __init__(self, name):
        super().__init__(name, 'wireless')
        # Log-distance path loss model parameters
        self.path_loss_exponent = 2.0  # Free space
        self.reference_distance = 1.0  # 1 meter
        self.reference_loss_db = 40.0  # Loss at 1m
    
    def loss_probability(self, distance_m):
        """
        Calculate loss probability using log-distance path loss model
        Source: Rappaport, Wireless Communications, Section 4.7
        """
        if distance_m <= 0:
            return 0.0
        
        # Path loss in dB
        path_loss_db = self.reference_loss_db + \
                      10 * self.path_loss_exponent * \
                      (distance_m / self.reference_distance)
        
        # Convert to probability (simplified model)
        # Higher path loss = higher probability of loss
        loss_prob = min(path_loss_db / 120.0, 1.0)  # 120dB = complete loss
        
        return loss_prob


class ApplicationProtocol(ProtocolInterface):
    """Base class for application layer protocols (run on top of link layer)"""
    
    def __init__(self, name, underlying_protocol):
        super().__init__(name, 'application')
        self.underlying_protocol = underlying_protocol
    
    def loss_probability(self, distance_m):
        """Use underlying protocol's loss model"""
        return self.underlying_protocol.loss_probability(distance_m)

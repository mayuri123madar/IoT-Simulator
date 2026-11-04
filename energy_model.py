"""
Energy Model for IoT Devices
Implements TX/RX/idle/sleep energy consumption and battery drain
Source: Energy = Current (A) x Voltage (V) x Time (s) x 1000 (for mJ)
"""

import json
import os

PARAMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protocol_parameters.json')


class EnergyModel:
    """
    Energy model for IoT devices
    Tracks energy consumption in different states and battery drain
    """
    
    def __init__(self, device_type, battery_mah=0, voltage_v=None):
        """
        Initialize energy model
        Args:
            device_type: Type of device (ESP32, Arduino, etc.)
            battery_mah: Battery capacity in mAh (0 if no battery)
            voltage_v: Supply voltage in volts
        """
        self.device_type = device_type
        self.battery_capacity_mah = battery_mah
        self.battery_current_mah = battery_mah

        # Load device parameters
        self.parameters = self._load_device_parameters()
        # Supply voltage: explicit argument, else the device's power_v from the JSON, else 3.3 V
        self.voltage_v = voltage_v if voltage_v is not None else self.parameters.get('power_v', 3.3)
        
        # Energy consumption tracking (in mJ)
        self.tx_energy_mj = 0.0
        self.rx_energy_mj = 0.0
        self.idle_energy_mj = 0.0
        self.sleep_energy_mj = 0.0
        self.total_energy_mj = 0.0
        
        # Time tracking (in seconds)
        self.tx_time_s = 0.0
        self.rx_time_s = 0.0
        self.idle_time_s = 0.0
        self.sleep_time_s = 0.0
        self.total_time_s = 0.0
        
        # Device state
        self.state = 'idle'  # idle, tx, rx, sleep, dead
        self.is_dead = False
    
    def _load_device_parameters(self):
        """Load device parameters from JSON file"""
        with open(PARAMS_FILE, 'r') as f:
            data = json.load(f)
        return data.get('device_parameters', {}).get(self.device_type, {})
    
    def get_current_ma(self, state):
        """
        Get current draw for a given state
        Args:
            state: 'tx', 'rx', 'idle', 'sleep'
        Returns:
            Current in mA
        """
        # Try to get from device parameters
        if state == 'tx':
            return self.parameters.get('tx_current_ma', 100)
        elif state == 'rx':
            return self.parameters.get('rx_current_ma', 50)
        elif state == 'idle':
            return self.parameters.get('idle_current_ma', 15)
        elif state == 'sleep':
            return self.parameters.get('sleep_current_ma', 0.01)
        return 0
    
    def _add(self, state, time_s, current_ma=None):
        """
        Charge `time_s` seconds in `state` ('tx', 'rx', 'idle', 'sleep').
        current_ma: override the current (e.g. the radio's TX current from the protocol).
        Returns the energy added in mJ. This is the ONLY place energy is computed.
        Formula: E(mJ) = I(A) x V(V) x t(s) x 1000
        """
        if self.is_dead or time_s <= 0:
            return 0.0
        if current_ma is None:
            current_ma = self.get_current_ma(state)
        energy_mj = (current_ma / 1000.0) * self.voltage_v * time_s * 1000
        setattr(self, f'{state}_energy_mj', getattr(self, f'{state}_energy_mj') + energy_mj)
        setattr(self, f'{state}_time_s', getattr(self, f'{state}_time_s') + time_s)
        self.total_energy_mj += energy_mj
        self.total_time_s += time_s
        self._drain_battery(current_ma, time_s)
        return energy_mj

    def add_tx_energy(self, time_s, current_ma=None):
        """Add transmission energy (mJ returned)"""
        return self._add('tx', time_s, current_ma)

    def add_rx_energy(self, time_s, current_ma=None):
        """Add reception energy (mJ returned)"""
        return self._add('rx', time_s, current_ma)

    def add_idle_energy(self, time_s, current_ma=None):
        """Add idle energy (mJ returned)"""
        return self._add('idle', time_s, current_ma)

    def add_sleep_energy(self, time_s, current_ma=None):
        """Add sleep energy (mJ returned)"""
        return self._add('sleep', time_s, current_ma)

    def _drain_battery(self, current_ma, time_s):
        """
        Drain battery based on current and time
        Formula: drain (mAh) = current (mA) x time (s) / 3600
        Source: Battery discharge formula
        """
        if self.battery_capacity_mah <= 0:
            return  # No battery
        
        drain_mah = current_ma * time_s / 3600.0
        self.battery_current_mah -= drain_mah
        
        # Check if battery is dead
        if self.battery_current_mah <= 0:
            self.battery_current_mah = 0
            self.is_dead = True
            self.state = 'dead'
            return True  # Battery just died
        return False
    
    def get_battery_percentage(self):
        """
        Get battery percentage
        Returns:
            Battery percentage (0-100), or None if no battery
        """
        if self.battery_capacity_mah <= 0:
            return None
        
        return (self.battery_current_mah / self.battery_capacity_mah) * 100
    
    def get_energy_summary(self):
        """
        Get energy consumption summary
        Returns:
            Dictionary with energy statistics
        """
        return {
            'tx_energy_mj': self.tx_energy_mj,
            'rx_energy_mj': self.rx_energy_mj,
            'idle_energy_mj': self.idle_energy_mj,
            'sleep_energy_mj': self.sleep_energy_mj,
            'total_energy_mj': self.total_energy_mj,
            'tx_time_s': self.tx_time_s,
            'rx_time_s': self.rx_time_s,
            'idle_time_s': self.idle_time_s,
            'sleep_time_s': self.sleep_time_s,
            'total_time_s': self.total_time_s,
            'battery_percentage': self.get_battery_percentage(),
            'is_dead': self.is_dead,
            'state': self.state
        }
    
    def reset(self):
        """Reset energy counters"""
        self.tx_energy_mj = 0.0
        self.rx_energy_mj = 0.0
        self.idle_energy_mj = 0.0
        self.sleep_energy_mj = 0.0
        self.total_energy_mj = 0.0
        self.tx_time_s = 0.0
        self.rx_time_s = 0.0
        self.idle_time_s = 0.0
        self.sleep_time_s = 0.0
        self.total_time_s = 0.0
        self.battery_current_mah = self.battery_capacity_mah
        self.is_dead = False
        self.state = 'idle'

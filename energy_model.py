"""
Energy Model for IoT Devices
Implements TX/RX/idle/sleep energy consumption and battery drain
Source: Energy = Current (A) x Voltage (V) x Time (s) x 1000 (for mJ)
"""

import json


class EnergyModel:
    """
    Energy model for IoT devices
    Tracks energy consumption in different states and battery drain
    """
    
    def __init__(self, device_type, battery_mah=0, voltage_v=3.3):
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
        self.voltage_v = voltage_v
        
        # Load device parameters
        self.parameters = self._load_device_parameters()
        
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
        try:
            with open('protocol_parameters.json', 'r') as f:
                data = json.load(f)
                return data['device_parameters'].get(self.device_type, {})
        except:
            return {}
    
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
    
    def add_tx_energy(self, time_s):
        """
        Add transmission energy
        Args:
            time_s: Transmission time in seconds
        """
        if self.is_dead:
            return
        
        current_ma = self.get_current_ma('tx')
        current_a = current_ma / 1000.0
        energy_j = current_a * self.voltage_v * time_s
        energy_mj = energy_j * 1000
        
        self.tx_energy_mj += energy_mj
        self.total_energy_mj += energy_mj
        self.tx_time_s += time_s
        self.total_time_s += time_s
        
        # Drain battery
        self._drain_battery(current_ma, time_s)
    
    def add_rx_energy(self, time_s):
        """
        Add reception energy
        Args:
            time_s: Reception time in seconds
        """
        if self.is_dead:
            return
        
        current_ma = self.get_current_ma('rx')
        current_a = current_ma / 1000.0
        energy_j = current_a * self.voltage_v * time_s
        energy_mj = energy_j * 1000
        
        self.rx_energy_mj += energy_mj
        self.total_energy_mj += energy_mj
        self.rx_time_s += time_s
        self.total_time_s += time_s
        
        # Drain battery
        self._drain_battery(current_ma, time_s)
    
    def add_idle_energy(self, time_s):
        """
        Add idle energy
        Args:
            time_s: Idle time in seconds
        """
        if self.is_dead:
            return
        
        current_ma = self.get_current_ma('idle')
        current_a = current_ma / 1000.0
        energy_j = current_a * self.voltage_v * time_s
        energy_mj = energy_j * 1000
        
        self.idle_energy_mj += energy_mj
        self.total_energy_mj += energy_mj
        self.idle_time_s += time_s
        self.total_time_s += time_s
        
        # Drain battery
        self._drain_battery(current_ma, time_s)
    
    def add_sleep_energy(self, time_s):
        """
        Add sleep energy
        Args:
            time_s: Sleep time in seconds
        """
        if self.is_dead:
            return
        
        current_ma = self.get_current_ma('sleep')
        current_a = current_ma / 1000.0
        energy_j = current_a * self.voltage_v * time_s
        energy_mj = energy_j * 1000
        
        self.sleep_energy_mj += energy_mj
        self.total_energy_mj += energy_mj
        self.sleep_time_s += time_s
        self.total_time_s += time_s
        
        # Drain battery
        self._drain_battery(current_ma, time_s)
    
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

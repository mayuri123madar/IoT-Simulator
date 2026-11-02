"""
Recommendation Engine for Protocol and Topology Comparison
Provides intelligent recommendations based on use case requirements
"""

from protocols import I2C, SPI, UART, CAN, WiFi, BLE, Zigbee, LoRa, MQTT, CoAP


class RecommendationEngine:
    """
    Engine for recommending protocols and topologies based on requirements
    """
    
    def __init__(self):
        self.protocol_capabilities = self._build_protocol_capabilities()
    
    def _build_protocol_capabilities(self):
        """Build capability matrix for all protocols"""
        return {
            'I2C': {
                'type': 'wired',
                'max_range_m': 0.5,
                'max_data_rate_kbps': 400,
                'power_consumption': 'low',
                'topology': ['bus'],
                'use_cases': ['sensor_readings', 'short_range', 'low_power'],
                'pros': ['Simple', 'Low power', 'Multi-master'],
                'cons': ['Short range', 'Low speed', 'No error correction']
            },
            'SPI': {
                'type': 'wired',
                'max_range_m': 1.0,
                'max_data_rate_kbps': 10000,
                'power_consumption': 'medium',
                'topology': ['point-to-point'],
                'use_cases': ['high_speed', 'short_range', 'sensor_readings'],
                'pros': ['High speed', 'Full duplex', 'Simple'],
                'cons': ['Short range', 'No addressing', 'More pins']
            },
            'UART': {
                'type': 'wired',
                'max_range_m': 15.0,
                'max_data_rate_kbps': 115.2,
                'power_consumption': 'low',
                'topology': ['point-to-point'],
                'use_cases': ['debugging', 'modem', 'short_range'],
                'pros': ['Simple', 'Widely available', 'Configurable'],
                'cons': ['Point-to-point only', 'No addressing', 'No flow control']
            },
            'CAN': {
                'type': 'wired',
                'max_range_m': 40.0,
                'max_data_rate_kbps': 1000,
                'power_consumption': 'medium',
                'topology': ['bus'],
                'use_cases': ['automotive', 'industrial', 'reliable'],
                'pros': ['Reliable', 'Error detection', 'Priority arbitration'],
                'cons': ['Complex', 'Overhead', 'Limited bandwidth']
            },
            'WiFi': {
                'type': 'wireless',
                'max_range_m': 100.0,
                'max_data_rate_kbps': 54000,
                'power_consumption': 'high',
                'topology': ['star', 'mesh', 'infrastructure'],
                'use_cases': ['high_bandwidth', 'internet', 'streaming'],
                'pros': ['High speed', 'Widely available', 'IP connectivity'],
                'cons': ['High power', 'Short range', 'Complex setup']
            },
            'BLE': {
                'type': 'wireless',
                'max_range_m': 100.0,
                'max_data_rate_kbps': 1000,
                'power_consumption': 'low',
                'topology': ['star', 'mesh'],
                'use_cases': ['low_power', 'short_range', 'wearables'],
                'pros': ['Low power', 'Widely available', 'Secure'],
                'cons': ['Limited bandwidth', 'Short range', 'Complex']
            },
            'Zigbee': {
                'type': 'wireless',
                'max_range_m': 100.0,
                'max_data_rate_kbps': 250,
                'power_consumption': 'low',
                'topology': ['mesh', 'star', 'tree'],
                'use_cases': ['home_automation', 'iot', 'low_power'],
                'pros': ['Mesh networking', 'Low power', 'Scalable'],
                'cons': ['Low bandwidth', 'Complex', 'Limited range']
            },
            'LoRa': {
                'type': 'wireless',
                'max_range_m': 15000.0,
                'max_data_rate_kbps': 50,
                'power_consumption': 'low',
                'topology': ['star'],
                'use_cases': ['long_range', 'low_power', 'rural'],
                'pros': ['Very long range', 'Low power', 'Penetrates obstacles'],
                'cons': ['Very low bandwidth', 'High latency', 'Duty cycle limits']
            },
            'MQTT': {
                'type': 'application',
                'max_range_m': 100.0,  # Depends on underlying protocol
                'max_data_rate_kbps': 54000,  # Depends on underlying protocol
                'power_consumption': 'medium',
                'topology': ['star', 'pub-sub'],
                'use_cases': ['iot', 'messaging', 'cloud'],
                'pros': ['Lightweight', 'Pub-sub model', 'QoS levels'],
                'cons': ['Requires broker', 'TCP overhead', 'Not real-time']
            },
            'CoAP': {
                'type': 'application',
                'max_range_m': 100.0,  # Depends on underlying protocol
                'max_data_rate_kbps': 250,  # Depends on underlying protocol
                'power_consumption': 'low',
                'topology': ['star', 'client-server'],
                'use_cases': ['iot', 'constrained', 'restful'],
                'pros': ['Lightweight', 'RESTful', 'UDP efficient'],
                'cons': ['Limited reliability', 'No pub-sub', 'Complex']
            }
        }
    
    def recommend_protocol(self, requirements):
        """
        Recommend protocol based on requirements
        Args:
            requirements: Dictionary with keys:
                - range_m: Required range in meters
                - data_rate_kbps: Required data rate in kbps
                - power_level: 'low', 'medium', 'high'
                - topology: 'star', 'mesh', 'bus', 'point-to-point'
                - use_case: 'sensor_readings', 'streaming', 'control', etc.
        Returns:
            List of recommended protocols with scores
        """
        recommendations = []
        
        for protocol_name, capabilities in self.protocol_capabilities.items():
            score = 0
            reasons = []
            
            # Check range requirement
            if 'range_m' in requirements:
                if capabilities['max_range_m'] >= requirements['range_m']:
                    score += 25
                    reasons.append(f"Meets range requirement ({requirements['range_m']}m)")
                else:
                    score -= 50
                    reasons.append(f"Insufficient range (max {capabilities['max_range_m']}m)")
            
            # Check data rate requirement
            if 'data_rate_kbps' in requirements:
                if capabilities['max_data_rate_kbps'] >= requirements['data_rate_kbps']:
                    score += 25
                    reasons.append(f"Meets data rate requirement ({requirements['data_rate_kbps']}kbps)")
                else:
                    score -= 50
                    reasons.append(f"Insufficient data rate (max {capabilities['max_data_rate_kbps']}kbps)")
            
            # Check power requirement
            if 'power_level' in requirements:
                power_map = {'low': 1, 'medium': 2, 'high': 3}
                if power_map.get(capabilities['power_consumption'], 2) <= power_map.get(requirements['power_level'], 2):
                    score += 25
                    reasons.append(f"Meets power requirement ({requirements['power_level']})")
                else:
                    score -= 25
                    reasons.append(f"Exceeds power limit ({capabilities['power_consumption']})")
            
            # Check topology requirement
            if 'topology' in requirements:
                if requirements['topology'] in capabilities['topology']:
                    score += 25
                    reasons.append(f"Supports {requirements['topology']} topology")
                else:
                    score -= 25
                    reasons.append(f"Does not support {requirements['topology']} topology")
            
            # Check use case
            if 'use_case' in requirements:
                if requirements['use_case'] in capabilities['use_cases']:
                    score += 20
                    reasons.append(f"Suitable for {requirements['use_case']}")
            
            if score > 0:
                recommendations.append({
                    'protocol': protocol_name,
                    'score': score,
                    'reasons': reasons,
                    'pros': capabilities['pros'],
                    'cons': capabilities['cons']
                })
        
        # Sort by score (highest first)
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations
    
    def compare_protocols(self, protocol_names, payload_bytes=100, distance_m=10):
        """
        Compare multiple protocols with actual calculations
        Args:
            protocol_names: List of protocol names to compare
            payload_bytes: Payload size in bytes for calculations
            distance_m: Distance in meters for loss calculation
        Returns:
            Comparison results with metrics
        """
        comparison = {}
        
        for protocol_name in protocol_names:
            try:
                protocol = create_protocol(protocol_name)
                
                comparison[protocol_name] = {
                    'frame_bits': protocol.frame_bits(payload_bytes),
                    'airtime_s': protocol.airtime(payload_bytes),
                    'tx_energy_mj': protocol.tx_energy(payload_bytes),
                    'rx_energy_mj': protocol.rx_energy(payload_bytes),
                    'loss_probability': protocol.loss_probability(distance_m),
                    'extra_packets': protocol.extra_packets(payload_bytes),
                    'capabilities': self.protocol_capabilities.get(protocol_name, {})
                }
            except ValueError:
                comparison[protocol_name] = {'error': 'Unknown protocol'}
        
        return comparison
    
    def recommend_topology(self, num_devices, area_size_m2, requirements):
        """
        Recommend network topology based on requirements
        Args:
            num_devices: Number of devices in network
            area_size_m2: Area size in square meters
            requirements: Dictionary with requirements
        Returns:
            Recommended topology with reasoning
        """
        recommendations = []
        
        # Calculate device density
        density = num_devices / area_size_m2 if area_size_m2 > 0 else 0
        
        # Star topology
        star_score = 0
        star_reasons = []
        if num_devices < 50:
            star_score += 30
            star_reasons.append("Suitable for small networks")
        if density > 0.1:
            star_score += 20
            star_reasons.append("High device density")
        if requirements.get('low_latency', False):
            star_score += 25
            star_reasons.append("Low latency")
        if requirements.get('simple_setup', False):
            star_score += 25
            star_reasons.append("Simple setup")
        
        recommendations.append({
            'topology': 'star',
            'score': star_score,
            'reasons': star_reasons,
            'suitable_protocols': ['WiFi', 'BLE', 'Zigbee']
        })
        
        # Mesh topology
        mesh_score = 0
        mesh_reasons = []
        if num_devices > 20:
            mesh_score += 30
            mesh_reasons.append("Suitable for larger networks")
        if area_size_m2 > 1000:
            mesh_score += 25
            mesh_reasons.append("Large coverage area")
        if requirements.get('reliability', False):
            mesh_score += 25
            mesh_reasons.append("High reliability with redundancy")
        if requirements.get('self_healing', False):
            mesh_score += 20
            mesh_reasons.append("Self-healing capability")
        
        recommendations.append({
            'topology': 'mesh',
            'score': mesh_score,
            'reasons': mesh_reasons,
            'suitable_protocols': ['Zigbee', 'BLE']
        })
        
        # Bus topology
        bus_score = 0
        bus_reasons = []
        if num_devices < 20:
            bus_score += 25
            bus_reasons.append("Suitable for small networks")
        if requirements.get('wired', False):
            bus_score += 35
            bus_reasons.append("Wired infrastructure")
        if requirements.get('cost_sensitive', False):
            bus_score += 25
            bus_reasons.append("Low cost")
        if requirements.get('deterministic', False):
            bus_score += 15
            bus_reasons.append("Deterministic timing")
        
        recommendations.append({
            'topology': 'bus',
            'score': bus_score,
            'reasons': bus_reasons,
            'suitable_protocols': ['I2C', 'CAN']
        })
        
        # Sort by score
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        
        return recommendations


# Import create_protocol from app.py context
def create_protocol(protocol_name, **kwargs):
    """Protocol factory (duplicate of app.py function for standalone use)"""
    protocol_map = {
        'I2C': I2C,
        'SPI': SPI,
        'UART': UART,
        'CAN': CAN,
        'WiFi': WiFi,
        'BLE': BLE,
        'Zigbee': Zigbee,
        'LoRa': LoRa,
        'MQTT': MQTT,
        'CoAP': CoAP
    }
    
    protocol_class = protocol_map.get(protocol_name)
    if protocol_class:
        return protocol_class(**kwargs)
    else:
        raise ValueError(f"Unknown protocol: {protocol_name}")

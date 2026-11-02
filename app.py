from flask import Flask, render_template, request, jsonify, send_from_directory
import ast
import sys
import json
import os
from io import StringIO
from datetime import datetime
import re

# Import new protocol system
from protocols import I2C, SPI, UART, CAN, WiFi, BLE, Zigbee, LoRa, MQTT, CoAP
from energy_model import EnergyModel
from recommendation_engine import RecommendationEngine

# Protocol factory
def create_protocol(protocol_name, **kwargs):
    """
    Create a protocol instance by name
    Args:
        protocol_name: Name of protocol (I2C, SPI, UART, CAN, WiFi, BLE, Zigbee, LoRa, MQTT, CoAP)
        **kwargs: Protocol-specific parameters
    Returns:
        Protocol instance
    """
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

# OpenAI API integration (optional)
try:
    import openai
    OPENAI_AVAILABLE = True
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
except ImportError:
    OPENAI_AVAILABLE = False
    OPENAI_API_KEY = ''

app = Flask(__name__)

# Create networks directory if it doesn't exist
NETWORKS_DIR = "saved_networks"
if not os.path.exists(NETWORKS_DIR):
    os.makedirs(NETWORKS_DIR)

# Create trace files directory if it doesn't exist
TRACE_DIR = "trace_files"
if not os.path.exists(TRACE_DIR):
    os.makedirs(TRACE_DIR)

# ---------- IOT CLASSES FOR PYTHON SCRIPTS ----------
class IoTNetwork:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.states = {}
        self.dead_nodes = set()  # Track dead nodes for rerouting
    
    def add_node(self, node_obj):
        self.nodes[node_obj.id] = node_obj.type
        if hasattr(node_obj, 'state'):
            self.states[node_obj.id] = node_obj.state
    
    def connect_nodes(self, source_obj, target_obj):
        if source_obj.id not in self.nodes:
            raise ValueError(f"Source node '{source_obj.id}' does not exist")
        if target_obj.id not in self.nodes:
            raise ValueError(f"Target node '{target_obj.id}' does not exist")
        self.edges.append((source_obj.id, target_obj.id))
    
    def mark_node_dead(self, node_id):
        """Mark a node as dead (battery depleted)"""
        if node_id in self.nodes:
            self.dead_nodes.add(node_id)
            self.states[node_id] = 'dead'
    
    def get_alternative_path(self, source_id, target_id):
        """
        Find alternative path avoiding dead nodes
        Returns list of node IDs forming the path, or None if no path exists
        """
        if source_id not in self.nodes or target_id not in self.nodes:
            return None
        
        if source_id in self.dead_nodes or target_id in self.dead_nodes:
            return None
        
        # BFS to find path avoiding dead nodes
        from collections import deque
        queue = deque([(source_id, [])])
        visited = set()
        
        while queue:
            current, path = queue.popleft()
            
            if current == target_id:
                return path + [current]
            
            if current in visited or current in self.dead_nodes:
                continue
            
            visited.add(current)
            
            # Find neighbors
            neighbors = [edge[1] for edge in self.edges if edge[0] == current]
            neighbors += [edge[0] for edge in self.edges if edge[1] == current]
            
            for neighbor in neighbors:
                if neighbor not in visited and neighbor not in self.dead_nodes:
                    queue.append((neighbor, path + [current]))
        
        return None  # No path found

# Mock RPi.GPIO module for simulation
class MockGPIO:
    """Mock GPIO module for simulation purposes"""
    BCM = 'BCM'
    BOARD = 'BOARD'
    OUT = 'OUT'
    IN = 'IN'
    HIGH = 1
    LOW = 0
    
    @staticmethod
    def setmode(mode):
        pass
    
    @staticmethod
    def setup(channel, direction):
        pass
    
    @staticmethod
    def output(channel, value):
        pass
    
    @staticmethod
    def input(channel):
        return 0
    
    @staticmethod
    def cleanup():
        pass

# Mock RPi module
class MockRPi:
    GPIO = MockGPIO()

# Initialize recommendation engine
recommendation_engine = RecommendationEngine()

# Base IoT Device Class
class IoTDevice:
    def __init__(self, device_id, device_type, network_ref=None, protocol=None, battery_mah=0):
        self.id = device_id
        self.type = device_type
        self.state = "off"
        self.protocol = protocol
        # Use provided network or global network
        if network_ref:
            self.network = network_ref
        else:
            # Don't use global network here - it might not exist yet
            self.network = None
        
        # Initialize energy model
        self.energy_model = EnergyModel(device_type, battery_mah)
    
    def turn_on(self):
        self.state = "on"
        # Update network state if network exists
        if self.network:
            self.network.states[self.id] = "on"
    
    def turn_off(self):
        self.state = "off"
        # Update network state if network exists
        if self.network:
            self.network.states[self.id] = "off"
    
    def connect(self, other_device):
        if self.network:
            self.network.connect_nodes(self, other_device)
        else:
            raise ValueError("No network available for connection")
    
    def get_data(self):
        """Simulate data retrieval from device"""
        if self.type == "Sensor":
            return {"sensor_id": self.id, "value": 25.5, "unit": "C"}
        elif self.type == "Camera":
            return {"camera_id": self.id, "status": "recording"}
        else:
            return {"device_id": self.id, "status": self.state}
    
    def send_data(self, data):
        """Simulate sending data from device using protocol"""
        if self.protocol:
            # Calculate energy and latency using protocol
            data_size = len(str(data))  # Simplified data size
            airtime = self.protocol.airtime(data_size)
            tx_energy = self.protocol.tx_energy(data_size)
            
            # Add to energy model
            self.energy_model.add_tx_energy(airtime)
            
            return {
                "device_id": self.id, 
                "data": data, 
                "sent": True,
                "airtime_s": airtime,
                "energy_mj": tx_energy
            }
        return {"device_id": self.id, "data": data, "sent": True}
    
    def set_protocol(self, protocol):
        """Set the protocol for this device"""
        self.protocol = protocol

# Specific IoT Device Classes
class Sensor(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Sensor", network_ref)

class Gateway(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Gateway", network_ref)

class Actuator(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Actuator", network_ref)

class Camera(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Camera", network_ref)

class Switch(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Switch", network_ref)

class Router(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Router", network_ref)

class Server(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Server", network_ref)

class Cloud(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Cloud", network_ref)

class Mobile(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Mobile", network_ref)

class LED(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "LED", network_ref)

class Motor(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Motor", network_ref)

class Display(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Display", network_ref)

# ---------- NEW IOT HARDWARE DEVICES ----------
# Microcontrollers
class Arduino(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Arduino", network_ref)

class ESP32(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "ESP32", network_ref)

class STM32(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "STM32", network_ref)

class PIC(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "PIC", network_ref)

# Single Board Computers
class RaspberryPi(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "RaspberryPi", network_ref)

class BeagleBone(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "BeagleBone", network_ref)

class JetsonNano(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "JetsonNano", network_ref)

# Communication Modules
class WiFi(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "WiFi", network_ref)

class Bluetooth(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Bluetooth", network_ref)

class LoRa(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "LoRa", network_ref)

class Zigbee(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Zigbee", network_ref)

# Power Management
class Battery(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "Battery", network_ref)

class PowerSupply(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "PowerSupply", network_ref)

class SolarPanel(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "SolarPanel", network_ref)

# Storage Devices
class SDCard(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "SDCard", network_ref)

class EEPROM(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "EEPROM", network_ref)

class FlashMemory(IoTDevice):
    def __init__(self, device_id, network_ref=None):
        super().__init__(device_id, "FlashMemory", network_ref)

# Global network instance - created AFTER all classes
network = IoTNetwork()

# ---------- VALIDATION ----------
def validate_python_script(script: str):
    try:
        # Check if it's valid Python syntax
        ast.parse(script)
        
        # Execute in restricted environment
        test_network = IoTNetwork()
        
        # Create device classes that automatically register with test_network
        def make_device_class(device_type):
            class TestDevice(IoTDevice):
                def __init__(self, device_id):
                    super().__init__(device_id, device_type, test_network)
                    # Manually register with network
                    test_network.add_node(self)
            return TestDevice
        
        # Create restricted globals with test-specific device classes
        restricted_globals = {
            '__builtins__': {
                # Remove __import__ for security - prevent arbitrary imports
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'list': list,
                'dict': dict,
                'range': range,
                'enumerate': enumerate,
                'zip': zip,
                'abs': abs,
                'min': min,
                'max': max,
                'sum': sum,
                'round': round,
            },
            'print': print,  # Standard print for validation
            'IoTNetwork': IoTNetwork,
            'IoTDevice': IoTDevice,
            # Add mock RPi module for GPIO simulation
            'RPi': MockRPi(),
            'GPIO': MockGPIO(),
            # Add protocol factory and protocol classes
            'create_protocol': create_protocol,
            'I2C': I2C,
            'SPI': SPI,
            'UART': UART,
            'CAN': CAN,
            'WiFi': WiFi,
            'BLE': BLE,
            'Zigbee': Zigbee,
            'LoRa': LoRa,
            'MQTT': MQTT,
            'CoAP': CoAP,
            'EnergyModel': EnergyModel,
            # Original devices
            'Sensor': make_device_class('Sensor'),
            'Gateway': make_device_class('Gateway'),
            'Actuator': make_device_class('Actuator'),
            'Camera': make_device_class('Camera'),
            'Switch': make_device_class('Switch'),
            'Router': make_device_class('Router'),
            'Server': make_device_class('Server'),
            'Cloud': make_device_class('Cloud'),
            'Mobile': make_device_class('Mobile'),
            'LED': make_device_class('LED'),
            'Motor': make_device_class('Motor'),
            'Display': make_device_class('Display'),
            # Microcontrollers
            'Arduino': make_device_class('Arduino'),
            'ESP32': make_device_class('ESP32'),
            'STM32': make_device_class('STM32'),
            'PIC': make_device_class('PIC'),
            # Single Board Computers
            'RaspberryPi': make_device_class('RaspberryPi'),
            'BeagleBone': make_device_class('BeagleBone'),
            'JetsonNano': make_device_class('JetsonNano'),
            # Communication Modules
            'WiFi': make_device_class('WiFi'),
            'Bluetooth': make_device_class('Bluetooth'),
            'LoRa': make_device_class('LoRa'),
            'Zigbee': make_device_class('Zigbee'),
            # Power Management
            'Battery': make_device_class('Battery'),
            'PowerSupply': make_device_class('PowerSupply'),
            'SolarPanel': make_device_class('SolarPanel'),
            # Storage Devices
            'SDCard': make_device_class('SDCard'),
            'EEPROM': make_device_class('EEPROM'),
            'FlashMemory': make_device_class('FlashMemory'),
            'network': test_network
        }
        
        # Capture output
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            exec(script, restricted_globals)
        finally:
            sys.stdout = old_stdout
        
        # Allow scripts without devices - only check syntax
        return True, "Valid Python script"
        
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error: {e}"

# ---------- SIMULATOR ----------
@app.route("/simulate", methods=["POST"])
def simulate():
    data = request.json or {}
    script = data.get("script", "")

    ok, msg = validate_python_script(script)
    if not ok:
        return jsonify({"error": msg}), 400

    # Execute script to get network data
    network = IoTNetwork()
    
    # Capture print output
    print_output = []
    def custom_print(*args, **kwargs):
        output = ' '.join(str(arg) for arg in args)
        print_output.append(output)
        # Also print to console for debugging
        print(f"[CAPTURED]: {output}")
        return output  # Return for debugging
    
    # Test custom print
    print(f"[DEBUG] Testing custom_print...")
    custom_print("Test message")
    print(f"[DEBUG] print_output after test: {print_output}")
    
    # Create device classes that automatically register with network
    def make_device_class(device_type):
        class NetworkDevice(IoTDevice):
            def __init__(self, device_id):
                super().__init__(device_id, device_type, network)
                # Manually register with network
                network.add_node(self)
        return NetworkDevice
    
    restricted_globals = {
        '__builtins__': {
            # Remove __import__ for security - prevent arbitrary imports
            # 'print': custom_print,  # Custom print for capturing output
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'abs': abs,
            'min': min,
            'max': max,
            'sum': sum,
            'round': round,
        },
        'print': custom_print,  # Custom print outside __builtins__
        'IoTNetwork': IoTNetwork,
        'IoTDevice': IoTDevice,
        # Add mock RPi module for GPIO simulation
        'RPi': MockRPi(),
        'GPIO': MockGPIO(),
        # Add protocol factory and protocol classes
        'create_protocol': create_protocol,
        'I2C': I2C,
        'SPI': SPI,
        'UART': UART,
        'CAN': CAN,
        'WiFi': WiFi,
        'BLE': BLE,
        'Zigbee': Zigbee,
        'LoRa': LoRa,
        'MQTT': MQTT,
        'CoAP': CoAP,
        'EnergyModel': EnergyModel,
        # Original devices
        'Sensor': make_device_class('Sensor'),
        'Gateway': make_device_class('Gateway'),
        'Actuator': make_device_class('Actuator'),
        'Camera': make_device_class('Camera'),
        'Switch': make_device_class('Switch'),
        'Router': make_device_class('Router'),
        'Server': make_device_class('Server'),
        'Cloud': make_device_class('Cloud'),
        'Mobile': make_device_class('Mobile'),
        'LED': make_device_class('LED'),
        'Motor': make_device_class('Motor'),
        'Display': make_device_class('Display'),
        # Microcontrollers
        'Arduino': make_device_class('Arduino'),
        'ESP32': make_device_class('ESP32'),
        'STM32': make_device_class('STM32'),
        'PIC': make_device_class('PIC'),
        # Single Board Computers
        'RaspberryPi': make_device_class('RaspberryPi'),
        'BeagleBone': make_device_class('BeagleBone'),
        'JetsonNano': make_device_class('JetsonNano'),
        # Communication Modules
        'WiFi': make_device_class('WiFi'),
        'Bluetooth': make_device_class('Bluetooth'),
        'LoRa': make_device_class('LoRa'),
        'Zigbee': make_device_class('Zigbee'),
        # Power Management
        'Battery': make_device_class('Battery'),
        'PowerSupply': make_device_class('PowerSupply'),
        'SolarPanel': make_device_class('SolarPanel'),
        # Storage Devices
        'SDCard': make_device_class('SDCard'),
        'EEPROM': make_device_class('EEPROM'),
        'FlashMemory': make_device_class('FlashMemory'),
        'network': network
    }
    
    try:
        print(f"[DEBUG] Executing script...")
        exec(script, restricted_globals)
        print(f"[DEBUG] Script execution completed")
    except Exception as e:
        print(f"[DEBUG] Execution error: {e}")
        return jsonify({"error": f"Execution error: {e}"}), 400

    # Build cytoscape elements
    elements = []

    # nodes
    for nid, ntype in network.nodes.items():
        elements.append({
            "data": {
                "id": nid,
                "label": f"{ntype} ({nid})",
                "type": ntype
            }
        })

    # edges (only if both ends exist)
    for s, t in network.edges:
        if s in network.nodes and t in network.nodes:
            elements.append({
                "data": {
                    "source": s,
                    "target": t
                }
            })

    # Check if any devices were created
    has_devices = len(network.nodes) > 0
    
    # Debug logging
    print(f"[DEBUG] has_devices: {has_devices}")
    print(f"[DEBUG] print_output length: {len(print_output)}")
    print(f"[DEBUG] print_output: {print_output}")
    
    # Build response
    response_data = {
        "elements": elements,
        "states": network.states,
        "script": script,
        "has_devices": has_devices
    }
    
    # If no devices, add print output or no devices message
    if not has_devices:
        if print_output:
            response_data["print_output"] = "\n".join(print_output)
            response_data["message"] = "No IoT devices in script, but print output captured"
        else:
            response_data["print_output"] = ""
            response_data["message"] = "No IoT devices in script and no print output"
    
    return jsonify(response_data)

# ---------- SAVE/LOAD NETWORK FUNCTIONALITY ----------
@app.route("/save_network", methods=["POST"])
def save_network():
    try:
        data = request.json or {}
        script = data.get("script", "")
        name = data.get("name", "unnetwork")
        
        if not script.strip():
            return jsonify({"error": "No script to save"}), 400
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.json"
        filepath = os.path.join(NETWORKS_DIR, filename)
        
        # Save network data
        network_data = {
            "name": name,
            "script": script,
            "timestamp": timestamp,
            "created_at": datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(network_data, f, indent=2)
        
        return jsonify({
            "message": "Network saved successfully",
            "filename": filename
        })
        
    except Exception as e:
        return jsonify({"error": f"Save failed: {e}"}), 500

@app.route("/load_network", methods=["POST"])
def load_network():
    try:
        data = request.json or {}
        filename = data.get("filename", "")
        
        if not filename:
            return jsonify({"error": "No filename provided"}), 400
        
        # Validate filename - prevent path traversal
        # Only allow alphanumeric, underscore, hyphen, and dot
        if not re.match(r'^[\w\-\.]+$', filename):
            return jsonify({"error": "Invalid filename"}), 400
        
        # Ensure filename ends with .json
        if not filename.endswith('.json'):
            return jsonify({"error": "Filename must end with .json"}), 400
        
        # Prevent path traversal
        if '..' in filename or filename.startswith('/'):
            return jsonify({"error": "Invalid filename"}), 400
        
        filepath = os.path.join(NETWORKS_DIR, filename)
        
        # Ensure filepath is within NETWORKS_DIR
        if not os.path.abspath(filepath).startswith(os.path.abspath(NETWORKS_DIR)):
            return jsonify({"error": "Invalid filename"}), 400
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Network file not found"}), 404
        
        with open(filepath, 'r') as f:
            network_data = json.load(f)
        
        return jsonify(network_data)
        
    except Exception as e:
        return jsonify({"error": f"Load failed: {e}"}), 500

@app.route("/list_networks", methods=["GET"])
def list_networks():
    try:
        networks = []
        
        for filename in os.listdir(NETWORKS_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(NETWORKS_DIR, filename)
                
                with open(filepath, 'r') as f:
                    network_data = json.load(f)
                
                networks.append({
                    "filename": filename,
                    "name": network_data.get("name", "Unnamed"),
                    "created_at": network_data.get("created_at", "Unknown"),
                    "timestamp": network_data.get("timestamp", "")
                })
        
        # Sort by timestamp (newest first)
        networks.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return jsonify({"networks": networks})
        
    except Exception as e:
        return jsonify({"error": f"List failed: {e}"}), 500

@app.route("/delete_network", methods=["POST"])
def delete_network():
    try:
        data = request.json or {}
        filename = data.get("filename", "")
        
        if not filename:
            return jsonify({"error": "No filename provided"}), 400
        
        # Validate filename - prevent path traversal
        # Only allow alphanumeric, underscore, hyphen, and dot
        if not re.match(r'^[\w\-\.]+$', filename):
            return jsonify({"error": "Invalid filename"}), 400
        
        # Ensure filename ends with .json
        if not filename.endswith('.json'):
            return jsonify({"error": "Filename must end with .json"}), 400
        
        # Prevent path traversal
        if '..' in filename or filename.startswith('/'):
            return jsonify({"error": "Invalid filename"}), 400
        
        filepath = os.path.join(NETWORKS_DIR, filename)
        
        # Ensure filepath is within NETWORKS_DIR
        if not os.path.abspath(filepath).startswith(os.path.abspath(NETWORKS_DIR)):
            return jsonify({"error": "Invalid filename"}), 400
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Network file not found"}), 404
        
        os.remove(filepath)
        
        return jsonify({"message": "Network deleted successfully"})
        
    except Exception as e:
        return jsonify({"error": f"Delete failed: {e}"}), 500


# ---------- TRACE FILE FUNCTIONALITY ----------
@app.route("/create_trace_file", methods=["POST"])
def create_trace_file():
    """Create a new trace file for a script"""
    try:
        data = request.json or {}
        script = data.get("script", "")
        script_name = data.get("script_name", "unnamed_script")
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{script_name}_{timestamp}.tr"
        filepath = os.path.join(TRACE_DIR, filename)
        
        # Create trace file with header
        trace_content = f"""# IoT Simulator Trace File
# Script: {script_name}
# Created: {datetime.now().isoformat()}
# Format: time event source target packetType description
# Event Types: s=send, r=receive, d=drop, f=forward

# Script Content:
{script}

# Trace Events:
"""
        
        with open(filepath, 'w') as f:
            f.write(trace_content)
        
        return jsonify({
            "success": True,
            "trace_file": filename,
            "filepath": filepath,
            "message": f"Trace file created: {filename}"
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to create trace file: {e}"}), 500

@app.route("/append_trace", methods=["POST"])
def append_trace():
    """Append trace events to existing trace file"""
    try:
        data = request.json or {}
        trace_file = data.get("trace_file", "")
        events = data.get("events", [])
        
        if not trace_file or not events:
            return jsonify({"error": "Missing trace file or events"}), 400
        
        filepath = os.path.join(TRACE_DIR, trace_file)
        
        # Append events to trace file
        with open(filepath, 'a') as f:
            for event in events:
                timestamp = event.get('time', '0.000000')
                event_type = event.get('event', 's')
                source = event.get('source', 'unknown')
                target = event.get('target', 'unknown')
                packet_type = event.get('packetType', 'data')
                description = event.get('description', '')
                
                trace_line = f"{timestamp} {event_type} {source} {target} {packet_type} \"{description}\"\n"
                f.write(trace_line)
        
        return jsonify({
            "success": True,
            "message": f"Appended {len(events)} events to {trace_file}"
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to append trace: {e}"}), 500

@app.route("/list_trace_files", methods=["GET"])
def list_trace_files():
    """List all trace files"""
    try:
        trace_files = []
        if os.path.exists(TRACE_DIR):
            for filename in os.listdir(TRACE_DIR):
                if filename.endswith('.tr'):
                    filepath = os.path.join(TRACE_DIR, filename)
                    stat = os.stat(filepath)
                    trace_files.append({
                        "filename": filename,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        
        # Sort by creation time (newest first)
        trace_files.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({"trace_files": trace_files})
        
    except Exception as e:
        return jsonify({"error": f"Failed to list trace files: {e}"}), 500

@app.route("/get_trace_file/<filename>")
def get_trace_file(filename):
    """Download or view a trace file"""
    try:
        return send_from_directory(TRACE_DIR, filename, as_attachment=True)
    except Exception as e:
        return jsonify({"error": f"Failed to get trace file: {e}"}), 500

@app.route("/delete_trace_file", methods=["POST"])
def delete_trace_file():
    """Delete a trace file"""
    try:
        data = request.json or {}
        filename = data.get("filename", "")
        
        if not filename:
            return jsonify({"error": "Missing filename"}), 400
        
        filepath = os.path.join(TRACE_DIR, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Trace file not found"}), 404
        
        os.remove(filepath)
        return jsonify({"message": f"Trace file {filename} deleted successfully"})
        
    except Exception as e:
        return jsonify({"error": f"Failed to delete trace file: {e}"}), 500

# ---------- RECOMMENDATION ENGINE ENDPOINTS ----------
@app.route("/recommend_protocol", methods=["POST"])
def recommend_protocol():
    """Recommend protocol based on requirements"""
    try:
        data = request.json or {}
        requirements = data.get("requirements", {})
        
        recommendations = recommendation_engine.recommend_protocol(requirements)
        
        return jsonify({
            "recommendations": recommendations,
            "count": len(recommendations)
        })
        
    except Exception as e:
        return jsonify({"error": f"Recommendation failed: {e}"}), 500

@app.route("/compare_protocols", methods=["POST"])
def compare_protocols():
    """Compare multiple protocols with actual calculations"""
    try:
        data = request.json or {}
        protocol_names = data.get("protocols", [])
        payload_bytes = data.get("payload_bytes", 100)
        distance_m = data.get("distance_m", 10)
        
        if not protocol_names:
            return jsonify({"error": "No protocols specified"}), 400
        
        comparison = recommendation_engine.compare_protocols(protocol_names, payload_bytes, distance_m)
        
        return jsonify({
            "comparison": comparison,
            "parameters": {
                "payload_bytes": payload_bytes,
                "distance_m": distance_m
            }
        })
        
    except Exception as e:
        return jsonify({"error": f"Comparison failed: {e}"}), 500

@app.route("/recommend_topology", methods=["POST"])
def recommend_topology():
    """Recommend network topology based on requirements"""
    try:
        data = request.json or {}
        num_devices = data.get("num_devices", 10)
        area_size_m2 = data.get("area_size_m2", 100)
        requirements = data.get("requirements", {})
        
        recommendations = recommendation_engine.recommend_topology(num_devices, area_size_m2, requirements)
        
        return jsonify({
            "recommendations": recommendations,
            "parameters": {
                "num_devices": num_devices,
                "area_size_m2": area_size_m2
            }
        })
        
    except Exception as e:
        return jsonify({"error": f"Topology recommendation failed: {e}"}), 500

# ---------- AI CHATBOT SYSTEM ----------

# System prompt for OpenAI context
IOT_SIMULATOR_SYSTEM_PROMPT = """You are an expert AI assistant for the IoT Network Simulator. Your role is to help users with:

1. **Script Generation**: Create Python scripts for the IoT simulator using available device classes
2. **Technical Support**: Answer questions about simulator features, protocols, and usage
3. **Troubleshooting**: Help debug scripts and resolve errors

**Available Device Classes:**
- Microcontrollers: Arduino, ESP32, STM32, PIC
- I/O Devices: Sensor, Camera, LED, Motor, Display
- Network Devices: Gateway, Router, Server, Cloud

**Device Methods:**
- turn_on() / turn_off() - Power control
- connect(device) - Create connections
- get_data() - Retrieve sensor data
- send_data(data) - Send data to network

**Key Features:**
- Multi-layer visualization (Device, Protocol, Energy, DataFlow)
- Protocol support: I2C, SPI, UART, WiFi, BLE, LoRa, Zigbee, MQTT, CoAP, CAN
- Import support: json, datetime, math, and other standard Python modules
- Export: JSON export with performance metrics
- Trace files: Single-line format with energy and latency data

**Script Guidelines:**
- Use simple, clear variable names
- Include comments explaining device setup
- Always turn on devices before operations
- Connect devices before using them
- Use get_data() for sensors, send_data() for gateways

**Response Style:**
- Be concise and practical
- Provide working code examples
- Explain key concepts briefly
- Focus on simulator-specific features

When generating scripts, always provide complete, runnable code. When answering questions, be specific to the IoT simulator context."""

def call_openai_api(user_query):
    """Call OpenAI API for intelligent responses"""
    if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
        return None, "OpenAI not available"
    
    try:
        openai.api_key = OPENAI_API_KEY
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": IOT_SIMULATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_query}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        return response.choices[0].message.content, "openai"
    except Exception as e:
        return None, f"OpenAI API error: {e}"

# Script generation templates
SCRIPT_TEMPLATES = {
    "smart home": """# Smart Home IoT Network
# Temperature sensor and LED control

# Create devices
arduino = Arduino("uno")
temp_sensor = Sensor("temp_sensor")
led = LED("status_led")

# Connect devices
temp_sensor.connect(arduino)
arduino.connect(led)

# Power on system
arduino.turn_on()
temp_sensor.turn_on()
led.turn_on()

# Read sensor data
sensor_data = temp_sensor.get_data()
print(f"Temperature: {sensor_data}")

# Control LED based on temperature
if sensor_data["value"] > 25:
    led.turn_on()
else:
    led.turn_off()
""",

    "industrial": """# Industrial IoT Network
# PLC and sensor monitoring

# Create industrial devices
temp_sensor = Sensor("industrial_temp")
pressure_sensor = Sensor("industrial_pressure")
plc = Arduino("plc_controller")
gateway = Gateway("industrial_gateway")
server = Server("edge_server")

# Connect devices
temp_sensor.connect(plc)
pressure_sensor.connect(plc)
plc.connect(gateway)
gateway.connect(server)

# Power on industrial network
temp_sensor.turn_on()
pressure_sensor.turn_on()
plc.turn_on()
gateway.turn_on()
server.turn_on()

# Monitor sensors
temp_data = temp_sensor.get_data()
pressure_data = pressure_sensor.get_data()
print(f"Temperature: {temp_data}")
print(f"Pressure: {pressure_data}")

# Send data to server
gateway.send_data({"status": "normal", "sensors": 2})
""",

    "smart city": """# Smart City IoT Network
# Traffic and environmental monitoring

# Create smart city devices
traffic_camera = Camera("traffic_cam_01")
air_sensor = Sensor("air_quality_01")
street_light = LED("smart_light_01")
gateway = Gateway("city_gateway")
cloud = Cloud("city_cloud")

# Connect devices
traffic_camera.connect(gateway)
air_sensor.connect(gateway)
street_light.connect(gateway)
gateway.connect(cloud)

# Power on smart city
traffic_camera.turn_on()
air_sensor.turn_on()
street_light.turn_on()
gateway.turn_on()
cloud.turn_on()

# Monitor traffic
traffic_data = traffic_camera.get_data()
print(f"Traffic status: {traffic_data}")

# Monitor air quality
air_data = air_sensor.get_data()
print(f"Air quality: {air_data}")

# Smart lighting control
street_light.turn_on()
""",

    "simple": """# Simple IoT Network
# Basic sensor and actuator setup

# Create devices
sensor = Sensor("sensor_01")
actuator = LED("actuator_01")

# Connect devices
sensor.connect(actuator)

# Power on
sensor.turn_on()
actuator.turn_on()

# Read sensor and control actuator
data = sensor.get_data()
print(f"Sensor data: {data}")
actuator.turn_on()
"""
}

# Knowledge base for Q&A
KNOWLEDGE_BASE = {
    "what is": "The IoT Network Simulator is a Python-based simulation platform for designing, testing, and analyzing IoT networks. It features: 1) Web-based editor for writing IoT scripts, 2) Multi-layer network visualization (Device, Protocol, Energy, DataFlow), 3) Support for 10 IoT protocols (I2C, SPI, UART, WiFi, BLE, LoRa, Zigbee, MQTT, CoAP, CAN), 4) Resource-constrained device modeling, 5) Energy-aware simulation with performance metrics, 6) Single-line trace file generation for analysis, 7) AI-powered chatbot for script generation and Q&A.",
    "simulator": "The IoT Network Simulator is a Python-based simulation platform for designing, testing, and analyzing IoT networks. It features: 1) Web-based editor for writing IoT scripts, 2) Multi-layer network visualization (Device, Protocol, Energy, DataFlow), 3) Support for 10 IoT protocols (I2C, SPI, UART, WiFi, BLE, LoRa, Zigbee, MQTT, CoAP, CAN), 4) Resource-constrained device modeling, 5) Energy-aware simulation with performance metrics, 6) Single-line trace file generation for analysis, 7) AI-powered chatbot for script generation and Q&A.",
    "purpose": "The purpose of this IoT simulator is to provide a comprehensive platform for designing, testing, and analyzing IoT networks without requiring physical hardware. It enables researchers, students, and developers to prototype IoT systems, analyze protocol performance, and visualize network behavior in a controlled environment.",
    "goal": "The goal of this IoT simulator is to bridge the gap between theoretical IoT concepts and practical implementation by providing a realistic simulation environment that models device behavior, protocol characteristics, energy consumption, and network topology.",
    "features": "Key features include: Web-based Python editor, Multi-layer visualization (Device/Protocol/Energy/DataFlow), 10 IoT protocols (I2C/SPI/UART/WiFi/BLE/LoRa/Zigbee/MQTT/CoAP/CAN), Resource-constrained device modeling, Energy-aware simulation, Performance metrics, Trace file generation, AI chatbot assistant, Import support for Python modules.",
    "how to use": "To use the IoT simulator: 1) Write your script in the editor using device classes like Arduino, Sensor, LED. 2) Click 'Run Simulation' to execute. 3) View the network visualization. 4) Use multi-layer view by clicking 'Layer' button.",
    "multi-layer": "Multi-layer visualization shows different aspects: Device layer (device types), Protocol layer (communication protocols), Energy layer (power consumption), DataFlow layer (data intensity). Click 'Layer' button to cycle through them.",
    "export": "To export data: Click 'Export' button to download JSON file with complete simulation data including devices, protocols, and performance metrics.",
    "trace": "Trace files contain single-line format with timestamp, device, event, protocol, data size, energy consumption, and latency. Click 'Download Trace' to get the trace file.",
    "devices": "Available devices: Arduino, ESP32, STM32, PIC (microcontrollers), Sensor, Camera, LED, Motor, Display (I/O devices), Gateway, Router, Server, Cloud (network devices).",
    "protocols": "The simulator supports IoT protocols: I2C, SPI, UART, WiFi, BLE, LoRa, Zigbee, MQTT, CoAP, CAN. Each protocol has specific timing and energy characteristics.",
    "pause": "Pause/Resume button allows you to stop the simulation and continue from the exact same point. It preserves all device states and packet positions.",
    "import": "You can now use Python imports in the editor! Import modules like json, datetime, math, etc. for advanced scripting.",
    "script": "Scripts use simple Python syntax with device classes. Example: arduino = Arduino('uno'); sensor = Sensor('temp'); sensor.connect(arduino); arduino.turn_on()",
    "error": "Common errors: Check device names are unique, ensure devices are connected before use, verify turn_on() is called before operations.",
    "help": "I can help you with: Creating IoT scripts for any scenario (smart home, industrial, smart city, etc.), Answering questions about simulator features, Troubleshooting script errors, Explaining protocols and devices, Providing usage examples. Just ask your question!",
    "support": "Supported features: Script generation, Q&A about simulator, Multi-layer visualization, Protocol simulation, Device modeling, Energy analysis, Trace file generation, Export functionality, Import support, AI chatbot assistance.",
    "example": "Example script: arduino = Arduino('uno'); sensor = Sensor('temp'); led = LED('status'); sensor.connect(arduino); arduino.connect(led); arduino.turn_on(); sensor.turn_on(); led.turn_on();",
    "tutorial": "Quick tutorial: 1) Open editor at /editor, 2) Write script using device classes, 3) Click Run Simulation, 4) View network visualization, 5) Use Layer button for different views, 6) Click Export for JSON data.",
    "network": "Network creation: Use device classes (Arduino, Sensor, LED, etc.), Connect devices with .connect() method, Turn on devices with .turn_on(), Run simulation to visualize network.",
    "connection": "Device connections: Use device1.connect(device2) to create connections. Devices must be created before connecting. Example: sensor = Sensor('temp'); arduino = Arduino('uno'); sensor.connect(arduino);",
    "visualization": "Visualization features: Interactive network graph, Multi-layer views (Device/Protocol/Energy/DataFlow), Packet animation, Real-time status updates, Zoom and pan controls.",
    "energy": "Energy simulation: Models power consumption based on device type and protocol, Calculates energy per transmission, Shows energy metrics in visualization, Available in Energy layer view.",
    "latency": "Latency modeling: Calculates transmission delay based on protocol characteristics, Shows latency in trace files, Displays in performance metrics, Varies by protocol type.",
    "performance": "Performance metrics: Total energy consumption, Average latency, Packet transmission count, Device utilization, Network throughput. Available in export JSON.",
    "advanced": "Advanced features: Python import support, Custom device classes, Protocol library integration, Trace file analysis, Performance optimization, Network topology design.",
    "beginner": "For beginners: Start with simple scripts (sensor + LED), Use Load Example button, Try the AI chatbot for help, Read the documentation, Experiment with different devices.",
    "student": "For students: Great for learning IoT concepts, Practice network design, Understand protocol behavior, Analyze energy consumption, Prepare for projects.",
    "research": "For researchers: Analyze protocol performance, Compare network topologies, Study energy efficiency, Generate trace data, Validate IoT algorithms.",
}

def generate_script(user_query):
    """Generate IoT simulator script based on user query"""
    query_lower = user_query.lower()
    
    # Check if user wants interactive script generation
    interactive_keywords = ["create", "generate", "make", "build", "script", "network", "iot", "setup"]
    if any(keyword in query_lower for keyword in interactive_keywords):
        # Check if specific type is mentioned
        script_keywords = {
            "smart home": "smart home",
            "home": "smart home",
            "temperature": "smart home",
            "industrial": "industrial",
            "plc": "industrial",
            "factory": "industrial",
            "smart city": "smart city",
            "traffic": "smart city",
            "city": "smart city",
            "simple": "simple",
            "basic": "simple",
            "beginner": "simple"
        }
        
        for keyword, template_key in script_keywords.items():
            if keyword in query_lower:
                return SCRIPT_TEMPLATES[template_key], "script"
        
        # If no specific type, ask for details
        interactive_response = """🔧 I'll help you create a custom IoT script!

**What type of IoT network do you want to create?**

**1. Smart Home** - Temperature sensors, LEDs, home automation
   Type: "smart home"

**2. Industrial IoT** - PLCs, sensors, gateways, factory automation
   Type: "industrial"

**3. Smart City** - Traffic cameras, air sensors, street lights
   Type: "smart city"

**4. Simple Setup** - Basic sensor and actuator
   Type: "simple"

Just tell me the type, and I'll generate the script for you! 🚀"""
        return interactive_response, "qa"
    
    # Default to simple script if no match
    return SCRIPT_TEMPLATES["simple"], "script"

def answer_question(user_query):
    """Answer questions about the IoT simulator"""
    query_lower = user_query.lower()
    
    # Check for greetings - show menu
    greetings = ["hi", "hello", "hey", "hii", "helo", "greetings", "good morning", "good afternoon", "good evening"]
    if any(greeting in query_lower for greeting in greetings):
        menu_response = """👋 Hello! I'm your IoT Simulator AI Assistant!

**What can I help you with?**

**1️⃣ Script Generation**
   - "Create a script"
   - "Generate IoT network"
   - "Make a smart home setup"

**2️⃣ Learn About Simulator**
   - "What is this simulator?"
   - "What are the features?"
   - "How does it work?"

**3️⃣ Get Help Using It**
   - "How do I use it?"
   - "How to create devices?"
   - "How to visualize network?"

**4️⃣ Technical Details**
   - "What devices are available?"
   - "What protocols are supported?"
   - "How does energy simulation work?"

**5️⃣ Troubleshooting**
   - "Fix my error"
   - "Why is my script not working?"
   - "Common errors"

Just type your question or choose an option above! 🚀"""
        return menu_response, "qa"
    
    # Check knowledge base with partial matching
    for keyword, answer in KNOWLEDGE_BASE.items():
        if keyword in query_lower:
            return answer, "qa"
    
    # Enhanced keyword matching for common questions
    question_keywords = {
        # General questions
        "what": KNOWLEDGE_BASE["what is"],
        "explain": KNOWLEDGE_BASE["what is"],
        "describe": KNOWLEDGE_BASE["what is"],
        "tell me": KNOWLEDGE_BASE["what is"],
        "about": KNOWLEDGE_BASE["what is"],
        
        # Usage
        "use": KNOWLEDGE_BASE["how to use"],
        "start": KNOWLEDGE_BASE["how to use"],
        "begin": KNOWLEDGE_BASE["tutorial"],
        "run": KNOWLEDGE_BASE["how to use"],
        "execute": KNOWLEDGE_BASE["how to use"],
        
        # Features
        "feature": KNOWLEDGE_BASE["features"],
        "capability": KNOWLEDGE_BASE["features"],
        "can": KNOWLEDGE_BASE["features"],
        "do": KNOWLEDGE_BASE["features"],
        
        # Visualization
        "view": KNOWLEDGE_BASE["visualization"],
        "see": KNOWLEDGE_BASE["visualization"],
        "display": KNOWLEDGE_BASE["visualization"],
        "show": KNOWLEDGE_BASE["visualization"],
        
        # Energy
        "power": KNOWLEDGE_BASE["energy"],
        "battery": KNOWLEDGE_BASE["energy"],
        "consumption": KNOWLEDGE_BASE["energy"],
        
        # Performance
        "speed": KNOWLEDGE_BASE["performance"],
        "fast": KNOWLEDGE_BASE["performance"],
        "metric": KNOWLEDGE_BASE["performance"],
        "statistic": KNOWLEDGE_BASE["performance"],
        
        # Help
        "assist": KNOWLEDGE_BASE["help"],
        "guide": KNOWLEDGE_BASE["help"],
        "support": KNOWLEDGE_BASE["support"],
        
        # Network
        "connect": KNOWLEDGE_BASE["connection"],
        "link": KNOWLEDGE_BASE["connection"],
        "topology": KNOWLEDGE_BASE["network"],
        
        # Protocols
        "communication": KNOWLEDGE_BASE["protocols"],
        "wireless": KNOWLEDGE_BASE["protocols"],
        "wired": KNOWLEDGE_BASE["protocols"],
        
        # Devices
        "hardware": KNOWLEDGE_BASE["devices"],
        "sensor": KNOWLEDGE_BASE["devices"],
        "actuator": KNOWLEDGE_BASE["devices"],
        "microcontroller": KNOWLEDGE_BASE["devices"],
        
        # Learning
        "learn": KNOWLEDGE_BASE["tutorial"],
        "study": KNOWLEDGE_BASE["student"],
        "teach": KNOWLEDGE_BASE["tutorial"],
        
        # Troubleshooting
        "problem": KNOWLEDGE_BASE["error"],
        "issue": KNOWLEDGE_BASE["error"],
        "fix": KNOWLEDGE_BASE["error"],
        "debug": KNOWLEDGE_BASE["error"],
    }
    
    # Check enhanced keywords
    for keyword, answer in question_keywords.items():
        if keyword in query_lower:
            return answer, "qa"
    
    # Default response with more helpful suggestions
    default_response = """I can help you with the IoT Simulator! Here are some things you can ask:

**About the Simulator:**
- "What is this simulator?"
- "What are the features?"
- "How does it work?"

**Using the Simulator:**
- "How do I use it?"
- "How to create a network?"
- "How to visualize devices?"

**Technical Details:**
- "What devices are available?"
- "What protocols are supported?"
- "How does energy simulation work?"

**Script Generation:**
- "Create a smart home network"
- "Generate an industrial IoT script"
- "Make a simple IoT setup"

**Troubleshooting:**
- "How to fix common errors?"
- "Why is my script not working?"

Try asking any of these, or be more specific about what you need help with!"""
    
    return default_response, "qa"

@app.route('/chatbot', methods=['POST'])
def chatbot():
    """AI Chatbot endpoint for script generation and Q&A with OpenAI integration"""
    try:
        data = request.json or {}
        user_query = data.get("query", "").strip()
        
        if not user_query:
            return jsonify({"error": "No query provided"}), 400
        
        # Try OpenAI API first if available
        if OPENAI_AVAILABLE and OPENAI_API_KEY:
            openai_response, openai_status = call_openai_api(user_query)
            if openai_response:
                # Determine response type based on content
                script_keywords = ["arduino", "sensor", "led", "device", "connect", "turn_on", "get_data", "send_data"]
                is_script = any(keyword in openai_response.lower() for keyword in script_keywords)
                response_type = "script" if is_script else "qa"
                
                return jsonify({
                    "response": openai_response,
                    "type": response_type,
                    "source": "openai",
                    "query": user_query
                })
        
        # Fallback to rule-based system
        script_keywords = ["create", "generate", "make", "write", "script", "network", "iot", "setup", "build"]
        is_script_request = any(keyword in user_query.lower() for keyword in script_keywords)
        
        if is_script_request:
            response, response_type = generate_script(user_query)
        else:
            response, response_type = answer_question(user_query)
        
        return jsonify({
            "response": response,
            "type": response_type,
            "source": "rule-based",
            "query": user_query
        })
        
    except Exception as e:
        return jsonify({"error": f"Chatbot error: {e}"}), 500


# ---------- PAGES ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/editor")
def editor():
    return render_template("editor.html")

@app.route("/simulation")
def simulation():
    return render_template("simulation.html")


if __name__ == "__main__":
    app.run(debug=True)

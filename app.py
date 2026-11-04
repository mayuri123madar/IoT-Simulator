from flask import Flask, render_template, request, jsonify, send_from_directory
import ast
import sys
import json
import os
from io import StringIO
from datetime import datetime
import re

# Import new protocol system
import protocols as _proto   # protocol classes; app.py later defines device classes named WiFi/LoRa/Zigbee, so use _proto.X for protocols
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
    protocol_map = {name: getattr(_proto, name) for name in ('I2C', 'SPI', 'UART', 'CAN', 'WiFi', 'BLE', 'Zigbee', 'LoRa', 'MQTT', 'CoAP')}
    
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

def clean_name(name, default="unnamed"):
    """Make a user-supplied name safe to use inside a filename"""
    name = re.sub(r'[^\w\- ]', '_', str(name)).strip()[:50]
    return name or default

def safe_join(base_dir, filename):
    """Join base_dir + filename; return None if the result would leave base_dir"""
    name = str(filename)
    if not name or name != os.path.basename(name) or name in ('.', '..') or '\x00' in name or '\\' in name:
        return None
    base = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(full) != base:
        return None
    return full

# ---------- IOT CLASSES FOR PYTHON SCRIPTS ----------
class IoTNetwork:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.states = {}
        self.dead_nodes = set()  # Track dead nodes for rerouting
        self.devices = {}        # id -> device object (used by the simulation engine)
        self.edge_attrs = {}     # (source, target) -> {'distance_m': ...}
        self.flows = []          # traffic flows added with device.send_interval(...)
        self.duration_s = None   # simulated time; set with network.set_duration(...)
    
    def add_node(self, node_obj):
        self.nodes[node_obj.id] = node_obj.type
        self.devices[node_obj.id] = node_obj
        if hasattr(node_obj, 'state'):
            self.states[node_obj.id] = node_obj.state
    
    def connect_nodes(self, source_obj, target_obj, distance_m=10.0):
        if source_obj.id not in self.nodes:
            raise ValueError(f"Source node '{source_obj.id}' does not exist")
        if target_obj.id not in self.nodes:
            raise ValueError(f"Target node '{target_obj.id}' does not exist")
        if distance_m <= 0:
            raise ValueError("distance_m must be positive")
        self.edges.append((source_obj.id, target_obj.id))
        self.edge_attrs[(source_obj.id, target_obj.id)] = {'distance_m': float(distance_m)}

    def edge_distance(self, a, b):
        attrs = self.edge_attrs.get((a, b)) or self.edge_attrs.get((b, a)) or {}
        return attrs.get('distance_m', 10.0)

    def set_duration(self, seconds):
        """Simulated time in seconds (e.g. network.set_duration(86400) for one day)"""
        if seconds <= 0:
            raise ValueError("duration must be positive")
        self.duration_s = float(seconds)

    def add_flow(self, source_id, sink_id, interval_s, payload_bytes):
        if interval_s <= 0:
            raise ValueError("interval must be positive")
        self.flows.append({'source': source_id, 'sink': sink_id, 'interval': float(interval_s),
                           'payload': int(payload_bytes)})
    
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
    def __init__(self, device_id, device_type, network_ref=None, protocol=None, battery_mah=0, memory_kb=None):
        self.id = device_id
        self.type = device_type
        self.state = "off"
        self.protocol = protocol
        self.always_on = None        # None = decide from the device type (gateways/servers stay awake)
        self.memory_kb = memory_kb   # None = use the value from protocol_parameters.json (if any)
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
    
    def connect(self, other_device, distance_m=10.0):
        if self.network:
            self.network.connect_nodes(self, other_device, distance_m)
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
            data_size = len(str(data))  # Simplified data size
            airtime = self.protocol.airtime(data_size)
            # ONE energy calculation: the radio's TX current comes from the protocol,
            # the supply voltage and battery from the device's energy model.
            link = getattr(self.protocol, 'underlying_protocol', None) or self.protocol
            energy_mj = self.energy_model.add_tx_energy(airtime, current_ma=getattr(link, 'tx_current_ma', None))
            
            return {
                "device_id": self.id, 
                "data": data, 
                "sent": True,
                "airtime_s": airtime,
                "energy_mj": energy_mj
            }
        return {"device_id": self.id, "data": data, "sent": True}
    
    def set_protocol(self, protocol):
        """Set the protocol for this device"""
        self.protocol = protocol

    def set_always_on(self, value=True):
        """True: the device stays awake (idle current). False: it sleeps between transmissions."""
        self.always_on = bool(value)

    def send_interval(self, interval_s, payload_bytes=20, to=None):
        """Send `payload_bytes` every `interval_s` seconds to device `to` (default: nearest Gateway/Server/Cloud)"""
        if not self.network:
            raise ValueError("No network available")
        self.network.add_flow(self.id, to.id if to is not None else None, interval_s, payload_bytes)

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

# ---------- SANDBOX (static check + separate process) ----------
import multiprocessing
from engine import run_simulation

SCRIPT_TIMEOUT_S = 5
DEFAULT_DURATION_S = 3600
MAX_DURATION_S = 10 * 365 * 24 * 3600
SCRIPT_MEMORY_BYTES = 768 * 1024 * 1024
MAX_PRINT_CHARS = 20000

# Names a script may never use
DENIED_NAMES = {
    'eval', 'exec', 'compile', 'open', 'input', 'breakpoint', 'getattr', 'setattr', 'delattr',
    'globals', 'locals', 'vars', 'dir', 'type', 'object', 'super', 'memoryview', 'bytearray',
    'classmethod', 'staticmethod', 'property',
}
# Attributes that give access to frames / globals / code objects (no underscores, so the "__" rule misses them)
DENIED_ATTRS = {
    'gi_frame', 'gi_code', 'gi_yieldfrom', 'cr_frame', 'cr_code', 'cr_await', 'ag_frame', 'ag_code',
    'f_back', 'f_globals', 'f_locals', 'f_builtins', 'f_code', 'tb_frame', 'tb_next',
    'func_globals', 'func_code', 'mro',
}
ALLOWED_DUNDER = {'__init__', '__str__', '__repr__'}

SAFE_BUILTINS = {
    'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool, 'list': list, 'dict': dict,
    'range': range, 'enumerate': enumerate, 'zip': zip, 'abs': abs, 'min': min, 'max': max,
    'sum': sum, 'round': round,
}

def check_script_static(script):
    """Reject scripts that try imports, dunder access, frame access or dangerous builtins.
    Returns an error message, or None if the script passes."""
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        return f"Syntax error: {e}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "Imports are not allowed in scripts"
        if isinstance(node, ast.Attribute):
            if node.attr in DENIED_ATTRS or (node.attr.startswith('__') and node.attr not in ALLOWED_DUNDER):
                return f"Attribute '{node.attr}' is not allowed"
        elif isinstance(node, ast.Name):
            if node.id in DENIED_NAMES or (node.id.startswith('__') and node.id not in ALLOWED_DUNDER):
                return f"Name '{node.id}' is not allowed"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and '__' in node.value:
            return "Strings containing '__' are not allowed"
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            return "global/nonlocal are not allowed"
    return None

# Battery capacity presets (mAh). Sources: CR2032 Varta p.2 (230); Energizer E91 p.1 (2850, low drain);
# EEMB LIR18650 p.1 (2600); LP652530 p.1 (500). Alkaline capacity falls at high drain.
BATTERY_PRESETS = {
    'CR2032': 230,
    'AA2_ALKALINE': 2850,
    'LI_ION_18650': 2600,
    'LIPO_500': 500,
}

def build_script_globals(network, print_fn):
    """Everything a script can see. Built inside the child process."""
    def make_device_class(device_type):
        class NetworkDevice(IoTDevice):
            def __init__(self, device_id, battery_mah=0, protocol=None, memory_kb=None):
                super().__init__(device_id, device_type, network, protocol, battery_mah, memory_kb)
                network.add_node(self)
        return NetworkDevice

    g = {'__builtins__': dict(SAFE_BUILTINS), 'print': print_fn, 'network': network,
         'IoTNetwork': IoTNetwork, 'IoTDevice': IoTDevice, 'RPi': MockRPi(), 'GPIO': MockGPIO(),
         'create_protocol': create_protocol, 'EnergyModel': EnergyModel}
    g.update(BATTERY_PRESETS)
    # Protocol classes. "<Name>Protocol" aliases avoid the clash with the WiFi/LoRa/Zigbee device names.
    for name in ('I2C', 'SPI', 'UART', 'CAN', 'WiFi', 'BLE', 'Zigbee', 'LoRa', 'MQTT', 'CoAP'):
        cls = getattr(_proto, name)
        g[name] = cls
        g[name + 'Protocol'] = cls
    # Device classes (these intentionally override WiFi / LoRa / Zigbee, as before)
    for device_type in ('Sensor', 'Gateway', 'Actuator', 'Camera', 'Switch', 'Router', 'Server', 'Cloud',
                        'Mobile', 'LED', 'Motor', 'Display', 'Arduino', 'ESP32', 'STM32', 'PIC',
                        'RaspberryPi', 'BeagleBone', 'JetsonNano', 'WiFi', 'Bluetooth', 'LoRa', 'Zigbee',
                        'Battery', 'PowerSupply', 'SolarPanel', 'SDCard', 'EEPROM', 'FlashMemory'):
        g[device_type] = make_device_class(device_type)
    return g

def _script_worker(script, conn, duration_s=None, force=None):
    """Runs in a separate process. Sends ('ok', result) or ('error', message)."""
    try:
        os.environ.clear()                      # no secrets (API keys) visible to the script
        try:
            import resource                     # Linux/macOS only; on Windows only the timeout applies
            resource.setrlimit(resource.RLIMIT_CPU, (SCRIPT_TIMEOUT_S, SCRIPT_TIMEOUT_S))
            resource.setrlimit(resource.RLIMIT_AS, (SCRIPT_MEMORY_BYTES, SCRIPT_MEMORY_BYTES))
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))   # cannot write files
        except ImportError:
            pass
        net = IoTNetwork()
        printed = []
        size = [0]
        def script_print(*args, **kwargs):
            text = ' '.join(str(a) for a in args)
            if size[0] < MAX_PRINT_CHARS:
                printed.append(text)
                size[0] += len(text)
        exec(compile(script, '<script>', 'exec'), build_script_globals(net, script_print))
        simulation = None
        if net.flows:
            seconds = net.duration_s or duration_s or DEFAULT_DURATION_S
            forced = None
            if force:
                forced = lambda: getattr(_proto, force[0])(**force[1])
            simulation = run_simulation(net, seconds, default_protocol=_proto.WiFi, force_protocol=forced)
        conn.send(('ok', {
            'nodes': dict(net.nodes),
            'edges': [list(e) for e in net.edges],
            'states': dict(net.states),
            'print_output': printed,
            'simulation': simulation,
        }))
    except BaseException as e:
        try:
            conn.send(('error', f"{e}"))
        except Exception:
            pass
    finally:
        conn.close()

def run_script_sandboxed(script, duration_s=None, force=None):
    """Returns (ok, message, result). Script runs in a child process with a timeout and resource limits."""
    problem = check_script_static(script)
    if problem:
        return False, problem, None
    # fork on Linux/macOS (fast); spawn on Windows (slower, no resource limits)
    method = os.environ.get('SANDBOX_START_METHOD') or ('fork' if 'fork' in multiprocessing.get_all_start_methods() else 'spawn')
    ctx = multiprocessing.get_context(method)
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_script_worker, args=(script, child_conn, duration_s, force), daemon=True)
    proc.start()
    child_conn.close()
    try:
        if parent_conn.poll(SCRIPT_TIMEOUT_S + (6 if method == 'spawn' else 1)):
            status, payload = parent_conn.recv()
        else:
            return False, f"Script timed out after {SCRIPT_TIMEOUT_S} seconds", None
    except EOFError:
        return False, "Script was stopped (memory or CPU limit exceeded)", None
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(1)
        parent_conn.close()
    if status == 'ok':
        return True, "Valid Python script", payload
    return False, f"Execution error: {payload}", None

def validate_python_script(script: str):
    ok, msg, _ = run_script_sandboxed(script)
    return ok, msg

# ---------- SIMULATOR ----------
@app.route("/simulate", methods=["POST"])
def simulate():
    data = request.json or {}
    script = data.get("script", "")

    duration_s = data.get("duration_s")
    try:
        duration_s = None if duration_s is None else min(max(float(duration_s), 1.0), MAX_DURATION_S)
    except (TypeError, ValueError):
        return jsonify({"error": "duration_s must be a number of seconds"}), 400

    ok, msg, result = run_script_sandboxed(script, duration_s)
    if not ok:
        return jsonify({"error": msg}), 400

    nodes = result['nodes']
    sim = result.get('simulation')
    sim_nodes = sim['nodes'] if sim else {}
    elements = []
    for nid, ntype in nodes.items():
        node_data = {"id": nid, "label": f"{ntype} ({nid})", "type": ntype}
        if nid in sim_nodes:
            sn = sim_nodes[nid]
            node_data.update({"energy": sn['energy_mj']['total'], "battery_pct": sn['battery_pct'],
                              "node_state": sn['state'], "protocol": sn['protocol']})
        elements.append({"data": node_data})
    edge_info = {}
    if sim:
        for e in sim['edges']:
            edge_info[(e['source'], e['target'])] = e
    for src, tgt in result['edges']:
        if src in nodes and tgt in nodes:
            ed = {"source": src, "target": tgt}
            e = edge_info.get((src, tgt))
            if e:
                ed.update({"protocol": e['protocol'], "load_pct": e['load_pct'], "loss_pct": e['loss_pct']})
            elements.append({"data": ed})

    has_devices = len(nodes) > 0
    response_data = {
        "elements": elements,
        "states": result['states'],
        "script": script,
        "has_devices": has_devices,
    }
    if sim:
        response_data["simulation"] = sim
    if not has_devices:
        printed = result['print_output']
        response_data["print_output"] = "\n".join(printed)
        response_data["message"] = ("No IoT devices in script, but print output captured"
                                    if printed else "No IoT devices in script and no print output")
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
        filename = f"{clean_name(name, 'unnetwork')}_{timestamp}.json"
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
        
        if not filename.endswith('.json'):
            return jsonify({"error": "Filename must end with .json"}), 400

        filepath = safe_join(NETWORKS_DIR, filename)
        if filepath is None:
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
        
        if not filename.endswith('.json'):
            return jsonify({"error": "Filename must end with .json"}), 400

        filepath = safe_join(NETWORKS_DIR, filename)
        if filepath is None:
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
        filename = f"{clean_name(script_name, 'unnamed_script')}_{timestamp}.tr"
        filepath = safe_join(TRACE_DIR, filename)
        if filepath is None:
            return jsonify({"error": "Invalid filename"}), 400
        
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
        
        filepath = safe_join(TRACE_DIR, trace_file)
        if filepath is None:
            return jsonify({"error": "Invalid filename"}), 400
        
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
        
        filepath = safe_join(TRACE_DIR, filename)
        if filepath is None:
            return jsonify({"error": "Invalid filename"}), 400
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Trace file not found"}), 404
        
        os.remove(filepath)
        return jsonify({"message": f"Trace file {filename} deleted successfully"})
        
    except Exception as e:
        return jsonify({"error": f"Failed to delete trace file: {e}"}), 500


# ---------- RECOMMENDATION BY SIMULATION ----------
# Candidate protocol setups that are tried for the whole network: name -> (protocol class, parameters)
RECOMMEND_CANDIDATES = {
    'BLE': ('BLE', {}),
    'WiFi': ('WiFi', {}),
    'Zigbee': ('Zigbee', {}),
    'LoRa SF7': ('LoRa', {'spreading_factor': 7}),
    'LoRa SF9': ('LoRa', {'spreading_factor': 9}),
    'LoRa SF12': ('LoRa', {'spreading_factor': 12}),
}

def network_lifetime_s(sim):
    """Time until the first battery node dies (measured if it died, projected from the drain rate if not)"""
    values = []
    for n in sim['nodes'].values():
        if n['battery_pct'] is None:
            continue
        if n['died_at_s'] is not None:
            values.append(n['died_at_s'])
        elif n['projected_lifetime_s'] is not None:
            values.append(n['projected_lifetime_s'])
    return min(values) if values else None

@app.route("/recommend_by_simulation", methods=["POST"])
def recommend_by_simulation():
    """Run the script's traffic once per protocol option and rank the options by network lifetime"""
    import time as _time
    data = request.json or {}
    script = data.get("script", "")
    constraints = data.get("constraints") or {}
    try:
        duration_s = data.get("duration_s")
        duration_s = None if duration_s is None else min(max(float(duration_s), 1.0), MAX_DURATION_S)
        max_latency_ms = constraints.get("max_latency_ms")
        max_latency_ms = None if max_latency_ms in (None, "") else float(max_latency_ms)
        min_delivery = constraints.get("min_delivery_ratio", 0.9)
        min_delivery = 0.9 if min_delivery in (None, "") else float(min_delivery)
    except (TypeError, ValueError):
        return jsonify({"error": "duration_s and constraints must be numbers"}), 400

    names = data.get("candidates") or list(RECOMMEND_CANDIDATES)
    if not isinstance(names, list) or not names or len(names) > 8 or any(n not in RECOMMEND_CANDIDATES for n in names):
        return jsonify({"error": f"candidates must be a list of: {', '.join(RECOMMEND_CANDIDATES)}"}), 400

    started = _time.time()
    results = []
    has_battery = False
    for name in names:
        if _time.time() - started > 40:
            results.append({"name": name, "error": "skipped (time limit)"})
            continue
        proto_name, kwargs = RECOMMEND_CANDIDATES[name]
        ok, msg, res = run_script_sandboxed(script, duration_s, force=(proto_name, kwargs))
        if not ok:
            return jsonify({"error": msg}), 400
        sim = res.get('simulation')
        if not sim:
            return jsonify({"error": "The script has no traffic. Add device.send_interval(seconds, payload_bytes, to=gateway)."}), 400
        s = sim['summary']
        life = network_lifetime_s(sim)
        has_battery = has_battery or any(n['battery_pct'] is not None for n in sim['nodes'].values())
        reasons = []
        if s['delivery_ratio'] is None or s['delivery_ratio'] < min_delivery:
            got = 'none delivered' if s['delivery_ratio'] is None else f"{s['delivery_ratio'] * 100:.1f}%"
            reasons.append(f"delivery {got} is below {min_delivery * 100:.0f}%")
        if max_latency_ms is not None and (s['avg_latency_ms'] is None or s['avg_latency_ms'] > max_latency_ms):
            reasons.append(f"average latency {s['avg_latency_ms']} ms is above {max_latency_ms:g} ms")
        results.append({
            "name": name, "protocol": proto_name, "parameters": kwargs,
            "delivery_ratio": s['delivery_ratio'], "avg_latency_ms": s['avg_latency_ms'],
            "lifetime_s": life, "first_node_death_s": s['first_node_death_s'],
            "first_flow_disconnected_s": s['first_flow_disconnected_s'],
            "total_energy_mj": s['total_energy_mj'], "truncated": sim['truncated'],
            "meets_constraints": not reasons, "fails_because": reasons,
        })

    def rank_key(r):
        life = r.get("lifetime_s")
        return (-(life if life is not None else -1), r.get("total_energy_mj", 0))
    ok_results = sorted([r for r in results if r.get("meets_constraints")], key=rank_key)
    failed = [r for r in results if not r.get("meets_constraints")]
    best = ok_results[0]["name"] if ok_results else None
    notes = ["Lifetime = time until the first battery node dies (measured if it died during the run, otherwise projected from its drain rate)."]
    if not has_battery:
        notes.append("No device has battery_mah, so options are ranked by total energy. Add battery_mah to compare lifetime.")
    if any(r.get("truncated") for r in results):
        notes.append("Some runs were cut short to stay within the time budget; use a shorter duration or fewer devices.")
    return jsonify({"best": best, "ranked": ok_results, "excluded": failed, "constraints": {
        "max_latency_ms": max_latency_ms, "min_delivery_ratio": min_delivery}, "notes": notes})

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
- Scripts cannot use import statements; devices, protocols and math helpers are pre-loaded
- Battery & timing: Device(name, battery_mah=220) or a preset (CR2032, AA2_ALKALINE, LI_ION_18650, LIPO_500), dev.set_protocol(LoRa(spreading_factor=9)), dev.send_interval(60, payload_bytes=20, to='gw'), network.set_duration(3600)
- 'Recommend' button runs the event engine per protocol and ranks by network lifetime
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
    """Call OpenAI (openai>=1.0 client). Model via OPENAI_MODEL env var."""
    if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
        return None, "OpenAI not available"
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
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
    "battery": """# Example script for the editor: battery sensors -> two relays -> gateway.
# Relay r1 has a small battery, so it dies and traffic is re-routed through r2.
# Paste into the editor, click Run (default 1 hour), or call /simulate with "duration_s".

g  = Gateway("gw");  g.turn_on()
r1 = Router("r1", battery_mah=0.5, protocol=BLEProtocol()); r1.turn_on()   # tiny battery on purpose
r2 = Router("r2", protocol=BLEProtocol());                  r2.turn_on()
s1 = Sensor("s1", battery_mah=220, protocol=BLEProtocol()); s1.turn_on()
s2 = Sensor("s2", battery_mah=220, protocol=BLEProtocol()); s2.turn_on()

s1.connect(r1, distance_m=8);  s1.connect(r2, distance_m=12)
s2.connect(r1, distance_m=10); s2.connect(r2, distance_m=15)
r1.connect(g, distance_m=20)
r2.connect(g, distance_m=20)

s1.send_interval(10, 20, to=g)     # every 10 s, 20-byte payload
s2.send_interval(15, 20, to=g)
network.set_duration(600)          # simulate 10 minutes
""",
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
    "features": "Key features include: Web-based Python editor, Multi-layer visualization (Device/Protocol/Energy/DataFlow), 10 IoT protocols (I2C/SPI/UART/WiFi/BLE/LoRa/Zigbee/MQTT/CoAP/CAN), Resource-constrained device modeling, Energy-aware simulation, Performance metrics, Trace file generation, AI chatbot assistant, Battery-aware event simulation with protocol recommendation.",
    "how to use": "To use the IoT simulator: 1) Write your script in the editor using device classes like Arduino, Sensor, LED. 2) Click 'Run Simulation' to execute. 3) View the network visualization. 4) Use multi-layer view by clicking 'Layer' button.",
    "multi-layer": "Multi-layer visualization shows different aspects: Device layer (device types), Protocol layer (communication protocols), Energy layer (power consumption), DataFlow layer (data intensity). Click 'Layer' button to cycle through them.",
    "export": "To export data: Click 'Export' button to download JSON file with complete simulation data including devices, protocols, and performance metrics.",
    "trace": "Trace files contain single-line format with timestamp, device, event, protocol, data size, energy consumption, and latency. Click 'Download Trace' to get the trace file.",
    "devices": "Available devices: Arduino, ESP32, STM32, PIC (microcontrollers), Sensor, Camera, LED, Motor, Display (I/O devices), Gateway, Router, Server, Cloud (network devices).",
    "protocols": "The simulator supports IoT protocols: I2C, SPI, UART, WiFi, BLE, LoRa, Zigbee, MQTT, CoAP, CAN. Each protocol has specific timing and energy characteristics.",
    "pause": "Pause/Resume button allows you to stop the simulation and continue from the exact same point. It preserves all device states and packet positions.",
    "import": "Import statements are blocked in the sandboxed editor for security. Devices, protocols and math helpers are already available without importing.",
    "script": "Scripts use simple Python syntax with device classes. Example: arduino = Arduino('uno'); sensor = Sensor('temp'); sensor.connect(arduino); arduino.turn_on()",
    "error": "Common errors: Check device names are unique, ensure devices are connected before use, verify turn_on() is called before operations.",
    "help": "I can help you with: Creating IoT scripts for any scenario (smart home, industrial, smart city, etc.), Answering questions about simulator features, Troubleshooting script errors, Explaining protocols and devices, Providing usage examples. Just ask your question!",
    "support": "Supported features: Script generation, Q&A about simulator, Multi-layer visualization, Protocol simulation, Device modeling, Energy analysis, Trace file generation, Export functionality, AI chatbot assistance.",
    "example": "Example script: arduino = Arduino('uno'); sensor = Sensor('temp'); led = LED('status'); sensor.connect(arduino); arduino.connect(led); arduino.turn_on(); sensor.turn_on(); led.turn_on();",
    "tutorial": "Quick tutorial: 1) Open editor at /editor, 2) Write script using device classes, 3) Click Run Simulation, 4) View network visualization, 5) Use Layer button for different views, 6) Click Export for JSON data.",
    "network": "Network creation: Use device classes (Arduino, Sensor, LED, etc.), Connect devices with .connect() method, Turn on devices with .turn_on(), Run simulation to visualize network.",
    "connection": "Device connections: Use device1.connect(device2) to create connections. Devices must be created before connecting. Example: sensor = Sensor('temp'); arduino = Arduino('uno'); sensor.connect(arduino);",
    "visualization": "Visualization features: Interactive network graph, Multi-layer views (Device/Protocol/Energy/DataFlow), Packet animation, Real-time status updates, Zoom and pan controls.",
    "energy": "Energy simulation: Models power consumption based on device type and protocol, Calculates energy per transmission, Shows energy metrics in visualization, Available in Energy layer view.",
    "latency": "Latency modeling: Calculates transmission delay based on protocol characteristics, Shows latency in trace files, Displays in performance metrics, Varies by protocol type.",
    "performance": "Performance metrics: Total energy consumption, Average latency, Packet transmission count, Device utilization, Network throughput. Available in export JSON.",
    "advanced": "Advanced features: Custom device classes, Protocol library integration, Trace file analysis, Performance optimization, Network topology design.",
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
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")

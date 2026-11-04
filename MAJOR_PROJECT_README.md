# IoT Network Simulator (Major Project)

A web-based, script-driven simulator for small IoT networks. You describe devices, links and traffic in Python; one event-driven engine simulates the network and shows the result in four views (Device, Protocol, Energy, DataFlow) built from the same simulation state.

## What it does
- Script -> topology: devices, links (with distance), protocols, periodic traffic, battery capacity, memory.
- Event-driven engine (heapq): packet generation, transmission, loss, retries, delivery, buffer overflow, battery death.
- Closed loop: when a node's battery runs out it dies, and traffic is re-routed around it if another path exists.
- Protocol models: I2C, SPI, UART, CAN (wired); WiFi, BLE, Zigbee, LoRa (wireless); MQTT, CoAP (over a link). Airtime is computed from frame bits and data rate; LoRa uses the Semtech airtime formula and duty-cycle off-time; wireless loss uses a log-distance path-loss link budget.
- Energy: E = I x V x t from one source of truth; TX/RX/idle/sleep accumulate over simulated time.
- Protocol recommendation: runs the engine for each candidate protocol and ranks by network lifetime.
- Sandboxed script execution: static AST check plus a separate process with timeout and limits (not a container).

## Lifetime definitions
Reported separately: first node death, first flow disconnected, all flows disconnected. Long runs are cut by a time/event budget and the lifetime is then extrapolated (flagged in warnings).

## Validation status
- Hand-calculated tests for airtime, frame size, energy, LoRa (SF7/9/12), MQTT/CoAP packet sizes, loss and battery death: `test_hand_calculations.py`.
- Unit tests for protocols, sandbox, engine, chatbot: run `python -m pytest`.
- NOT yet done: comparison against published battery-life measurements; verification of every parameter against its datasheet.

## Limitations
- Radio parameters (TX power, sensitivity, path-loss exponent, reference loss) and some wired currents are assumptions.
- No MAC-layer collisions or interference between nodes; no real devices; simplified half-duplex model.
- Fixed random seed (42) gives reproducible, but single-run, results.
- The sandbox is not a hardened container; do not expose to untrusted users without additional isolation.

## Run
```
pip install -r requirements.txt
python app.py        # or: gunicorn app:app
python -m pytest
```
Example script: `example_battery_network.py` (relay with a tiny battery dies and traffic reroutes).

## Chatbot
Template-based assistant by default; optional OpenAI mode via `OPENAI_API_KEY` (and `OPENAI_MODEL`).

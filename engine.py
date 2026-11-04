"""
Event-driven IoT network simulation engine.

One simulation timeline drives everything:
  * every device has a battery and an energy state (TX / RX / idle / sleep)
  * every hop uses the sender's protocol model (airtime, current, loss, retries)
  * resource state feeds back into the network:
        - battery empty        -> node dies -> traffic is re-routed around it
        - send buffer full     -> packet dropped
        - radio busy / LoRa duty cycle -> packet waits (queueing delay)
  * the results (per node, per edge, per flow, timeline) are projections of the same state

Simplifications (state them in your report):
  * half-duplex radios: a node's radio does one thing at a time (TX or RX)
  * no interference between different pairs of nodes, only per-node serialisation
  * application protocols (MQTT/CoAP) are charged as one exchange: the sender pays TX, the receiver RX
  * constant distance per link, loss drawn from the protocol's link-budget model
"""

import heapq
import random
import time
from collections import deque

SINK_TYPES = ('Cloud', 'Server', 'Gateway')
ALWAYS_ON_TYPES = {'Gateway', 'Router', 'Switch', 'Server', 'Cloud', 'RaspberryPi', 'JetsonNano',
                   'BeagleBone', 'PowerSupply'}
MAX_EVENTS = 400000
TIME_BUDGET_S = 3.0          # wall-clock budget: stop early and report partial results instead of timing out
TRACE_LIMIT = 2000
SAMPLES = 100

# event kinds
GEN, HOP_START, HOP_END, BATTERY_DEAD, SAMPLE = 'GEN', 'HOP_START', 'HOP_END', 'BATTERY_DEAD', 'SAMPLE'


class _Node:
    def __init__(self, dev):
        self.dev = dev
        self.id = dev.id
        self.type = dev.type
        self.model = dev.energy_model
        self.active = (dev.state == 'on')
        self.always_on = getattr(dev, 'always_on', None)
        if self.always_on is None:
            self.always_on = dev.type in ALWAYS_ON_TYPES
        self.proto = None
        self.proto_assumed = False
        self.last_t = 0.0
        self.busy_until = 0.0
        self.version = 0
        self.dead = False
        self.died_at = None
        self.pending = deque()          # start times of packets waiting for this node's radio
        mem = getattr(dev, 'memory_kb', None)
        if mem is None:
            mem = self.model.parameters.get('memory_kb')
        self.buffer_bytes = (mem * 1024 * 0.5) if mem else None   # half of RAM usable as send buffer
        self.generated = 0
        self.sent = 0
        self.received = 0
        self.forwarded = 0
        self.dropped = {}
        self.tx_time = 0.0
        self.rx_time = 0.0

    def available(self):
        return self.active and not self.dead


class Simulation:
    def __init__(self, network, duration_s, seed=42, default_protocol=None, max_events=MAX_EVENTS, time_budget_s=TIME_BUDGET_S,
                 force_protocol=None):
        self.net = network
        self.force_protocol = force_protocol       # callable -> new protocol instance for EVERY node (used to compare protocols)
        self.key_events = []
        self.time_budget_s = time_budget_s
        self.duration = float(duration_s)
        self.rng = random.Random(seed)
        self.max_events = max_events
        self.default_protocol_factory = default_protocol
        self.heap = []
        self.seq = 0
        self.events_processed = 0
        self.truncated = False
        self.trace = []
        self.warnings = []

        self.nodes = {nid: _Node(dev) for nid, dev in network.devices.items()}
        self.adj = {nid: {} for nid in self.nodes}
        self.edge_stats = {}
        for (s, t) in network.edges:
            if s in self.nodes and t in self.nodes:
                dist = network.edge_distance(s, t)
                self.adj[s][t] = dist
                self.adj[t][s] = dist
                key = self._ekey(s, t)
                self.edge_stats.setdefault(key, {'source': s, 'target': t, 'distance_m': dist, 'attempts': 0, 'ok': 0,
                                                 'lost': 0, 'airtime_s': 0.0, 'protocol': None})
        self.flows = []
        for f in network.flows:
            self.flows.append({**f, 'generated': 0, 'delivered': 0, 'dropped': 0, 'drop_reasons': {},
                               'lat_sum': 0.0, 'lat_max': 0.0, 'broken_at': None})

        self.first_death = None
        self.first_flow_broken = None
        self.all_flows_broken = None
        self._airtime_cache = {}

        for ns in self.nodes.values():
            self._assign_protocol(ns)

    # ---------- helpers ----------
    @staticmethod
    def _ekey(a, b):
        return (a, b) if a <= b else (b, a)

    def _assign_protocol(self, ns):
        if self.force_protocol is not None:
            ns.proto = self.force_protocol()
            return
        p = getattr(ns.dev, 'protocol', None)
        if p is None:
            if self.default_protocol_factory is None:
                return
            p = self.default_protocol_factory()
            ns.proto_assumed = True
        ns.proto = p

    def _push(self, t, kind, payload):
        self.seq += 1
        heapq.heappush(self.heap, (t, self.seq, kind, payload))

    def _trace(self, t, kind, src, dst, info=''):
        if len(self.trace) < TRACE_LIMIT:
            self.trace.append([round(t, 6), kind, src, dst, info])
        if kind in ('DEAD', 'REROUTE') and len(self.key_events) < 500:      # never lost to the trace limit
            self.key_events.append([round(t, 6), kind, src, dst, info])

    def _airtime(self, proto, payload):
        key = (id(proto), payload)
        if key not in self._airtime_cache:
            off = proto.min_off_time(payload) if hasattr(proto, 'min_off_time') else 0.0
            self._airtime_cache[key] = (proto.airtime(payload), off)
        return self._airtime_cache[key]

    @staticmethod
    def _radio(proto):
        """(tx_ma, rx_ma) of the radio behind a protocol (unwraps MQTT/CoAP to the link below)"""
        link = getattr(proto, 'underlying_protocol', None) or proto
        tx = getattr(link, 'tx_current_ma', 0.0)
        rx = getattr(link, 'rx_current_ma', tx)
        return tx, rx

    @staticmethod
    def _retry_limit(proto):
        if hasattr(proto, 'max_retransmit'):
            return proto.max_retransmit
        link = getattr(proto, 'underlying_protocol', None) or proto
        return getattr(link, 'retry_limit', 3)

    @staticmethod
    def _retry_delay(proto, attempt, airtime):
        if hasattr(proto, 'ack_timeout_s'):     # CoAP (RFC 7252): timeout doubles on every retransmission
            t0 = proto.ack_timeout_s * (1 + (proto.ack_random_factor - 1) / 2)
            return t0 * (2 ** attempt)
        return 2 * airtime

    def _route(self, src, dst):
        """Shortest path (hops) over nodes that are active and alive"""
        if not self.nodes[src].available() or not self.nodes[dst].available():
            return None
        queue = deque([(src, [src])])
        seen = {src}
        while queue:
            cur, path = queue.popleft()
            if cur == dst:
                return path
            for nb in self.adj[cur]:
                if nb not in seen and self.nodes[nb].available():
                    seen.add(nb)
                    queue.append((nb, path + [nb]))
        return None

    def _nearest_sink(self, src):
        queue = deque([src])
        seen = {src}
        while queue:
            cur = queue.popleft()
            if cur != src and self.nodes[cur].type in SINK_TYPES and self.nodes[cur].available():
                return cur
            for nb in self.adj[cur]:
                if nb not in seen and self.nodes[nb].available():
                    seen.add(nb)
                    queue.append(nb)
        return None

    def _pending(self, ns, now):
        while ns.pending and ns.pending[0] <= now:
            ns.pending.popleft()
        return len(ns.pending)

    def _drop(self, pkt, reason, now):
        flow = self.flows[pkt['flow']]
        flow['dropped'] += 1
        flow['drop_reasons'][reason] = flow['drop_reasons'].get(reason, 0) + 1
        node = self.nodes[pkt['path'][pkt['hop']]]
        node.dropped[reason] = node.dropped.get(reason, 0) + 1
        self._trace(now, 'DROP', node.id, pkt['path'][-1], reason)

    # ---------- energy / battery ----------
    def _advance(self, ns, t):
        """Charge baseline current (idle for always-on devices, sleep otherwise) from last_t to t"""
        dt = t - ns.last_t
        if dt > 0 and ns.active and not ns.dead:
            if ns.always_on:
                ns.model.add_idle_energy(dt)
            else:
                ns.model.add_sleep_energy(dt)
        if t > ns.last_t:
            ns.last_t = t

    def _baseline_ma(self, ns):
        return ns.model.get_current_ma('idle' if ns.always_on else 'sleep')

    def _schedule_death(self, ns):
        """Predict when the baseline drain alone empties the battery (re-done after every activity)"""
        model = ns.model
        if model.battery_capacity_mah <= 0 or ns.dead or not ns.active:
            return
        base = self._baseline_ma(ns)
        ns.version += 1
        if base <= 0:
            t_death = ns.last_t if model.battery_current_mah <= 0 else None
        else:
            t_death = ns.last_t + model.battery_current_mah / base * 3600.0
        if t_death is not None and t_death <= self.duration:
            self._push(t_death, BATTERY_DEAD, (ns.id, ns.version))

    def _kill(self, ns, t):
        ns.dead = True
        ns.died_at = t
        ns.model.is_dead = True
        ns.model.state = 'dead'
        ns.model.battery_current_mah = 0
        if hasattr(self.net, 'mark_node_dead'):
            self.net.mark_node_dead(ns.id)
        if self.first_death is None:
            self.first_death = t
        self._trace(t, 'DEAD', ns.id, '', 'battery empty')
        self._check_flows(t)

    def _check_flows(self, t):
        for flow in self.flows:
            if flow['broken_at'] is None:
                dst = flow['sink'] or self._nearest_sink(flow['source'])
                if dst is None or self._route(flow['source'], dst) is None:
                    flow['broken_at'] = t
                    if self.first_flow_broken is None:
                        self.first_flow_broken = t
        if self.flows and self.all_flows_broken is None and all(f['broken_at'] is not None for f in self.flows):
            self.all_flows_broken = t

    # ---------- event handlers ----------
    def _on_gen(self, t, fi):
        flow = self.flows[fi]
        src = self.nodes[flow['source']]
        if not src.available():
            return
        nxt = t + flow['interval']
        if nxt < self.duration:             # a packet generated exactly at the end could never be delivered
            self._push(nxt, GEN, fi)
        flow['generated'] += 1
        src.generated += 1
        pkt = {'flow': fi, 'gen_t': t, 'payload': flow['payload'], 'path': [src.id], 'hop': 0}
        dst = flow['sink'] or self._nearest_sink(src.id)
        path = self._route(src.id, dst) if dst else None
        if path is None:
            self._drop(pkt, 'no_route', t)
            if flow['broken_at'] is None:
                flow['broken_at'] = t
                if self.first_flow_broken is None:
                    self.first_flow_broken = t
                if all(f['broken_at'] is not None for f in self.flows) and self.all_flows_broken is None:
                    self.all_flows_broken = t
            return
        pkt['path'] = path
        if src.buffer_bytes is not None and (self._pending(src, t) + 1) * pkt['payload'] > src.buffer_bytes:
            self._drop(pkt, 'buffer_full', t)
            return
        self._trace(t, 'GEN', src.id, path[-1], f"{pkt['payload']}B")
        self._schedule_hop(pkt, 0, 0, t)

    def _schedule_hop(self, pkt, i, attempt, earliest):
        s = self.nodes[pkt['path'][i]]
        r = self.nodes[pkt['path'][i + 1]]
        proto = s.proto
        if proto is None:
            self._drop({**pkt, 'hop': i}, 'no_protocol', earliest)
            return
        airtime, off = self._airtime(proto, pkt['payload'])
        start = max(earliest, s.busy_until, r.busy_until)
        s.busy_until = start + airtime + off      # LoRa duty cycle: sender must stay silent after sending
        r.busy_until = start + airtime
        s.pending.append(start)
        pkt['hop'] = i
        self._push(start, HOP_START, (pkt, i, attempt, airtime))

    def _on_hop_start(self, t, data):
        pkt, i, attempt, airtime = data
        s = self.nodes[pkt['path'][i]]
        r = self.nodes[pkt['path'][i + 1]]
        pkt['hop'] = i
        if not s.available():
            self._drop(pkt, 'sender_dead', t)
            return
        if not r.available():                       # next hop died: re-route from here
            dst = pkt['path'][-1]
            new = self._route(s.id, dst)
            if new is None:
                self._drop(pkt, 'no_route', t)
                return
            pkt['path'] = pkt['path'][:i] + new
            self._trace(t, 'REROUTE', s.id, dst, '->'.join(new))
            self._schedule_hop(pkt, i, attempt, t)
            return
        proto = s.proto
        self._advance(s, t)
        self._advance(r, t)
        tx_ma, rx_ma = self._radio(proto)
        s.model.add_tx_energy(airtime, current_ma=tx_ma)
        r.model.add_rx_energy(airtime, current_ma=rx_ma)
        end = t + airtime
        s.last_t = max(s.last_t, end)
        r.last_t = max(r.last_t, end)
        s.tx_time += airtime
        r.rx_time += airtime
        s.sent += 1
        es = self.edge_stats[self._ekey(s.id, r.id)]
        es['attempts'] += 1
        es['airtime_s'] += airtime
        es['protocol'] = proto.name
        self._schedule_death(s)
        self._schedule_death(r)
        self._trace(t, 'TX', s.id, r.id, f'{proto.name} {airtime * 1000:.3f} ms')
        dist = self.adj[s.id][r.id]
        ok = self.rng.random() >= proto.loss_probability(dist)
        self._push(end, HOP_END, (pkt, i, attempt, airtime, ok))

    def _on_hop_end(self, t, data):
        pkt, i, attempt, airtime, ok = data
        s = self.nodes[pkt['path'][i]]
        r = self.nodes[pkt['path'][i + 1]]
        es = self.edge_stats[self._ekey(s.id, r.id)]
        if ok and r.dead:
            ok = False                              # receiver ran out of battery during the packet
        if ok:
            es['ok'] += 1
            r.received += 1
            if i + 1 == len(pkt['path']) - 1:
                flow = self.flows[pkt['flow']]
                lat = t - pkt['gen_t']
                flow['delivered'] += 1
                flow['lat_sum'] += lat
                flow['lat_max'] = max(flow['lat_max'], lat)
                self._trace(t, 'DELIVER', s.id, r.id, f'{lat * 1000:.2f} ms')
            else:
                r.forwarded += 1
                if r.buffer_bytes is not None and (self._pending(r, t) + 1) * pkt['payload'] > r.buffer_bytes:
                    pkt['hop'] = i + 1
                    self._drop(pkt, 'buffer_full', t)
                    return
                self._schedule_hop(pkt, i + 1, 0, t)
            return
        es['lost'] += 1
        self._trace(t, 'LOSS', s.id, r.id, f'attempt {attempt + 1}')
        if attempt < self._retry_limit(s.proto):
            delay = self._retry_delay(s.proto, attempt, airtime)
            self._schedule_hop(pkt, i, attempt + 1, t + delay)
        else:
            self._drop(pkt, 'max_retries', t)

    def _on_battery_dead(self, t, data):
        nid, version = data
        ns = self.nodes[nid]
        if ns.dead or version != ns.version:
            return
        self._advance(ns, t)
        self._kill(ns, t)

    def _on_sample(self, t, _):
        for ns in self.nodes.values():
            if ns.available():
                self._advance(ns, t)
        self.timeline.append(self._snapshot(t))

    def _snapshot(self, t):
        batt = {}
        for ns in self.nodes.values():
            pct = ns.model.get_battery_percentage()
            if pct is not None:
                batt[ns.id] = round(pct, 3)
        alive = sum(1 for ns in self.nodes.values() if ns.available())
        return {'t': round(t, 3), 'battery_pct': batt, 'alive': alive}

    # ---------- run ----------
    def run(self):
        self.timeline = []
        for ns in self.nodes.values():
            if not ns.active:
                self.warnings.append(f"{ns.id} is off (call turn_on()), so it takes no part in the simulation")
        for fi, flow in enumerate(self.flows):
            if flow['source'] not in self.nodes:
                continue
            self._push(0.0, GEN, fi)
        for ns in self.nodes.values():
            self._schedule_death(ns)
        for k in range(1, SAMPLES + 1):
            self._push(self.duration * k / SAMPLES, SAMPLE, None)
        handlers = {GEN: self._on_gen, HOP_START: self._on_hop_start, HOP_END: self._on_hop_end,
                    BATTERY_DEAD: self._on_battery_dead, SAMPLE: self._on_sample}
        started = time.perf_counter()
        while self.heap:
            t, _, kind, data = heapq.heappop(self.heap)
            if t > self.duration:
                break
            out_of_events = self.events_processed >= self.max_events
            out_of_time = (self.events_processed % 2048 == 0 and time.perf_counter() - started > self.time_budget_s)
            if out_of_events or out_of_time:
                self.truncated = True
                why = f"{self.max_events} events" if out_of_events else f"{self.time_budget_s:.0f} s of computing time"
                self.warnings.append(f"Stopped after {why}: simulated {t:.0f} s of the requested {self.duration:.0f} s. "
                                     f"Use fewer devices, a larger interval or a shorter duration; projected lifetimes still extrapolate from the simulated part.")
                self.duration_simulated = t
                break
            self.events_processed += 1
            handlers[kind](t, data)
        end_t = getattr(self, 'duration_simulated', self.duration)
        for ns in self.nodes.values():
            if ns.available():
                self._advance(ns, end_t)
        return self._results(end_t)

    def _results(self, end_t):
        hours = end_t / 3600.0 if end_t > 0 else 1.0
        nodes = {}
        for ns in self.nodes.values():
            m = ns.model
            drained = (m.battery_capacity_mah - m.battery_current_mah) if m.battery_capacity_mah > 0 else None
            proj = None
            if drained is not None and not ns.dead and drained > 0:
                proj = m.battery_current_mah / (drained / hours) * 3600.0
            nodes[ns.id] = {
                'type': ns.type,
                'state': 'dead' if ns.dead else ('on' if ns.active else 'off'),
                'protocol': ns.proto.name if ns.proto else None,
                'protocol_assumed': ns.proto_assumed,
                'battery_pct': None if m.get_battery_percentage() is None else round(m.get_battery_percentage(), 4),
                'battery_mah_left': None if m.battery_capacity_mah <= 0 else round(m.battery_current_mah, 6),
                'died_at_s': ns.died_at,
                'projected_lifetime_s': proj,
                'energy_mj': {'tx': m.tx_energy_mj, 'rx': m.rx_energy_mj, 'idle': m.idle_energy_mj,
                              'sleep': m.sleep_energy_mj, 'total': m.total_energy_mj},
                'tx_time_s': ns.tx_time, 'rx_time_s': ns.rx_time,
                'generated': ns.generated, 'sent': ns.sent, 'received': ns.received, 'forwarded': ns.forwarded,
                'dropped': dict(ns.dropped),
                'always_on': ns.always_on,
            }
        edges = []
        for e in self.edge_stats.values():
            edges.append({**e, 'load_pct': round(100.0 * e['airtime_s'] / end_t, 4) if end_t > 0 else 0.0,
                          'loss_pct': round(100.0 * e['lost'] / e['attempts'], 3) if e['attempts'] else 0.0})
        flows = []
        tot_gen = tot_del = tot_done = 0
        lat_sum = 0.0
        for f in self.flows:
            d = f['delivered']
            done = d + f['dropped']
            flows.append({'source': f['source'], 'sink': f['sink'], 'interval_s': f['interval'],
                          'payload_bytes': f['payload'], 'generated': f['generated'], 'delivered': d,
                          'dropped': f['dropped'], 'drop_reasons': f['drop_reasons'],
                          'in_flight': f['generated'] - done,
                          'delivery_ratio': round(d / done, 4) if done else None,
                          'avg_latency_ms': round(f['lat_sum'] / d * 1000, 4) if d else None,
                          'max_latency_ms': round(f['lat_max'] * 1000, 4) if d else None,
                          'disconnected_at_s': f['broken_at']})
            tot_gen += f['generated']
            tot_del += d
            tot_done += done
            lat_sum += f['lat_sum']
        total_e = sum(n['energy_mj']['total'] for n in nodes.values())
        return {
            'duration_s': end_t, 'requested_duration_s': self.duration, 'events_processed': self.events_processed, 'truncated': self.truncated,
            'warnings': self.warnings,
            'summary': {
                'first_node_death_s': self.first_death,
                'first_flow_disconnected_s': self.first_flow_broken,
                'all_flows_disconnected_s': self.all_flows_broken,
                'packets_generated': tot_gen, 'packets_delivered': tot_del,
                'delivery_ratio': round(tot_del / tot_done, 4) if tot_done else None,   # delivered / (delivered + dropped); packets still in flight at the end are excluded
                'avg_latency_ms': round(lat_sum / tot_del * 1000, 4) if tot_del else None,
                'total_energy_mj': total_e,
            },
            'nodes': nodes, 'edges': edges, 'flows': flows,
            'timeline': self.timeline, 'trace': self.trace, 'key_events': self.key_events,
        }


def run_simulation(network, duration_s, seed=42, default_protocol=None, max_events=MAX_EVENTS, time_budget_s=TIME_BUDGET_S,
                   force_protocol=None):
    """Run the network's traffic flows for duration_s simulated seconds and return a results dict"""
    return Simulation(network, duration_s, seed, default_protocol, max_events, time_budget_s, force_protocol).run()

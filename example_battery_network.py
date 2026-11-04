# Example script for the editor: battery sensors -> two relays -> gateway.
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

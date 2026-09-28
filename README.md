# Espresso Monitor

An [Indigo](https://www.indigodomo.com) plugin that works out what an espresso machine is doing from the
power reading of the smart plug it's plugged into — no connection to the machine itself.

Built and measured on a **Lelit Bianca V3**. A **Lelit Elizabeth** preset is included but unverified (see below).

## What it tells you

An **Espresso Machine** device with a status of:

| Status | Meaning |
|---|---|
| Off | Plug off (or, without plug state, nothing drawn for 45 min) |
| Heating | Warming up after switch-on or waking from eco |
| Ready | At temperature — only short keep-warm bursts |
| Brewing / Steaming / Backflushing | Happening now |
| Eco (asleep) | The machine's own idle timer has put it to sleep |
| Tank empty | Heaters and pump stopped when they shouldn't have — the machine cuts both when the tank runs dry |
| No draw | Plug on but nothing drawn — tank empty or the machine's own switch is off |

Plus counters for charts: shots today / total, last shot length and time, steams today, last heat-up time,
last backflush and days since, pump seconds since refill, tank % used.

**Events** for ordinary Indigo triggers (each can be limited to one machine): Machine ready, Shot finished,
Steaming finished, Backflush finished, Entered eco, Tank empty, Tank low, Tank refilled.

**Actions:** Mark tank refilled, Reset shot and steam counters. Also **Plugins → Espresso Monitor → Mark tank refilled…**

## Setup

1. Install the plugin and enable it.
2. Create a device: type **Espresso Machine**.
3. Choose the **power device** — any Indigo device reporting power (`curEnergyLevel`), ideally with an on/off state.
4. Choose the **machine model** and press **Load preset values**. Adjust any field if your plug reads differently.

## How a few things work

- **Shots** are confirmed, not instant: a shot is counted as soon as steaming follows it, or about 6 minutes
  later if not. Three or more pump runs within 6 minutes are a **backflush** and are never counted as shots.
- **Tank low** is learned. Each time the tank runs dry and is refilled, the plugin records how many pump-seconds
  that tank lasted and warns at 85 % of the median of the last three. It stays quiet until it has learned one
  tankful. If you top up early, use **Mark tank refilled** — that resets the count without teaching the plugin a
  smaller tank.
- The plug only reports when the reading changes, so the plugin also checks the clock every 10 seconds: eco and
  an empty tank are both *silence*. It tells them apart by timing — the machine goes to sleep a fixed time
  (30 min on the Bianca) after you last used it.

## Measured on the Lelit Bianca V3

| Level | Watts |
|---|---|
| Idle, heaters off | ~1.2–1.8 |
| Pump alone (rotary) | ~200–290 |
| Steam heater | ~1,245–1,330 |
| Brew heater | ~1,390–1,450 |
| Pump + brew heater | ~1,500–1,690 |

Heat-up from cold: ~14.5 min with both boilers, ~6–8 min with the steam boiler off.

## Lelit Elizabeth and other machines

The Elizabeth preset is estimated from published specs, not measured. Its vibratory pump draws tens of watts,
so "pump + heater" may be indistinguishable from "heater alone"; the preset finds shots from pump-alone readings
only. To help tune it: tick **Log raw readings** in the device, make a drink (with milk), then send the Indigo
log lines starting `raw`.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

`detector.py` has no Indigo dependency. `tests/test_replay.py` replays two weeks of recorded Bianca data through
it; `tools/make_fixture.py` cuts new fixtures from a SQL Logger export.

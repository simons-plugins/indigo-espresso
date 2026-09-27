# Espresso Monitor — design

Date: 2026-09-27. Status: draft for review.

## Purpose

An Indigo plugin that works out what an espresso machine is doing from the
power reading of the smart plug it sits on. For Simon's Lelit Bianca V3 now;
shareable, so a friend with a Lelit Elizabeth can use it too.

Success means:

- a status device that is right at a glance (heating, ready, brewing, steaming,
  backflushing, eco, tank empty);
- Indigo events that fire once per real occurrence, so ordinary triggers can
  notify (Pushover, Domio, anything);
- counters SQL Logger can chart (shots per day, backflush interval, tank use);
- a tank-low warning before the machine runs dry, learned from use, not set by
  hand.

## Scope

In v1:

- one Indigo device per machine, fed by any Indigo device with a
  `curEnergyLevel` state (and optionally `onOffState`);
- built-in model presets: **Lelit Bianca V3** (measured) and **Lelit
  Elizabeth** (from published specs, marked unverified);
- every threshold editable in the device config after loading a preset;
- a raw-reading debug log, so an unverified machine's owner can capture a
  session for tuning;
- manual "Mark tank refilled" action.

Not in v1 (v2 candidate): guided learn mode (Learn idle / shot / steam) that
measures levels and writes them into the device config. Not planned: the plugin
sending notifications itself; auto-updating the shipped presets.

## Evidence the design rests on

From 30 days of the Bianca's SQL Logger history (IKEA GRILLPLATS Matter plug,
readings every ~3 s, only when the value changes), confirmed with Simon:

| Level | Bianca V3 |
|---|---|
| Idle, heaters off | ~1.2–1.8 W |
| Pump alone (rotary) | ~200–290 W |
| Steam heater | ~1,245–1,330 W |
| Brew heater | ~1,390–1,450 W |
| Pump + brew heater | ~1,500–1,690 W |

- Cold heat-up: ~14.5 min with both boilers, ~7.75 min with the steam boiler
  off.
- Shot: pump starts (~230 W), pump + heater, pump alone; 25–40 s in all.
- Steaming usually starts ~10 s after the shot: steam heater 30–60 s.
- Steam-boiler refill: a few seconds of pump alone, then ~50 s steam heater.
- Backflush (26 Sep 16:23–16:34): repeated 10–15 s pump runs a few seconds
  apart, no steaming.
- Eco: 30 min after the last activity the heaters stop for ~20–25 min while
  the machine cools to its eco temperature, then keep-warm resumes at a lower
  duty (average ~175 W falls to ~40–65 W). The plug sends nothing during the
  cool-down because the value doesn't change.
- Empty tank: the Bianca cuts heaters and pump (Simon). Often happens just
  after switch-on, after the pump has filled the steam boiler.

## Architecture

```
Power device (curEnergyLevel, onOffState)
      │ deviceUpdated                        every 10 s
      ▼                                         │
plugin.py ── reading(t, watts, plug_on) ──► detector.py ◄── tick(t)
      ▲                                         │
      └──────── events + state snapshot ────────┘
profiles.py — presets → default thresholds
```

- **`detector.py`** — pure Python, no Indigo import. `Detector(thresholds,
  saved_state)`; `reading(t, watts, plug_on)` and `tick(t)` each return a list
  of events; `snapshot()` returns the state to persist. All timing uses the
  `t` passed in, never the wall clock, so recorded data can be replayed.
- **`profiles.py`** — preset name → threshold dict. Pure data.
- **`plugin.py`** — thin: subscribes to device changes, forwards readings for
  each monitored power device, calls `tick` from `runConcurrentThread`, writes
  device states, fires plugin events, handles actions and menu items. No
  detection logic.
- Standard library only. Indigo 2025.x (Python 3.13).

## Thresholds (device config)

| Field | Meaning | Bianca V3 preset |
|---|---|---|
| `idleMaxW` | at or below: nothing running | 20 |
| `pumpMinW` / `pumpMaxW` | pump alone | 150 / 350 |
| `steamMinW` / `steamMaxW` | steam heater | 1150 / 1360 |
| `brewMinW` / `brewMaxW` | brew heater | 1360 / 1480 |
| `pumpHeaterMinW` | pump + heater | 1480 |
| `ecoTimeoutMin` | machine's own idle-to-eco timer | 30 |
| `silenceMin` | no heat/pump this long = eco or empty | 3 |
| `tankLowPct` | warn at this share of a learned tank | 85 |

Readings between bands (heater switching mid-sample, e.g. 590 W) count as
"heater on, unknown which".

## Detection rules

States: `off`, `heating`, `ready`, `brewing`, `steaming`, `backflushing`,
`eco`, `tankEmpty`, `noDraw`.

- **Off** — plug off, or no plug state and ≤ idle for longer than the eco
  window plus silence.
- **Heating** — entered on plug-on, or on leaving eco/empty with sustained
  heater draw. **Ready** once 90 s pass in which every heater burst is ≤ 15 s (keep-warm);
  the 20–40 s bursts at the end of a steam-off heat-up still count as heating. Records `lastHeatUpSeconds`.
- **Brewing (shot)** — starts at the first pump-indicating reading (pump band or
  ≥ pump+heater) while ready/heating; ends when no pump-indicating reading for
  6 s. Duration = end − start. Emits `shotFinished`.
- **Steaming** — ≥ 20 s of steam-band readings. Emits `steamFinished`.
- **Backflush** — ≥ 3 pump runs of 5–20 s within 3 min with no steaming in
  between. Replaces the shots those runs would have counted (a backflush is not
  shots). Emits `backflushFinished`; sets `lastBackflush`.
- **Eco** — no heater/pump for `silenceMin` when the time since the last
  activity (switch-on, shot, steam, backflush) is ≥ `ecoTimeoutMin` − 2 min.
  Emits `ecoEntered`. Leaves eco on the next sustained heating.
- **Tank empty** — no heater/pump for `silenceMin` when eco can't explain it
  (time since activity < `ecoTimeoutMin` − 2 min) and the machine had been
  drawing power. Emits `tankEmpty`.
- **No draw** — plug on but nothing above idle within `silenceMin` of
  switch-on. Status text: "No draw — tank empty or machine switched off".
  Emits `tankEmpty` (same trigger; the two can't be told apart).
- **Refilled** — first pump-indicating reading while in tankEmpty/noDraw, or
  the manual action. Emits `tankRefilled`.

Because the plug reports only on change, silence rules are evaluated by
`tick()` every 10 s, not only on readings.

## Tank learning

- Pump-seconds accumulate from pump-indicating readings (sample-and-hold,
  capped at 5 s per reading so a missed report can't inflate it).
- An **auto-detected** empty closes a tankful: its pump-seconds are recorded;
  the last 3 are kept.
- A **manual** refill resets the count but the interrupted tankful is **not**
  recorded (it wasn't used up, so it would make the tank look smaller).
- Refill is assumed to be to the top.
- `tankLow` fires once per tankful when pump-seconds ≥ `tankLowPct` % of the
  median recorded tankful. Silent until at least one tankful is recorded.

## Device states

`status` (enum above), `statusText`, `lastHeatUpSeconds`, `readySince`,
`shotsToday`, `shotsTotal`, `lastShotSeconds`, `lastShotTime`, `steamsToday`,
`lastBackflush`, `daysSinceBackflush`, `pumpSecondsSinceRefill`,
`tankPercentUsed`, `tankLearnedPumpSeconds`, plus a JSON `detectorState` for
restart persistence. `shotsToday` and `steamsToday` reset at local midnight.

## Events and actions

Events: `machineReady`, `shotFinished`, `steamFinished`, `backflushFinished`,
`ecoEntered`, `tankEmpty`, `tankLow`, `tankRefilled` — each filterable to one
machine device or any.

Actions: `markTankRefilled`, `resetCounters`. Menu item: "Mark tank refilled".
The device config has a "Load preset" button that fills the threshold fields.

## Presets

- **Lelit Bianca V3** — the measured values above.
- **Lelit Elizabeth** — unverified, from published specs: vibratory pump
  (tens of watts, not ~230 W), smaller brew heater. **Known risk:** a vibratory
  pump may be too small to separate "pump + heater" from "heater alone", so
  shot detection may need a different rule on this machine. The preset ships
  labelled unverified; the debug log exists to capture a real session and
  settle it.
- **Custom** — all fields blank for manual entry.

## Error handling

- Power device missing or disabled: status `off`, one warning in the log, no
  events.
- Non-numeric or negative readings: ignored, logged at debug.
- Plugin restart: detector restored from `detectorState`; a reading gap across
  the restart is treated as silence, not activity.
- Clock jumps (DST): all rules use monotonic durations between readings;
  midnight reset uses local date change.

## Testing

`pytest`, no Indigo needed for the detector:

- **Replay fixtures** extracted from SQL Logger (CSV: epoch, watts, plug_on):
  - 27 Sep 09:23–09:28 → one shot (~30 s) then one steam;
  - 26 Sep 16:20–16:40 → one backflush, zero shots;
  - 25 Sep 08:55–09:35 → eco entered ~09:04, no tankEmpty;
  - 13 Sep 08:00–08:30 → noDraw then heating;
  - 25 Sep full day → shots per drink window, no spurious events;
  - 27 Sep 08:00 cold start (steam off) → ready after ~7–8 min.
- Synthetic sequences for tank learning, manual vs auto refill, restart
  persistence, midnight reset.
- `plugin.py` covered by the repo's existing pattern (fake `indigo` module in
  `tests/support.py`, as in indigo-xbox).

## Repo and release

`simons-plugins/indigo-espresso`, public. `Espresso.indigoPlugin/`,
`tests/`, `README.md`, `CHANGELOG.md`, CI copied from indigo-xbox (tests,
version-check, create-release). Bundle id
`com.simons-plugins.indigo-espresso`, version `2026.0.1`. Developed on jarvis
(Indigo and the recorded data live there); GitHub is the only shared copy.

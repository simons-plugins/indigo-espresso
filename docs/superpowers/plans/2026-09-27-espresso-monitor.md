# Espresso Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Indigo plugin, "Espresso Monitor", that turns a smart plug's power reading into espresso-machine status, events and counters.

**Architecture:** A pure-Python `detector.py` (no Indigo import) consumes `(time, watts, plug_on)` readings plus a 10 s clock tick and returns events; `profiles.py` holds model presets; `plugin.py` is a thin Indigo shell that routes power-device updates to one detector per machine device, writes states and fires plugin events. Real recorded data from Simon's Bianca is replayed through the detector in pytest.

**Tech Stack:** Python 3.13 standard library only; Indigo 2025.x plugin API (ServerApiVersion 3.4); pytest; GitHub Actions (tests, version-check, create-release copied from indigo-xbox).

**Spec:** `docs/superpowers/specs/2026-09-27-espresso-monitor-design.md`

## Global Constraints

- Plugin display name `Espresso Monitor`; bundle `Espresso Monitor.indigoPlugin`; bundle id `com.simons-plugins.indigo-espresso`; `PluginVersion` `2026.0.1`; `ServerApiVersion` `3.4`.
- Standard library only — no `requirements.txt`.
- `detector.py` and `profiles.py` must not import `indigo`.
- Custom state IDs: camelCase ASCII letters/digits only, no underscores (Indigo rejects them).
- `deviceUpdated` must start with `super().deviceUpdated(...)` then the `newDev.pluginId == self.pluginId` self-loop guard.
- Custom events fire via `indigo.trigger.execute(trigger)` from triggers registered in `triggerStartProcessing` — never `indigo.server.fireEvent` / `self.triggerEvent` (they don't exist).
- Use `self.sleep()` in `runConcurrentThread`, never `time.sleep()`.
- Every PR bumps `PluginVersion` (version-check CI). Never merge locally, never squash, never merge without Simon's go-ahead.
- Git: use `/usr/bin/git` on jarvis (`/usr/local/bin/git` is too old).

## Deviations from the spec (found by replaying the data, agreed in chat 2026-09-27)

- `silenceMin` is split: `heatSilenceMin` 2 (during heat-up), `idleSilenceMin` 8 (when ready — the Bianca goes quiet 3–6 min after a heat-up overshoot or shot recovery), `noDrawMin` 3. Eco still needs only 3 min of silence (`ECO_SILENCE_S`).
- The eco timer counts from the last *user* action (switch-on, shot, steam), not from the end of heat-up.
- Shot events are confirmed, not instant: a shot is emitted when steaming follows it, or 6 min after it if no further pump runs arrive (≥ 3 runs within 6 min = backflush, and those runs never count as shots).
- Pump runs within 90 s of switch-on are the steam boiler filling, not shots.
- After a restore (plugin restart) silence rules are suspended until the first new reading, so a restart can't raise a false "tank empty".
- `noDraw` does not record a tankful (it may be the machine's own switch being off).

## Review Focus

1. **Plug reports only on change** — a steady 1.5 W produces no readings for 20+ min; silence must come from `tick()`, and a held high reading with no new report must not count as silence. (Task 3 `test_held_high_reading_is_not_silence`.)
2. **Plugin restart mid-session** — restored detector must not fire `tankEmpty` from the reporting gap across the restart. (Task 5 `test_restore_suspends_silence_until_first_reading`.)
3. **Power device without `onOffState`** (friend's plug may only meter) — machine still goes heating → ready → off. (Task 3 `test_no_plug_state_starts_on_draw_and_goes_off_after_45_min`.)
4. **Midnight / DST** — `shotsToday` resets on the local date change, including across a DST change. (Task 5 `test_midnight_reset_across_dst`.)
5. **Power device deleted or disabled** — plugin logs one warning, leaves the machine's states alone, no events. (Task 8 `test_missing_power_device_warns_once`.)

---

## File Structure

```
indigo-espresso/
├── Espresso Monitor.indigoPlugin/Contents/
│   ├── Info.plist
│   └── Server Plugin/
│       ├── plugin.py        # Indigo shell: routing, states, events, actions, config UI
│       ├── detector.py      # pure detection state machine
│       ├── profiles.py      # presets + threshold parsing/validation
│       ├── Devices.xml      # espressoMachine device, config UI, states
│       ├── Events.xml       # 8 plugin events
│       ├── Actions.xml      # markTankRefilled, resetCounters
│       ├── MenuItems.xml    # "Mark tank refilled…"
│       └── PluginConfig.xml # debug toggle
├── tests/
│   ├── conftest.py          # fake indigo module + sys.path
│   ├── replay.py            # fixture loader + replay driver
│   ├── fixtures/*.csv(.gz)  # recorded Bianca data
│   ├── test_profiles.py
│   ├── test_detector_basic.py
│   ├── test_detector_shots.py
│   ├── test_detector_tank.py
│   ├── test_replay.py
│   ├── test_xml.py
│   └── test_plugin.py
├── tools/make_fixture.py    # cut a fixture from a SQL Logger export
├── .github/workflows/{tests,version-check,create-release}.yml
├── pyproject.toml  .gitignore  README.md  CHANGELOG.md
```

---

### Task 1: Scaffold the repo

**Files:**
- Create: `Espresso Monitor.indigoPlugin/Contents/Info.plist`, `pyproject.toml`, `.gitignore`, `CHANGELOG.md`, `README.md` (stub), `.github/workflows/tests.yml`, `.github/workflows/version-check.yml`, `.github/workflows/create-release.yml`, `tests/conftest.py`, `tests/test_xml.py`

**Interfaces:**
- Produces: `tests/conftest.py` puts `Server Plugin/` on `sys.path` and installs a fake `indigo` module (`FakeDevice`, `FakeDevices`, `PluginBase`, `trigger.execute` recorder) used by Task 8.

- [ ] **Step 1: Branch**

```bash
cd ~/indigo-espresso && /usr/bin/git checkout -b feat/v1
mkdir -p "Espresso Monitor.indigoPlugin/Contents/Server Plugin" tests/fixtures tools .github/workflows
```

- [ ] **Step 2: Copy CI workflows from indigo-xbox verbatim**

```bash
for f in tests version-check create-release; do
  gh api repos/simons-plugins/indigo-xbox/contents/.github/workflows/$f.yml --jq .content | base64 -d > .github/workflows/$f.yml
done
```

- [ ] **Step 3: Write Info.plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDisplayName</key>
	<string>Espresso Monitor</string>
	<key>CFBundleIdentifier</key>
	<string>com.simons-plugins.indigo-espresso</string>
	<key>CFBundleURLTypes</key>
	<array>
		<dict>
			<key>CFBundleURLName</key>
			<string>https://github.com/simons-plugins/indigo-espresso</string>
		</dict>
	</array>
	<key>CFBundleVersion</key>
	<string>1.0.0</string>
	<key>GithubInfo</key>
	<dict>
		<key>GithubRepo</key>
		<string>indigo-espresso</string>
		<key>GithubUser</key>
		<string>simons-plugins</string>
	</dict>
	<key>PluginVersion</key>
	<string>2026.0.1</string>
	<key>ServerApiVersion</key>
	<string>3.4</string>
</dict>
</plist>
```

- [ ] **Step 4: Write pyproject.toml, .gitignore, CHANGELOG.md, README stub**

`pyproject.toml`:
```toml
[project]
name = "indigo-espresso"
version = "2026.0.1"
description = "Espresso Monitor — Indigo plugin tracking an espresso machine from its smart plug's power"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
```

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

`CHANGELOG.md`:
```markdown
# Changelog

## 2026.0.1
- First release: status device, events and counters for a Lelit Bianca V3; unverified Lelit Elizabeth preset.
```

`README.md`: `# Espresso Monitor` plus one line; the full README is written in Task 9.

- [ ] **Step 5: Write tests/conftest.py (fake indigo)**

```python
"""Test harness: puts Server Plugin on sys.path and installs a fake ``indigo``."""
import sys
import types
from pathlib import Path
from unittest.mock import Mock

SERVER_PLUGIN_DIR = Path(__file__).parent.parent / "Espresso Monitor.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(SERVER_PLUGIN_DIR))
sys.path.insert(0, str(Path(__file__).parent))


class FakeDevice:
    def __init__(self, id, name="Dev", pluginId="", deviceTypeId="", pluginProps=None, states=None,  # noqa: A002
                 enabled=True):
        self.id = id
        self.name = name
        self.pluginId = pluginId
        self.deviceTypeId = deviceTypeId
        self.pluginProps = dict(pluginProps or {})
        self.states = dict(states or {})
        self.enabled = enabled
        self.batches = []
        self.state_list_refreshes = 0

    def updateStatesOnServer(self, items):
        self.batches.append([dict(i) for i in items])
        for item in items:
            self.states[item["key"]] = item["value"]

    def stateListOrDisplayStateIdChanged(self):
        self.state_list_refreshes += 1


class FakeDevices:
    def __init__(self):
        self._d = {}
        self.subscribed = False

    def add(self, dev):
        self._d[dev.id] = dev
        return dev

    def __getitem__(self, key):
        return self._d[key]

    def __contains__(self, key):
        return key in self._d

    def __iter__(self):
        return iter(list(self._d.values()))

    def iter(self, filter=""):  # noqa: A002
        if filter == "self":
            return [d for d in self._d.values() if d.pluginId == "com.simons-plugins.indigo-espresso"]
        return list(self._d.values())

    def subscribeToChanges(self):
        self.subscribed = True


class _StopThread(Exception):
    pass


class PluginBase:
    StopThread = _StopThread

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs, **kwargs):
        self.pluginId = pluginId
        self.pluginDisplayName = pluginDisplayName
        self.pluginVersion = pluginVersion
        self.pluginPrefs = pluginPrefs
        self.logger = Mock()
        self.debug = False

    def deviceUpdated(self, origDev, newDev):
        pass

    def sleep(self, seconds):
        pass


def install_fake_indigo():
    mod = types.ModuleType("indigo")
    mod.PluginBase = PluginBase
    mod.devices = FakeDevices()
    mod.trigger = types.SimpleNamespace(execute=Mock())
    mod.Dict = dict
    mod.List = list
    sys.modules["indigo"] = mod
    return mod


install_fake_indigo()
```

- [ ] **Step 6: Write the first failing test: tests/test_xml.py checks Info.plist**

```python
import plistlib
import xml.etree.ElementTree as ET
from pathlib import Path

CONTENTS = Path(__file__).parent.parent / "Espresso Monitor.indigoPlugin" / "Contents"
SP = CONTENTS / "Server Plugin"


def test_info_plist():
    with open(CONTENTS / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleDisplayName"] == "Espresso Monitor"
    assert info["CFBundleIdentifier"] == "com.simons-plugins.indigo-espresso"
    assert info["PluginVersion"] == "2026.0.1"
```

- [ ] **Step 7: Run and commit**

Run: `cd ~/indigo-espresso && python3 -m pytest -q`
Expected: 1 passed.

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "chore: scaffold Espresso Monitor plugin"
```

---

### Task 2: Presets and threshold parsing (`profiles.py`)

**Files:**
- Create: `Espresso Monitor.indigoPlugin/Contents/Server Plugin/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Produces:
  - `THRESHOLD_KEYS: tuple[str, ...]` — `("idleMaxW","pumpMinW","pumpMaxW","steamMinW","steamMaxW","brewMinW","brewMaxW","pumpHeaterMinW","heaterMinW","ecoTimeoutMin","heatSilenceMin","idleSilenceMin","noDrawMin","tankLowPct")`
  - `PRESETS: dict[str, dict]` — keys `"biancaV3"`, `"elizabeth"`; each `{"label": str, "verified": bool, "thresholds": dict[str, float]}`
  - `preset_menu() -> list[tuple[str, str]]` (includes `("custom", "Custom")`)
  - `preset_thresholds(key: str) -> dict[str, float]` (raises `KeyError` for unknown/custom)
  - `thresholds_from_props(props: Mapping) -> dict[str, float]` (raises `ValueError` naming bad keys)
  - `validate_props(props: Mapping) -> dict[str, str]` (field → error message; empty if valid)

- [ ] **Step 1: Write the failing tests**

```python
import pytest

import profiles


def test_bianca_preset_matches_measured_values():
    th = profiles.preset_thresholds("biancaV3")
    assert th["pumpMinW"] == 150 and th["pumpMaxW"] == 350
    assert th["steamMinW"] == 1150 and th["steamMaxW"] == 1360
    assert th["brewMinW"] == 1360 and th["brewMaxW"] == 1480
    assert th["pumpHeaterMinW"] == 1480
    assert th["ecoTimeoutMin"] == 30 and th["idleSilenceMin"] == 8
    assert set(th) == set(profiles.THRESHOLD_KEYS)


def test_elizabeth_is_unverified_and_complete():
    assert profiles.PRESETS["elizabeth"]["verified"] is False
    assert set(profiles.preset_thresholds("elizabeth")) == set(profiles.THRESHOLD_KEYS)


def test_menu_lists_presets_and_custom():
    keys = [k for k, _ in profiles.preset_menu()]
    assert keys == ["biancaV3", "elizabeth", "custom"]


def test_custom_has_no_thresholds():
    with pytest.raises(KeyError):
        profiles.preset_thresholds("custom")


def test_thresholds_from_props_parses_strings():
    props = {k: str(v) for k, v in profiles.preset_thresholds("biancaV3").items()}
    assert profiles.thresholds_from_props(props)["pumpMinW"] == 150.0


def test_thresholds_from_props_names_bad_keys():
    props = {k: "1" for k in profiles.THRESHOLD_KEYS}
    props["pumpMinW"] = "abc"
    del props["tankLowPct"]
    with pytest.raises(ValueError) as exc:
        profiles.thresholds_from_props(props)
    assert "pumpMinW" in str(exc.value) and "tankLowPct" in str(exc.value)


def test_validate_rejects_min_above_max_and_bad_pct():
    props = {k: str(v) for k, v in profiles.preset_thresholds("biancaV3").items()}
    props["pumpMinW"] = "400"
    props["tankLowPct"] = "150"
    errors = profiles.validate_props(props)
    assert set(errors) == {"pumpMinW", "tankLowPct"}


def test_validate_accepts_both_presets():
    for key in ("biancaV3", "elizabeth"):
        props = {k: str(v) for k, v in profiles.preset_thresholds(key).items()}
        assert profiles.validate_props(props) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_profiles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'profiles'`.

- [ ] **Step 3: Implement profiles.py**

```python
"""Machine presets and threshold parsing. No Indigo import."""

THRESHOLD_KEYS = (
    "idleMaxW", "pumpMinW", "pumpMaxW", "steamMinW", "steamMaxW", "brewMinW", "brewMaxW",
    "pumpHeaterMinW", "heaterMinW", "ecoTimeoutMin", "heatSilenceMin", "idleSilenceMin",
    "noDrawMin", "tankLowPct",
)

PRESETS = {
    "biancaV3": {
        "label": "Lelit Bianca V3 (measured)",
        "verified": True,
        # Measured 2026-09 on an IKEA GRILLPLATS plug: pump ~230 W, steam heater
        # ~1.25-1.33 kW, brew heater ~1.39-1.45 kW, pump + brew heater ~1.5-1.69 kW.
        "thresholds": {
            "idleMaxW": 20, "pumpMinW": 150, "pumpMaxW": 350, "steamMinW": 1150, "steamMaxW": 1360,
            "brewMinW": 1360, "brewMaxW": 1480, "pumpHeaterMinW": 1480, "heaterMinW": 1000,
            "ecoTimeoutMin": 30, "heatSilenceMin": 2, "idleSilenceMin": 8, "noDrawMin": 3, "tankLowPct": 85,
        },
    },
    "elizabeth": {
        "label": "Lelit Elizabeth (unverified)",
        "verified": False,
        # From published specs, not measured: vibratory pump (tens of watts),
        # ~800 W brew and ~1.2 kW steam heaters. Pump + heater can't be told from
        # heater alone, so pumpHeaterMinW is set out of reach and shots are found
        # from pump-alone readings only. Capture a session with debug logging on.
        "thresholds": {
            "idleMaxW": 20, "pumpMinW": 30, "pumpMaxW": 120, "steamMinW": 1000, "steamMaxW": 1300,
            "brewMinW": 650, "brewMaxW": 950, "pumpHeaterMinW": 99999, "heaterMinW": 600,
            "ecoTimeoutMin": 30, "heatSilenceMin": 2, "idleSilenceMin": 8, "noDrawMin": 3, "tankLowPct": 85,
        },
    },
}

_BANDS = (("pumpMinW", "pumpMaxW"), ("steamMinW", "steamMaxW"), ("brewMinW", "brewMaxW"))


def preset_menu():
    return [(key, p["label"]) for key, p in PRESETS.items()] + [("custom", "Custom")]


def preset_thresholds(key):
    return {k: float(v) for k, v in PRESETS[key]["thresholds"].items()}


def thresholds_from_props(props):
    out, bad = {}, []
    for key in THRESHOLD_KEYS:
        try:
            out[key] = float(props[key])
        except (KeyError, TypeError, ValueError):
            bad.append(key)
    if bad:
        raise ValueError("missing or non-numeric: " + ", ".join(bad))
    return out


def validate_props(props):
    errors = {}
    values = {}
    for key in THRESHOLD_KEYS:
        try:
            values[key] = float(props.get(key, ""))
            if values[key] < 0:
                errors[key] = "Must be zero or more"
        except (TypeError, ValueError):
            errors[key] = "Enter a number"
    for lo, hi in _BANDS:
        if lo in values and hi in values and values[lo] >= values[hi]:
            errors[lo] = "Must be below " + hi
    if "tankLowPct" in values and not 1 <= values["tankLowPct"] <= 100:
        errors["tankLowPct"] = "Enter 1-100"
    return errors
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_profiles.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "feat: machine presets and threshold validation"
```

---

### Task 3: Detector core — classification, heat-up, ready, no-draw, off

**Files:**
- Create: `Espresso Monitor.indigoPlugin/Contents/Server Plugin/detector.py`
- Test: `tests/test_detector_basic.py`

**Interfaces:**
- Consumes: `profiles.preset_thresholds("biancaV3")`.
- Produces (used by Tasks 4, 5, 6, 8):
  - `Detector(thresholds: dict, saved: dict | None = None, tz=None)`
  - `.reading(t: float, watts: float, plug_on: bool | None = None) -> list[dict]`
  - `.tick(t: float) -> list[dict]`
  - `.classify(watts: float) -> str` — one of `IDLE PUMP PUMPHEAT STEAM BREW OTHER`
  - `.current_status(t: float) -> str` — `off heating ready brewing steaming backflushing eco tankEmpty noDraw`
  - attributes `status`, `last_heat_up_seconds`, `ready_since`
  - events are dicts `{"type": <event id>, "t": float, ...}`; event ids: `machineReady shotFinished steamFinished backflushFinished ecoEntered tankEmpty tankLow tankRefilled`

Task 3 writes the **whole** `detector.py` (it is one state machine; splitting it across tasks would leave half-wired methods). Tasks 4 and 5 add tests that exercise the shot/steam/backflush and eco/tank parts and fix whatever those tests expose.

- [ ] **Step 1: Write the failing tests**

```python
import profiles
from detector import Detector

BIANCA = profiles.preset_thresholds("biancaV3")
T0 = 1_790_000_000.0


def feed(det, samples, tick_every=10):
    """samples: list of (offset_s, watts, plug_on). Ticks between readings like the plugin."""
    events = []
    last = None
    for off, w, plug in samples:
        t = T0 + off
        if last is not None:
            k = last + tick_every
            while k < t:
                events += det.tick(k)
                k += tick_every
        events += det.reading(t, w, plug)
        last = t
    return events


def types(events):
    return [e["type"] for e in events]


def test_classify_bianca():
    d = Detector(BIANCA)
    assert d.classify(1.6) == "idle"
    assert d.classify(230) == "pump"
    assert d.classify(1260) == "steam"
    assert d.classify(1420) == "brew"
    assert d.classify(1600) == "pumpHeat"
    assert d.classify(700) == "other"


def cold_start(minutes_heating=14.5):
    """Switch-on, continuous ~1.4 kW, then keep-warm 5 s bursts every 40 s."""
    s = [(0, 1.7, True)]
    t = 3
    while t < minutes_heating * 60:
        s.append((t, 1400 + (t % 7), True))
        t += 3
    s.append((t, 1.6, True))
    end = t
    for k in range(12):
        b = end + 40 * (k + 1)
        s += [(b, 1380, True), (b + 3, 1390, True), (b + 6, 1.5, True)]
    return s, end


def test_cold_start_goes_ready_after_settle_and_records_heat_up():
    det = Detector(BIANCA)
    samples, end = cold_start()
    ev = feed(det, samples)
    ready = [e for e in ev if e["type"] == "machineReady"]
    assert len(ready) == 1
    assert abs(det.last_heat_up_seconds - end) < 4
    assert ready[0]["t"] >= T0 + end + 90
    assert det.status == "ready"


def test_warm_switch_on_is_ready_after_90s_of_short_bursts():
    det = Detector(BIANCA)
    s = [(0, 1.5, True)]
    for k in range(6):
        s += [(5 + 30 * k, 1390, True), (8 + 30 * k, 1.5, True)]
    ev = feed(det, s)
    assert "machineReady" in types(ev)


def test_no_draw_after_switch_on_is_reported_as_tank_empty():
    det = Detector(BIANCA)
    ev = feed(det, [(0, 1.7, True), (400, 1.7, True)])
    empty = [e for e in ev if e["type"] == "tankEmpty"]
    assert len(empty) == 1 and empty[0]["reason"] == "noDraw"
    assert det.status == "noDraw"
    assert 180 <= empty[0]["t"] - T0 < 200


def test_draw_after_no_draw_means_refilled_and_heating():
    det = Detector(BIANCA)
    ev = feed(det, [(0, 1.7, True), (400, 1.7, True), (410, 1153, True), (413, 1420, True)])
    assert "tankRefilled" in types(ev)
    assert det.status == "heating"


def test_plug_off_goes_off():
    det = Detector(BIANCA)
    samples, end = cold_start()
    feed(det, samples + [(end + 600, 1.5, False)])
    assert det.status == "off"


def test_held_high_reading_is_not_silence():
    det = Detector(BIANCA)
    samples, end = cold_start()
    feed(det, samples)
    # a heater reading then no reports for 10 min: the plug is holding a high value
    ev = det.reading(T0 + end + 700, 1400, True)
    for k in range(60):
        ev += det.tick(T0 + end + 700 + 10 * k)
    assert "tankEmpty" not in types(ev)


def test_no_plug_state_starts_on_draw_and_goes_off_after_45_min():
    det = Detector(BIANCA)
    s = [(0, 1.5, None)]
    t = 3
    while t < 600:
        s.append((t, 1400, None))
        t += 3
    s.append((t, 1.5, None))
    ev = feed(det, s)
    assert det.status in ("heating", "ready")
    for k in range(400):
        ev += det.tick(T0 + t + 10 * k)
    assert det.status == "off"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_detector_basic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'detector'`.

- [ ] **Step 3: Implement detector.py (complete)**

```python
"""Espresso machine activity detector.

Pure Python, no Indigo import, so recorded power data can be replayed in tests.
Feed ``reading()`` whenever the power plug reports and call ``tick()`` about
every 10 s: the plug only reports when the value changes, so silence (eco mode,
an empty tank) is visible only to the clock.
"""
import datetime as dt
import statistics

# Timing constants (seconds), measured on a Lelit Bianca V3 in 2026-09.
PUMP_GAP_S = 10            # pump readings closer than this are one run
SAMPLE_S = 3               # the plug's reporting interval, added to run lengths
MIN_RUN_READINGS = 3       # a shot has at least this many pump readings...
MIN_RUN_S = 12             # ...and lasts at least this long
STARTUP_FILL_S = 90        # pump runs this soon after switch-on fill the steam boiler
STEAM_WINDOW_S = 180       # steaming counts if it happens within this after a shot
STEAM_MIN_S = 20
BACKFLUSH_WINDOW_S = 360   # pump runs this close together may be one backflush
BACKFLUSH_MIN_RUNS = 3
BURST_MAX_S = 15           # heater runs up to this long are keep-warm bursts
READY_SETTLE_S = 90        # this long with only keep-warm bursts => ready
HOLD_CAP_S = 5             # sample-and-hold cap per reading
OFF_SILENCE_S = 45 * 60    # without plug state: idle this long => off
ECO_MARGIN_S = 3 * 60      # eco silence may start this long before the timeout
ECO_SILENCE_S = 3 * 60

IDLE, PUMP, PUMPHEAT, STEAM, BREW, OTHER = "idle", "pump", "pumpHeat", "steam", "brew", "other"

STATUS_TEXT = {
    "off": "Off",
    "heating": "Heating",
    "ready": "Ready",
    "brewing": "Brewing",
    "steaming": "Steaming",
    "backflushing": "Backflushing",
    "eco": "Eco (asleep)",
    "tankEmpty": "Tank empty",
    "noDraw": "No draw - tank empty or machine switched off",
}

_TRANSIENT = ("brewing", "steaming", "backflushing")


class Detector:
    def __init__(self, thresholds, saved=None, tz=None):
        self.th = {k: float(v) for k, v in thresholds.items()}
        self.tz = tz
        s = saved or {}
        status = s.get("status", "off")
        self.status = "ready" if status in _TRANSIENT else status
        self.plug_on = s.get("plugOn")
        self.heat_start = s.get("heatStart")
        self.last_user_activity = s.get("lastUserActivity")
        self.day = s.get("day")
        self.shots_today = int(s.get("shotsToday", 0))
        self.shots_total = int(s.get("shotsTotal", 0))
        self.steams_today = int(s.get("steamsToday", 0))
        self.last_shot_seconds = s.get("lastShotSeconds")
        self.last_shot_time = s.get("lastShotTime")
        self.last_heat_up_seconds = s.get("lastHeatUpSeconds")
        self.ready_since = s.get("readySince")
        self.last_backflush = s.get("lastBackflush")
        self.pump_seconds = float(s.get("pumpSeconds", 0.0))
        self.tank_history = [float(x) for x in s.get("tankHistory", [])]
        self.tank_low_fired = bool(s.get("tankLowFired", False))
        # Transient state, rebuilt from readings.
        self.suspended = saved is not None      # no silence rules until the first reading
        self.last_t = None
        self.last_watts = 0.0
        self.last_active_t = None
        self.any_draw = False
        self.run_start = None                   # current heater run (>= heaterMinW)
        self.ready_candidate = self.heat_start if self.status == "heating" else None
        self.ep = None                          # current pump episode {start, last, n}
        self.pending = []                       # closed pump runs awaiting classification
        self.steam_window_end = None
        self.steam_acc = 0.0
        self.steam_confirmed = False

    # ---- public -----------------------------------------------------------
    def classify(self, watts):
        th = self.th
        if watts <= th["idleMaxW"]:
            return IDLE
        if th["pumpMinW"] <= watts <= th["pumpMaxW"]:
            return PUMP
        if watts >= th["pumpHeaterMinW"]:
            return PUMPHEAT
        if th["steamMinW"] <= watts < th["steamMaxW"]:
            return STEAM
        if th["brewMinW"] <= watts < th["brewMaxW"]:
            return BREW
        return OTHER

    def reading(self, t, watts, plug_on=None):
        events = self._advance(t)
        if plug_on is not None and plug_on != self.plug_on:
            events += self._plug_changed(t, plug_on)
        if self.last_t is not None:
            self._hold(self.last_watts, self.last_t, t)
        self.suspended = False
        if watts > self.th["idleMaxW"]:
            events += self._on_draw(t, watts)
        self._track_heater(t, watts)
        cls = self.classify(watts)
        if cls in (PUMP, PUMPHEAT) and self.status not in ("off",):
            if self.ep and t - self.ep["last"] <= PUMP_GAP_S:
                self.ep["last"] = t
                self.ep["n"] += 1
            else:
                self.ep = {"start": t, "last": t, "n": 1}
        self.last_t, self.last_watts = t, watts
        return events

    def tick(self, t):
        return self._advance(t)

    def mark_refilled(self, t):
        self.pump_seconds = 0.0
        self.tank_low_fired = False
        if self.status in ("tankEmpty", "noDraw"):
            self._start_heating(t, user=True)
        return [{"type": "tankRefilled", "t": t, "manual": True}]

    def reset_counters(self):
        self.shots_today = self.shots_total = self.steams_today = 0

    def tank_percent_used(self):
        if not self.tank_history:
            return None
        return round(100 * self.pump_seconds / statistics.median(self.tank_history))

    def tank_learned_seconds(self):
        return round(statistics.median(self.tank_history)) if self.tank_history else None

    def current_status(self, t):
        if self.status in ("ready", "heating", "eco"):
            if self.ep and self.ep["n"] >= 2 and t - self.ep["last"] <= PUMP_GAP_S:
                return "brewing"
            if len(self.pending) >= 2:
                return "backflushing"
            if self.steam_window_end and t <= self.steam_window_end and self.classify(self.last_watts) == STEAM:
                return "steaming"
        return self.status

    def snapshot(self):
        return {
            "status": self.status, "plugOn": self.plug_on, "heatStart": self.heat_start,
            "lastUserActivity": self.last_user_activity, "day": self.day,
            "shotsToday": self.shots_today, "shotsTotal": self.shots_total, "steamsToday": self.steams_today,
            "lastShotSeconds": self.last_shot_seconds, "lastShotTime": self.last_shot_time,
            "lastHeatUpSeconds": self.last_heat_up_seconds, "readySince": self.ready_since,
            "lastBackflush": self.last_backflush, "pumpSeconds": self.pump_seconds,
            "tankHistory": self.tank_history, "tankLowFired": self.tank_low_fired,
        }

    # ---- internals --------------------------------------------------------
    def _local_date(self, t):
        return dt.datetime.fromtimestamp(t, self.tz).date().isoformat()

    def _start_heating(self, t, user):
        self.status = "heating"
        self.heat_start = t
        self.ready_candidate = t
        self.any_draw = False
        self.last_active_t = None
        if user:
            self.last_user_activity = t

    def _plug_changed(self, t, on):
        events = []
        self.plug_on = on
        if on:
            self._start_heating(t, user=True)
        else:
            events += self._resolve_pending(force_shots=True)
            self.status = "off"
            self.ep = None
            self.run_start = None
            self.steam_window_end = None
        return events

    def _hold(self, watts, t0, t1):
        if self.steam_window_end and t0 <= self.steam_window_end and self.classify(watts) == STEAM:
            self.steam_acc += min(t1 - t0, HOLD_CAP_S)

    def _on_draw(self, t, watts):
        events = []
        self.last_active_t = t
        if self.status == "off" and self.plug_on is None:
            self._start_heating(t, user=True)
            self.last_active_t = t
        if self.status in ("tankEmpty", "noDraw") and watts >= self.th["pumpMinW"]:
            events.append({"type": "tankRefilled", "t": t, "manual": False})
            self.pump_seconds = 0.0
            self.tank_low_fired = False
            self._start_heating(t, user=True)
            self.last_active_t = t
        if self.status == "heating":
            self.any_draw = True
        return events

    def _track_heater(self, t, watts):
        if watts >= self.th["heaterMinW"]:
            if self.run_start is None:
                self.run_start = t
            if t - self.run_start > BURST_MAX_S:
                if self.status == "eco":
                    self._start_heating(self.run_start, user=True)
                    self.any_draw = True
                    self.last_active_t = t
                if self.status == "heating":
                    self.ready_candidate = None
        elif self.run_start is not None:
            if t - self.run_start > BURST_MAX_S and self.status == "heating":
                self.ready_candidate = t
            self.run_start = None

    def _advance(self, t):
        events = []
        day = self._local_date(t)
        if self.day != day:
            if self.day is not None:
                self.shots_today = 0
                self.steams_today = 0
            self.day = day
        if self.ep and t - self.ep["last"] > PUMP_GAP_S:
            events += self._close_episode()
        events += self._advance_steam(t)
        if self.pending and t - self.pending[-1]["end"] >= BACKFLUSH_WINDOW_S:
            events += self._resolve_pending(force_shots=False)
        events += self._advance_status(t)
        return events

    def _advance_steam(self, t):
        events = []
        if self.steam_window_end is None:
            return events
        if not self.steam_confirmed and self.steam_acc >= STEAM_MIN_S:
            self.steam_confirmed = True
            events += self._resolve_pending(force_shots=True)
        if t > self.steam_window_end:
            if self.steam_confirmed:
                self.steams_today += 1
                self.last_user_activity = self.steam_window_end
                events.append({"type": "steamFinished", "t": t})
            self.steam_window_end = None
            self.steam_acc = 0.0
            self.steam_confirmed = False
        return events

    def _close_episode(self):
        ep, self.ep = self.ep, None
        events = []
        seconds = ep["last"] - ep["start"] + SAMPLE_S
        if ep["n"] >= 2:
            self.pump_seconds += seconds
            events += self._check_tank_low(ep["last"])
        if ep["n"] < MIN_RUN_READINGS or seconds < MIN_RUN_S:
            return events
        switched_on_just_now = (
            self.heat_start is not None
            and ep["start"] - self.heat_start < STARTUP_FILL_S
            and self.last_user_activity == self.heat_start
        )
        if switched_on_just_now:
            return events
        end = ep["last"] + SAMPLE_S
        self.pending.append({"start": ep["start"], "end": end, "seconds": seconds})
        self.last_user_activity = end
        self.steam_window_end = end + STEAM_WINDOW_S
        self.steam_acc = 0.0
        self.steam_confirmed = False
        return events

    def _resolve_pending(self, force_shots):
        runs, self.pending = self.pending, []
        if not runs:
            return []
        if not force_shots and len(runs) >= BACKFLUSH_MIN_RUNS:
            self.last_backflush = runs[-1]["end"]
            return [{"type": "backflushFinished", "t": runs[-1]["end"], "runs": len(runs)}]
        events = []
        for run in runs:
            self.shots_today += 1
            self.shots_total += 1
            self.last_shot_seconds = round(run["seconds"])
            self.last_shot_time = run["start"]
            events.append({"type": "shotFinished", "t": run["end"], "start": run["start"],
                           "seconds": round(run["seconds"])})
        return events

    def _check_tank_low(self, t):
        if not self.tank_history or self.tank_low_fired:
            return []
        if self.pump_seconds >= self.th["tankLowPct"] / 100 * statistics.median(self.tank_history):
            self.tank_low_fired = True
            return [{"type": "tankLow", "t": t, "percent": self.tank_percent_used()}]
        return []

    def _tank_empty(self, t, reason):
        self.status = "noDraw" if reason == "noDraw" else "tankEmpty"
        if reason != "noDraw" and self.pump_seconds > 0:
            self.tank_history = (self.tank_history + [self.pump_seconds])[-3:]
        return [{"type": "tankEmpty", "t": t, "reason": reason}]

    def _advance_status(self, t):
        if self.suspended or self.status == "off":
            return []
        events = []
        th = self.th
        heater_long = self.run_start is not None and t - self.run_start > BURST_MAX_S
        if self.status == "heating" and self.ready_candidate is not None and self.any_draw \
                and not heater_long and t - self.ready_candidate >= READY_SETTLE_S:
            self.status = "ready"
            self.ready_since = t
            self.last_heat_up_seconds = round(self.ready_candidate - self.heat_start)
            events.append({"type": "machineReady", "t": t, "heatUpSeconds": self.last_heat_up_seconds})
        silent = self.last_watts <= th["idleMaxW"]
        if self.status == "heating":
            if not self.any_draw and self.heat_start is not None and t - self.heat_start >= th["noDrawMin"] * 60:
                events += self._tank_empty(t, "noDraw")
            elif self.any_draw and silent and self.last_active_t is not None \
                    and t - self.last_active_t >= th["heatSilenceMin"] * 60:
                events += self._tank_empty(t, "silence")
        elif self.status == "ready" and silent and self.last_active_t is not None:
            silence = t - self.last_active_t
            since_user = self.last_active_t - (self.last_user_activity or self.last_active_t)
            if since_user >= th["ecoTimeoutMin"] * 60 - ECO_MARGIN_S and silence >= ECO_SILENCE_S:
                self.status = "eco"
                events.append({"type": "ecoEntered", "t": t})
            elif silence >= th["idleSilenceMin"] * 60:
                events += self._tank_empty(t, "silence")
        if self.plug_on is None and self.status in ("ready", "eco", "tankEmpty", "noDraw") \
                and self.last_active_t is not None and silent and t - self.last_active_t >= OFF_SILENCE_S:
            self.status = "off"
        return events
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_detector_basic.py -q`
Expected: 8 passed. If one fails, fix `detector.py` (not the test) unless the test contradicts the spec's evidence table; record any rule change in the commit message.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "feat: detector core — heat-up, ready, no-draw, off"
```

---

### Task 4: Shots, steaming and backflush

**Files:**
- Modify: `Espresso Monitor.indigoPlugin/Contents/Server Plugin/detector.py` (only if the tests expose bugs)
- Test: `tests/test_detector_shots.py`

**Interfaces:**
- Consumes: `Detector`, `feed`/`cold_start` helpers — copy them into this test file (tests must not import each other).
- Produces: confirmed behaviour of `shotFinished {start, seconds}`, `steamFinished`, `backflushFinished {runs}`.

- [ ] **Step 1: Write the tests**

```python
import profiles
from detector import Detector

BIANCA = profiles.preset_thresholds("biancaV3")
T0 = 1_790_000_000.0


def feed(det, samples, tick_every=10, start_tick=None):
    events, last = [], start_tick
    for off, w, plug in samples:
        t = T0 + off
        if last is not None:
            k = last + tick_every
            while k < t:
                events += det.tick(k)
                k += tick_every
        events += det.reading(t, w, plug)
        last = t
    return events


def ready_machine():
    det = Detector(BIANCA)
    s = [(0, 1.5, True)]
    for k in range(6):
        s += [(5 + 30 * k, 1390, True), (8 + 30 * k, 1.5, True)]
    feed(det, s)
    assert det.status == "ready"
    return det


def shot(at, seconds=30):
    """Pump start ~230 W, pump + heater ~1.57 kW, pump alone at the end."""
    s = [(at, 233, True)]
    t = at + 3
    while t < at + seconds - 6:
        s.append((t, 1565, True))
        t += 3
    s += [(t, 238, True), (t + 3, 240, True), (t + 6, 1.6, True)]
    return s


def steam(at, seconds=50):
    s, t = [], at
    while t < at + seconds:
        s.append((t, 1265, True))
        t += 3
    s.append((t, 1.6, True))
    return s


def idle_until(at, until):
    return [(t, 1.5, True) for t in range(int(at), int(until), 60)]


def types(ev):
    return [e["type"] for e in ev]


def test_shot_then_steam_confirms_shot_quickly_and_counts_steam():
    det = ready_machine()
    ev = feed(det, shot(1000) + steam(1045) + idle_until(1100, 1400))
    shots = [e for e in ev if e["type"] == "shotFinished"]
    assert len(shots) == 1
    assert 24 <= shots[0]["seconds"] <= 36
    assert shots[0]["t"] - T0 < 1045 + 60          # confirmed by the steam, not after 6 min
    assert types(ev).count("steamFinished") == 1
    assert det.shots_today == 1 and det.steams_today == 1


def test_espresso_only_is_confirmed_after_backflush_window():
    det = ready_machine()
    ev = feed(det, shot(1000) + idle_until(1060, 1500))
    shots = [e for e in ev if e["type"] == "shotFinished"]
    assert len(shots) == 1
    assert shots[0]["t"] - T0 < 1100
    assert "steamFinished" not in types(ev)


def test_two_shots_close_together_are_two_shots():
    det = ready_machine()
    ev = feed(det, shot(1000) + idle_until(1040, 1120) + shot(1120) + idle_until(1160, 1700))
    assert types(ev).count("shotFinished") == 2
    assert "backflushFinished" not in types(ev)


def test_backflush_runs_count_as_one_backflush_and_no_shots():
    det = ready_machine()
    s = []
    at = 1000
    for _ in range(5):
        s += shot(at, seconds=20) + idle_until(at + 25, at + 60)
        at += 60
    ev = feed(det, s + idle_until(at, at + 600))
    assert types(ev).count("backflushFinished") == 1
    assert "shotFinished" not in types(ev)
    assert det.shots_today == 0
    assert det.last_backflush is not None


def test_single_pump_band_readings_are_not_shots():
    det = ready_machine()
    s = []
    for k in range(20):   # keep-warm bursts with a partial-sample 300 W reading each
        b = 1000 + 40 * k
        s += [(b, 300, True), (b + 3, 1390, True), (b + 6, 1.5, True)]
    ev = feed(det, s + idle_until(1900, 2400))
    assert "shotFinished" not in types(ev)


def test_pump_run_right_after_switch_on_is_boiler_fill_not_shot():
    det = Detector(BIANCA)
    s = [(0, 1.7, True)] + shot(6, seconds=35)
    t = 45
    while t < 600:
        s.append((t, 1400, True))
        t += 3
    ev = feed(det, s + [(t, 1.5, True)] + idle_until(t + 10, t + 500))
    assert "shotFinished" not in types(ev)


def test_status_shows_brewing_during_a_shot():
    det = ready_machine()
    feed(det, shot(1000)[:5])
    assert det.current_status(T0 + 1012) == "brewing"
```

- [ ] **Step 2: Run**

Run: `python3 -m pytest tests/test_detector_shots.py -q`
Expected: 7 passed. For any failure, read the event list (`print(ev)`), fix the rule in `detector.py`, re-run the whole suite (`python3 -m pytest -q`) so Task 3 stays green.

- [ ] **Step 3: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "test: shots, steaming and backflush rules"
```

---

### Task 5: Eco, empty tank, refill, tank learning, persistence, midnight

**Files:**
- Modify: `detector.py` (only if tests expose bugs)
- Test: `tests/test_detector_tank.py`

**Interfaces:**
- Consumes: `Detector.snapshot()`, `Detector(thresholds, saved=...)`, `mark_refilled`, `tank_percent_used`, `tank_learned_seconds`, `reset_counters`.

- [ ] **Step 1: Write the tests**

```python
import datetime as dt
from zoneinfo import ZoneInfo

import profiles
from detector import Detector

BIANCA = profiles.preset_thresholds("biancaV3")
T0 = 1_790_000_000.0
LONDON = ZoneInfo("Europe/London")


def feed(det, samples, tick_every=10):
    events, last = [], None
    for off, w, plug in samples:
        t = T0 + off
        if last is not None:
            k = last + tick_every
            while k < t:
                events += det.tick(k)
                k += tick_every
        events += det.reading(t, w, plug)
        last = t
    return events


def ticks(det, start, seconds):
    ev = []
    for k in range(0, int(seconds), 10):
        ev += det.tick(T0 + start + k)
    return ev


def types(ev):
    return [e["type"] for e in ev]


def warm_on(det, at=0):
    s = [(at, 1.5, True)]
    for k in range(6):
        s += [(at + 5 + 30 * k, 1390, True), (at + 8 + 30 * k, 1.5, True)]
    return feed(det, s)


def pump(at, seconds):
    s = [(at + k, 233, True) for k in range(0, seconds, 3)]
    return s + [(at + seconds, 1.5, True)]


def test_silence_near_eco_timeout_is_eco_not_empty():
    det = Detector(BIANCA)
    warm_on(det)
    # keep-warm bursts until 29 min after switch-on, then silence
    s = []
    for k in range(200, 29 * 60, 40):
        s += [(k, 1390, True), (k + 3, 1.5, True)]
    ev = feed(det, s)
    ev += ticks(det, 29 * 60, 20 * 60)
    assert "ecoEntered" in types(ev)
    assert "tankEmpty" not in types(ev)
    assert det.status == "eco"


def test_silence_soon_after_a_shot_is_empty_tank():
    det = Detector(BIANCA)
    warm_on(det)
    ev = feed(det, pump(400, 30))
    ev += ticks(det, 431, 10 * 60)
    empty = [e for e in ev if e["type"] == "tankEmpty"]
    assert len(empty) == 1 and empty[0]["reason"] == "silence"
    assert 431 + 8 * 60 <= empty[0]["t"] - T0 <= 431 + 8 * 60 + 20


def test_waking_from_eco_heats_then_ready():
    det = Detector(BIANCA)
    warm_on(det)
    det.status = "eco"
    s = [(5000 + k, 1400, True) for k in range(0, 60, 3)] + [(5060, 1.5, True)]
    for k in range(5100, 5300, 40):
        s += [(k, 1390, True), (k + 3, 1.5, True)]
    ev = feed(det, s)
    assert det.status == "ready"
    assert "machineReady" in types(ev)


def test_auto_empty_records_tankful_and_refill_resets():
    det = Detector(BIANCA)
    warm_on(det)
    feed(det, pump(400, 30))
    ticks(det, 431, 10 * 60)
    assert det.status == "tankEmpty"
    assert len(det.tank_history) == 1 and det.tank_history[0] >= 30
    ev = feed(det, [(1100, 230, True), (1103, 1400, True)])
    assert "tankRefilled" in types(ev)
    assert det.pump_seconds == 0 and det.status == "heating"


def test_manual_refill_resets_count_but_does_not_record_tankful():
    det = Detector(BIANCA)
    det.tank_history = [300.0]
    det.pump_seconds = 120.0
    ev = det.mark_refilled(T0)
    assert types(ev) == ["tankRefilled"] and ev[0]["manual"] is True
    assert det.pump_seconds == 0 and det.tank_history == [300.0]


def test_tank_low_fires_once_at_85_percent():
    det = Detector(BIANCA)
    warm_on(det)
    det.tank_history = [100.0]
    ev = []
    at = 400
    for _ in range(4):                 # 4 x 30 s pump = 120 s > 85
        ev += feed(det, pump(at, 30))
        at += 60
    ev += ticks(det, at, 30)
    assert types(ev).count("tankLow") == 1
    assert det.tank_percent_used() >= 85


def test_tank_low_silent_until_a_tankful_is_learned():
    det = Detector(BIANCA)
    warm_on(det)
    ev = feed(det, pump(400, 30) + pump(500, 30))
    assert "tankLow" not in types(ev)
    assert det.tank_percent_used() is None


def test_snapshot_round_trip_keeps_counters_and_tank():
    det = Detector(BIANCA)
    det.shots_total, det.pump_seconds, det.tank_history = 7, 42.0, [300.0]
    det.status = "ready"
    again = Detector(BIANCA, saved=det.snapshot())
    assert again.shots_total == 7 and again.pump_seconds == 42.0 and again.tank_history == [300.0]
    assert again.status == "ready"


def test_restore_suspends_silence_until_first_reading():
    det = Detector(BIANCA)
    warm_on(det)
    saved = det.snapshot()
    again = Detector(BIANCA, saved=saved)
    ev = []
    for k in range(0, 3600, 10):       # an hour of ticks with no readings after restart
        ev += again.tick(T0 + 1000 + k)
    assert "tankEmpty" not in types(ev) and "ecoEntered" not in types(ev)


def test_midnight_reset_across_dst():
    # 2026-10-25 is the UK clock change (01:00 BST -> 01:00 GMT)
    det = Detector(BIANCA, tz=LONDON)
    before = dt.datetime(2026, 10, 24, 23, 30, tzinfo=LONDON).timestamp()
    det.tick(before)
    det.shots_today, det.steams_today = 3, 2
    det.tick(before + 45 * 60)          # 00:15 on the 25th
    assert det.shots_today == 0 and det.steams_today == 0
    det.shots_today = 1
    det.tick(dt.datetime(2026, 10, 25, 23, 59, tzinfo=LONDON).timestamp())
    assert det.shots_today == 1         # same local day despite the 25-hour day


def test_reset_counters():
    det = Detector(BIANCA)
    det.shots_today, det.shots_total, det.steams_today = 1, 2, 3
    det.reset_counters()
    assert (det.shots_today, det.shots_total, det.steams_today) == (0, 0, 0)
```

- [ ] **Step 2: Run**

Run: `python3 -m pytest tests/test_detector_tank.py -q`
Expected: 11 passed; fix `detector.py` for any failure and re-run the full suite.

- [ ] **Step 3: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "test: eco, empty tank, refill, tank learning, persistence, midnight"
```

---

### Task 6: Replay real Bianca data

**Files:**
- Create: `tools/make_fixture.py`, `tests/replay.py`, `tests/fixtures/*.csv`, `tests/fixtures/sep14-27.csv.gz`, `tests/test_replay.py`
- Modify: `detector.py` / `profiles.py` only if replay shows a rule is wrong (record why in the commit).

**Interfaces:**
- Produces: `replay.load(name) -> list[tuple[float, float | None, bool | None]]`; `replay.run(det, rows, tick_every=10) -> list[dict]`.

- [ ] **Step 1: Export the SQL Logger history on jarvis**

```bash
export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.orbstack/bin
cd ~/ClarkCastle/jarvis-infra && docker compose exec -T postgres sh -c \
 'psql -U "$POSTGRES_USER" -d indigo_history -At -F"," -c "select extract(epoch from ts), onoffstate, curenergylevel from device_history_1794293937 where ts >= '"'"'2026-09-01'"'"' order by ts"' \
 > /tmp/coffee_export.csv
wc -l /tmp/coffee_export.csv
```
Expected: roughly 70,000+ lines of `epoch,t|f|,watts|`.

- [ ] **Step 2: Write tools/make_fixture.py**

```python
"""Cut a replay fixture from a SQL Logger export.

Usage: python3 tools/make_fixture.py EXPORT.csv "2026-09-27 07:59" "2026-09-27 10:30" OUT.csv[.gz]
Times are Europe/London. Output rows: epoch,watts,plug where watts/plug may be empty.
"""
import csv
import datetime as dt
import gzip
import sys
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def main(src, start, end, out):
    t0 = dt.datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=LONDON).timestamp()
    t1 = dt.datetime.strptime(end, "%Y-%m-%d %H:%M").replace(tzinfo=LONDON).timestamp()
    opener = gzip.open if out.endswith(".gz") else open
    kept = 0
    with open(src, newline="") as fin, opener(out, "wt", newline="") as fout:
        writer = csv.writer(fout)
        for row in csv.reader(fin):
            if len(row) != 3:
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue
            if not t0 <= t < t1 or (row[1] == "" and row[2] == ""):
                continue
            writer.writerow([f"{t:.3f}", row[2], row[1]])
            kept += 1
    print(f"{out}: {kept} rows")


if __name__ == "__main__":
    main(*sys.argv[1:5])
```

- [ ] **Step 3: Cut the fixtures**

```bash
cd ~/indigo-espresso
E=/tmp/coffee_export.csv
python3 tools/make_fixture.py $E "2026-09-27 07:59" "2026-09-27 10:30" tests/fixtures/sep27-steamoff-morning.csv
python3 tools/make_fixture.py $E "2026-09-25 07:59" "2026-09-25 10:00" tests/fixtures/sep25-morning.csv
python3 tools/make_fixture.py $E "2026-09-26 13:59" "2026-09-26 17:00" tests/fixtures/sep26-backflush.csv
python3 tools/make_fixture.py $E "2026-09-26 08:30" "2026-09-26 11:30" tests/fixtures/sep26-tank-empty.csv
python3 tools/make_fixture.py $E "2026-09-13 07:59" "2026-09-13 08:45" tests/fixtures/sep13-no-draw.csv
python3 tools/make_fixture.py $E "2026-09-14 00:00" "2026-09-28 00:00" tests/fixtures/sep14-27.csv.gz
ls -la tests/fixtures
```

Note: `sep26-tank-empty` starts at 08:30 with the machine already on; the replay driver treats the first plug value as the current state.

- [ ] **Step 4: Write tests/replay.py**

```python
"""Replay recorded plug data through a Detector, ticking like the plugin does."""
import csv
import gzip
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    path = FIXTURES / name
    opener = gzip.open if name.endswith(".gz") else open
    rows = []
    with opener(path, "rt", newline="") as f:
        for t, watts, plug in csv.reader(f):
            rows.append((float(t), float(watts) if watts else None, {"t": True, "f": False}.get(plug)))
    return rows


def run(det, rows, tick_every=10):
    events, last_t, last_w, plug = [], None, 0.0, None
    for t, watts, p in rows:
        if last_t is not None:
            k = last_t + tick_every
            while k < t:
                events += det.tick(k)
                k += tick_every
        if p is not None:
            plug = p
        if watts is not None:
            last_w = watts
        events += det.reading(t, last_w, plug)
        last_t = t
    return events


def of(events, kind):
    return [e for e in events if e["type"] == kind]
```

Note: when a fixture starts mid-session with no plug-on row, pass the first plug value as a change so the detector starts heating; the Sep 26 fixture then settles to ready from keep-warm bursts within minutes.

- [ ] **Step 5: Write tests/test_replay.py**

```python
import datetime as dt
from zoneinfo import ZoneInfo

import profiles
import replay
from detector import Detector

LONDON = ZoneInfo("Europe/London")
BIANCA = profiles.preset_thresholds("biancaV3")


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 9, day, h, m, tzinfo=LONDON).timestamp()


def det():
    return Detector(BIANCA, tz=LONDON)


def test_steam_off_morning_sep27():
    d = det()
    ev = replay.run(d, replay.load("sep27-steamoff-morning.csv"))
    ready = replay.of(ev, "machineReady")
    assert ready and 5 * 60 <= ready[0]["heatUpSeconds"] <= 9 * 60
    shots = replay.of(ev, "shotFinished")
    assert len(shots) == 1
    assert at(27, "09:23") <= shots[0]["start"] <= at(27, "09:25")
    assert 20 <= shots[0]["seconds"] <= 45
    assert len(replay.of(ev, "steamFinished")) == 1
    assert replay.of(ev, "ecoEntered")
    assert not replay.of(ev, "tankEmpty")


def test_both_boilers_morning_sep25():
    d = det()
    ev = replay.run(d, replay.load("sep25-morning.csv"))
    ready = replay.of(ev, "machineReady")
    assert ready and 13 * 60 <= ready[0]["heatUpSeconds"] <= 16 * 60
    shots = replay.of(ev, "shotFinished")
    assert len(shots) == 1 and at(25, "08:30") <= shots[0]["start"] <= at(25, "08:32")
    assert len(replay.of(ev, "steamFinished")) == 1
    eco = replay.of(ev, "ecoEntered")
    assert eco and at(25, "09:03") <= eco[0]["t"] <= at(25, "09:10")
    assert not replay.of(ev, "tankEmpty")


def test_backflush_sep26():
    d = det()
    ev = replay.run(d, replay.load("sep26-backflush.csv"))
    bf = replay.of(ev, "backflushFinished")
    assert len(bf) == 1 and at(26, "16:20") <= bf[0]["t"] <= at(26, "16:40")
    assert not [s for s in replay.of(ev, "shotFinished") if at(26, "16:20") <= s["start"] <= at(26, "16:40")]


def test_tank_ran_dry_sep26_morning():
    d = det()
    ev = replay.run(d, replay.load("sep26-tank-empty.csv"))
    empty = replay.of(ev, "tankEmpty")
    assert len(empty) == 1 and at(26, "09:38") <= empty[0]["t"] <= at(26, "09:45")
    refill = replay.of(ev, "tankRefilled")
    assert refill and at(26, "10:58") <= refill[0]["t"] <= at(26, "11:00")


def test_no_draw_sep13():
    d = det()
    ev = replay.run(d, replay.load("sep13-no-draw.csv"))
    empty = replay.of(ev, "tankEmpty")
    assert empty and empty[0]["reason"] == "noDraw" and empty[0]["t"] <= at(13, "08:04")
    assert replay.of(ev, "tankRefilled")
    assert replay.of(ev, "machineReady")


def test_two_weeks_no_false_alarms():
    d = det()
    ev = replay.run(d, replay.load("sep14-27.csv.gz"))
    empties = replay.of(ev, "tankEmpty")
    # the only real empty in this fortnight is 26 Sep ~09:32
    assert len(empties) == 1 and at(26, "09:38") <= empties[0]["t"] <= at(26, "09:45")
    per_day = {}
    for s in replay.of(ev, "shotFinished"):
        day = dt.datetime.fromtimestamp(s["start"], LONDON).day
        per_day[day] = per_day.get(day, 0) + 1
    assert all(n <= 5 for n in per_day.values()), per_day
    assert sum(per_day.values()) >= 12, per_day      # at least most mornings found
    assert len(replay.of(ev, "backflushFinished")) == 1
```

- [ ] **Step 6: Run and tune**

Run: `python3 -m pytest tests/test_replay.py -q`
Expected: all pass. Where one fails, print the relevant events and the raw rows around the failure time, decide whether the rule or the expectation is wrong against the spec's evidence table, fix, and re-run the **whole** suite. Do not loosen an assertion without writing the reason in the commit message. The 26 Sep empty tank is confirmed by Simon (he refilled it that morning) — keep that expectation.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "test: replay two weeks of recorded Bianca data"
```

---

### Task 7: Plugin XML

**Files:**
- Create: `Server Plugin/Devices.xml`, `Events.xml`, `Actions.xml`, `MenuItems.xml`, `PluginConfig.xml`
- Modify: `tests/test_xml.py`

**Interfaces:**
- Consumes: `profiles.THRESHOLD_KEYS` (config field ids must match).
- Produces: device type `espressoMachine`; state ids listed below; event ids = detector event types; action ids `markTankRefilled`, `resetCounters`; menu id `markTankRefilledMenu`; callbacks named in Task 8: `powerDeviceMenu`, `presetMenu`, `loadPreset`, `machineMenu`, `markTankRefilledAction`, `resetCountersAction`, `markTankRefilledMenu`.

- [ ] **Step 1: Add failing XML tests**

Append to `tests/test_xml.py`:

```python
import profiles

STATES = ["status", "statusText", "lastHeatUpSeconds", "readySince", "shotsToday", "shotsTotal",
          "lastShotSeconds", "lastShotTime", "steamsToday", "lastBackflush", "daysSinceBackflush",
          "pumpSecondsSinceRefill", "tankPercentUsed", "tankLearnedPumpSeconds", "detectorState"]
EVENTS = ["machineReady", "shotFinished", "steamFinished", "backflushFinished", "ecoEntered",
          "tankEmpty", "tankLow", "tankRefilled"]


def parse(name):
    return ET.parse(SP / name).getroot()


def test_all_xml_parses():
    for name in ("Devices.xml", "Events.xml", "Actions.xml", "MenuItems.xml", "PluginConfig.xml"):
        parse(name)


def test_device_states_and_threshold_fields():
    dev = parse("Devices.xml").find("Device[@id='espressoMachine']")
    states = [s.get("id") for s in dev.find("States")]
    assert states == STATES
    assert all(s.isascii() and s.isalnum() and s[0].isalpha() for s in states)
    fields = {f.get("id") for f in dev.find("ConfigUI")}
    assert set(profiles.THRESHOLD_KEYS) <= fields
    assert {"powerDeviceId", "preset", "loadPresetButton", "debugRaw"} <= fields


def test_events_match_detector_event_types():
    assert [e.get("id") for e in parse("Events.xml")] == EVENTS


def test_actions_and_menu():
    assert [a.get("id") for a in parse("Actions.xml")] == ["markTankRefilled", "resetCounters"]
    assert [m.get("id") for m in parse("MenuItems.xml")] == ["markTankRefilledMenu"]
```

Run: `python3 -m pytest tests/test_xml.py -q` — Expected: FAIL (files missing).

- [ ] **Step 2: Write Devices.xml**

```xml
<?xml version="1.0"?>
<Devices>
    <Device type="custom" id="espressoMachine">
        <Name>Espresso Machine</Name>
        <ConfigUI>
            <Field id="powerDeviceId" type="menu">
                <Label>Power device:</Label>
                <List class="self" method="powerDeviceMenu" dynamicReload="true"/>
            </Field>
            <Field id="powerHelp" type="label" fontSize="small" fontColor="darkgray">
                <Label>The smart plug or meter the machine is plugged into. It must report power (curEnergyLevel).</Label>
            </Field>
            <Field id="sep1" type="separator"/>
            <Field id="preset" type="menu" defaultValue="biancaV3">
                <Label>Machine model:</Label>
                <List class="self" method="presetMenu"/>
            </Field>
            <Field id="loadPresetButton" type="button">
                <Label> </Label>
                <Title>Load preset values</Title>
                <CallbackMethod>loadPreset</CallbackMethod>
            </Field>
            <Field id="presetHelp" type="label" fontSize="small" fontColor="darkgray">
                <Label>Fills the fields below. Unverified presets are estimates from published specs - turn on raw logging and send a session to tune them.</Label>
            </Field>
            <Field id="sep2" type="separator"/>
            <Field id="idleMaxW" type="textfield" defaultValue="20"><Label>Idle at or below (W):</Label></Field>
            <Field id="pumpMinW" type="textfield" defaultValue="150"><Label>Pump alone, from (W):</Label></Field>
            <Field id="pumpMaxW" type="textfield" defaultValue="350"><Label>Pump alone, to (W):</Label></Field>
            <Field id="steamMinW" type="textfield" defaultValue="1150"><Label>Steam heater, from (W):</Label></Field>
            <Field id="steamMaxW" type="textfield" defaultValue="1360"><Label>Steam heater, below (W):</Label></Field>
            <Field id="brewMinW" type="textfield" defaultValue="1360"><Label>Brew heater, from (W):</Label></Field>
            <Field id="brewMaxW" type="textfield" defaultValue="1480"><Label>Brew heater, below (W):</Label></Field>
            <Field id="pumpHeaterMinW" type="textfield" defaultValue="1480"><Label>Pump + heater, from (W):</Label></Field>
            <Field id="heaterMinW" type="textfield" defaultValue="1000"><Label>Any heater on, from (W):</Label></Field>
            <Field id="ecoTimeoutMin" type="textfield" defaultValue="30"><Label>Machine's eco timer (min):</Label></Field>
            <Field id="heatSilenceMin" type="textfield" defaultValue="2"><Label>Empty if silent while heating (min):</Label></Field>
            <Field id="idleSilenceMin" type="textfield" defaultValue="8"><Label>Empty if silent when ready (min):</Label></Field>
            <Field id="noDrawMin" type="textfield" defaultValue="3"><Label>No draw after switch-on (min):</Label></Field>
            <Field id="tankLowPct" type="textfield" defaultValue="85"><Label>Warn at % of a learned tank:</Label></Field>
            <Field id="sep3" type="separator"/>
            <Field id="debugRaw" type="checkbox" defaultValue="false">
                <Label>Log raw readings:</Label>
                <Description>For calibrating a new machine</Description>
            </Field>
        </ConfigUI>
        <States>
            <State id="status"><ValueType>String</ValueType><TriggerLabel>Status</TriggerLabel><ControlPageLabel>Status</ControlPageLabel></State>
            <State id="statusText"><ValueType>String</ValueType><TriggerLabel>Status text</TriggerLabel><ControlPageLabel>Status text</ControlPageLabel></State>
            <State id="lastHeatUpSeconds"><ValueType>Integer</ValueType><TriggerLabel>Last heat-up (s)</TriggerLabel><ControlPageLabel>Last heat-up (s)</ControlPageLabel></State>
            <State id="readySince"><ValueType>String</ValueType><TriggerLabel>Ready since</TriggerLabel><ControlPageLabel>Ready since</ControlPageLabel></State>
            <State id="shotsToday"><ValueType>Integer</ValueType><TriggerLabel>Shots today</TriggerLabel><ControlPageLabel>Shots today</ControlPageLabel></State>
            <State id="shotsTotal"><ValueType>Integer</ValueType><TriggerLabel>Shots total</TriggerLabel><ControlPageLabel>Shots total</ControlPageLabel></State>
            <State id="lastShotSeconds"><ValueType>Integer</ValueType><TriggerLabel>Last shot (s)</TriggerLabel><ControlPageLabel>Last shot (s)</ControlPageLabel></State>
            <State id="lastShotTime"><ValueType>String</ValueType><TriggerLabel>Last shot time</TriggerLabel><ControlPageLabel>Last shot time</ControlPageLabel></State>
            <State id="steamsToday"><ValueType>Integer</ValueType><TriggerLabel>Steams today</TriggerLabel><ControlPageLabel>Steams today</ControlPageLabel></State>
            <State id="lastBackflush"><ValueType>String</ValueType><TriggerLabel>Last backflush</TriggerLabel><ControlPageLabel>Last backflush</ControlPageLabel></State>
            <State id="daysSinceBackflush"><ValueType>Integer</ValueType><TriggerLabel>Days since backflush</TriggerLabel><ControlPageLabel>Days since backflush</ControlPageLabel></State>
            <State id="pumpSecondsSinceRefill"><ValueType>Integer</ValueType><TriggerLabel>Pump seconds since refill</TriggerLabel><ControlPageLabel>Pump seconds since refill</ControlPageLabel></State>
            <State id="tankPercentUsed"><ValueType>Integer</ValueType><TriggerLabel>Tank % used</TriggerLabel><ControlPageLabel>Tank % used</ControlPageLabel></State>
            <State id="tankLearnedPumpSeconds"><ValueType>Integer</ValueType><TriggerLabel>Learned tank (pump s)</TriggerLabel><ControlPageLabel>Learned tank (pump s)</ControlPageLabel></State>
            <State id="detectorState"><ValueType>String</ValueType><TriggerLabel>Detector state (internal)</TriggerLabel><ControlPageLabel>Detector state</ControlPageLabel></State>
        </States>
        <UiDisplayStateId>statusText</UiDisplayStateId>
    </Device>
</Devices>
```

- [ ] **Step 3: Write Events.xml** (same ConfigUI for each of the 8 events)

```xml
<?xml version="1.0"?>
<Events>
    <Event id="machineReady"><Name>Machine ready</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="shotFinished"><Name>Shot finished</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="steamFinished"><Name>Steaming finished</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="backflushFinished"><Name>Backflush finished</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="ecoEntered"><Name>Entered eco</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="tankEmpty"><Name>Tank empty</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="tankLow"><Name>Tank low</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
    <Event id="tankRefilled"><Name>Tank refilled</Name>
        <ConfigUI><Field id="machineId" type="menu" defaultValue="any"><Label>Machine:</Label><List class="self" method="machineMenu"/></Field></ConfigUI></Event>
</Events>
```

- [ ] **Step 4: Write Actions.xml, MenuItems.xml, PluginConfig.xml**

`Actions.xml`:
```xml
<?xml version="1.0"?>
<Actions>
    <Action id="markTankRefilled" deviceFilter="self.espressoMachine">
        <Name>Mark tank refilled</Name>
        <CallbackMethod>markTankRefilledAction</CallbackMethod>
    </Action>
    <Action id="resetCounters" deviceFilter="self.espressoMachine">
        <Name>Reset shot and steam counters</Name>
        <CallbackMethod>resetCountersAction</CallbackMethod>
    </Action>
</Actions>
```

`MenuItems.xml`:
```xml
<?xml version="1.0"?>
<MenuItems>
    <MenuItem id="markTankRefilledMenu">
        <Name>Mark tank refilled...</Name>
        <ButtonTitle>Refilled</ButtonTitle>
        <CallbackMethod>markTankRefilledMenu</CallbackMethod>
        <ConfigUI>
            <Field id="machineId" type="menu">
                <Label>Machine:</Label>
                <List class="indigo.devices" filter="self.espressoMachine"/>
            </Field>
        </ConfigUI>
    </MenuItem>
</MenuItems>
```

`PluginConfig.xml`:
```xml
<?xml version="1.0"?>
<PluginConfig>
    <Field id="showDebugInfo" type="checkbox" defaultValue="false">
        <Label>Debug logging:</Label>
    </Field>
</PluginConfig>
```

- [ ] **Step 5: Run and commit**

Run: `python3 -m pytest tests/test_xml.py -q` — Expected: 5 passed.

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "feat: device, event, action and menu XML"
```

---

### Task 8: plugin.py

**Files:**
- Create: `Espresso Monitor.indigoPlugin/Contents/Server Plugin/plugin.py`
- Test: `tests/test_plugin.py`

**Interfaces:**
- Consumes: `Detector`, `STATUS_TEXT` (detector), `profiles.*`, XML callback names from Task 7.
- Produces: `Plugin` class; helper `Plugin.process_reading(power_dev, now)` and `Plugin.tick_all(now)` so tests can drive it without threads.

- [ ] **Step 1: Write failing tests**

```python
import json

import indigo
from conftest import FakeDevice

import profiles
from plugin import Plugin

PID = "com.simons-plugins.indigo-espresso"
T0 = 1_790_000_000.0


def make_plugin():
    indigo.devices._d.clear()
    indigo.trigger.execute.reset_mock()
    return Plugin(PID, "Espresso Monitor", "2026.0.1", {})


def machine(plugin, power_id=100, dev_id=1):
    props = {k: str(v) for k, v in profiles.preset_thresholds("biancaV3").items()}
    props.update({"powerDeviceId": str(power_id), "preset": "biancaV3", "debugRaw": False})
    dev = indigo.devices.add(FakeDevice(dev_id, "Coffee", pluginId=PID, deviceTypeId="espressoMachine",
                                        pluginProps=props, states={"detectorState": ""}))
    plugin.deviceStartComm(dev)
    return dev


def power(power_id=100, watts=1.5, on=True):
    return indigo.devices.add(FakeDevice(power_id, "Plug", pluginId="other",
                                         states={"curEnergyLevel": watts, "onOffState": on}))


class Trig:
    def __init__(self, id, typ, machine_id="any"):  # noqa: A002
        self.id, self.pluginTypeId, self.pluginProps = id, typ, {"machineId": machine_id}


def test_startup_subscribes_to_device_changes():
    p = make_plugin()
    p.startup()
    assert indigo.devices.subscribed


def test_reading_routes_to_detector_and_writes_status():
    p = make_plugin()
    plug = power(watts=1.5, on=False)
    dev = machine(p)
    new = FakeDevice(100, "Plug", pluginId="other", states={"curEnergyLevel": 1400.0, "onOffState": True})
    p.deviceUpdated(plug, new)
    assert dev.states["status"] == "heating"
    assert json.loads(dev.states["detectorState"])["status"] == "heating"


def test_own_device_updates_are_ignored():
    p = make_plugin()
    dev = machine(p)
    before = len(dev.batches)
    p.deviceUpdated(dev, dev)
    assert len(dev.batches) == before


def test_event_fires_matching_triggers_only():
    p = make_plugin()
    dev = machine(p)
    t_any, t_this, t_other = Trig(1, "tankRefilled"), Trig(2, "tankRefilled", "1"), Trig(3, "tankRefilled", "99")
    for t in (t_any, t_this, t_other):
        p.triggerStartProcessing(t)
    p.markTankRefilledAction(type("A", (), {"deviceId": dev.id})(), dev)
    fired = [c.args[0].id for c in indigo.trigger.execute.call_args_list]
    assert sorted(fired) == [1, 2]


def test_load_preset_fills_threshold_fields():
    p = make_plugin()
    values = p.loadPreset({"preset": "elizabeth", "pumpMinW": "1"}, "espressoMachine", 1)
    assert values["pumpMinW"] == "30" and values["pumpHeaterMinW"] == "99999"


def test_validate_reports_bad_fields():
    p = make_plugin()
    values = {k: "1" for k in profiles.THRESHOLD_KEYS}
    values.update({"powerDeviceId": "", "pumpMinW": "x"})
    ok, _, errors = p.validateDeviceConfigUi(values, "espressoMachine", 1)
    assert not ok and "pumpMinW" in errors and "powerDeviceId" in errors


def test_missing_power_device_warns_once():
    p = make_plugin()
    dev = machine(p, power_id=555)
    p.tick_all(T0)
    p.tick_all(T0 + 10)
    warnings = [c for c in p.logger.warning.call_args_list if "555" in str(c)]
    assert len(warnings) == 1


def test_power_device_menu_lists_metering_devices_only():
    p = make_plugin()
    power(100)
    indigo.devices.add(FakeDevice(200, "Lamp", pluginId="x", states={"onOffState": True}))
    ids = [k for k, _ in p.powerDeviceMenu()]
    assert ids == ["100"]


def test_stop_comm_persists_snapshot():
    p = make_plugin()
    dev = machine(p)
    p.detectors[dev.id].shots_total = 5
    p.deviceStopComm(dev)
    assert json.loads(dev.states["detectorState"])["shotsTotal"] == 5
```

Run: `python3 -m pytest tests/test_plugin.py -q` — Expected: FAIL (`No module named 'plugin'`).

- [ ] **Step 2: Implement plugin.py**

```python
"""Espresso Monitor — Indigo shell around detector.Detector."""
import datetime as dt
import json
import time

import indigo  # pylint: disable=import-error

import profiles
from detector import STATUS_TEXT, Detector

TICK_S = 10


def _fmt(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


class Plugin(indigo.PluginBase):
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs, **kwargs):
        super().__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs, **kwargs)
        self.debug = bool(pluginPrefs.get("showDebugInfo", False))
        self.detectors = {}        # machine dev id -> Detector
        self.power_map = {}        # power dev id -> [machine dev ids]
        self.event_triggers = {}   # trigger id -> trigger
        self.missing_warned = set()

    # ---- lifecycle -------------------------------------------------------
    def startup(self):
        indigo.devices.subscribeToChanges()

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.debug = bool(valuesDict.get("showDebugInfo", False))

    def deviceStartComm(self, dev):
        try:
            thresholds = profiles.thresholds_from_props(dev.pluginProps)
        except ValueError as exc:
            self.logger.error(f"{dev.name}: {exc} - open the device settings and load a preset")
            return
        raw = dev.states.get("detectorState") or ""
        saved = json.loads(raw) if raw else None
        self.detectors[dev.id] = Detector(thresholds, saved=saved)
        power_id = self._power_id(dev)
        if power_id is not None:
            self.power_map.setdefault(power_id, []).append(dev.id)
        dev.stateListOrDisplayStateIdChanged()
        self._write_states(dev, time.time())

    def deviceStopComm(self, dev):
        if dev.id in self.detectors:
            self._write_states(dev, time.time())
            del self.detectors[dev.id]
        for ids in self.power_map.values():
            if dev.id in ids:
                ids.remove(dev.id)

    def deviceUpdated(self, origDev, newDev):
        super().deviceUpdated(origDev, newDev)
        if newDev.pluginId == self.pluginId:
            return
        if newDev.id in self.power_map:
            self.process_reading(newDev, time.time())

    def runConcurrentThread(self):
        try:
            while True:
                self.tick_all(time.time())
                self.sleep(TICK_S)
        except self.StopThread:
            pass

    # ---- readings and ticks ----------------------------------------------
    def process_reading(self, power_dev, now):
        watts = power_dev.states.get("curEnergyLevel")
        if watts is None:
            return
        plug_on = power_dev.states.get("onOffState") if "onOffState" in power_dev.states else None
        for dev_id in list(self.power_map.get(power_dev.id, [])):
            dev = indigo.devices[dev_id]
            if dev.pluginProps.get("debugRaw"):
                self.logger.info(f"raw {dev.name}: t={now:.1f} watts={watts} plug={plug_on}")
            events = self.detectors[dev_id].reading(now, float(watts), plug_on)
            self._apply(dev, events, now)

    def tick_all(self, now):
        for dev_id, det in list(self.detectors.items()):
            if dev_id not in indigo.devices:
                continue
            dev = indigo.devices[dev_id]
            power_id = self._power_id(dev)
            if power_id is None or power_id not in indigo.devices or not indigo.devices[power_id].enabled:
                if dev_id not in self.missing_warned:
                    self.logger.warning(f"{dev.name}: power device {power_id} is missing or disabled")
                    self.missing_warned.add(dev_id)
                continue
            self.missing_warned.discard(dev_id)
            self._apply(dev, det.tick(now), now)

    def _apply(self, dev, events, now):
        for event in events:
            self.logger.info(f"{dev.name}: {event['type']}" +
                             (f" ({event['seconds']} s)" if "seconds" in event else ""))
            self._fire(event["type"], dev.id)
        self._write_states(dev, now)

    def _write_states(self, dev, now):
        det = self.detectors.get(dev.id)
        if det is None:
            return
        status = det.current_status(now)
        days = None
        if det.last_backflush:
            days = (dt.date.fromtimestamp(now) - dt.date.fromtimestamp(det.last_backflush)).days
        values = {
            "status": status,
            "statusText": STATUS_TEXT[status],
            "lastHeatUpSeconds": det.last_heat_up_seconds or 0,
            "readySince": _fmt(det.ready_since) if det.status == "ready" else "",
            "shotsToday": det.shots_today,
            "shotsTotal": det.shots_total,
            "lastShotSeconds": det.last_shot_seconds or 0,
            "lastShotTime": _fmt(det.last_shot_time),
            "steamsToday": det.steams_today,
            "lastBackflush": _fmt(det.last_backflush),
            "daysSinceBackflush": days if days is not None else -1,
            "pumpSecondsSinceRefill": round(det.pump_seconds),
            "tankPercentUsed": det.tank_percent_used() if det.tank_percent_used() is not None else -1,
            "tankLearnedPumpSeconds": det.tank_learned_seconds() or 0,
            "detectorState": json.dumps(det.snapshot()),
        }
        changed = [{"key": k, "value": v} for k, v in values.items() if dev.states.get(k) != v]
        if changed:
            dev.updateStatesOnServer(changed)

    # ---- events ------------------------------------------------------------
    def triggerStartProcessing(self, trigger):
        self.event_triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.event_triggers.pop(trigger.id, None)

    def _fire(self, event_type, machine_id):
        for trigger in list(self.event_triggers.values()):
            if trigger.pluginTypeId != event_type:
                continue
            wanted = str(trigger.pluginProps.get("machineId", "any") or "any")
            if wanted not in ("any", str(machine_id)):
                continue
            try:
                indigo.trigger.execute(trigger)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception(f"could not execute trigger {trigger.id}")

    # ---- actions and menus -----------------------------------------------
    def markTankRefilledAction(self, action, dev):
        self._mark_refilled(dev)

    def resetCountersAction(self, action, dev):
        det = self.detectors.get(dev.id)
        if det:
            det.reset_counters()
            self._write_states(dev, time.time())

    def markTankRefilledMenu(self, valuesDict, typeId):
        try:
            dev = indigo.devices[int(valuesDict.get("machineId"))]
        except (TypeError, ValueError, KeyError):
            return False, valuesDict, {"machineId": "Choose a machine"}
        self._mark_refilled(dev)
        return True

    def _mark_refilled(self, dev):
        det = self.detectors.get(dev.id)
        if det is None:
            return
        now = time.time()
        self._apply(dev, det.mark_refilled(now), now)

    # ---- config UI -------------------------------------------------------
    def powerDeviceMenu(self, filter="", valuesDict=None, typeId="", targetId=0):  # noqa: A002
        return [(str(d.id), d.name) for d in indigo.devices
                if d.pluginId != self.pluginId and "curEnergyLevel" in d.states]

    def presetMenu(self, filter="", valuesDict=None, typeId="", targetId=0):  # noqa: A002
        return profiles.preset_menu()

    def machineMenu(self, filter="", valuesDict=None, typeId="", targetId=0):  # noqa: A002
        return [("any", "Any machine")] + [(str(d.id), d.name) for d in indigo.devices.iter("self")]

    def loadPreset(self, valuesDict, typeId, devId):
        key = valuesDict.get("preset", "")
        if key in profiles.PRESETS:
            for k, v in profiles.preset_thresholds(key).items():
                valuesDict[k] = str(int(v)) if float(v).is_integer() else str(v)
        return valuesDict

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errors = profiles.validate_props(valuesDict)
        if not valuesDict.get("powerDeviceId"):
            errors["powerDeviceId"] = "Choose the power device"
        if errors:
            return False, valuesDict, errors
        return True, valuesDict

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _power_id(dev):
        try:
            return int(dev.pluginProps.get("powerDeviceId"))
        except (TypeError, ValueError):
            return None
```

Note: the fake `indigo.devices` in conftest needs `__iter__` and `iter("self")` (both provided). `errors` returned by `validateDeviceConfigUi` is a plain dict; Indigo accepts `indigo.Dict` or dict.

- [ ] **Step 3: Run**

Run: `python3 -m pytest -q`
Expected: every test in the suite passes.

- [ ] **Step 4: Commit**

```bash
/usr/bin/git add -A && /usr/bin/git commit -m "feat: plugin shell — routing, states, events, actions, config UI"
```

---

### Task 9: README, live install on jarvis, PR

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md` (only if behaviour changed during tuning)

- [ ] **Step 1: Write README.md** covering: what it detects (the status list and the 8 events), setup (install, add an "Espresso Machine" device, choose the power device and model, Load preset values), how tank learning works (only runs-to-empty teach it; "Mark tank refilled" for early top-ups), the Elizabeth caveat and how to capture raw readings (tick "Log raw readings", make a drink, send the Indigo log lines starting `raw`), and the measured Bianca V3 table from the spec.

- [ ] **Step 2: Install on jarvis and create the device**

```bash
cp -R ~/indigo-espresso/"Espresso Monitor.indigoPlugin" /tmp/ && open "/tmp/Espresso Monitor.indigoPlugin"
```
Then in Indigo (Simon, or via the Indigo UI): enable the plugin, create device **Coffee Machine Monitor** (type Espresso Machine), power device **Coffee Machine Matter Switch** (1794293937), model **Lelit Bianca V3**, Load preset values, Save. Check the Indigo event log for errors.

- [ ] **Step 3: Live check**

Confirm with the Indigo MCP tools (`get_device_by_id` on the new device) that `status` is sensible for the time of day (`eco` or `ready` if the plug is on, `off` if not) and `detectorState` is populated. Ask Simon to make a drink and confirm `shotsToday` and `steamsToday` increment and the log shows `shotFinished` / `steamFinished`.

- [ ] **Step 4: Push and open the PR**

```bash
cd ~/indigo-espresso && /usr/bin/git push -u origin feat/v1
gh pr create --title "Espresso Monitor v1 [release]" --body "$(cat <<'EOF'
First version of Espresso Monitor: status device, 8 events and counters for a Lelit Bianca V3 from its smart plug's power, with an unverified Lelit Elizabeth preset. Detector replay-tested against two weeks of recorded data.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks --watch
```
Expected: Tests and Version Check green. **Do not merge** — wait for Simon's go-ahead; merge with `gh pr merge --merge` (never squash).

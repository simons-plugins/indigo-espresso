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

import profiles  # noqa: E402

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

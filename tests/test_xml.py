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

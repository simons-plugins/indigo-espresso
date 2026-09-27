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

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
    machine(p, power_id=555)
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


def test_updates_that_do_not_change_power_or_plug_are_ignored():
    p = make_plugin()
    plug = power(watts=233.0, on=True)
    dev = machine(p)
    det = p.detectors[dev.id]
    p.deviceUpdated(power(watts=1.5, on=True), plug)          # real change: 1.5 -> 233
    before = det.ep["n"] if det.ep else 0
    same = FakeDevice(100, "Plug", pluginId="other",
                      states={"curEnergyLevel": 233.0, "onOffState": True, "accumEnergyTotal": 9.9})
    p.deviceUpdated(plug, same)                               # only another state changed
    assert (det.ep["n"] if det.ep else 0) == before

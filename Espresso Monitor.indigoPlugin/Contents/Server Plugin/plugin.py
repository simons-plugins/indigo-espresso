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
        if newDev.id not in self.power_map:
            return
        # updates to other states (energy totals, comms time) re-send the same watts
        if all(origDev.states.get(k) == newDev.states.get(k) for k in ("curEnergyLevel", "onOffState")):
            return
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
        tank_pct = det.tank_percent_used()
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
            "tankPercentUsed": tank_pct if tank_pct is not None else -1,
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
    def startBackflushAction(self, action, dev):
        self._start_backflush(dev)

    def startBackflushMenu(self, valuesDict, typeId):
        try:
            dev = indigo.devices[int(valuesDict.get("machineId"))]
        except (TypeError, ValueError, KeyError):
            return False, valuesDict, {"machineId": "Choose a machine"}
        self._start_backflush(dev)
        return True

    def _start_backflush(self, dev):
        det = self.detectors.get(dev.id)
        if det is None:
            return
        now = time.time()
        self.logger.info(f"{dev.name}: backflush started - pump runs now count as backflush, not shots")
        self._apply(dev, det.start_backflush(now), now)

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

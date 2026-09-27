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
MIN_RUN_S = 12             # ...and lasts at least this long...
MIN_PUMP_ONLY_READINGS = 6 # ...and includes a pump + heater reading, or this many pump readings
                           # (heater bursts sampled mid-switch give stray pump-band readings)
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
        self.steam_last = None

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
        if cls in (PUMP, PUMPHEAT) and self.status != "off":
            if not (self.ep and t - self.ep["last"] <= PUMP_GAP_S):
                self.ep = {"start": t, "last": t, "n": 0, "heat": 0}
            self.ep["last"] = t
            self.ep["n"] += 1
            if cls == PUMPHEAT:
                self.ep["heat"] += 1
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
            self.steam_last = t1

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
                self.last_user_activity = self.steam_last
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
        if ep["heat"] == 0 and ep["n"] < MIN_PUMP_ONLY_READINGS:
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
        self.steam_last = None
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

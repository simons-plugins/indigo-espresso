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
    assert 431 + 8 * 60 - 10 <= empty[0]["t"] - T0 <= 431 + 8 * 60 + 20


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
    feed(det, pump(400, 60))
    ticks(det, 461, 10 * 60)
    assert det.status == "tankEmpty"
    assert len(det.tank_history) == 1 and det.tank_history[0] >= 60
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
    for warmed in (True, False):       # restored while ready, and while still heating
        det = Detector(BIANCA)
        if warmed:
            warm_on(det)
        else:
            feed(det, [(0, 1.7, True), (3, 1400, True)])
        again = Detector(BIANCA, saved=det.snapshot())
        ev = []
        for k in range(0, 3600, 10):   # an hour of ticks with no readings after restart
            ev += again.tick(T0 + 1000 + k)
        assert "tankEmpty" not in types(ev) and "ecoEntered" not in types(ev), warmed


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


def test_eco_timer_counts_from_actual_steaming_not_the_steam_window():
    # Shot ends ~1033, steaming 1036-1090. The Bianca sleeps 29 min after the last use;
    # that must read as eco even though the 3-minute steam window ended at ~1213.
    det = Detector(BIANCA)
    warm_on(det)
    s = []
    for k in range(200, 990, 40):
        s += [(k, 1390, True), (k + 3, 1.5, True)]
    s += [(1000, 233, True)] + [(1000 + k, 1565, True) for k in range(3, 24, 3)] + [(1027, 238, True), (1030, 1.6, True)]
    s += [(1036 + k, 1265, True) for k in range(0, 55, 3)] + [(1091, 1.6, True)]
    for k in range(1130, 1090 + 29 * 60, 40):
        s += [(k, 1390, True), (k + 3, 1.5, True)]
    ev = feed(det, s)
    ev += ticks(det, 1090 + 29 * 60 + 5, 15 * 60)
    assert "shotFinished" in types(ev) and "steamFinished" in types(ev)
    assert "ecoEntered" in types(ev)
    assert "tankEmpty" not in types(ev)


# ---- final-review findings -------------------------------------------------

def empty_after_shot(det):
    warm_on(det)
    feed(det, pump(400, 60))
    ticks(det, 461, 10 * 60)
    assert det.status == "tankEmpty"


def test_refill_with_plug_off_starts_the_new_tank_at_zero():
    det = Detector(BIANCA)
    det.tank_history = [100.0]
    empty_after_shot(det)             # a 60 pump-second tank, plausible against 100
    feed(det, [(1200, 1.5, False), (1500, 1.5, True), (1503, 1400, True)])
    assert det.pump_seconds == 0
    assert det.tank_history == [100.0, 60.0]


def test_implausibly_small_tankful_is_not_learned():
    # e.g. the machine switched off at its own switch soon after a shot: silence looks like empty
    det = Detector(BIANCA)
    det.tank_history = [300.0]
    empty_after_shot(det)             # "tank" of ~63 pump-seconds, well under half the median
    assert det.tank_history == [300.0]


def test_first_tankful_needs_a_minimum_to_be_learned():
    det = Detector(BIANCA)
    warm_on(det)
    feed(det, pump(400, 30))
    ticks(det, 431, 10 * 60)
    assert det.status == "tankEmpty" and det.tank_history == []


def test_restore_while_heating_then_idle_reading_is_not_no_draw():
    det = Detector(BIANCA)
    feed(det, [(0, 1.7, True), (3, 1400, True)])
    again = Detector(BIANCA, saved=det.snapshot())
    ev = again.reading(T0 + 1000, 1.5, True)
    ev += ticks(again, 1001, 120)
    assert "tankEmpty" not in types(ev)


def test_shot_pulled_from_eco_is_counted():
    det = Detector(BIANCA)
    warm_on(det)
    det.status = "eco"
    s = [(5000, 233, True)] + [(5000 + k, 1565, True) for k in range(3, 27, 3)] + \
        [(5027, 238, True), (5030, 1.6, True)]
    for k in range(5070, 5500, 40):
        s += [(k, 1390, True), (k + 3, 1.5, True)]
    ev = feed(det, s)
    assert types(ev).count("shotFinished") == 1


def test_drop_to_idle_after_long_unreported_draw_is_not_instant_silence():
    # a meter reporting on a deadband holds 1400 W for minutes without a report
    det = Detector(BIANCA)
    ev = feed(det, [(0, 1.5, True), (3, 1400, True), (200, 1.5, True)])
    ev += ticks(det, 201, 60)
    assert "tankEmpty" not in types(ev)

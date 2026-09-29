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
    for k in range(33):   # keep-warm bursts every 30 s up to the test's first action at 1000 s
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


def test_two_shots_close_together_are_two_shots():
    det = ready_machine()
    ev = feed(det, shot(1000) + idle_until(1040, 1120) + shot(1120) + idle_until(1160, 1700))
    assert types(ev).count("shotFinished") == 2
    assert "backflushFinished" not in types(ev)


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


def test_heater_transition_readings_are_not_a_shot():
    # Real data, 18 Sep 14:18:58-14:19:14: keep-warm bursts sampled mid-switch give
    # 319/310/262 W readings within 10 s of each other, but no pump + heater reading.
    det = ready_machine()
    s = [(1000, 319, True), (1004, 1314, True), (1007, 716, True), (1009, 310, True),
         (1016, 262, True), (1046, 138, True), (1052, 125, True), (1055, 1404, True), (1057, 121, True)]
    ev = feed(det, s + idle_until(1100, 1600))
    assert "shotFinished" not in types(ev)


def test_pump_alone_shot_counts_without_pump_heater_readings():
    # e.g. a machine whose pump + heater can't be separated (pumpHeaterMinW out of reach)
    det = ready_machine()
    s = [(1000 + k, 233, True) for k in range(0, 27, 3)] + [(1027, 1.5, True)]
    ev = feed(det, s + idle_until(1060, 1500))
    assert types(ev).count("shotFinished") == 1


def test_espresso_is_recorded_as_soon_as_the_pump_stops():
    det = ready_machine()
    feed(det, shot(1000))                      # pump stops ~1030
    for k in (1035, 1040, 1045):               # ticks, as the plugin does every 10 s
        det.tick(T0 + k)
    assert det.shots_today == 1


def test_without_start_backflush_every_pump_run_is_a_shot():
    # Backflush runs can't be told from shots by power alone (issue #3), so there is no
    # automatic backflush rule any more.
    det = ready_machine()
    s, at = [], 1000
    for _ in range(3):
        s += shot(at, seconds=30) + idle_until(at + 40, at + 60)
        at += 60
    ev = feed(det, s + idle_until(at, at + 600))
    assert types(ev).count("shotFinished") == 3
    assert "backflushFinished" not in types(ev)


def backflush_runs(at, pattern):
    """Pump runs with the given lengths, 10 s apart (how Simon's backflush shows)."""
    s = []
    for seconds in pattern:
        s += shot(at, seconds=seconds)
        at += seconds + 10
    return s, at


def test_start_backflush_counts_one_long_run_as_one_backflush():
    det = ready_machine()
    det.start_backflush(T0 + 990)
    assert det.current_status(T0 + 991) == "backflushing"
    s, end = backflush_runs(1000, [75])
    ev = feed(det, s + idle_until(end, end + 400))
    assert types(ev).count("backflushFinished") == 1
    assert "shotFinished" not in types(ev)
    assert det.last_backflush is not None and det.shots_today == 0
    assert det.current_status(T0 + end + 400) == "ready"


def test_start_backflush_counts_several_runs_as_one_backflush():
    det = ready_machine()
    det.start_backflush(T0 + 990)
    s, end = backflush_runs(1000, [35, 33, 20])
    ev = feed(det, s + idle_until(end, end + 400))
    bf = [e for e in ev if e["type"] == "backflushFinished"]
    assert len(bf) == 1 and bf[0]["runs"] == 3
    assert "shotFinished" not in types(ev)
    assert abs(bf[0]["t"] - (T0 + end - 10)) <= 6        # recorded at the end of the last run


def test_shot_before_start_backflush_is_still_a_shot():
    # 26 Sep: a kept shot at 15:28, then the backflush at 15:30
    det = ready_machine()
    s = shot(1000) + idle_until(1040, 1100)
    ev = feed(det, s)
    ev += det.start_backflush(T0 + 1100)
    s2, end = backflush_runs(1110, [60])
    ev += feed(det, s2 + idle_until(end, end + 400))
    assert types(ev).count("shotFinished") == 1
    assert types(ev).count("backflushFinished") == 1


def test_start_backflush_with_no_pumping_cancels_after_ten_minutes():
    det = ready_machine()
    det.start_backflush(T0 + 1000)
    keep_warm = []
    for k in range(1010, 1700, 40):
        keep_warm += [(k, 1390, True), (k + 3, 1.5, True)]
    ev = feed(det, keep_warm)
    assert "backflushFinished" not in types(ev)
    assert det.current_status(T0 + 1700) == "ready"
    assert det.last_backflush is None


def test_backflush_water_still_counts_towards_the_tank():
    det = ready_machine()
    before = det.pump_seconds
    det.start_backflush(T0 + 990)
    s, end = backflush_runs(1000, [35, 33])
    feed(det, s + idle_until(end, end + 400))
    assert det.pump_seconds - before >= 60


def test_backflush_session_survives_a_restart():
    det = ready_machine()
    det.start_backflush(T0 + 990)
    s, end = backflush_runs(1000, [35])
    feed(det, s + [(end + 5, 1.5, True)])
    again = Detector(BIANCA, saved=det.snapshot())
    s2, end2 = backflush_runs(end + 10, [30])
    ev = feed(again, s2 + idle_until(end2, end2 + 400))
    assert types(ev).count("backflushFinished") == 1 and "shotFinished" not in types(ev)


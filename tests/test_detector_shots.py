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


def test_espresso_without_milk_is_recorded_within_about_two_minutes_of_the_shot():
    det = ready_machine()
    feed(det, shot(1000))                       # shot ends ~1030
    ev = []
    for k in range(1040, 1180, 10):             # 2 min 30 s of quiet, ticking like the plugin
        ev += det.tick(T0 + k)
    assert types(ev).count("shotFinished") == 1


def test_backflush_is_not_split_by_a_long_run_still_in_progress():
    # 26 Sep: a 30 s run, then 100 s later a 63 s run - the 2-minute window from the
    # first run elapses while the second is still pumping
    det = ready_machine()
    s = shot(1000, seconds=30) + idle_until(1040, 1130)
    s += shot(1130, seconds=63) + idle_until(1200, 1210)
    s += shot(1210, seconds=30) + idle_until(1250, 1700)
    ev = feed(det, s)
    assert types(ev).count("backflushFinished") == 1
    assert "shotFinished" not in types(ev)

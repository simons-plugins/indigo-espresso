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

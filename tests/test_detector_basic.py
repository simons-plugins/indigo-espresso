import profiles
from detector import Detector

BIANCA = profiles.preset_thresholds("biancaV3")
T0 = 1_790_000_000.0


def feed(det, samples, tick_every=10):
    """samples: list of (offset_s, watts, plug_on). Ticks between readings like the plugin."""
    events = []
    last = None
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


def types(events):
    return [e["type"] for e in events]


def test_classify_bianca():
    d = Detector(BIANCA)
    assert d.classify(1.6) == "idle"
    assert d.classify(230) == "pump"
    assert d.classify(1260) == "steam"
    assert d.classify(1420) == "brew"
    assert d.classify(1600) == "pumpHeat"
    assert d.classify(700) == "other"


def cold_start(minutes_heating=14.5):
    """Switch-on, continuous ~1.4 kW, then keep-warm 5 s bursts every 40 s."""
    s = [(0, 1.7, True)]
    t = 3
    while t < minutes_heating * 60:
        s.append((t, 1400 + (t % 7), True))
        t += 3
    s.append((t, 1.6, True))
    end = t
    for k in range(12):
        b = end + 40 * (k + 1)
        s += [(b, 1380, True), (b + 3, 1390, True), (b + 6, 1.5, True)]
    return s, end


def test_cold_start_goes_ready_after_settle_and_records_heat_up():
    det = Detector(BIANCA)
    samples, end = cold_start()
    ev = feed(det, samples)
    ready = [e for e in ev if e["type"] == "machineReady"]
    assert len(ready) == 1
    assert abs(det.last_heat_up_seconds - end) < 4
    assert ready[0]["t"] >= T0 + end + 90
    assert det.status == "ready"


def test_warm_switch_on_is_ready_after_90s_of_short_bursts():
    det = Detector(BIANCA)
    s = [(0, 1.5, True)]
    for k in range(6):
        s += [(5 + 30 * k, 1390, True), (8 + 30 * k, 1.5, True)]
    ev = feed(det, s)
    assert "machineReady" in types(ev)


def test_no_draw_after_switch_on_is_reported_as_tank_empty():
    det = Detector(BIANCA)
    ev = feed(det, [(0, 1.7, True), (400, 1.7, True)])
    empty = [e for e in ev if e["type"] == "tankEmpty"]
    assert len(empty) == 1 and empty[0]["reason"] == "noDraw"
    assert det.status == "noDraw"
    assert 180 <= empty[0]["t"] - T0 < 200


def test_draw_after_no_draw_means_refilled_and_heating():
    det = Detector(BIANCA)
    ev = feed(det, [(0, 1.7, True), (400, 1.7, True), (410, 1153, True), (413, 1420, True)])
    assert "tankRefilled" in types(ev)
    assert det.status == "heating"


def test_plug_off_goes_off():
    det = Detector(BIANCA)
    samples, end = cold_start()
    feed(det, samples + [(end + 600, 1.5, False)])
    assert det.status == "off"


def test_held_high_reading_is_not_silence():
    det = Detector(BIANCA)
    samples, end = cold_start()
    feed(det, samples)
    # a heater reading then no reports for 10 min: the plug is holding a high value
    ev = det.reading(T0 + end + 700, 1400, True)
    for k in range(60):
        ev += det.tick(T0 + end + 700 + 10 * k)
    assert "tankEmpty" not in types(ev)


def test_no_plug_state_starts_on_draw_and_goes_off_after_45_min():
    det = Detector(BIANCA)
    s = [(0, 1.5, None)]
    t = 3
    while t < 600:
        s.append((t, 1400, None))
        t += 3
    s.append((t, 1.5, None))
    ev = feed(det, s)
    assert det.status in ("heating", "ready")
    for k in range(400):
        ev += det.tick(T0 + t + 10 * k)
    assert det.status == "off"

import datetime as dt
from zoneinfo import ZoneInfo

import profiles
import replay
from detector import Detector

LONDON = ZoneInfo("Europe/London")
BIANCA = profiles.preset_thresholds("biancaV3")


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 9, day, h, m, tzinfo=LONDON).timestamp()


def det():
    return Detector(BIANCA, tz=LONDON)


def test_steam_off_morning_sep27():
    d = det()
    ev = replay.run(d, replay.load("sep27-steamoff-morning.csv"))
    ready = replay.of(ev, "machineReady")
    assert ready and 5 * 60 <= ready[0]["heatUpSeconds"] <= 9 * 60
    shots = replay.of(ev, "shotFinished")
    assert len(shots) == 1
    assert at(27, "08:23") <= shots[0]["start"] <= at(27, "08:25")
    assert 20 <= shots[0]["seconds"] <= 45
    assert len(replay.of(ev, "steamFinished")) == 1
    assert replay.of(ev, "ecoEntered")
    assert not replay.of(ev, "tankEmpty")


def test_both_boilers_morning_sep25():
    d = det()
    ev = replay.run(d, replay.load("sep25-morning.csv"))
    ready = replay.of(ev, "machineReady")
    assert ready and 13 * 60 <= ready[0]["heatUpSeconds"] <= 16 * 60
    shots = replay.of(ev, "shotFinished")
    assert len(shots) == 1 and at(25, "07:30") <= shots[0]["start"] <= at(25, "07:32")
    assert len(replay.of(ev, "steamFinished")) == 1
    eco = replay.of(ev, "ecoEntered")
    assert eco and at(25, "08:03") <= eco[0]["t"] <= at(25, "08:10")
    assert not replay.of(ev, "tankEmpty")


def test_backflush_sep26_with_start_backflush_pressed():
    # 26 Sep afternoon: sink shot 15:23, kept shot 15:28, backflush 15:30-15:33 (Simon).
    # Simulate "Start backflush" being pressed at 15:30.
    rows = replay.load("sep26-backflush.csv")
    press = at(26, "15:30")
    d = det()
    ev = replay.run(d, [r for r in rows if r[0] < press])
    ev += d.start_backflush(press)
    ev += replay.run(d, [r for r in rows if r[0] >= press], plug=True)
    bf = replay.of(ev, "backflushFinished")
    assert len(bf) == 1 and at(26, "15:32") <= bf[0]["t"] <= at(26, "15:36")   # top-ups can extend it
    shots = [s for s in replay.of(ev, "shotFinished") if at(26, "15:20") <= s["start"] <= at(26, "15:40")]
    assert len(shots) == 2 and all(s["start"] < press for s in shots)


def test_backflush_without_the_button_counts_as_shots_sep26():
    # No automatic backflush rule: power alone can't tell a backflush from a shot (#3)
    ev = replay.run(det(), replay.load("sep26-backflush.csv"))
    assert not replay.of(ev, "backflushFinished")


def test_tank_ran_dry_sep26_morning():
    # Confirmed by Simon: he refilled the tank that morning.
    d = det()
    ev = replay.run(d, replay.load("sep26-tank-empty.csv"), plug=True)
    empty = replay.of(ev, "tankEmpty")
    assert len(empty) == 1 and at(26, "08:38") <= empty[0]["t"] <= at(26, "08:45")
    refill = replay.of(ev, "tankRefilled")
    assert refill and at(26, "09:58") <= refill[0]["t"] <= at(26, "10:00")


def test_no_draw_sep13():
    d = det()
    ev = replay.run(d, replay.load("sep13-no-draw.csv"))
    empty = replay.of(ev, "tankEmpty")
    assert empty and empty[0]["reason"] == "noDraw" and empty[0]["t"] <= at(13, "07:04")
    assert replay.of(ev, "tankRefilled")
    assert replay.of(ev, "machineReady")


def test_two_weeks_no_false_alarms():
    d = det()
    ev = replay.run(d, replay.load("sep14-27.csv.gz"))
    empties = replay.of(ev, "tankEmpty")
    # the only real empty in this fortnight is 26 Sep ~08:32
    assert len(empties) == 1 and at(26, "08:38") <= empties[0]["t"] <= at(26, "08:45"), \
        [dt.datetime.fromtimestamp(e["t"], LONDON).isoformat() for e in empties]
    per_day = {}
    for s in replay.of(ev, "shotFinished"):
        day = dt.datetime.fromtimestamp(s["start"], LONDON).day
        per_day[day] = per_day.get(day, 0) + 1
    assert sum(per_day.values()) >= 12, per_day      # at least most mornings found


def test_shot_with_low_pump_heater_readings_sep29():
    # 29 Sep 07:25: pump + heater read only 1,476-1,514 W (other days 1,550-1,690 W);
    # logged in Visualizer at 07:27:54, 28.7 s
    d = Detector(BIANCA, tz=LONDON)
    ev = replay.run(d, replay.load("sep29-morning.csv"))
    shots = [s for s in replay.of(ev, "shotFinished")
             if dt.datetime(2026, 9, 29, 7, 24, tzinfo=LONDON).timestamp() <= s["start"]
             <= dt.datetime(2026, 9, 29, 7, 26, tzinfo=LONDON).timestamp()]
    assert len(shots) == 1
    assert len(replay.of(ev, "steamFinished")) >= 1

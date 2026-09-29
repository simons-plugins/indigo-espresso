"""Detected shots vs the shots Simon logged in Beanconqueror (he logs every shot).

A baseline, not a target: any rule change must not lose a real shot, and should
not add false detections. Improve the numbers here when a change earns it.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import groundtruth
import profiles
import replay
from detector import Detector

LONDON = ZoneInfo("Europe/London")
KNOWN_MISSED = set()
# 2026-09-29 baseline: the 26 Sep backflush (15:30:52 and 15:32:13) counts as two shots,
# because nobody pressed "Start backflush" then - there is no automatic backflush rule.
MAX_FALSE_DETECTIONS = 2


def _fmt(t):
    return dt.datetime.fromtimestamp(t, LONDON).strftime("%a %d %H:%M:%S")


def test_every_logged_shot_is_detected_and_false_detections_do_not_grow():
    det = Detector(profiles.preset_thresholds("biancaV3"), tz=LONDON)
    ev = replay.run(det, replay.load("sep14-27.csv.gz"))
    starts = [s["start"] for s in replay.of(ev, "shotFinished")]
    pairs, missed, extra = groundtruth.match(starts, groundtruth.load_logged())
    assert set(missed) <= KNOWN_MISSED, "missed real shots: " + ", ".join(map(_fmt, missed))
    assert len(extra) <= MAX_FALSE_DETECTIONS, "false detections: " + ", ".join(map(_fmt, extra))
    assert len(pairs) == 24

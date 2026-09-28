"""Replay recorded plug data through a Detector, ticking like the plugin does."""
import csv
import gzip
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    path = FIXTURES / name
    opener = gzip.open if name.endswith(".gz") else open
    rows = []
    with opener(path, "rt", newline="") as f:
        for t, watts, plug in csv.reader(f):
            rows.append((float(t), float(watts) if watts else None, {"t": True, "f": False}.get(plug)))
    return rows


def run(det, rows, tick_every=10, plug=None):
    """Feed rows in order. ``plug`` is the plug state before the first row, for
    fixtures cut mid-session that carry no plug-on row."""
    events, last_t, last_w = [], None, 0.0
    for t, watts, p in rows:
        if last_t is not None:
            k = last_t + tick_every
            while k < t:
                events += det.tick(k)
                k += tick_every
        if p is not None:
            plug = p
        if watts is not None:
            last_w = watts
        events += det.reading(t, last_w, plug)
        last_t = t
    return events


def of(events, kind):
    return [e for e in events if e["type"] == kind]

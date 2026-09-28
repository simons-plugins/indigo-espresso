"""Compare detected shots with the shots Simon logged in Beanconqueror."""
import csv
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BEFORE_S = 6 * 60   # a shot starts up to this long before it is logged (saved)
AFTER_S = 60


def load_logged(name="shots-logged-sep14-27.csv"):
    with open(FIXTURES / name) as f:
        rows = [r for r in csv.reader(line for line in f if not line.startswith("#"))][1:]
    return [float(r[0]) for r in rows]


def match(detected_starts, logged):
    """Pair each logged shot with the closest unused detection in its window.
    Returns (matched pairs, missed logged times, unmatched detections)."""
    unused = sorted(detected_starts)
    pairs, missed = [], []
    for t in sorted(logged):
        cands = [d for d in unused if t - BEFORE_S <= d <= t + AFTER_S]
        if cands:
            best = min(cands, key=lambda d: abs(t - d))
            unused.remove(best)
            pairs.append((t, best))
        else:
            missed.append(t)
    return pairs, missed, unused

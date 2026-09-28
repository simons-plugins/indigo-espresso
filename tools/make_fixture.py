"""Cut a replay fixture from a SQL Logger export.

Usage: python3 tools/make_fixture.py EXPORT.csv "2026-09-27 07:59" "2026-09-27 10:30" OUT.csv[.gz]
Times are Europe/London. Output rows: epoch,watts,plug where watts/plug may be empty.
"""
import csv
import datetime as dt
import gzip
import sys
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def main(src, start, end, out):
    t0 = dt.datetime.strptime(start, "%Y-%m-%d %H:%M").replace(tzinfo=LONDON).timestamp()
    t1 = dt.datetime.strptime(end, "%Y-%m-%d %H:%M").replace(tzinfo=LONDON).timestamp()
    opener = gzip.open if out.endswith(".gz") else open
    kept = 0
    with open(src, newline="") as fin, opener(out, "wt", newline="") as fout:
        writer = csv.writer(fout)
        for row in csv.reader(fin):
            if len(row) != 3:
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue
            if not t0 <= t < t1 or (row[1] == "" and row[2] == ""):
                continue
            writer.writerow([f"{t:.3f}", row[2], row[1]])
            kept += 1
    print(f"{out}: {kept} rows")


if __name__ == "__main__":
    main(*sys.argv[1:5])

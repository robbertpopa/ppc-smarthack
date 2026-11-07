"""Compare solvers using saved household interval profiles, not uniform inputs."""

import argparse

import pandas as pd

from .compare_station import compare

parser = argparse.ArgumentParser()
parser.add_argument("csv")
args = parser.parse_args()
frame = pd.read_csv(args.csv)
frame = frame[frame.scenario == "unlimited"]
times = sorted(frame.interval_start_local_sydney.unique())
for index in (0, 12, 24, 36, 47):
    timestamp = times[index]
    rows = frame[frame.interval_start_local_sydney == timestamp].sort_values(
        ["neighborhood", "customer_id"]
    )
    difference = compare(0, 0, list(zip(rows.load_kw, rows.pv_available_kw)))
    print(f"{timestamp}: max voltage difference {difference:.9f} pu")
    if difference > 0.001:
        raise AssertionError("voltage disagreement exceeds 0.001 pu")

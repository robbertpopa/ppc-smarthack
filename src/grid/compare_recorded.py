import argparse

import pandas as pd

from .compare_station import compare


def main(path):
    frame = pd.read_csv(path)
    frame = frame[frame.scenario == "unlimited"]
    times = sorted(frame.interval_start_local_sydney.unique())
    for index in (0, 12, 24, 36, 47):
        timestamp = times[index]
        rows = frame[frame.interval_start_local_sydney == timestamp].sort_values(
            ["neighborhood", "customer_id"]
        )
        difference = compare(list(zip(rows.load_kw, rows.pv_available_kw)))
        print(f"{timestamp}: max voltage difference {difference:.9f} pu")
        if difference > 0.001:
            raise AssertionError("voltage disagreement exceeds 0.001 pu")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    main(parser.parse_args().csv)

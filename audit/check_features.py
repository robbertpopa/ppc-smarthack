"""Audit check: train/inference parity and look-ahead in the feature code (read only).

    .venv/bin/python -m audit.check_features

Uses the labels in DATA_DIR/labels/A (train period only).
"""

import numpy as np
import pandas as pd

from src.ml import features
from src.ml import labels as labels_io
from src.ml.split import split


def main(n: int = 300, seed: int = 0) -> None:
    labels = labels_io.load("A")
    train = split(labels)["train"].reset_index(drop=True)
    frame = features.build_frame(train)
    rng = np.random.default_rng(seed)
    rows = frame.dropna(subset=["net_now"]).sample(n, random_state=seed)

    # 1. parity: build() for one decision time == the row of build_frame()
    worst = 0.0
    for _, row in rows.iterrows():
        one = features.build(train, row["decision_time"])
        for name in features.FEATURES:
            a, b = one[name], row[name]
            if np.isnan(a) and np.isnan(b):
                continue
            worst = max(worst, abs(a - b))
    print(f"parity build vs build_frame on {n} rows: max |diff| = {worst:.3g}")

    # 2. look-ahead: corrupt everything that becomes available after t, features must not move
    moved = 0
    for _, row in rows.head(100).iterrows():
        t = row["decision_time"]
        future = train["available_at"] > t
        noisy = train.copy()
        noisy.loc[future, ["net_kw", "safe_share"]] = rng.uniform(-5, 5, (future.sum(), 2))
        a = features.build(train, t)
        b = features.build(noisy, t)
        moved += any(
            not (np.isnan(a[k]) and np.isnan(b[k])) and a[k] != b[k] for k in features.FEATURES
        )
    print(f"look-ahead: rows whose features change when the future is corrupted: {moved}/100")

    # 3. the same on build_frame (the training path): corrupt after a cut, rows before must stay
    cut = train["interval_start"].iloc[len(train) // 2]
    noisy = train.copy()
    after = noisy["available_at"] > cut
    noisy.loc[after, ["net_kw", "safe_share"]] = 9.0
    fa, fb = features.build_frame(train), features.build_frame(noisy)
    before = fa["decision_time"] <= cut
    diff = (fa.loc[before, features.FEATURES] - fb.loc[before, features.FEATURES]).abs().max().max()
    print(f"look-ahead in build_frame: max |diff| of rows decided before the cut = {diff}")

    # 4. how many feature rows have no history at all (labels cover daylight only)
    missing = frame[features.FEATURES].isna().mean().round(3)
    print("share of NaN per feature in build_frame (all target times):")
    print(missing[missing > 0].to_string())
    labelled = frame[frame["safe_share"].notna()]
    print("share of NaN among rows with a target:")
    print(labelled[features.FEATURES].isna().mean().round(3)[lambda s: s > 0].to_string())


if __name__ == "__main__":
    pd.set_option("display.width", 120)
    main()

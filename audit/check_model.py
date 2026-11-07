"""Audit check: what the saved safe-cap model does on the validation period (read only).

    .venv/bin/python -m audit.check_model

Loads ARTIFACT_URI/models/safe-cap-qgb-v1/PT-A, never the test period.
"""

import numpy as np
import pandas as pd

from src.ml import abstention, baselines, features, model_io, train
from src.ml import labels as labels_io
from src.ml.split import split

SYD = "Australia/Sydney"


def main() -> None:
    labels = labels_io.load("A")
    print("labels source_ref:", labels["source_ref"].unique(), "mock:", labels_io.is_mock(labels))
    local = labels["interval_start"].dt.tz_convert(SYD)
    print("labels range (local):", local.min(), "->", local.max())
    parts = split(labels)
    for name, part in parts.items():
        months = part["interval_start"].dt.tz_convert(SYD).dt.month.value_counts().sort_index()
        print(f"{name}: {len(part)} rows, months {months.index.tolist()}")

    s = labels["safe_share"]
    print(
        "safe_share: ==1.0",
        round(float((s >= 1 - 1e-9).mean()), 3),
        "| at the 0.05 floor",
        round(float((s <= 0.05 + 1e-9).mean()), 3),
        "| below fixed 0.36",
        round(float((s < 0.36).mean()), 3),
    )

    models, meta = model_io.load(train.MODEL_VERSION, "PT-A")
    print("model trained on mock labels:", meta["is_mock_labels"], "git", meta["git_sha"][:10])
    rows = split(train.training_rows(labels))["val"]
    X, y = rows[features.FEATURES], rows["safe_share"].to_numpy()
    pred = train.predict_quantiles(models, X)
    q05, q50, q90 = pred[:, 0], pred[:, 3], pred[:, 4]

    # point accuracy against persistence (the label is already a share of kWp: nMAE)
    persist = rows["share_last"].to_numpy()
    yday = rows["share_same_T_yesterday"].to_numpy()
    ok = ~np.isnan(persist)
    mae = lambda a, b: float(np.nanmean(np.abs(a - b)))  # noqa: E731
    print(
        f"val nMAE q50 {mae(q50[ok], y[ok]):.4f} | persistence {mae(persist[ok], y[ok]):.4f} "
        f"| same-T-yesterday {mae(yday[ok], y[ok]):.4f} (rows with a last value: {ok.sum()})"
    )
    print(f"skill of q50 vs persistence: {1 - mae(q50[ok], y[ok]) / mae(persist[ok], y[ok]):.3f}")

    # coverage per quantile and by group
    hour = pd.DatetimeIndex(rows["target_start"]).tz_convert(SYD).hour
    binding = y < 1 - 1e-9
    viol = q05 > y + 1e-6
    print(
        f"q05 violation rate: all {viol.mean():.4f} | when the limit binds (y<1) "
        f"{viol[binding].mean():.4f} | y==1 {viol[~binding].mean():.4f} "
        f"| share binding {binding.mean():.3f}"
    )
    print(f"q05..q90 interval coverage {np.mean((y >= q05) & (y <= q90)):.3f} (nominal 0.85)")
    by_hour = pd.DataFrame({"hour": hour, "viol": viol, "spread": q90 - q05}).groupby("hour").mean()
    print("q05 violation and spread by local hour:")
    print(by_hour.round(3).T.to_string())

    flagged = np.array([bool(abstention.quality_flags(r)) for r in X.to_dict("records")])
    print(
        f"rows abstained by input checks alone: {flagged.mean():.3f}; of which missing net_now "
        f"{np.mean(np.isnan(X['net_now'].to_numpy())):.3f}"
    )

    info = meta.get("abstention") or meta["validation"]["abstention"]
    print(
        "stored abstention:",
        {k: info[k] for k in ("tau", "abstain_rate", "violation_rate_with_fallback")},
    )
    print("stored holdout check:", info.get("holdout"))

    # last_known baseline on the same rows (from the same function the table uses)
    last = baselines.apply("last_known", labels).reindex(pd.DatetimeIndex(rows["target_start"]))
    print(f"last_known baseline violation rate: {np.mean(last.to_numpy() > y + 1e-6):.4f}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()

"""What happens when the inputs get worse: missing, noisy and censored readings.

The model is trained on clean data and used as deployed. Only the **inputs** are
corrupted (per-house readings, then the station totals are rebuilt from them); the labels
and the realised surplus used for scoring stay clean. Lagged safe shares, which come from
the grid twin and not from meters, are left as they are.

| Variant      | What changes                                                              |
|--------------|---------------------------------------------------------------------------|
| missing_20   | 20% of house readings become NaN; totals use the houses that remain,     |
|              | scaled by n_houses / n_available; fewer than half the houses means NaN   |
| noise_30     | every reading multiplied by N(1, 0.3), clipped at 0                      |
| censored     | the meter only shows what the fixed limit let through: export is capped  |
|              | at 0.36 x kWp, so sunny middays under-report the potential PV            |
| net_only     | the model never sees gross generation or consumption (checked)           |
"""

import zlib

import numpy as np
import pandas as pd

from src.eval.metrics import FIXED_SHARE, evaluate
from src.ml import abstention, features

VARIANTS = ("missing_20", "noise_30", "censored")
LABELS = {
    "missing_20": "20% of readings missing",
    "noise_30": "30% noise on readings",
    "censored": "censored production",
}
MISSING_SHARE = 0.20
NOISE_SIGMA = 0.30
GROSS_WORDS = ("gg_", "gc_", "pv_", "load_", "gross", "generation", "consumption")


def net_only_check() -> bool:
    """True if no model feature is gross generation or consumption (only net values)."""
    bad = [f for f in features.FEATURES if f.startswith(GROSS_WORDS) or "gross" in f]
    if bad:
        raise AssertionError(f"features use gross values, not only the net: {bad}")
    return True


def readings(profiles: pd.DataFrame, houses: pd.DataFrame) -> pd.DataFrame:
    """Per-house readings of the station, one row per simulated house and interval."""
    mapping = houses[["house_id", "source_house_id", "load_scale", "pv_scale", "kwp"]]
    data = mapping.merge(
        profiles[["house_id", "interval_start", "gc_kw", "cl_kw", "gg_kw"]],
        left_on="source_house_id",
        right_on="house_id",
        suffixes=("", "_src"),
    )
    return data.drop(columns=["house_id_src"]).reset_index(drop=True)


def aggregate(data: pd.DataFrame, n_houses: int) -> pd.DataFrame:
    """Station ``load_kw`` and ``pv_kw`` per interval from per-house readings.

    A house reports an interval when both its consumption and generation are present. The
    totals of the reporting houses are scaled by ``n_houses / n_available``; with fewer than
    half the houses the total is NaN. With every house present this is the plain sum, which
    is what the label file holds.
    """
    ok = data["gc_kw"].notna() & data["gg_kw"].notna()
    load = data["load_scale"] * (data["gc_kw"] + data["cl_kw"].fillna(0))
    pv = data["pv_scale"] * data["gg_kw"]
    frame = pd.DataFrame(
        {
            "interval_start": data["interval_start"],
            "load": load.where(ok),
            "pv": pv.where(ok),
            "ok": ok.astype(int),
        }
    )
    grouped = frame.groupby("interval_start")
    n_ok = grouped["ok"].sum()
    scale = n_houses / n_ok.where(n_ok > 0)
    enough = n_ok >= n_houses / 2
    out = pd.DataFrame(
        {
            "load_kw": (grouped["load"].sum(min_count=1) * scale).where(enough),
            "pv_kw": (grouped["pv"].sum(min_count=1) * scale).where(enough),
        }
    )
    return out.sort_index()


def corrupt(data: pd.DataFrame, variant: str, seed: int = 0) -> pd.DataFrame:
    """A corrupted copy of the per-house readings. Deterministic for a given seed."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}, expected one of {VARIANTS}")
    rng = np.random.default_rng([seed, zlib.crc32(variant.encode())])
    out = data.copy()
    cols = ["gc_kw", "cl_kw", "gg_kw"]
    if variant == "missing_20":
        gone = rng.random(len(out)) < MISSING_SHARE  # a missing house reading loses all columns
        out.loc[gone, cols] = np.nan
    elif variant == "noise_30":
        for col in cols:
            factor = rng.normal(1.0, NOISE_SIGMA, len(out))
            out[col] = (out[col] * factor).clip(lower=0)
    else:  # censored: the meter shows load plus the export the fixed limit allowed
        load = out["load_scale"] * (out["gc_kw"] + out["cl_kw"].fillna(0))
        pv = out["pv_scale"] * out["gg_kw"]
        cap = FIXED_SHARE * out["kwp"]
        seen = pv.where(pv - load <= cap, load + cap)
        out["gg_kw"] = seen / out["pv_scale"]
    return out


def corrupted_labels(
    labels: pd.DataFrame, data: pd.DataFrame, houses: pd.DataFrame
) -> pd.DataFrame:
    """Copy of ``labels`` whose input columns come from the (corrupted) readings."""
    totals = aggregate(data, len(houses)).reindex(pd.DatetimeIndex(labels["interval_start"]))
    out = labels.copy()
    out["load_kw"] = totals["load_kw"].to_numpy()
    out["pv_kw"] = totals["pv_kw"].to_numpy()
    out["net_kw"] = out["load_kw"] - out["pv_kw"]
    return out


def _flag_share(X: pd.DataFrame) -> float:
    return float(np.mean([bool(abstention.quality_flags(r)) for r in X.to_dict("records")]))


def run_variants(ctx: dict, clean: dict, seed: int = 0) -> dict:
    """Rows for every variant, with the change against the clean model in the label.

    Returns ``{"rows": {key: metrics}, "notes": {...}}`` or no rows when the per-house
    profiles are not available.
    """
    from src.eval.run import score_model

    net_only_check()
    if ctx["profiles"] is None:
        return {
            "rows": {},
            "notes": {"skipped": "no profiles.parquet, robustness needs per-house readings"},
        }
    base = clean["rows"]["model_fallback"]
    data = readings(ctx["profiles"], ctx["houses"])
    rows, notes = {}, {"net_only": True}
    test, surplus, kwp = ctx["test_labels"], ctx["surplus"], ctx["kwp"]
    clean_flagged = float(clean["scored"]["flagged"].mean())
    for variant in VARIANTS:
        labels = corrupted_labels(ctx["labels"], corrupt(data, variant, seed), ctx["houses"])
        scored = score_model(ctx, labels)
        metrics = evaluate(scored["fallback"], test, surplus, kwp, abstain=scored["abstain"])
        delta = {
            "delta_violation_rate": metrics["violation_rate"] - base["violation_rate"],
            "delta_export_index": metrics["export_index"] - base["export_index"],
            "delta_abstain_rate": metrics["abstain_rate"] - base["abstain_rate"],
        }
        d_viol, d_abst = delta["delta_violation_rate"] * 100, delta["delta_abstain_rate"] * 100
        note = f"violations {d_viol:+.2f} pt, abstentions {d_abst:+.1f} pt"
        key = f"robust_{variant}"
        rows[key] = {**metrics, **delta, "label": f"Model + fallback, {LABELS[variant]} ({note})"}
        extra_flagged = _flag_share(scored["X"]) - clean_flagged
        notes[variant] = {"extra_flagged_by_input_checks": float(extra_flagged), **delta}
    return {"rows": rows, "notes": notes}

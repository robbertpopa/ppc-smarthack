"""M3: give the features the net reading of every half hour, not only the labelled ones.

The labels exist only where a power flow ran (daytime, PV > 0), so the first hour after
sunrise never has ``net_now``. A meter reports at night too. This adds the missing
intervals from ``profiles.parquet``: their ``net_kw`` is the measured value. Where PV is
exactly 0 nothing can be exported, so every cap is safe (``safe_share = 1``,
``binding = none``); elsewhere the share stays unknown (null, ``converged = False``).
"""

import pandas as pd

from src.ml import labels as labels_io

STEP = pd.Timedelta(minutes=30)


def station_inputs(profiles: pd.DataFrame, houses: pd.DataFrame) -> pd.DataFrame:
    """Station ``load_kw`` and ``pv_kw`` per half hour; null unless every house reported."""
    m = houses[["source_house_id", "load_scale", "pv_scale"]].merge(
        profiles, left_on="source_house_id", right_on="house_id"
    )
    m["load"] = m["load_scale"] * (m["gc_kw"] + m["cl_kw"].fillna(0))
    m["pv"] = m["pv_scale"] * m["gg_kw"]
    n = len(houses)
    g = m.groupby("interval_start")
    return pd.DataFrame(
        {"load_kw": g["load"].sum(min_count=n), "pv_kw": g["pv"].sum(min_count=n)}
    ).sort_index()


def with_full_day(labels: pd.DataFrame, inputs: pd.DataFrame) -> pd.DataFrame:
    """``labels`` plus one row for every interval of ``inputs`` that has no label."""
    one = labels.iloc[0]
    extra = inputs.loc[~inputs.index.isin(labels["interval_start"])].dropna()
    no_pv = (extra["pv_kw"] <= 0).to_numpy()
    add = pd.DataFrame(
        {
            "pt_id": one["pt_id"],
            "interval_start": extra.index,
            "safe_share": pd.Series(no_pv, dtype="float64").where(no_pv).to_numpy(),
            "converged": no_pv,
            "binding": pd.Series(["none" if x else None for x in no_pv], dtype=object).to_numpy(),
            "load_kw": extra["load_kw"].to_numpy(),
            "pv_kw": extra["pv_kw"].to_numpy(),
            "net_kw": (extra["load_kw"] - extra["pv_kw"]).to_numpy(),
            "kwp_total": one["kwp_total"],
            "n_houses": pd.Series(int(one["n_houses"]), index=range(len(extra)), dtype="int64"),
            "provenance": "measured",
            "source_ref": one["source_ref"],
        }
    )
    add["available_at"] = add["interval_start"] + STEP
    out = pd.concat([labels, add[list(labels_io.COLUMNS)]], ignore_index=True)
    out = out.sort_values("interval_start").reset_index(drop=True)
    labels_io.validate(out)
    return out

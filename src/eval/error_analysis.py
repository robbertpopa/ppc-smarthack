"""Where does the model fail, on which cases, and what did we try?

Everything here is computed on the **test period** from the same scored intervals as the
evaluation table; only the "what we tried" table uses training and validation (never the
test period). Every number written to ``slides_numbers.md`` is found verbatim in a
generated table.

Residual ``r = safe_share - q05``: negative is a violation, a large positive value is
wasted export.

Day types: the ratio of a day's PV to a clear-sky expectation (installed power times the
sum of the sine of the sun's height). The scale ``k`` is the 95th percentile of the daily
ratio over training and validation days; a day is *cloudy* when its ratio is below
``0.5 k``, otherwise *clear*. The illustrated days are chosen by rule, not by looks: the
median clear day and the median cloudy day of the test period.
"""

import numpy as np
import pandas as pd

from src.eval import plots, robustness
from src.eval.metrics import EPS, FIXED_SHARE, evaluate, export_by_interval
from src.ml import train
from src.ml.config import SYDNEY, violation_target
from src.ml.split import TEST_START, split
from src.ml.sun import solar_elevation

EDGE_DEG = 10.0
CLOUDY_BELOW = 0.5
SEASONS = {
    **dict.fromkeys((12, 1, 2), "summer"),
    **dict.fromkeys((3, 4, 5), "autumn"),
    **dict.fromkeys((6, 7, 8), "winter"),
    **dict.fromkeys((9, 10, 11), "spring"),
}
SEASON_ORDER = ["summer", "autumn", "winter", "spring"]
DECIMALS = 4
COLUMNS = ["bin", "n_intervals", "violation_rate", "abstain_rate", "mean_residual", "export_index"]


def fmt(value) -> str:
    return f"{value:.{DECIMALS}f}"


def daily_ratio(labels: pd.DataFrame) -> pd.DataFrame:
    """Per Sydney day: PV over clear-sky expectation, with the days that cannot be judged."""
    start = pd.DatetimeIndex(labels["interval_start"])
    sine = np.clip(np.sin(np.radians(solar_elevation(start + pd.Timedelta(minutes=15)))), 0, None)
    frame = pd.DataFrame(
        {
            "date": start.tz_convert(SYDNEY).tz_localize(None).normalize(),
            "pv": labels["pv_kw"].to_numpy(),
            "clear": labels["kwp_total"].to_numpy() * sine,
        }
    )
    frame["pv_missing"] = frame["pv"].isna()
    daily = frame.groupby("date").agg(
        pv=("pv", "sum"), clear=("clear", "sum"), missing=("pv_missing", "sum")
    )
    daily["ratio"] = (daily["pv"] / daily["clear"]).where(
        (daily["clear"] > 0) & (daily["missing"] == 0)
    )
    return daily


def day_types(labels: pd.DataFrame) -> tuple[pd.Series, pd.Series, float]:
    daily = daily_ratio(labels)
    scale = daily.loc[daily.index < TEST_START.tz_localize(None), "ratio"].quantile(0.95)
    kind = pd.Series("unknown", index=daily.index)
    judged = daily["ratio"].notna()
    kind[judged] = np.where(daily.loc[judged, "ratio"] < CLOUDY_BELOW * scale, "cloudy", "clear")
    return kind, daily["ratio"], float(scale)


def interval_frame(ctx: dict, result: dict, kind: pd.Series) -> pd.DataFrame:
    """One row per scored test interval with everything the breakdowns need."""
    scored = result["scored"]
    rows, index = scored["rows"], scored["index"]
    df = pd.DataFrame(
        {
            "safe_share": rows["safe_share"].to_numpy(),
            "q05": scored["pred"][:, 0],
            "q90": scored["pred"][:, -1],
            "abstain": scored["abstain"].to_numpy(),
            "applied": scored["fallback"].to_numpy(),
            "sun_elev": rows["sun_elev_T"].to_numpy(),
        },
        index=index,
    )
    df["violation"] = df["applied"] > df["safe_share"] + EPS
    df["residual"] = df["safe_share"] - df["q05"]
    local = index.tz_convert(SYDNEY)
    df["hour"] = local.hour
    df["sun_band"] = np.where(df["sun_elev"] <= EDGE_DEG, "sunrise_sunset", "higher_sun")
    df["weekend"] = np.where(local.day_of_week >= 5, "weekend", "weekday")
    df["season"] = [SEASONS[m] for m in local.month]
    binding = ctx["test_labels"].set_index("interval_start")["binding"].reindex(index)
    df["binding"] = binding.fillna("unknown").to_numpy()
    df["day_type"] = kind.reindex(local.tz_localize(None).normalize()).fillna("unknown").to_numpy()
    surplus, kwp = ctx["surplus"], ctx["kwp"]
    if surplus is None:
        df["export_applied"] = df["export_fixed"] = np.nan
    else:
        df["export_applied"] = (
            export_by_interval(df["applied"], surplus, kwp).reindex(index).to_numpy()
        )
        fixed = pd.Series(FIXED_SHARE, index=index)
        df["export_fixed"] = export_by_interval(fixed, surplus, kwp).reindex(index).to_numpy()
    return df


def breakdown(df: pd.DataFrame, column: str, order: list | None = None) -> pd.DataFrame:
    """Metrics per bin of ``column``. Every interval lands in exactly one bin."""
    keys = order or sorted(df[column].unique())
    rows = []
    for key in keys:
        g = df[df[column] == key]
        if g.empty:
            continue
        fixed = g["export_fixed"].sum()
        rows.append(
            {
                "bin": key,
                "n_intervals": len(g),
                "violation_rate": float(g["violation"].mean()),
                "abstain_rate": float(g["abstain"].mean()),
                "mean_residual": float(g["residual"].mean()),
                "export_index": 100 * g["export_applied"].sum() / fixed if fixed > 0 else np.nan,
            }
        )
    out = pd.DataFrame(rows, columns=COLUMNS)
    if column == "hour":
        edge = df.groupby("hour")["sun_band"].apply(lambda s: float((s == "sunrise_sunset").mean()))
        out["sun_edge_share"] = out["bin"].map(edge)
    return out


def breakdowns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "hour": breakdown(df, "hour", list(range(24))),
        "sun_band": breakdown(df, "sun_band", ["sunrise_sunset", "higher_sun"]),
        "day_type": breakdown(df, "day_type", ["clear", "cloudy", "unknown"]),
        "weekend": breakdown(df, "weekend", ["weekday", "weekend"]),
        "season": breakdown(df, "season", SEASON_ORDER),
        "binding": breakdown(df, "binding"),
    }


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format=f"%.{DECIMALS}f", lineterminator="\n")


def _cell(column: str, value) -> str:
    if isinstance(value, float) and np.isnan(value):
        return "–"
    return str(value) if column in ("bin", "n_intervals") else fmt(value)


def _md(frame: pd.DataFrame) -> str:
    cols = [c for c in frame.columns if c != "sun_edge_share"]
    head = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    body = ""
    for _, r in frame.iterrows():
        body += "| " + " | ".join(_cell(c, r[c]) for c in cols) + " |\n"
    return head + body


def attempts(ctx: dict) -> pd.DataFrame:
    """Things we tried, scored on **validation** with the same code as the model."""
    meta, labels = ctx["meta"], ctx["labels"]
    rows = split(train.training_rows(labels))
    tr, va = rows["train"].copy(), rows["val"].copy()
    for part in (tr, va):  # a derived "how cloudy is it now" feature
        sine = np.clip(np.sin(np.radians(part["sun_elev_now"])), 0.1, None)
        part["cloud_ratio"] = -part["net_now"] / sine
    val_labels = split(labels)["val"]
    surplus, kwp = ctx["surplus"], ctx["kwp"]
    params, base = meta["hyperparameters"], meta["features"]
    index = pd.DatetimeIndex(va["target_start"])

    def score(name, share, alpha, note):
        share = pd.Series(np.clip(share, 0, 1), index=index)
        result = evaluate(share, val_labels, surplus, kwp)
        from sklearn.metrics import mean_pinball_loss

        loss = float(mean_pinball_loss(va["safe_share"], share.to_numpy(), alpha=alpha))
        return {
            "attempt": name,
            "limit_quantile": alpha,
            "pinball_val": loss,
            "violation_rate_val": result["violation_rate"],
            "export_index_val": result["export_index"],
            "note": note,
        }

    def refit(name, cols, p=params, note=""):
        model = train.fit_quantile(tr[cols], tr["safe_share"], 0.05, p, 0)
        return score(name, model.predict(va[cols]), 0.05, note)

    out = [
        refit("reference: q05, all features", base),
        score("limit = q10", ctx["models"][0.10].predict(va[base]), 0.10, "higher quantile"),
        score("limit = q20", ctx["models"][0.20].predict(va[base]), 0.20, "higher quantile"),
        refit("without the lag features", [f for f in base if "lag" not in f]),
        refit("without the yesterday features", [f for f in base if "yesterday" not in f]),
        refit("shallower trees (7 leaves)", base, {**params, "max_leaf_nodes": 7}),
        refit(
            "plus a cloud-ratio feature", [*base, "cloud_ratio"], note="-net_now over sun height"
        ),
    ]
    table = pd.DataFrame(out)
    ref = table.iloc[0]

    def dominates(r) -> bool:
        better_v = r["violation_rate_val"] <= ref["violation_rate_val"]
        e, e0 = r["export_index_val"], ref["export_index_val"]
        better_e = True if np.isnan(e) or np.isnan(e0) else e >= e0
        strict = r["violation_rate_val"] < ref["violation_rate_val"] or (
            not (np.isnan(e) or np.isnan(e0)) and e > e0
        )
        return bool(better_v and better_e and strict)

    table["improves_validation"] = [False] + [
        dominates(table.iloc[i]) for i in range(1, len(table))
    ]
    return table


def _pick_day(df: pd.DataFrame, ratio: pd.Series, kind: str):
    local_days = df.index.tz_convert(SYDNEY).tz_localize(None).normalize()
    days = ratio.reindex(sorted(set(local_days)))
    kinds = df["day_type"].groupby(local_days).first()
    chosen = days[(kinds.reindex(days.index) == kind) & days.notna()].sort_values(kind="stable")
    if chosen.empty:
        return None
    return chosen.index[(len(chosen) - 1) // 2]


def _sentence(df: pd.DataFrame, tables: dict) -> list[str]:
    overall = float(df["violation"].mean())
    hour = tables["hour"].sort_values(["violation_rate", "bin"], ascending=[False, True]).iloc[0]
    sun = tables["sun_band"].set_index("bin")["violation_rate"]
    kind = tables["day_type"].set_index("bin")["violation_rate"]
    wk = tables["weekend"].set_index("bin")["violation_rate"]

    def pick(series, key):
        return fmt(series[key]) if key in series.index else "n/a"

    return [
        f"The violation rate of model + fallback is {fmt(overall)} overall and highest at hour "
        f"{int(hour['bin'])} ({fmt(hour['violation_rate'])}); at sunrise and sunset (sun at most "
        f"{EDGE_DEG:.0f} degrees) it is {pick(sun, 'sunrise_sunset')} against "
        f"{pick(sun, 'higher_sun')} with the sun higher.",
        f"On cloudy days it is {pick(kind, 'cloudy')} against {pick(kind, 'clear')} on clear "
        f"days, and {pick(wk, 'weekend')} at weekends against {pick(wk, 'weekday')} on weekdays.",
        f"The agent sends {fmt(float(df['abstain'].mean()))} of intervals to a person.",
    ]


TITLES = {
    "hour": "By hour of day (Sydney)",
    "sun_band": "Sunrise and sunset",
    "day_type": "Clear and cloudy days",
    "weekend": "Weekday and weekend",
    "season": "Season",
    "binding": "Binding constraint",
}


def _day_plots(df, ratio, out_dir, pt_id):
    local_days = df.index.tz_convert(SYDNEY).tz_localize(None).normalize()
    shown = []
    for kind in ("clear", "cloudy"):
        day = _pick_day(df, ratio, kind)
        if day is None:
            continue
        name = f"band_{kind}_{pt_id}.png"
        title = f"{kind.capitalize()} day {day:%Y-%m-%d} (median {kind} day of the test period)"
        plots.band_vs_realised(df[local_days == day], title, out_dir / name)
        shown.append((kind, f"{day:%Y-%m-%d}", name))
    return shown


def analyse(ctx: dict, result: dict, rows: dict, out_dir, pt_id: str) -> dict:
    """Write tables and plots for one station; return its report text and slide numbers."""
    kind, ratio, scale = day_types(ctx["labels"])  # once: it scans the whole label table
    df = interval_frame(ctx, result, kind)
    tables = breakdowns(df)
    total = len(df)
    for name, table in tables.items():
        assert int(table["n_intervals"].sum()) == total, f"{name} bins do not add up to {total}"
        plain = table.drop(columns="sun_edge_share", errors="ignore")
        (out_dir / f"error_by_{name}_{pt_id}.csv").write_text(_csv(plain))
    tried = attempts(ctx)
    (out_dir / f"attempts_{pt_id}.csv").write_text(_csv(tried))

    plots.violation_by_hour(tables["hour"], out_dir / f"violation_by_hour_{pt_id}.png")
    plots.risk_coverage(result["risk_coverage"], out_dir / f"risk_coverage_{pt_id}.png")
    shown = _day_plots(df, ratio, out_dir, pt_id)

    md = [f"## {pt_id}", "", f"{total} daylight test intervals.", ""]
    md += [
        f"Day types: a day is cloudy when its PV is below {CLOUDY_BELOW} of the clear-sky "
        f"expectation; the scale k = {fmt(scale)} is the 95th percentile of the daily ratio "
        "before the test period. The plots show the median clear day and the median cloudy "
        "day of the test period, chosen by this rule and not by how they look.",
        "",
    ]
    for name, table in tables.items():
        md += [f"### {TITLES[name]}", "", _md(table), ""]
    md += ["### What we tried (validation only)", "", _md_attempts(tried), ""]
    md += ["### Plots", "", f"![violations by hour](violation_by_hour_{pt_id}.png)", ""]
    md += [f"![{kind} day {day}]({name})" for kind, day, name in shown]
    md += [f"![risk-coverage](risk_coverage_{pt_id}.png)", "", "### Findings", ""]
    md += [f"- {line}" for line in _sentence(df, tables)] + [""]
    return {
        "md": "\n".join(md),
        "slides": slide_numbers(tables, rows, pt_id),
        "drift": result["drift"],
        "rows": rows,
        "station": pt_id,
    }


def _md_attempts(tried: pd.DataFrame) -> str:
    head = (
        "| attempt | limit quantile | pinball (val) | violations (val) | export index (val) "
        "| improves validation |\n|---|---|---|---|---|---|\n"
    )
    body = ""
    for _, r in tried.iterrows():
        export = "–" if np.isnan(r["export_index_val"]) else fmt(r["export_index_val"])
        body += (
            f"| {r['attempt']} | {r['limit_quantile']} | {fmt(r['pinball_val'])} | "
            f"{fmt(r['violation_rate_val'])} | {export} | "
            f"{'yes' if r['improves_validation'] else 'no'} |\n"
        )
    return head + body


def slide_numbers(tables: dict, rows: dict, pt_id: str) -> list[tuple]:
    """(what, station, value text, file, row) for the numbers the slides use."""
    fb, row = rows["model_fallback"], "Model + fallback"
    items = [
        ("Export index, model + fallback (fixed = 100)", fb["export_index"], "table.csv", row),
        ("Violation rate, model + fallback", fb["violation_rate"], "table.csv", row),
        ("Violation rate, last known baseline", rows["last_known"]["violation_rate"],
         "table.csv", "Last known"),
        ("Abstention rate, model + fallback", fb["abstain_rate"], "table.csv", row),
        ("Flagged cases per day (max)", fb["per_day_max"], "table.csv", row),
    ]  # fmt: skip
    where = (
        ("day_type", "cloudy", "cloudy days"),
        ("sun_band", "sunrise_sunset", "sunrise and sunset"),
    )
    for table, key, label in where:
        found = tables[table].set_index("bin")["violation_rate"]
        if key in found.index:
            items.append(
                (f"Violation rate on {label}", found[key], f"error_by_{table}_{pt_id}.csv", key)
            )
    censored = rows.get("robust_censored")
    if censored is not None:
        items.append(
            ("Violation rate with censored production", censored["violation_rate"], "table.csv",
             censored["label"])
        )  # fmt: skip
    return [
        (w, pt_id, fmt(float(v)), f, r) for w, v, f, r in items if v is not None and not np.isnan(v)
    ]


NOTICEABLE = 0.0005  # 0.05 percentage points


def robustness_sentence(rows: dict) -> str | None:
    """Which input problem moves the violation rate most, from the robustness rows."""
    found = {v: rows.get(f"robust_{v}") for v in robustness.VARIANTS}
    found = {v: r for v, r in found.items() if r is not None}
    if not found:
        return None
    worst = max(found, key=lambda v: abs(found[v]["delta_violation_rate"]))
    row = found[worst]
    delta = row["delta_violation_rate"]
    if abs(delta) < NOTICEABLE:
        return (
            "No input problem tested (missing, noisy or censored readings) changes the "
            "violation rate noticeably."
        )
    return (
        f"The input problem that moves the violation rate most is {robustness.LABELS[worst]}: "
        f"{delta * 100:+.2f} points against a run without corruption, with abstentions "
        f"changing by {row['delta_abstain_rate'] * 100:+.1f} points."
    )


def limits(sections: list[dict]) -> list[str]:
    lines = [
        "The labels come from a simulated low-voltage grid, not from measured network states.",
        "The grid is a German SimBench network driven by Australian household profiles.",
        f"The violation target ({violation_target()}) and the crew budget are proposals that "
        "the team has not confirmed.",
    ]
    for section in sections:
        drift, station = section["drift"], section["station"]
        lines.append(
            f"{station}: calibration drifts, the violation rate was {fmt(drift['validation'])} "
            f"on validation and {fmt(drift['test'])} on test."
        )
        sentence = robustness_sentence(section["rows"])
        if sentence:
            lines.append(f"{station}: {sentence}")
    return lines


def write(sections: list[dict], out_dir, mock: bool) -> None:
    """Combine the stations into ``error_analysis.md`` and ``slides_numbers.md``."""
    stamp = "MOCK – NOT A RESULT – " if mock else ""
    md = [f"# {stamp}Error analysis on the test period", ""]
    md += ["Residual r = safe share − q05 (negative: violation).", ""]
    md += [section["md"] for section in sections]
    md += ["## Limits", ""] + [f"- {line}" for line in limits(sections)] + [""]
    (out_dir / "error_analysis.md").write_text("\n".join(md))
    slides = [f"# {stamp}Numbers for the slides", ""]
    slides += ["Each value is copied from the file and row named.", ""]
    slides += ["| Number | Station | Value | File | Row |", "|---|---|---|---|---|"]
    for section in sections:
        slides += [f"| {w} | {st} | {v} | {f} | {r} |" for w, st, v, f, r in section["slides"]]
    (out_dir / "slides_numbers.md").write_text("\n".join(slides) + "\n")

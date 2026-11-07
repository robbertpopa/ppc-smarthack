"""PNG plots for the error analysis, in one fixed style."""

import functools
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STYLE = {
    "figure.figsize": (7.0, 3.6),
    "figure.dpi": 100,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 9,
}
BLUE, ORANGE, GREY, RED = "#1f77b4", "#ff7f0e", "#8c8c8c", "#d62728"
NO_METADATA = {"Software": None}  # keep the PNG free of version stamps


def _quiet(function):
    """Silence one known NumPy deprecation raised inside matplotlib's date axis.

    The filter is narrow (that message only) and lives only while a plot is drawn, so it
    cannot hide the same warning in other code or after a dependency is upgraded.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="The 'generic' unit", category=DeprecationWarning
            )
            return function(*args, **kwargs)

    return wrapper


def _save(fig, path) -> None:
    fig.tight_layout()
    fig.savefig(path, metadata=NO_METADATA)
    plt.close(fig)


@_quiet
def violation_by_hour(table, path) -> None:
    """Bars of the violation rate per local hour; hours that touch sunrise or sunset in grey."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots()
        colors = [GREY if edge else BLUE for edge in table["sun_edge_share"] > 0.5]
        ax.bar(table["bin"].astype(int), table["violation_rate"], color=colors)
        ax.set_xlabel("hour of day, Sydney local time (grey: mostly sun below 10 degrees)")
        ax.set_ylabel("violation rate, model + fallback")
        ax.set_title("Where the limit is exceeded")
        _save(fig, path)


@_quiet
def band_vs_realised(day, title, path) -> None:
    """Predicted q05-q90 band against the realised safe share over one day."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots()
        x = day.index.tz_convert("Australia/Sydney")
        ax.fill_between(
            x, day["q05"], day["q90"], color=BLUE, alpha=0.25, label="predicted q05 to q90"
        )
        ax.plot(x, day["q05"], color=BLUE, lw=1, label="q05 (the limit)")
        ax.plot(x, day["safe_share"], color=ORANGE, lw=1.5, label="realised safe share")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("local time")
        ax.set_ylabel("share of installed kWp")
        ax.set_title(title)
        ax.legend(loc="lower right", fontsize=8)
        fig.autofmt_xdate()
        _save(fig, path)


@_quiet
def risk_coverage(curve, path) -> None:
    """Risk (violations among confident cases) against coverage (share not sent to a person)."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots()
        ax.plot(curve["coverage"], curve["risk"], color=RED, marker="o", ms=2.5, lw=1)
        ax.set_xlabel("coverage (share of intervals decided by the agent)")
        ax.set_ylabel("violation rate among those")
        ax.set_title("Risk-coverage curve on the test period")
        _save(fig, path)

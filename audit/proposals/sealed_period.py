"""C3: refuse to read the sealed test year unless the final evaluation asks for it.

Meant for ``src/grid/labels.py`` (``--start`` without a default, a ``--final-eval`` flag)
and for any script that opens a raw Ausgrid file.
"""

from pathlib import Path

import pandas as pd

from src.ml.split import TEST_START

SEALED_FILE = "Solar home 2012-2013.csv"


class SealedPeriodError(ValueError):
    pass


def check_window(start, days: int, final_eval: bool = False):
    """``(start, end)`` of a label run in Sydney dates, or raise if it touches the test year."""
    if start is None:
        raise SealedPeriodError("--start is required (there is no safe default)")
    if days < 1:
        raise ValueError("days must be positive")
    start = pd.Timestamp(start)
    end = start + pd.Timedelta(days=days)  # exclusive
    if end > TEST_START and not final_eval:
        raise SealedPeriodError(
            f"{start.date()} + {days} days reaches the sealed test year "
            f"(from {TEST_START.date()}); "
            "pass --final-eval only for the final evaluation"
        )
    return start, end


def check_source(path, final_eval: bool = False) -> Path:
    path = Path(path)
    if path.name == SEALED_FILE and not final_eval:
        raise SealedPeriodError(f"{SEALED_FILE} is the sealed test year; use 2010-11 or 2011-12")
    return path

"""C3: the label run cannot reach the sealed test year by accident."""

import pytest

from audit.proposals.sealed_period import SealedPeriodError, check_source, check_window


def test_todays_default_start_is_refused():
    with pytest.raises(SealedPeriodError):
        check_window("2013-01-01", 1)  # the default of src/grid/labels.py:103


def test_no_start_is_refused():
    with pytest.raises(SealedPeriodError, match="required"):
        check_window(None, 1)


@pytest.mark.parametrize(
    ("start", "days", "ok"),
    [
        ("2012-06-30", 1, True),
        ("2012-06-30", 2, False),
        ("2010-07-01", 731, True),
        ("2010-07-01", 732, False),
    ],
)
def test_window_edges(start, days, ok):
    if ok:
        check_window(start, days)
    else:
        with pytest.raises(SealedPeriodError):
            check_window(start, days)


def test_final_eval_opens_it():
    assert check_window("2013-01-01", 1, final_eval=True)


def test_the_readme_example_file_is_refused():
    with pytest.raises(SealedPeriodError):
        check_source("PATH_TO/Solar home 2012-2013.csv")
    check_source("data/raw/ausgrid/Solar home 2011-2012.csv")

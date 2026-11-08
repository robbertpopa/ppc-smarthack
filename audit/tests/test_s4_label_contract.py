"""S4: one label contract that both sides test against, with no pandapower needed."""

import pandas as pd

from audit.proposals import label_contract
from src.ml import labels as labels_io


def test_contract_has_exactly_the_columns_the_ml_loader_reads():
    assert set(label_contract.FIELDS) == set(labels_io.COLUMNS)


def test_todays_labels_fit_the_contract(labels_a):
    assert label_contract.check_frame(labels_a.iloc[::500]) == []


def test_the_grid_shape_and_inconsistent_rows_are_caught(labels_a):
    row = labels_a.iloc[[0]].copy()
    row["safe_share"] = float("nan")  # converged stays True: inconsistent
    assert label_contract.check_frame(row)
    late = labels_a.iloc[[1]].copy()
    late["available_at"] = late["interval_start"]  # available before it ended
    assert label_contract.check_frame(late)
    grid = pd.DataFrame(
        [{"pt_id": "PT", "interval_start": "2011-01-01T00:00:00Z", "safe_cap_share": 0.8}]
    )
    assert label_contract.check_frame(grid)


def test_the_label_schema_is_not_in_the_shared_contract_today():
    from src.common import contract

    names = {n.lower() for n in dir(contract)}
    assert not {"labelrow", "label", "labels"} & names

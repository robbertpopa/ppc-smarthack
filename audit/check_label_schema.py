"""Audit check: does the file written by the real label generator pass the ML loader?

    .venv/bin/python -m audit.check_label_schema

Builds one row exactly as ``src/grid/labels.py`` writes it (no power flow, no data read)
and passes it to ``src.ml.labels.validate``.
"""

import pandas as pd

from src.ml import labels as labels_io

row = {  # the dict appended in src/grid/labels.py generate()
    "pt_id": "PT-synthetic-400kVA",
    "interval_start": "2011-01-01T00:00:00Z",
    "safe_cap_share": 0.8,
    "provenance": "simulated",
    "n_houses": 30,
    "pv_scale": 1.0,
    "transformer_kva": 400,
    "source": "Ausgrid 2012-2013; synthetic radial 400 kVA",
}
frame = pd.DataFrame([row])
missing = [c for c in labels_io.COLUMNS if c not in frame.columns]
print("columns the ML loader needs but the generator does not write:", missing)
print(
    "interval_start dtype as written:", frame["interval_start"].dtype, "(string, not UTC timestamp)"
)
try:
    labels_io.validate(frame)
    print("validate: OK")
except ValueError as error:
    print("validate:", error)

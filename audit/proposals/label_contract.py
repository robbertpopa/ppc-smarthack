"""S4: the label file as a shared contract, testable without pandapower.

The label schema lives only in ``src/ml/labels.py`` (docstring and ``validate``); it is not
in ``src/common/contract.py`` nor in ``docs/09-contract.md``, and the grid side writes
another one. The grid tests skip themselves without pandapower (``tests/test_grid_labels.py:6-7``),
so locally and in the ``test`` CI job the boundary is never exercised. ``LabelRow`` is the
proposed shared model (to move into ``src/common/contract.py``); both sides test against it.
"""

from typing import Literal

import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

STEP = pd.Timedelta(minutes=30)


class LabelRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pt_id: str
    interval_start: AwareDatetime
    safe_share: float | None = Field(default=None, ge=0, le=1)
    converged: bool
    binding: Literal["voltage", "line", "trafo", "none"] | None = None
    load_kw: float | None
    pv_kw: float | None
    net_kw: float | None
    kwp_total: float = Field(gt=0)
    n_houses: int = Field(gt=0)
    available_at: AwareDatetime
    provenance: Literal["simulated", "measured"]
    source_ref: str

    @model_validator(mode="after")
    def _consistent(self):
        if self.converged != (self.safe_share is not None):
            raise ValueError("converged must be true exactly when safe_share is set")
        if self.available_at - self.interval_start != STEP.to_pytimedelta():
            raise ValueError("available_at must be interval_start + 30 min")
        if self.interval_start.utcoffset().total_seconds() != 0:
            raise ValueError("interval_start must be UTC")
        if None not in (self.load_kw, self.pv_kw, self.net_kw):
            if abs(self.net_kw - (self.load_kw - self.pv_kw)) > 1e-6:
                raise ValueError("net_kw must equal load_kw - pv_kw")
        return self


FIELDS = tuple(LabelRow.model_fields)


def check_frame(frame: pd.DataFrame) -> list[str]:
    """Row-level problems of a label frame (empty list when it fits the contract)."""
    problems = []
    for i, row in enumerate(frame.to_dict("records")):
        clean = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}
        for k in ("interval_start", "available_at"):
            if isinstance(clean.get(k), pd.Timestamp):
                clean[k] = clean[k].to_pydatetime()
        try:
            LabelRow.model_validate(clean)
        except ValidationError as error:
            problems.append(f"row {i}: {error.errors()[0]['msg']}")
    return problems


__all__ = ["LabelRow", "FIELDS", "check_frame"]

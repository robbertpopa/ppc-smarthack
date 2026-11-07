from datetime import datetime, timezone

from src.agent.log import ActionLog
from src.common.contract import ActionEvent


def event(n: int) -> ActionEvent:
    return ActionEvent(
        ts=datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc),
        plan_id=f"PLAN-{n}",
        event="plan_proposed",
        actor="agent",
        detail={"n": n},
    )


def test_read_returns_the_last_events_in_order(tmp_path):
    log = ActionLog(tmp_path / "a.jsonl")
    for n in range(500):
        log.append(event(n))
    assert [e.detail["n"] for e in log.read(3)] == [497, 498, 499]
    assert len(log.read(1000)) == 500
    assert log.read(0) == []


def test_a_torn_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "a.jsonl"
    log = ActionLog(path)
    log.append(event(1))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts": "2025-06-21T10:00:00Z", "plan_id": "PLAN-2", "ev')
    log = ActionLog(path)
    log.append(event(3))
    assert [e.detail["n"] for e in log.read()] == [1, 3]
    assert [e.detail["n"] for e in log.read_all()] == [1, 3]


def test_a_missing_log_reads_as_empty(tmp_path):
    log = ActionLog(tmp_path / "none.jsonl")
    assert log.read() == [] and list(log.read_all()) == []

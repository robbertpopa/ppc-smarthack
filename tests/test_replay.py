from datetime import date

from src.agent.replay import intervals, main, replay_day
from src.agent.wiring import build_service
from src.common.config import Settings

DAY = date(2025, 6, 21)


def test_a_day_has_48_half_hour_intervals_in_utc():
    slots = intervals(DAY)
    assert len(slots) == 48
    assert slots[0].isoformat() == "2025-06-21T00:00:00+00:00"
    assert slots[-1].isoformat() == "2025-06-21T23:30:00+00:00"


def test_replay_proposes_every_interval_and_sends_the_unsure_ones_to_a_person(tmp_path):
    service = build_service(Settings(log_uri=str(tmp_path / "a.jsonl")))
    rows = replay_day(service, DAY)
    assert len(rows) == 48
    assert any(r["abstain"] for r in rows) and any(not r["abstain"] for r in rows)
    assert all(r["status"] == "proposed" for r in rows)
    assert len(service.queue()["pending"]) == sum(r["abstain"] for r in rows)


def test_auto_execute_only_acts_on_confident_plans_and_logs_who(tmp_path):
    service = build_service(Settings(log_uri=str(tmp_path / "a.jsonl")))
    rows = replay_day(service, DAY, auto_execute=True)
    for row in rows:
        assert row["status"] == ("proposed" if row["abstain"] else "executed")
    actors = {e.actor for e in service.log.read(1000) if e.event == "plan_executed"}
    assert actors == {"replay-auto"}


def test_kill_switch_stops_auto_execute_without_crashing(tmp_path):
    service = build_service(Settings(log_uri=str(tmp_path / "a.jsonl")))
    service.kill_switch(True, "op")
    rows = replay_day(service, DAY, auto_execute=True)
    assert not any(r["status"] == "executed" for r in rows)


def test_the_command_prints_a_summary(tmp_path, capsys):
    code = main(["--date", "2025-06-21", "--log", str(tmp_path / "a.jsonl")])
    out = capsys.readouterr().out
    assert code == 0 and "48 intervals" in out and "sent to a person" in out

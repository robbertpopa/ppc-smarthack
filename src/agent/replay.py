import argparse
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from src.agent.service import AgentService, ServiceError
from src.agent.wiring import build_service
from src.common.config import Settings


def intervals(day: date, step_min: int = 30) -> list[datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    return [start + timedelta(minutes=m) for m in range(0, 24 * 60, step_min)]


def replay_day(
    service: AgentService,
    day: date,
    step_min: int = 30,
    auto_execute: bool = False,
    actor: str = "replay",
) -> list[dict]:
    rows = []
    for moment in intervals(day, step_min):
        plan = service.propose(moment, actor)
        if auto_execute and not plan.abstain and plan.status == "proposed":
            try:
                service.approve(plan.plan_id, f"{actor}-auto")
                plan = service.execute(plan.plan_id, f"{actor}-auto")
            except ServiceError:
                plan = service.get(plan.plan_id)
        rows.append(
            {
                "interval_start": plan.interval_start,
                "source": plan.source,
                "abstain": plan.abstain,
                "confidence": plan.confidence,
                "status": plan.status,
                "plan_id": plan.plan_id,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one UTC day through the agent")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--step-min", type=int, default=30)
    parser.add_argument("--auto-execute", action="store_true")
    parser.add_argument("--log", help="action log path, default LOG_URI")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.log:
        settings = replace(settings, log_uri=args.log)
    rows = replay_day(build_service(settings), args.date, args.step_min, args.auto_execute)
    for row in rows:
        print(
            f"{row['interval_start']:%H:%M} {row['source']:<15} "
            f"{'abstain' if row['abstain'] else 'confident':<9} "
            f"conf {row['confidence']:.2f}  {row['status']}"
        )
    unsure = sum(1 for row in rows if row["abstain"])
    print(f"{len(rows)} intervals, {unsure} sent to a person")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

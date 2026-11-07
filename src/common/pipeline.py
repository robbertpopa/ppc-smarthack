"""Train, forecast PV and load, and evaluate, with one command.

Runs the same steps locally and in the cloud batch job (``ARTIFACT_URI`` and ``DATA_DIR``
decide where files go). Scenarios without labels are skipped and listed.

    python -m src.common.pipeline --run-id cloud
"""

import argparse
import subprocess
import sys

from src.common.config import Settings


def scenarios_with_labels() -> list[str]:
    from src.ml import labels as labels_io

    return [
        s for s in labels_io.SCENARIOS if (labels_io.labels_path(s) / "labels.parquet").exists()
    ]


def steps(scenarios: list[str], run_id: str) -> list[list[str]]:
    commands = []
    for name in scenarios:
        commands.append([sys.executable, "-m", "src.ml.train", "--scenario", name])
        commands.append([sys.executable, "-m", "src.ml.forecast_pv_load", "--scenario", name])
    commands.append([sys.executable, "-m", "src.eval.run", "--run-id", run_id])
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.pipeline")
    parser.add_argument("--run-id", default="cloud")
    parser.add_argument("--dry-run", action="store_true", help="print the steps and stop")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    found = scenarios_with_labels()
    print(f"ARTIFACT_URI={settings.artifact_uri} DATA_DIR={settings.data_dir}")
    print(f"scenarios with labels: {found or 'none'}")
    if not found:
        print("no labels.parquet found; generate the labels first", file=sys.stderr)
        return 2
    for command in steps(found, args.run_id):
        print("+", " ".join(command))
        if not args.dry_run:
            result = subprocess.run(command)
            if result.returncode != 0:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

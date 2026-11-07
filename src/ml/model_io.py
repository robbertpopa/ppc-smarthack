"""Saving and loading trained models with their ``metadata.json``.

Layout: ``ARTIFACT_URI/models/<model_version>/<pt_id>/``  with ``q05.joblib`` ...
``metadata.json``. ``ARTIFACT_URI`` is a plain path (a mounted share in the cloud).
"""

import hashlib
import json
import subprocess
from pathlib import Path

import joblib

from src.ml.config import artifact_uri


def model_dir(model_version: str, pt_id: str) -> Path:
    return Path(artifact_uri()) / "models" / model_version / pt_id


def quantile_name(q: float) -> str:
    return f"q{round(q * 100):02d}"


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save(models: dict[float, object], meta: dict, out) -> None:
    """Write one file per quantile and ``metadata.json`` into the folder ``out``."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for q, model in models.items():
        joblib.dump(model, out / f"{quantile_name(q)}.joblib")
    (out / "metadata.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n"
    )


def load(model_version: str, pt_id: str) -> tuple[dict[float, object], dict]:
    """Load the models and metadata, or raise naming the folder that was expected."""
    path = model_dir(model_version, pt_id)
    meta_file = path / "metadata.json"
    if not meta_file.exists():
        raise FileNotFoundError(
            f"no model at {path}: train it with `python -m src.ml.train` (expected {meta_file})"
        )
    meta = json.loads(meta_file.read_text())
    models = {q: joblib.load(path / f"{quantile_name(q)}.joblib") for q in meta["quantiles"]}
    return models, meta

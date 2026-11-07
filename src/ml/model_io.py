"""Saving and loading trained models with their ``metadata.json``.

Layout: ``ARTIFACT_URI/models/<model_version>/<pt_id>/``  with ``q05.joblib`` ...
``metadata.json``. ``ARTIFACT_URI`` is a plain path (a mounted share in the cloud).
"""

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from src.ml.config import artifact_uri


def model_dir(model_version: str, pt_id: str) -> Path:
    return Path(artifact_uri()) / "models" / model_version / pt_id


def quantile_name(q: float) -> str:
    return f"q{round(q * 100):02d}"


def git_sha() -> str:
    """Commit of this code (``-dirty`` if tracked files have uncommitted changes)."""
    here = Path(__file__).resolve().parent

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=here, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        sha = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not sha:
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value):
    """Plain-JSON copy: numpy numbers become Python numbers, NaN and infinity become null."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(models: dict[float, object], meta: dict, out) -> None:
    """Write one file per quantile and ``metadata.json`` into the folder ``out``.

    The files are written to a temporary folder first and swapped in at the end, so a
    failure never leaves new models next to the old metadata.
    """
    import joblib

    out = Path(out)
    tmp = out.with_name(f".{out.name}.tmp")
    old = out.with_name(f".{out.name}.old")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    tmp.mkdir(parents=True)
    for q, model in models.items():
        joblib.dump(model, tmp / f"{quantile_name(q)}.joblib")
    text = json.dumps(_json_safe(meta), indent=2, sort_keys=True, default=str, allow_nan=False)
    (tmp / "metadata.json").write_text(text + "\n")
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    shutil.rmtree(old, ignore_errors=True)


def load_metadata(model_version: str, pt_id: str) -> dict:
    """Only ``metadata.json`` (no model files), or raise naming the expected path."""
    meta_file = model_dir(model_version, pt_id) / "metadata.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"no model at {meta_file.parent} (expected {meta_file})")
    return json.loads(meta_file.read_text())


def load(model_version: str, pt_id: str) -> tuple[dict[float, object], dict]:
    """Load the models and metadata, or raise naming the folder that was expected."""
    import joblib

    path = model_dir(model_version, pt_id)
    meta_file = path / "metadata.json"
    if not meta_file.exists():
        raise FileNotFoundError(
            f"no model at {path}: train it with `python -m src.ml.train` (expected {meta_file})"
        )
    meta = json.loads(meta_file.read_text())
    models = {q: joblib.load(path / f"{quantile_name(q)}.joblib") for q in meta["quantiles"]}
    return models, meta

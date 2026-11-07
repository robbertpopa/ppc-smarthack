"""Saving and loading trained models with their ``metadata.json``.

Layout: ``ARTIFACT_URI/models/<model_version>/<pt_id>/``  with ``q05.joblib`` ...
``metadata.json``. ``ARTIFACT_URI`` is a plain path (a mounted share in the cloud).
"""

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Callable
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


def save(models: dict, meta: dict, out, extra: Callable[[Path], None] | None = None) -> None:
    """Write one file per model (keyed by quantile or name) and ``metadata.json`` into ``out``.

    The files are written to a temporary folder first and swapped in at the end, so a
    failure never leaves new models next to the old metadata. ``extra(folder)`` may write
    more files (explanation data, curves) into the same temporary folder, so they are
    swapped in together with the models they describe.
    """
    import joblib

    out = Path(out)
    tmp = out.with_name(f".{out.name}.tmp")
    old = out.with_name(f".{out.name}.old")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    tmp.mkdir(parents=True)
    for key, model in models.items():
        name = key if isinstance(key, str) else quantile_name(key)
        joblib.dump(model, tmp / f"{name}.joblib")
    if extra is not None:
        extra(tmp)
    text = json.dumps(_json_safe(meta), indent=2, sort_keys=True, default=str, allow_nan=False)
    (tmp / "metadata.json").write_text(text + "\n")
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    shutil.rmtree(old, ignore_errors=True)


_caches: dict[tuple[str, str], tuple[int | None, tuple[bool, object]]] = {}


def stamp(folder) -> int | None:
    """Changes whenever a model is retrained into ``folder`` (``None`` if there is none)."""
    try:
        return (Path(folder) / "metadata.json").stat().st_mtime_ns
    except OSError:
        return None


# Failures that stay the same until the model is retrained: no model, or a model that does
# not fit the code. Anything else (a read error, memory) may be temporary and is not kept.
_DETERMINISTIC = (FileNotFoundError, ValueError)


def cached(name: str, folder, loader: Callable[[Path], object]):
    """``loader(folder)`` once per folder and training, including "there is no model".

    The cache entry is tied to the modification time of ``metadata.json``, so a model
    retrained into the same folder is picked up by a long-running process, and a missing
    model costs one ``stat`` per call instead of repeated file checks. Only deterministic
    failures are remembered, and as a type and arguments: a fresh exception is raised on
    every call, so no traceback is kept alive or grows. Temporary errors are raised and
    tried again on the next call.
    """
    folder = Path(folder)
    key, current = (name, str(folder)), stamp(folder)
    hit = _caches.get(key)
    if hit is None or hit[0] != current:
        try:
            hit = (current, (True, loader(folder)))
        except _DETERMINISTIC as error:
            hit = (current, (False, (type(error), error.args)))
        _caches[key] = hit
    ok, value = hit[1]
    if not ok:
        error_type, args = value
        raise error_type(*args) from None
    return value


def clear_caches() -> None:
    _caches.clear()


def load_metadata(model_version: str, pt_id: str) -> dict:
    """Only ``metadata.json`` (no model files), or raise naming the expected path."""
    meta_file = model_dir(model_version, pt_id) / "metadata.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"no model at {meta_file.parent} (expected {meta_file})")
    return json.loads(meta_file.read_text())


def load_dir(path) -> tuple[dict[float, object], dict]:
    """Load the quantile models and metadata of one model folder."""
    import joblib

    path = Path(path)
    meta_file = path / "metadata.json"
    if not meta_file.exists():
        raise FileNotFoundError(
            f"no model at {path}: train it with `python -m src.ml.train` (expected {meta_file})"
        )
    meta = json.loads(meta_file.read_text())
    models = {q: joblib.load(path / f"{quantile_name(q)}.joblib") for q in meta["quantiles"]}
    return models, meta


def load(model_version: str, pt_id: str) -> tuple[dict[float, object], dict]:
    """Load the models and metadata, or raise naming the folder that was expected."""
    return load_dir(model_dir(model_version, pt_id))

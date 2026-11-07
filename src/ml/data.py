"""Download, verify and describe the raw Ausgrid "Solar home electricity data".

    python -m src.ml.data download [--force] [--from DIR_OR_ZIP] [--include-held-out]

Raw files go to ``DATA_DIR/raw/``: the zip, ``ausgrid/`` (extracted) and
``SHA256SUMS``. Data is never committed. Parsing and cleaning live in task 02.

The 2012-13 file is the held-out test year (docs/tasks/p2/README.md, rule 2). It is
not extracted or copied unless ``--include-held-out`` is given, so nothing built
from ``DATA_DIR/raw/ausgrid/`` can touch it by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.ml.config import data_dir, profiles_path

SOURCE_URL = "https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip"
ZIP_NAME = "Ausgrid_solar_home_data.zip"
SUMS_NAME = "SHA256SUMS"
USER_AGENT = "smarthack-ppc-team"
TIMEOUT_S = 60
# What `--from DIR` takes from the top level of a local copy of the data.
LOCAL_COPY_GLOBS = ("Solar home 20??-20??.csv", "*.pdf", "README.md")
# Financial years that stay out of the raw folder until the final evaluation.
HELD_OUT_YEARS = ("2012-2013",)


def is_held_out(name: str) -> bool:
    return any(year in name for year in HELD_OUT_YEARS)


def raw_dir() -> Path:
    return data_dir() / "raw"


def ausgrid_dir() -> Path:
    return raw_dir() / "ausgrid"


# --- checksums -------------------------------------------------------------


def sha256(path: Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def read_sums(raw: Path) -> dict[str, str]:
    """``{path relative to raw: sha256}`` from SHA256SUMS (sha256sum format)."""
    sums_file = raw / SUMS_NAME
    if not sums_file.is_file():
        return {}
    pairs = (line.split("  ", 1) for line in sums_file.read_text().splitlines() if line)
    return {rel: digest for digest, rel in pairs}


def write_sums(raw: Path) -> dict[str, str]:
    """Hash the zip (if present) and every extracted file; write SHA256SUMS."""
    files = [p for p in sorted((raw / "ausgrid").rglob("*")) if p.is_file()]
    if (raw / ZIP_NAME).is_file():
        files.insert(0, raw / ZIP_NAME)
    sums = {p.relative_to(raw).as_posix(): sha256(p) for p in files}
    (raw / SUMS_NAME).write_text("".join(f"{d}  {rel}\n" for rel, d in sums.items()))
    return sums


def _matches(raw: Path, sums: dict[str, str], rel: str) -> bool:
    path = raw / rel
    return rel in sums and path.is_file() and sha256(path) == sums[rel]


def _zip_held_out(zip_path: Path) -> set[str]:
    """Extracted-folder paths (relative to ``raw``) of the held-out files inside the zip."""
    with zipfile.ZipFile(zip_path) as zf:
        return {
            f"ausgrid/{m.filename}"
            for m in zf.infolist()
            if not m.is_dir() and not m.filename.startswith("__MACOSX/") and is_held_out(m.filename)
        }


def _extracted_ok(raw: Path, sums: dict[str, str], include_held_out: bool = False) -> bool:
    rels = [rel for rel in sums if rel != ZIP_NAME]
    if include_held_out:
        if not _zip_held_out(raw / ZIP_NAME) <= set(rels):
            return False  # asked for the held-out year but it was never extracted: extract again
    elif any(is_held_out(rel) for rel in rels):
        return False  # a held-out file is lying in the folder: extract again without it
    return bool(rels) and all(_matches(raw, sums, rel) for rel in rels)


# --- download and extraction -----------------------------------------------


@contextmanager
def _atomic_path(dest: Path) -> Iterator[Path]:
    """Yield a ``.part`` path next to ``dest``; rename it onto ``dest`` if the block succeeds."""
    tmp = dest.with_name(dest.name + ".part")
    try:
        yield tmp
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _download_file(url: str, dest: Path) -> None:
    """Stream to a temporary file, then rename. Generic User-Agent only."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _atomic_path(dest) as tmp:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)


def _reset(dest: Path) -> None:
    """Empty the folder this module owns, so SHA256SUMS lists no stale file."""
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)


def _extract_zip(zip_path: Path, dest: Path, include_held_out: bool = False) -> None:
    _reset(dest)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir() or member.filename.startswith("__MACOSX/"):
                continue
            if not include_held_out and is_held_out(member.filename):
                print(f"held out, not extracted: {member.filename}")
                continue
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"unsafe path in zip: {member.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def download(force: bool = False, include_held_out: bool = False) -> list[Path]:
    """Fetch and extract the raw data unless SHA256SUMS says it is current.

    Returns the extracted half-hourly CSV paths (found by header, not by name).
    """
    raw, dest = raw_dir(), ausgrid_dir()
    sums = read_sums(raw)
    fresh = force or not _matches(raw, sums, ZIP_NAME)
    if fresh:
        print(f"downloading {SOURCE_URL}")
        _download_file(SOURCE_URL, raw / ZIP_NAME)
    else:
        print("zip already downloaded and matches SHA256SUMS: nothing to download")
    if fresh or not _extracted_ok(raw, sums, include_held_out):
        _extract_zip(raw / ZIP_NAME, dest, include_held_out)
        write_sums(raw)
    return half_hourly_csvs(dest, include_held_out)


def use_local_copy(src: Path, include_held_out: bool = False) -> list[Path]:
    """Offline alternative: take a local zip or an already extracted folder."""
    raw, dest = raw_dir(), ausgrid_dir()
    if src.is_file():
        _extract_zip(src, dest, include_held_out)
    elif src.is_dir():
        _reset(dest)
        for pattern in LOCAL_COPY_GLOBS:
            for path in sorted(src.glob(pattern)):
                if not include_held_out and is_held_out(path.name):
                    print(f"held out, not copied: {path.name}")
                    continue
                shutil.copy2(path, dest / path.name)
    else:
        raise FileNotFoundError(src)
    write_sums(raw)
    return half_hourly_csvs(dest, include_held_out)


# --- inspection ------------------------------------------------------------


@dataclass(frozen=True)
class CsvInfo:
    path: Path
    size: int
    lines: int
    first_line: str
    header_index: int | None  # 0-based line of the "Customer,..." header, None if absent
    header: str | None

    @property
    def data_rows(self) -> int:
        return self.lines - (self.header_index + 1 if self.header_index is not None else 0)

    @property
    def half_hourly(self) -> bool:
        return (
            self.header is not None
            and "Consumption Category" in self.header
            and "0:30" in self.header
        )


def inspect_csv(path: Path, header_only: bool = False) -> CsvInfo:
    """Find the header (the first line may be a title row) and count lines.

    ``header_only`` stops after the first 10 lines; ``lines`` (and so ``data_rows``) is then
    not the real count. Use it when only the layout matters, the files are large.
    """
    first, header_index, header, lines = "", None, None, 0
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for i, line in enumerate(fh):
            lines += 1
            if i == 0:
                first = line.rstrip("\r\n")
            if header is None and i < 10 and line.startswith("Customer,"):
                header_index, header = i, line.rstrip("\r\n")
            if header_only and i >= 9:
                break
    return CsvInfo(path, path.stat().st_size, lines, first, header_index, header)


def half_hourly_csvs(folder: Path, include_held_out: bool = False) -> list[Path]:
    """CSVs with the half-hourly layout (excludes the monthly dataset).

    The held-out year is left out unless ``include_held_out`` is set, so profiles and
    checks built from this list cannot touch the test year by accident.
    """
    return [
        p
        for p in sorted(folder.rglob("*.csv"))
        if (include_held_out or not is_held_out(p.name))
        and inspect_csv(p, header_only=True).half_hourly
    ]


def report(folder: Path) -> None:
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder)
        if path.suffix.lower() != ".csv":
            print(f"{rel}  {path.stat().st_size / 1e6:.2f} MB")
            continue
        info = inspect_csv(path)
        kind = "half-hourly" if info.half_hourly else "other layout"
        print(f"{rel}  {info.size / 1e6:.2f} MB  {info.data_rows} data rows  [{kind}]")
        print(f"    first line: {info.first_line[:100]}")
        if info.header_index not in (None, 0):
            print(f"    header (line {info.header_index + 1}): {(info.header or '')[:100]}")


def profiles() -> Path:
    """Build ``DATA_DIR/profiles.parquet`` from the raw files and print the quality summary."""
    from src.ml import ausgrid  # imported here: ausgrid itself imports this module

    table = ausgrid.build_profiles(ausgrid_dir())
    out = profiles_path()
    with _atomic_path(out) as tmp:
        table.to_parquet(tmp, index=False)
    print(ausgrid.summarize(table))
    print("gross generation, kWh (raw CSV vs profiles; raw = profile + removed by rules):")
    checks = ausgrid.generation_check(ausgrid_dir(), table)
    for row in checks:
        print(
            f"  {row['file']}: raw {row['raw_gg_kwh']:,.1f}  profiles {row['profile_gg_kwh']:,.1f}"
        )
    raw_total = sum(r["raw_gg_kwh"] for r in checks)
    kept = sum(r["profile_gg_kwh"] for r in checks) + table.attrs["rules"].get(
        "gg_kwh_removed", 0.0
    )
    print(f"  total: raw {raw_total:,.1f}  profiles + removed {kept:,.1f}")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.ml.data")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="fetch and verify the raw Ausgrid data")
    dl.add_argument("--force", action="store_true", help="download again even if current")
    dl.add_argument(
        "--from", dest="source", type=Path, help="use a local zip or folder, no network"
    )
    dl.add_argument(
        "--include-held-out",
        action="store_true",
        help=f"also take the held-out year ({', '.join(HELD_OUT_YEARS)}); final evaluation only",
    )
    sub.add_parser("profiles", help="clean the raw files into DATA_DIR/profiles.parquet")
    args = parser.parse_args(argv)

    if args.command == "profiles":
        profiles()
        return 0
    if args.source:
        csvs = use_local_copy(args.source, args.include_held_out)
    else:
        csvs = download(force=args.force, include_held_out=args.include_held_out)
    report(ausgrid_dir())
    print(f"{len(csvs)} half-hourly CSV file(s) in {ausgrid_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

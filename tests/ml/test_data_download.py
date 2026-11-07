"""Download, skip and checksum logic. No network: the downloader is replaced."""

import zipfile
from pathlib import Path

import pytest

from src.ml import data

HEADER_OLD = "Customer,Generator Capacity,Postcode,Consumption Category,date,0:30,1:00"
HEADER_NEW = HEADER_OLD + ",Row Quality"
MONTHLY_HEADER = "Customer ID,Netwk Bill Rate Type,Consumption Month,Sum,Unit of me"

MEMBERS = {
    "Ausgrid_solar_home_data/Solar home 2010-2011.csv": (
        '"2010-2011 Solar home electricity data",,,,,,\n'
        f"{HEADER_OLD}\n"
        "1,3.78,2076,GC,1-Jul-10,0.303,0.471\n"
        "1,3.78,2076,GG,1-Jul-10,0,0\n"
    ),
    "Ausgrid_solar_home_data/Solar home 2011-2012.csv": (
        '"2011-2012 Solar home electricity data",,,,,,,\n'
        f"{HEADER_NEW}\r\n"
        "1,3.78,2076,GC,1/07/2011,0.1,0.2,\r\n"
    ),
    "Ausgrid_solar_home_data/Solar home 2012-2013.csv": (  # the held-out test year
        '"2012-2013 Solar home electricity data",,,,,,,\n'
        f"{HEADER_NEW}\r\n"
        "1,3.78,2076,GC,1/07/2012,0.3,0.4,\r\n"
    ),
    "Ausgrid_solar_home_data/monthly/SolarMonthlyData.csv": (
        f"{MONTHLY_HEADER}\n1,SC,01.2007,31,DAY\n"
    ),
    "Ausgrid_solar_home_data/notes.pdf": "%PDF-1.4 not really\n",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """DATA_DIR in a temp folder and a fake downloader that counts its calls."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    calls = []

    def fake_download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as zf:
            for name, text in MEMBERS.items():
                zf.writestr(name, text)

    monkeypatch.setattr(data, "_download_file", fake_download)
    return calls


def test_config_defaults_are_relative(monkeypatch):
    from src.ml import config

    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("ARTIFACT_URI", raising=False)
    assert config.data_dir() == Path("./data") and not config.data_dir().is_absolute()
    assert config.artifact_uri() == "./artifacts"


def test_first_download_extracts_and_writes_sums(env):
    csvs = data.download()

    assert env == [data.SOURCE_URL]
    assert [p.name for p in csvs] == ["Solar home 2010-2011.csv", "Solar home 2011-2012.csv"]
    sums = data.read_sums(data.raw_dir())
    assert data.ZIP_NAME in sums
    assert "ausgrid/Ausgrid_solar_home_data/notes.pdf" in sums
    assert len(sums) == 1 + len(MEMBERS) - 1  # the zip plus every extracted file but the held-out
    assert sums[data.ZIP_NAME] == data.sha256(data.raw_dir() / data.ZIP_NAME)


def test_second_run_downloads_nothing(env):
    data.download()
    data.download()
    assert len(env) == 1


def test_force_downloads_again(env):
    data.download()
    data.download(force=True)
    assert len(env) == 2


def test_modified_zip_is_downloaded_again(env):
    data.download()
    (data.raw_dir() / data.ZIP_NAME).write_bytes(b"corrupt")
    data.download()
    assert len(env) == 2


def test_missing_extracted_file_is_restored_without_network(env):
    csvs = data.download()
    csvs[0].unlink()
    assert len(data.download()) == 2
    assert len(env) == 1


def test_edited_extracted_file_is_restored_without_network(env):
    csvs = data.download()
    csvs[0].write_text("tampered")
    assert len(data.download()) == 2
    assert csvs[0].read_text().startswith('"2010-2011')
    assert len(env) == 1


def test_failed_download_leaves_no_partial_file(env, monkeypatch):
    def boom(url: str, dest: Path) -> None:
        raise OSError("network down")

    monkeypatch.setattr(data, "_download_file", boom)
    with pytest.raises(OSError):
        data.download()
    assert not (data.raw_dir() / data.ZIP_NAME).exists()


def test_zip_path_traversal_is_rejected(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.csv", "x")
    with pytest.raises(ValueError, match="unsafe"):
        data._extract_zip(bad, tmp_path / "out")
    assert not (tmp_path / "escape.csv").exists()


def test_inspect_csv_finds_header_after_title_row(tmp_path):
    title_first = tmp_path / "a.csv"
    title_first.write_text(f'"title",,\n{HEADER_OLD}\n1,3.78,2076,GC,1-Jul-10,0.3,0.4\n')
    header_first = tmp_path / "b.csv"
    header_first.write_text(f"{HEADER_NEW}\n1,3.78,2076,GC,1/07/2011,0.1,0.2,\n")

    a, b = data.inspect_csv(title_first), data.inspect_csv(header_first)

    assert (a.header_index, a.data_rows, a.half_hourly) == (1, 1, True)
    assert a.first_line.startswith('"title"')
    assert (b.header_index, b.data_rows, b.half_hourly) == (0, 1, True)


def test_local_folder_copy_skips_extracts_and_subfolders(env, tmp_path):
    src = tmp_path / "local"
    (src / "monthly").mkdir(parents=True)
    (src / "Solar home 2010-2011.csv").write_text(
        MEMBERS["Ausgrid_solar_home_data/Solar home 2010-2011.csv"]
    )
    (src / "Solar home 1st customer 2010-2011 .csv").write_text(
        "sample extract, must not be copied\n"
    )
    (src / "monthly" / "SolarMonthlyData.csv").write_text(f"{MONTHLY_HEADER}\n")
    (src / "notes.pdf").write_text("pdf")

    csvs = data.use_local_copy(src)

    assert [p.name for p in csvs] == ["Solar home 2010-2011.csv"]
    names = sorted(p.name for p in data.ausgrid_dir().iterdir())
    assert names == ["Solar home 2010-2011.csv", "notes.pdf"]
    assert env == []  # no network
    assert "ausgrid/notes.pdf" in data.read_sums(data.raw_dir())


def test_held_out_year_is_not_extracted_by_default(env):
    csvs = data.download()

    assert [p.name for p in csvs] == ["Solar home 2010-2011.csv", "Solar home 2011-2012.csv"]
    assert not list(data.ausgrid_dir().rglob("*2012-2013*"))
    assert not any("2012-2013" in rel for rel in data.read_sums(data.raw_dir()))


def test_held_out_year_needs_an_explicit_flag(env):
    csvs = data.download(include_held_out=True)

    assert [p.name for p in csvs][-1] == "Solar home 2012-2013.csv"
    assert len(csvs) == 3


def test_leftover_held_out_file_is_removed_without_network(env):
    data.download(include_held_out=True)

    csvs = data.download()  # default run: the leftover must go, from the zip already on disk

    assert len(csvs) == 2 and not list(data.ausgrid_dir().rglob("*2012-2013*"))
    assert len(env) == 1


def test_local_copy_keeps_the_held_out_year_out_unless_asked(env, tmp_path):
    src = tmp_path / "local"
    src.mkdir()
    for name, text in MEMBERS.items():
        if name.count("/") == 1 and name.endswith(".csv"):
            (src / Path(name).name).write_text(text)

    assert [p.name for p in data.use_local_copy(src)] == [
        "Solar home 2010-2011.csv",
        "Solar home 2011-2012.csv",
    ]
    assert len(data.use_local_copy(src, include_held_out=True)) == 3


def test_held_out_year_is_skipped_from_a_local_zip(env, tmp_path):
    env_zip = tmp_path / "copy.zip"
    with zipfile.ZipFile(env_zip, "w") as zf:
        for name, text in MEMBERS.items():
            zf.writestr(name, text)

    assert len(data.use_local_copy(env_zip)) == 2

import pandas as pd
import pytest

from src.ml import data, geo

GEO = """Customer,Generator Capacity,Postcode,lat,lon,localities
1,3.78,2076,-33.71,151.11,"Normanhurst, Wahroonga"
2,1.62,2259,-33.20,151.39,"Alison, Bushells Ridge"
3,1.0,2259,-33.20,151.39,"Alison, Bushells Ridge"
"""
OFFICIAL = """2010-2011 ,,
Customer,Generator Capacity,Postcode
1,3.78,2076
2,1.62,2259
3,1,2259
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.fixture
def geo_file(tmp_path):
    return write(tmp_path, "geo.csv", GEO)


@pytest.fixture
def official_file(tmp_path):
    return write(tmp_path, "official.csv", OFFICIAL)


def test_the_geo_file_becomes_one_row_per_house(geo_file):
    table = geo.read_geo(geo_file)
    assert list(table.columns) == ["house_id", "postcode", "kwp", "lat", "lon", "localities"]
    assert list(table["house_id"]) == ["AG-0001", "AG-0002", "AG-0003"]
    assert table["postcode"].tolist() == ["2076", "2259", "2259"]  # text, not a number
    assert table.loc[0, "localities"] == "Normanhurst, Wahroonga"


def test_the_official_file_with_its_title_line_is_read(official_file):
    official = geo.read_official(official_file)
    assert list(official.columns) == ["Customer", "Generator Capacity", "Postcode"]
    assert len(official) == 3


def test_a_file_without_a_title_line_is_read_too(tmp_path):
    plain = write(tmp_path, "plain.csv", OFFICIAL.split("\n", 1)[1])
    assert len(geo.read_official(plain)) == 3


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("3,1.0,2259", "2,1.0,2259", "unique"),
        ("2076,-33.71", "2076,-3.71", "outside New South Wales"),
        ("2076,-33.71,151.11", "2076,,151.11", "must not be empty"),
        ("2076", "207", "four digits"),
        ("3.78", "-1", "positive"),
        ("3,1.0,2259,-33.20,151.39", "3,1.0,2259,-33.25,151.39", "more than one coordinate"),
    ],
)
def test_bad_geo_files_are_rejected_with_the_reason(tmp_path, old, new, message):
    bad = write(tmp_path, "bad.csv", GEO.replace(old, new))
    with pytest.raises(ValueError, match=message):
        geo.read_geo(bad)


def test_missing_columns_are_named(tmp_path):
    bad = write(tmp_path, "bad.csv", "Customer,Postcode\n1,2076\n")
    with pytest.raises(ValueError, match="missing columns"):
        geo.read_geo(bad)


def test_agreement_with_the_official_list_is_checked(geo_file, official_file, tmp_path):
    table = geo.read_geo(geo_file)
    geo.check_against_official(table, geo.read_official(official_file))  # no error
    other_capacity = write(tmp_path, "o1.csv", OFFICIAL.replace("1.62", "1.7"))
    with pytest.raises(ValueError, match="capacity differs"):
        geo.check_against_official(table, geo.read_official(other_capacity))
    other_post = write(tmp_path, "o2.csv", OFFICIAL.replace("3,1,2259", "3,1,2260"))
    with pytest.raises(ValueError, match="postcode differs"):
        geo.check_against_official(table, geo.read_official(other_post))
    fewer = write(tmp_path, "o3.csv", OFFICIAL.rsplit("\n", 2)[0] + "\n")
    with pytest.raises(ValueError, match="only in the geo file"):
        geo.check_against_official(table, geo.read_official(fewer))


def test_agreement_with_the_profiles_is_checked(geo_file):
    table = geo.read_geo(geo_file)
    profiles = pd.DataFrame(
        {
            "house_id": ["AG-0001", "AG-0001", "AG-0002", "AG-0003"],
            "kwp": [3.78, 3.78, 1.62, 1.0],
            "postcode": ["2076", "2076", "2259", "2259"],
        }
    )
    geo.check_against_profiles(table, profiles)
    profiles.loc[2, "postcode"] = "2261"
    with pytest.raises(ValueError, match="differs from the profiles"):
        geo.check_against_profiles(table, profiles)
    extra = pd.concat(
        [profiles, pd.DataFrame({"house_id": ["AG-0009"], "kwp": [1.0], "postcode": ["2000"]})]
    )
    with pytest.raises(ValueError, match="no location"):
        geo.check_against_profiles(table, extra)


def test_ingest_stores_both_files_and_load_reads_them_back(
    tmp_path, monkeypatch, geo_file, official_file
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    summary = geo.ingest(geo_file, official_file)
    assert (
        summary["houses"] == 3 and summary["postcodes"] == 2 and summary["checked_against_official"]
    )
    folder = tmp_path / "data" / "reference"
    assert (folder / geo.GEO_FILE).read_text() == GEO
    assert (folder / geo.OFFICIAL_FILE).read_text() == OFFICIAL
    assert geo.load()["house_id"].tolist() == ["AG-0001", "AG-0002", "AG-0003"]


def test_ingest_refuses_a_geo_file_that_disagrees_and_stores_nothing(
    tmp_path, monkeypatch, geo_file
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    wrong = write(tmp_path, "wrong.csv", OFFICIAL.replace("2076", "2077"))
    with pytest.raises(ValueError, match="postcode differs"):
        geo.ingest(geo_file, wrong)
    assert not (tmp_path / "data" / "reference").exists()


def test_load_says_how_to_add_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="data geo --from"):
        geo.load()


def test_the_command_checks_against_the_profiles_when_they_exist(
    tmp_path, monkeypatch, capsys, geo_file, official_file
):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        {"house_id": ["AG-0001", "AG-0002", "AG-0003"], "kwp": [3.78, 1.62, 1.0],
         "postcode": ["2076", "2259", "2259"], "gc_kw": 0.0}
    ).to_parquet(tmp_path / "data" / "profiles.parquet")  # fmt: skip
    code = data.main(["geo", "--from", str(geo_file), "--postcodes", str(official_file)])
    out = capsys.readouterr().out
    assert code == 0 and "3 houses in 2 postcodes" in out and "matches profiles.parquet" in out

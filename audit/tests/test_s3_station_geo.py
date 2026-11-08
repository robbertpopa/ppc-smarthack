"""S3: the place of the station is a constant; a Romanian station would get Sydney's sun."""

import inspect

import numpy as np
import pandas as pd

from audit.proposals import station_geo
from audit.tests.conftest import DATA, need
from src.ml import features
from src.ml.sun import solar_elevation

BUCHAREST = station_geo.StationGeo(44.43, 26.10, "Europe/Bucharest")


def test_feature_code_has_no_way_to_pass_a_location():
    for fn in (features.build, features.build_frame):
        assert not {"lat", "lon", "geo", "tz"} & set(inspect.signature(fn).parameters)


def test_bucharest_noon_is_night_for_the_current_code():
    noon = pd.DatetimeIndex(["2012-06-21 09:00"], tz="UTC")  # 12:00 in Bucharest
    assert solar_elevation(noon)[0] < 0  # what src.ml.features computes today
    geo = station_geo.time_features(noon + pd.Timedelta(hours=1), 60, BUCHAREST)
    assert geo["sun_elev_T"].iloc[0] > 60


def test_prototype_equals_todays_features_for_sydney(labels_a):
    sample = labels_a.iloc[::97]
    target = pd.DatetimeIndex(sample["interval_start"])
    today = features._compute(labels_a, target, 60)
    proto = station_geo.time_features(target, 60, station_geo.SYDNEY)
    for col in proto.columns:
        assert np.allclose(today[col].to_numpy(), proto[col].to_numpy()), col


def test_station_centroid_and_sunrise_spread(houses_a):
    need(DATA / "reference" / "ausgrid_postcodes_geo.csv")
    geo = pd.read_csv(DATA / "reference" / "ausgrid_postcodes_geo.csv")
    postcode_of = {
        f"AG-{c:04d}": pc for c, pc in zip(geo["Customer"], geo["Postcode"], strict=True)
    }
    station = station_geo.from_postcodes(
        houses_a["source_house_id"], postcode_of, geo, "Australia/Sydney"
    )
    east = station_geo.StationGeo(
        float(geo["lat"].iloc[geo["lon"].idxmax()]), float(geo["lon"].max()), "Australia/Sydney"
    )
    west = station_geo.StationGeo(
        float(geo["lat"].iloc[geo["lon"].idxmin()]), float(geo["lon"].min()), "Australia/Sydney"
    )
    spread = station_geo.sunrise_utc("2011-12-21", west) - station_geo.sunrise_utc(
        "2011-12-21", east
    )
    print(
        f"\nPT-A centroid {station.lat:.3f}, {station.lon:.3f}; sunrise spread across the "
        f"Ausgrid postcodes on 2011-12-21: {spread.total_seconds() / 60:.0f} min"
    )
    assert spread > pd.Timedelta(0)
    assert (station.lat, station.lon) != (station_geo.SYDNEY.lat, station_geo.SYDNEY.lon)

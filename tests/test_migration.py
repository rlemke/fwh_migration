"""Offline tests for the migration domain — join + render, no network.

``_fetch_indicator`` and ``_world_geojson`` are monkeypatched, so the World Bank
API and Natural Earth download are never hit; the join (per-year net count + rate
per 1,000) and the year-slider renderer are exercised end to end.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("FW_STORAGE", "local")
    monkeypatch.setenv("FW_DATA_ROOT", str(tmp_path))
    yield tmp_path


_NET = {
    "USA": {"2000": 1000000.0, "2010": 900000.0, "2020": 800000.0},
    "MEX": {"2000": -500000.0, "2010": -300000.0, "2020": -100000.0},
}
_POP = {
    "USA": {"2000": 282000000.0, "2010": 309000000.0, "2020": 331000000.0},
    "MEX": {"2000": 98000000.0, "2010": 114000000.0, "2020": 126000000.0},
}
_WORLD = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"NAME": "United States of America", "ISO_A3": "USA"},
         "geometry": {"type": "Point", "coordinates": [-98, 39]}},
        {"type": "Feature", "properties": {"NAME": "Mexico", "ISO_A3": "MEX"},
         "geometry": {"type": "Point", "coordinates": [-102, 23]}},
        {"type": "Feature", "properties": {"NAME": "Nowhere", "ISO_A3": "ZZZ"},
         "geometry": {"type": "Point", "coordinates": [0, 0]}},
    ],
}


def _patch(monkeypatch):
    from migration import _lib

    def fake_fetch(indicator):
        _lib._fetch_indicator._names = {"USA": "United States", "MEX": "Mexico"}
        return _NET if indicator == _lib.NET_INDICATOR else _POP

    monkeypatch.setattr(_lib, "_fetch_indicator", fake_fetch)
    monkeypatch.setattr(_lib, "_world_geojson", lambda: json.loads(json.dumps(_WORLD)))


def test_download_and_build(local_storage, monkeypatch):
    from migration import _lib

    _patch(monkeypatch)
    n = _lib.download_migration(force=True)
    assert n == 2

    res = _lib.build_migration_map()
    assert res.country_count == 2  # USA + MEX matched; Nowhere dropped
    assert (res.year_min, res.year_max) == (1960, 2025)

    fc = json.loads(open(_lib.cstore.localize(res.geojson_path)).read())
    props = {f["properties"]["NAME"]: f["properties"] for f in fc["features"]}
    usa = props["United States of America"]
    # net count + rate per 1,000 for a known year
    assert usa["c_2000"] == 1_000_000
    assert usa["r_2000"] == round(1_000_000 / 282_000_000 * 1000, 2)
    # Mexico is net emigration → negative
    assert props["Mexico"]["c_2020"] == -100_000
    assert props["Mexico"]["r_2020"] < 0
    # unmatched country carries no year props
    assert "c_2000" not in props["Nowhere"]


def test_html_has_year_slider_and_diverging(local_storage, monkeypatch):
    from migration import _lib

    _patch(monkeypatch)
    _lib.download_migration(force=True)
    res = _lib.build_migration_map()
    html = open(_lib.cstore.localize(res.html_path)).read()
    assert 'id="year" type="range"' in html          # year slider
    assert 'id="play"' in html                        # play button
    assert "function colorExpr" in html               # per-year choropleth
    assert "r_'+y" in html or "'r_'+y" in html         # colours the rate property
    assert "World Bank" in html and "Net migration" in html


def test_iso_alias_kosovo(local_storage, monkeypatch):
    from migration import _lib

    # WB uses XKX for Kosovo; NE geometry uses KOS — the alias must bridge them.
    world = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAME": "Kosovo", "ISO_A3": "-99", "ADM0_A3": "KOS"},
         "geometry": {"type": "Point", "coordinates": [21, 42]}}]}
    monkeypatch.setattr(_lib, "_world_geojson", lambda: json.loads(json.dumps(world)))

    def fake_fetch(indicator):
        _lib._fetch_indicator._names = {"XKX": "Kosovo"}
        return ({"XKX": {"2015": -20000.0}} if indicator == _lib.NET_INDICATOR
                else {"XKX": {"2015": 1800000.0}})
    monkeypatch.setattr(_lib, "_fetch_indicator", fake_fetch)

    _lib.download_migration(force=True)
    res = _lib.build_migration_map()
    assert res.country_count == 1
    fc = json.loads(open(_lib.cstore.localize(res.geojson_path)).read())
    assert fc["features"][0]["properties"]["c_2015"] == -20000


# ---------------------------------------------------------------------------
# Cache key: the parameters were recorded and never checked
# ---------------------------------------------------------------------------

def test_a_cache_built_for_different_parameters_is_not_reused(tmp_path, monkeypatch):
    """The blob always recorded indicator/year_min/year_max and nothing compared
    them, so widening the year range silently returned the old series under the
    same filename. Written and ignored is the worst kind of key: it looks like
    provenance and behaves like decoration."""
    from datetime import UTC, datetime

    from migration import _lib

    fresh = datetime.now(UTC).isoformat()
    same = {"indicator": _lib.NET_INDICATOR, "pop_indicator": _lib.POP_INDICATOR,
            "year_min": _lib.YEAR_MIN, "year_max": _lib.YEAR_MAX, "fetched_at": fresh}
    assert _lib._series_matches_request(same)

    for changed in (
        {**same, "year_max": _lib.YEAR_MAX - 5},      # narrower range
        {**same, "indicator": "SOMETHING.ELSE"},      # different metric
        {**same, "pop_indicator": "SOMETHING.ELSE"},  # different denominator
    ):
        assert not _lib._series_matches_request(changed)


def test_a_cache_with_no_timestamp_is_treated_as_expired():
    """Caches written before fetched_at existed must not be trusted forever.
    One re-download, once, is the right price for not knowing its age."""
    from migration import _lib

    assert _lib._age_hours(None) is None
    assert _lib._age_hours("not-a-date") is None


def test_the_series_is_stamped_so_freshness_is_answerable():
    """The World Bank revises these series on its own schedule. Without an
    expiry the map is pinned to whenever it was first built, because the cached
    file exists and nothing re-checks."""
    from datetime import UTC, datetime

    from migration import _lib

    assert _lib.SERIES_MAX_AGE_HOURS > 0
    assert _lib._age_hours(datetime.now(UTC).isoformat()) < 1.0

import json

import mapbox_vector_tile
import pytest

from app.garmin.client import CoachError
from app.services import climb_import
from app.services.climb_catalog import load_catalog
from app.services.climbs import haversine


def vector_fixture(multiplier=1, clipped_start=False, zoom=10):
    x, y = 539 * 2 ** (zoom - 10), 365 * 2 ** (zoom - 10)
    start, end = (-80, 100) if clipped_start else (100, 100), (160, 160)
    first = climb_import.lonlat((x * 4096 + start[0], y * 4096 + start[1]), zoom)
    last = climb_import.lonlat((x * 4096 + end[0], y * 4096 + end[1]), zoom)
    props = {
        "id": 123,
        "uuid": "8c111d17-0029-4287-a6f1-ea52a7fba391",
        "name_it": "Salita nominata da Paese",
        "length": haversine(first, last) * multiplier,
        "ascent": 100,
        "finishElevation": 500,
    }
    data = mapbox_vector_tile.encode(
        [
            {
                "name": "climblines",
                "features": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [start, end]},
                        "properties": props,
                    }
                ],
            },
            {
                "name": "climbpoints",
                "features": [
                    {"geometry": {"type": "Point", "coordinates": end}, "properties": props}
                ],
            },
        ],
        default_options={"y_coord_down": True},
    )
    bounds = [(last[1] - 0.001, last[0] - 0.001, last[1] + 0.001, last[0] + 0.001)]
    return data, bounds, first, last


def test_tile_projection_and_direction():
    data, _, first, last = vector_fixture()
    lines, points = climb_import.decode_tile(data, 10, 539, 365)
    assert climb_import.lonlat(lines[0][2][0], 10) == pytest.approx(first)
    assert climb_import.lonlat(lines[0][2][-1], 10) == pytest.approx(last)
    assert points["cf-123"]["point"] == pytest.approx(last)
    assert points["cf-123"]["summit_m"] == 500


def test_overlap_assembly_keeps_direction_and_rejects_gaps():
    route = [(i, i * 2) for i in range(10)]
    pieces = [route[:6], route[3:8], route[6:], route[:6]]
    assert climb_import.join_fragments(pieces) == [tuple(route)]
    assert len(climb_import.join_fragments([route[:4], route[6:]])) == 2
    assert len(climb_import.join_fragments([route[:6], list(reversed(route[3:]))])) == 2


def test_bounds_limit_and_validation():
    with pytest.raises(ValueError):
        climb_import.tile_coordinates([(-180, -80, 180, 80)], 10)
    with pytest.raises(ValueError):
        climb_import.tile_coordinates([(10, 45, 9, 46)], 10)
    with pytest.raises(ValueError):
        climb_import.tile_coordinates([(9, 45, 10, 46)], 8)
    with pytest.raises(ValueError):
        climb_import.tile_coordinates([(9, 45, float("nan"), 46)], 10)


def fake_service(monkeypatch, data):
    calls = []

    def fetch(url):
        calls.append(url)
        if url == climb_import.TILEJSON_URL:
            return json.dumps({"tiles": [climb_import.TILE_URL], "maxzoom": 14}).encode()
        return data

    monkeypatch.setattr(climb_import, "fetch", fetch)
    monkeypatch.setattr(climb_import.time, "sleep", lambda seconds: None)
    return calls


def test_catalog_import_cache_and_verified_source_link(tmp_path, monkeypatch):
    data, bounds, first, last = vector_fixture()
    calls = fake_service(monkeypatch, data)
    result = climb_import.import_catalog(tmp_path, bounds, progress=lambda line: None)
    assert result["added"] == 1 and result["downloaded"] == 1
    row = load_catalog(tmp_path / "climbfinder-catalog.json")["rows"][0]
    assert row["name"] == "Salita nominata da Paese"
    assert row["path"] == [first, last]
    assert (
        row["source_url"]
        == "https://climbfinder.com/it/mappa#climb=8c111d17-0029-4287-a6f1-ea52a7fba391"
    )
    first_calls = len(calls)
    again = climb_import.import_catalog(tmp_path, bounds, progress=lambda line: None)
    assert again["added"] == 0 and again["downloaded"] == 0
    assert len(calls) == first_calls


def test_clipped_geometry_is_not_accepted_as_complete(tmp_path, monkeypatch):
    data, bounds, _, _ = vector_fixture(multiplier=2)
    fake_service(monkeypatch, data)
    result = climb_import.import_catalog(tmp_path, bounds, progress=lambda line: None)
    assert result["routes"] == 0 and result["incomplete_or_ambiguous"] == 1


def test_clipped_start_rejected_even_when_length_matches(tmp_path, monkeypatch):
    data, bounds, _, _ = vector_fixture(clipped_start=True)
    fake_service(monkeypatch, data)
    result = climb_import.import_catalog(tmp_path, bounds, progress=lambda line: None)
    assert result["routes"] == 0


def test_service_failure_preserves_catalog(tmp_path, monkeypatch):
    data, bounds, _, _ = vector_fixture()
    fake_service(monkeypatch, data)
    climb_import.import_catalog(tmp_path, bounds, progress=lambda line: None)
    before = (tmp_path / "climbfinder-catalog.json").read_bytes()

    def unavailable(url):
        raise CoachError("Climbfinder HTTP 403", "climb_catalog", 503)

    monkeypatch.setattr(climb_import, "fetch", unavailable)
    with pytest.raises(CoachError):
        climb_import.import_catalog(tmp_path, bounds, refresh=True, progress=lambda line: None)
    assert (tmp_path / "climbfinder-catalog.json").read_bytes() == before


def test_detail_upgrade_preserves_aliases_source_and_regions_on_rejected_geometry(
    tmp_path, monkeypatch
):
    data, bounds, first, last = vector_fixture(zoom=14)
    row = {
        "id": "cf-123",
        "name": "Salita nominata da Paese",
        "source_url": "https://climbfinder.com/it/salite/prova",
        "aliases": ["Nome locale"],
        "distance_m": haversine(first, last),
        "gain_m": 100,
        "summit_m": 500,
        "path": [first, last],
        "geometry_zoom": 10,
    }
    path = tmp_path / "climbfinder-catalog.json"
    path.write_text(
        json.dumps({"source": "Climbfinder", "regions": ["Lombardia"], "rows": [row]}),
        encoding="utf-8",
    )
    fake_service(monkeypatch, data)
    result = climb_import.import_catalog(tmp_path, bounds, zoom=14, progress=lambda line: None)
    assert result["updated_geometries"] == 1
    catalog = load_catalog(path)
    upgraded = catalog["rows"][0]
    assert upgraded["geometry_zoom"] == 14
    assert upgraded["aliases"] == row["aliases"]
    assert upgraded["source_url"] == row["source_url"]
    assert catalog["regions"] == ["Lombardia"]
    upgraded.pop("geometry_zoom")
    path.write_text(json.dumps(catalog), encoding="utf-8")
    bad_data, _, _, _ = vector_fixture(zoom=14, clipped_start=True)
    fake_service(monkeypatch, bad_data)
    result = climb_import.import_catalog(
        tmp_path, bounds, zoom=14, refresh=True, progress=lambda line: None
    )
    assert result["updated_geometries"] == 0
    assert load_catalog(path)["rows"][0] == upgraded

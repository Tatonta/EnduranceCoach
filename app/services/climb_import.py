"""Personal catalog import from Climbfinder's public map vector service.

No account, API key, browser scraping or Garmin locations are used. Tile bounds
are chosen explicitly; cached responses make an interrupted import resumable.
"""

import json
import math
import time
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

import mapbox_vector_tile
from filelock import FileLock

from app.garmin.client import CoachError
from app.services.climb_catalog import load_catalog
from app.services.climbs import haversine
from app.services.planner import atomic_json

TILEJSON_URL = "https://pmtiles.climbfinder.com/climbs.json"
TILE_URL = "https://pmtiles.climbfinder.com/climbs/{z}/{x}/{y}.mvt"
DEFAULT_BOUNDS = [(8.4, 44.65, 11.43, 46.65), (12.3, 36.4, 15.7, 38.7)]


def tile_xy(lon, lat, zoom):
    scale = 2**zoom
    return (
        min(scale - 1, max(0, math.floor((lon + 180) / 360 * scale))),
        min(
            scale - 1,
            max(0, math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale)),
        ),
    )


def tile_coordinates(bounds, zoom):
    tiles = set()
    if not 10 <= zoom <= 14:
        raise ValueError("Zoom consentito: 10–14")
    for west, south, east, north in bounds:
        if not all(math.isfinite(v) for v in (west, south, east, north)) or not (
            -180 <= west < east <= 180 and -85 <= south < north <= 85
        ):
            raise ValueError("Area non valida: ovest,sud,est,nord")
        x0, y0 = tile_xy(west, north, zoom)
        x1, y1 = tile_xy(east, south, zoom)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > 512:
            raise ValueError("Area troppo grande: importa aree più piccole (massimo 512 tile)")
        tiles.update((zoom, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    if len(tiles) > 512:
        raise ValueError("Massimo 512 tile per importazione")
    return sorted(tiles)


def lonlat(point, zoom, extent=4096):
    scale = 2**zoom * extent
    x, y = point
    return [
        math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale)))),
        x / scale * 360 - 180,
    ]


def decode_tile(data, z, x, y):
    layers = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
    lines, finishes = [], {}
    for name in ("climblines", "climbpoints"):
        layer = layers.get(name, {})
        extent = layer.get("extent", 4096)
        for feature in layer.get("features", []):
            props, geom = feature["properties"], feature["geometry"]
            if "id" not in props or not props.get("uuid"):
                continue  # Cluster points are not climbs.
            aid = f"cf-{int(props['id'])}"
            if name == "climbpoints" and geom["type"] == "Point":
                p = geom["coordinates"]
                finishes[aid] = {
                    "point": lonlat((x * extent + p[0], y * extent + p[1]), z, extent),
                    "summit_m": props.get("finishElevation"),
                }
            elif name == "climblines" and geom["type"] in ("LineString", "MultiLineString"):
                paths = (
                    [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
                )
                for path in paths:
                    # Global integer Mercator coordinates align across tile boundaries.
                    nodes = [
                        (round((x + p[0] / extent) * 4096), round((y + p[1] / extent) * 4096))
                        for p in path
                    ]
                    nodes = [p for i, p in enumerate(nodes) if not i or p != nodes[i - 1]]
                    if len(nodes) > 1:
                        # The public service uses an 80-unit tile buffer.
                        # A clipped endpoint cannot become a full climb anchor.
                        clipped = [
                            nodes[i]
                            for i in (0, -1)
                            if any(v in (-80, extent + 80) for v in path[i])
                        ]
                        lines.append((aid, {**props, "_clipped_endpoints": clipped}, nodes))
    return lines, finishes


def path_length(nodes):
    return sum(math.dist(a, b) for a, b in zip(nodes, nodes[1:], strict=False))


def join_fragments(fragments):
    """Merge overlapping directed fragments; never bridge a missing tile or gap."""
    parts = list({tuple(p) for p in fragments})
    changed = True
    while changed:
        changed = False
        for i in range(len(parts)):
            a = parts[i]
            lookup = {p: j for j, p in enumerate(a)}
            for k in range(i + 1, len(parts)):
                b = parts[k]
                shared = [(lookup[p], j) for j, p in enumerate(b) if p in lookup]
                # Two shared vertices disambiguate intersections/reversed variants.
                if len(shared) < 2 or any(
                    u[0] >= v[0] for u, v in zip(shared, shared[1:], strict=False)
                ):
                    continue
                first_a, first_b = shared[0]
                last_a, last_b = shared[-1]
                prefix = (
                    a[:first_a]
                    if path_length(a[: first_a + 1]) >= path_length(b[: first_b + 1])
                    else b[:first_b]
                )
                suffix = (
                    a[last_a + 1 :]
                    if path_length(a[last_a:]) >= path_length(b[last_b:])
                    else b[last_b + 1 :]
                )
                parts[i] = tuple(prefix) + a[first_a : last_a + 1] + tuple(suffix)
                parts.pop(k)
                changed = True
                break
            if changed:
                break
    return parts


def fetch(url):
    try:
        with urlopen(
            Request(
                url, headers={"User-Agent": "GarminAdaptiveCoach/0.1 (personal local catalog)"}
            ),
            timeout=30,
        ) as response:
            data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise ValueError("Risposta tile troppo grande")
            return data
    except HTTPError as exc:
        raise CoachError(
            f"Climbfinder HTTP {exc.code}: importazione interrotta; cache conservata",
            "climb_catalog",
            503,
        ) from None
    except (URLError, TimeoutError):
        raise CoachError(
            "Climbfinder non raggiungibile; cache conservata", "climb_catalog", 503
        ) from None


def name_key(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name).casefold() if c.isalnum())


def import_catalog(data_dir: Path, bounds=None, zoom=10, refresh=False, progress=print):
    bounds = DEFAULT_BOUNDS if bounds is None else bounds
    tiles = tile_coordinates(bounds, zoom)
    with FileLock(str(data_dir / ".climb-import.lock"), timeout=1):
        return _import(data_dir, bounds, zoom, tiles, refresh, progress)


def _import(data_dir, bounds, zoom, tiles, refresh, progress):
    path = data_dir / "climbfinder-catalog.json"
    catalog = load_catalog(path)
    cache = data_dir / "climbfinder-tiles"
    cache.mkdir(parents=True, exist_ok=True)
    metadata_path = cache / "tilejson.json"
    if refresh or not metadata_path.exists():
        metadata_path.write_bytes(fetch(TILEJSON_URL))
    metadata = json.loads(metadata_path.read_bytes())
    if metadata.get("tiles") != [TILE_URL] or metadata.get("maxzoom", 0) < zoom:
        raise ValueError("Il formato del servizio Climbfinder è cambiato; catalogo conservato")
    lines, props, finishes, clipped = defaultdict(list), {}, {}, defaultdict(set)
    downloaded = 0
    for number, (z, x, y) in enumerate(tiles, 1):
        tile_path = cache / f"{z}-{x}-{y}.mvt"
        if refresh or not tile_path.exists():
            data = fetch(TILE_URL.format(z=z, x=x, y=y))
            # Validate before caching so a failed download can be retried safely.
            decoded = decode_tile(data, z, x, y)
            temp = tile_path.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(tile_path)
            downloaded += 1
            time.sleep(0.15)
        else:
            decoded = decode_tile(tile_path.read_bytes(), z, x, y)
        fragments, points = decoded
        for aid, properties, nodes in fragments:
            props[aid] = properties
            lines[aid].append(nodes)
            clipped[aid].update(properties["_clipped_endpoints"])
        finishes.update(points)
        if number % 10 == 0 or number == len(tiles):
            progress(f"Climbfinder: {number}/{len(tiles)} tile · {len(lines)} salite individuate")
    index_path = data_dir / "climbfinder-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    index_by_name = defaultdict(list)
    for row in index:
        index_by_name[name_key(row["name"])].append(row)
    rows = {r["id"]: r for r in catalog["rows"]}
    previous_ids = {r["id"] for r in catalog["rows"]}
    added, updated, rejected = 0, 0, 0
    point_tiles = set()
    for aid, fragments in lines.items():
        upgrade = aid in rows and zoom >= 12 and zoom > rows[aid].get("geometry_zoom", 0)
        if aid in rows and not upgrade:
            if props[aid].get("name_it"):
                rows[aid] = {**rows[aid], "name": props[aid]["name_it"]}
            continue  # Never downgrade an existing reference geometry.
        point, properties = finishes.get(aid), props[aid]
        name = properties.get("name_it") or properties.get("name_en")
        length = properties.get("length", 0)
        if not name or length <= 0:
            rejected += 1
            continue
        parts = join_fragments(fragments)
        valid = []
        for part in parts:
            if part[0] in clipped[aid] or part[-1] in clipped[aid]:
                continue
            geometry = [lonlat(p, zoom) for p in part]
            lat, lon = geometry[-1]
            if not any(w <= lon <= e and s <= lat <= n for w, s, e, n in bounds):
                continue
            measured = sum(haversine(a, b) for a, b in zip(geometry, geometry[1:], strict=False))
            # Even full-page lines differ from the source's nominal distance.
            # Unclipped endpoints establish completeness; length checks sanity.
            if abs(measured / length - 1) <= 0.08 and (
                not point or haversine(geometry[-1], point["point"]) <= 35
            ):
                valid.append(geometry)
        if len(valid) != 1:
            rejected += 1
            continue
        uuid = str(UUID(properties["uuid"]))
        candidates = index_by_name[name_key(name)]
        if not point or point["summit_m"] is None:
            # Overview tiles cluster some summit markers. Retrieve only their
            # detailed point tiles; no individual HTML pages are needed.
            lat, lon = valid[0][-1]
            px, py = tile_xy(lon, lat, 14)
            key = (14, px, py)
            if key not in point_tiles:
                tile_path = cache / f"14-{px}-{py}.mvt"
                if refresh or not tile_path.exists():
                    data = fetch(TILE_URL.format(z=14, x=px, y=py))
                    _, points = decode_tile(data, 14, px, py)
                    tile_path.write_bytes(data)
                    downloaded += 1
                    time.sleep(0.15)
                else:
                    _, points = decode_tile(tile_path.read_bytes(), 14, px, py)
                finishes.update(points)
                point_tiles.add(key)
                if len(point_tiles) % 20 == 0:
                    progress(
                        f"Climbfinder: {len(point_tiles)} tile di dettaglio per le quote di arrivo"
                    )
            point = finishes.get(aid)
            if (
                not point
                or point["summit_m"] is None
                or haversine(valid[0][-1], point["point"]) > 35
            ):
                rejected += 1
                continue
        url = (
            candidates[0]["url"]
            if len(candidates) == 1
            else f"https://climbfinder.com/it/mappa#climb={uuid}"
        )
        if aid in rows:
            url = rows[aid]["source_url"]
        rows[aid] = {
            **rows.get(aid, {}),
            "id": aid,
            "name": name,
            "source_url": url,
            "distance_m": length,
            "gain_m": properties["ascent"],
            "summit_m": point["summit_m"],
            "path": valid[0],
            "geometry_source": "Climbfinder vector tiles",
            "geometry_zoom": zoom,
        }
        added += aid not in previous_ids
        updated += upgrade
    result = {
        **catalog,
        "source": "Climbfinder",
        "imported_at": datetime.now(UTC).isoformat(),
        "regions": ["Lombardia e aree confinanti", "Sicilia"]
        if bounds == DEFAULT_BOUNDS
        else catalog.get("regions", []),
        "bounds": list(dict.fromkeys(tuple(b) for b in [*catalog.get("bounds", []), *bounds])),
        "index_count": max(len(index), len(rows)),
        "rows": list(rows.values()),
        "import": {
            "service": TILEJSON_URL,
            "zoom": zoom,
            "tiles": len(tiles),
            "summit_tiles": len(point_tiles),
            "downloaded": downloaded,
            "added": added,
            "updated_geometries": updated,
            "incomplete_or_ambiguous": rejected,
        },
    }
    # Validate the entire result before replacing the previous working catalog.
    validation = cache / "validated-catalog.json"
    atomic_json(validation, result)
    load_catalog(validation)
    atomic_json(path, result)
    return {**result["import"], "routes": len(rows), "catalog": str(path)}

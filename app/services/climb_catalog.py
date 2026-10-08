"""Private, local Climbfinder catalog. No Garmin coordinates leave this computer."""

import json
import math
from urllib.parse import urlsplit
from uuid import UUID


def valid_source(url):
    if url.scheme != "https" or url.hostname != "climbfinder.com" or url.username or url.password:
        return False
    if url.path.startswith("/it/salite/"):
        return True
    if url.path == "/it/mappa" and url.fragment.startswith("climb="):
        try:
            UUID(url.fragment.removeprefix("climb="))
            return True
        except ValueError:
            pass
    return False


def load_catalog(path):
    if not path.exists():
        return {"source": "Climbfinder", "regions": [], "rows": [], "index_count": 0}
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    seen = set()
    for row in catalog["rows"]:
        url = urlsplit(row["source_url"])
        if (
            not valid_source(url)
            or row["id"] in seen
            or not row["name"].strip()
            or not all(
                isinstance(row.get(k), (int, float)) and math.isfinite(row[k])
                for k in ("distance_m", "gain_m", "summit_m")
            )
            or row["distance_m"] <= 0
            or row["gain_m"] < 0
            or len(row["path"]) < 2
            or not all(
                len(p) == 2
                and all(isinstance(v, (float, int)) and math.isfinite(v) for v in p)
                and -90 <= p[0] <= 90
                and -180 <= p[1] <= 180
                for p in row["path"]
            )
        ):
            raise ValueError("Catalogo Climbfinder locale non valido")
        seen.add(row["id"])
    return catalog

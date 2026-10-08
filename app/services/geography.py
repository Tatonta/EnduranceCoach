"""Offline geographic lookup. Coordinates never leave this computer."""

import io
import threading
import zipfile

import shapefile

from app.config import ROOT

COUNTRIES = {
    "Italy": "Italia",
    "France": "Francia",
    "Switzerland": "Svizzera",
    "Austria": "Austria",
    "Germany": "Germania",
    "Spain": "Spagna",
    "United Kingdom": "Regno Unito",
}
REGIONS = {
    "Sicily": "Sicilia",
    "Sardinia": "Sardegna",
    "Apulia": "Puglia",
    "Piedmont": "Piemonte",
    "Tuscany": "Toscana",
}


def inside_polygon(lon, lat, shape):
    inside = False
    ends = list(shape.parts[1:]) + [len(shape.points)]
    for start, end in zip(shape.parts, ends, strict=True):
        ring = shape.points[start:end]
        if not ring:
            continue
        previous = ring[-1]
        for current in ring:
            if (current[1] > lat) != (previous[1] > lat) and lon < (
                (previous[0] - current[0]) * (lat - current[1]) / (previous[1] - current[1])
                + current[0]
            ):
                inside = not inside
            previous = current
    return inside


class Geography:
    def __init__(self):
        self.reader = None
        self.lock = threading.RLock()

    def lookup(self, lat, lon):
        with self.lock:
            if self.reader is None:
                path = ROOT / "app/assets/ne_10m_admin_1_states_provinces.zip"
                if not path.exists():
                    return {
                        "country": "Paese non identificato",
                        "region": "Regione non identificata",
                        "zone": "",
                    }
                with zipfile.ZipFile(path) as archive:
                    base = "ne_10m_admin_1_states_provinces"
                    self.reader = shapefile.Reader(
                        shp=io.BytesIO(archive.read(base + ".shp")),
                        dbf=io.BytesIO(archive.read(base + ".dbf")),
                        shx=io.BytesIO(archive.read(base + ".shx")),
                    )
            for record in self.reader.iterShapeRecords(
                fields=["admin", "name", "name_it", "region"], bbox=(lon, lat, lon, lat)
            ):
                if inside_polygon(lon, lat, record.shape):
                    values = record.record.as_dict()
                    area = values["name_it"] or values["name"] or "Zona non identificata"
                    region = values["region"] or area
                    return {
                        "country": COUNTRIES.get(values["admin"], values["admin"]),
                        "region": REGIONS.get(region, region),
                        "zone": area,
                    }
        return {
            "country": "Paese non identificato",
            "region": "Regione non identificata",
            "zone": "",
        }

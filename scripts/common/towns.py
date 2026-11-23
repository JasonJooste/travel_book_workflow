"""GeoNames towns (cities500), for naming places and finding their time zones."""
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.geo import distance_km
from repo import CITIES
from settings import settings

RADIUS_CAP_KM = 200  # Towns.near doubles its radius where there are none, up to this


class Towns:
    """GeoNames cities500, bucketed by whole degree for quick nearby searches."""

    def __init__(self, cities_txt=CITIES):
        if not cities_txt.exists():
            raise SystemExit(f"{cities_txt} is missing: run make geonames")
        self.cells, self.zones, self.zone_info = {}, {}, {}
        with open(cities_txt, encoding="utf-8") as f:
            for line in f:
                cols = line.split("\t")
                if cols[7] == "PPLX":  # districts of a bigger town
                    continue
                lat, lon = float(cols[4]), float(cols[5])
                self.cells.setdefault((math.floor(lat), math.floor(lon)), []).append(
                    (cols[1], lat, lon, int(cols[14] or 0), cols[8]))
                self.zones[(lat, lon)] = cols[17]

    def zone(self, lat, lon):
        """The time zone (ZoneInfo) of the closest town, or None."""
        town = min(((tlat, tlon) for _, tlat, tlon, _, _ in self.nearby(lat, lon)),
                   key=lambda t: distance_km(lat, lon, *t), default=None)
        name = self.zones.get(town) if town else None
        if name and name not in self.zone_info:
            try:
                self.zone_info[name] = ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                self.zone_info[name] = None
        return self.zone_info.get(name) if name else None

    def nearby(self, lat, lon):
        """(name, lat, lon, population, country) of towns in the cells around lat, lon."""
        for dlat in (-2, -1, 0, 1, 2):
            for dlon in (-2, -1, 0, 1, 2):
                yield from self.cells.get((math.floor(lat) + dlat, math.floor(lon) + dlon), [])

    def nearest(self, lat, lon):
        """(name, country code, km) of the closest town, or None."""
        return min(((name, country, distance_km(lat, lon, tlat, tlon))
                    for name, tlat, tlon, _, country in self.nearby(lat, lon)),
                   key=lambda t: t[2], default=None)

    def near(self, lat, lon, radius_km=None, limit=None):
        """Names of the most populous towns within radius_km, nearest first among equals.

        Where there are none (deserts), the radius doubles, up to RADIUS_CAP_KM."""
        radius_km = radius_km or settings.lookup.town_radius_km
        limit = limit or settings.lookup.towns
        found = []
        for name, tlat, tlon, pop, _ in self.nearby(lat, lon):
            km = distance_km(lat, lon, tlat, tlon)
            if km <= radius_km:
                found.append((-pop, km, name))
        if not found and radius_km < RADIUS_CAP_KM:
            return self.near(lat, lon, radius_km * 2, limit)
        return list(dict.fromkeys(name for _, _, name in sorted(found)))[:limit]

    def describe(self, lat, lon, big_km=None):
        """Nearest town, with the biggest one within big_km in brackets if that's another."""
        nearest = self.nearest(lat, lon)
        if not nearest:
            return "?"
        big_km = big_km or settings.stays.big_town_km
        big = [(pop, name) for name, tlat, tlon, pop, _ in self.nearby(lat, lon)
               if distance_km(lat, lon, tlat, tlon) <= big_km]
        big = max(big, default=(0, nearest[0]))[1]
        return nearest[0] if big == nearest[0] else f"{nearest[0]} ({big})"

"""Distances on the earth, and a flat projection for the few km around a point."""
import math


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


def length_km(line):
    """Length of a line of (lat, lon)s."""
    return sum(distance_km(*p, *q) for p, q in zip(line, line[1:]))


def kmh(a, b):
    """Speed between two (utc, lat, lon, ...) points, timed to at least a minute: times are to the minute."""
    hours = max(abs((b[0] - a[0]).total_seconds()) / 3600, 1 / 60)
    return distance_km(a[1], a[2], b[1], b[2]) / hours


class Flat:
    """A local flat projection in km, good for a few km around its origin."""

    def __init__(self, lat, lon=0.0):
        self.lat, self.lon, self.kx = lat, lon, 111.32 * math.cos(math.radians(lat))

    def xy(self, lat, lon):
        return ((lon - self.lon) * self.kx, (lat - self.lat) * 110.57)

    def latlon(self, x, y):
        return (self.lat + y / 110.57, self.lon + x / self.kx)

"""Photo sidecars (.xmp, from the gallery app) are left out: the photos carry their own EXIF, and the
sidecars have no GPS."""
PATTERNS = ["photos/*.xmp"]
DROP = True

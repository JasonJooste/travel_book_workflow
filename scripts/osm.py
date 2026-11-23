#!/usr/bin/env python3
"""OpenStreetMap for the regions the trip passed through, for routing and river crossings.

Usage: osm.py

Each region in osm.regions (settings.yaml) is downloaded once from Geofabrik into
processing/osm/extracts (delete one to refresh it). Those under osm.bike_prefixes have
motorroad=yes taken off every way, which keeps bikes off trunk roads that everyone rides (a
mapping habit in Africa, the law in Europe), and the motorways in osm.ridden_motorways opened to
bikes, with the links onto them: processing/osm/bike. Then all of them are merged into
processing/osm/trip.osm.pbf, and from it:

  waterways.geojsonseq   rivers, canals, tidal channels, bridges and fords, for make check's crossings
  valhalla/              Valhalla's routing tiles (tiles.tar) and config, for make route: a few hours

Each step runs only when its inputs are newer than its output, so a rerun is quick.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from repo import OSM, VALHALLA_CONFIG
from settings import settings

O = settings.osm
GEOFABRIK = "https://download.geofabrik.de/"
VENV_BIN = Path(sys.executable).parent


def newer(output, inputs):
    """Whether output is missing or older than any of inputs."""
    return not output.exists() or any(p.stat().st_mtime > output.stat().st_mtime for p in inputs)


def download(region):
    path = OSM / "extracts" / f"{region}.osm.pbf"
    if not path.exists():
        print(f"downloading {region}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".tmp.{path.name}")
        request = urllib.request.Request(f"{GEOFABRIK}{region}-latest.osm.pbf", headers={"User-Agent": "travel_book osm.py"})
        with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
        tmp.replace(path)
    return path


def bike(src, out):
    """src without motorroad=yes, and with the ridden motorways (and the links onto them) open to bikes."""
    import osmium
    ridden_names = set(O.ridden_motorways)

    def ridden(tags):
        return tags.get("name") in ridden_names or tags.get("bridge:name") in ridden_names

    # First pass: the nodes of the ridden ways, and of every motorway_link, to find the links onto
    # them: ramps often chain, one link reaching the road only through another
    ridden_nodes, links = set(), {}
    for w in osmium.FileProcessor(str(src), osmium.osm.WAY):
        if ridden(w.tags):
            ridden_nodes.update(n.ref for n in w.nodes)
        elif w.tags.get("highway") == "motorway_link":
            links[w.id] = [n.ref for n in w.nodes]
    open_links, grew = set(), True
    while grew:
        grew = False
        for wid, nodes in links.items():
            if wid not in open_links and any(n in ridden_nodes for n in nodes):
                open_links.add(wid)
                ridden_nodes.update(nodes)
                grew = True
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".tmp.{out.name}")
    changed = opened = 0
    with osmium.SimpleWriter(str(tmp), overwrite=True) as writer:
        for obj in osmium.FileProcessor(str(src)):
            if obj.is_way():
                tags = {t.k: t.v for t in obj.tags}
                if tags.get("motorroad") == "yes":
                    del tags["motorroad"]
                    changed += 1
                if ridden(tags) or obj.id in open_links:
                    tags["bicycle"] = "yes"
                    opened += 1
                if tags != {t.k: t.v for t in obj.tags}:
                    obj = obj.replace(tags=tags)
            writer.add(obj)
    tmp.replace(out)
    print(f"{src.name}: motorroad=yes taken off {changed} ways; {opened} ways of ridden motorways opened to bikes")


def run(*command, env=None):
    print(" ".join(map(str, command)), flush=True)
    subprocess.run([str(c) for c in command], check=True, env=env)


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    inputs = []
    for region in O.regions:
        extract = download(region)
        if any(region.startswith(p) for p in O.bike_prefixes):
            out = OSM / "bike" / f"{region}.osm.pbf"
            if newer(out, [extract]):
                bike(extract, out)
            inputs.append(out)
        else:
            inputs.append(extract)

    trip = OSM / "trip.osm.pbf"
    if newer(trip, inputs):
        run("osmium", "merge", "--overwrite", "-o", trip, *inputs)

    waterways = OSM / "waterways.geojsonseq"
    if newer(waterways, [trip]):
        filtered = OSM / "waterways.osm.pbf"
        run("osmium", "tags-filter", "--overwrite", "-o", filtered, trip,
            f"w/waterway={','.join(settings.checks.waterways)}", "w/bridge", "w/ford", "n/ford")
        run("osmium", "export", "--overwrite", "-f", "geojsonseq", "--geometry-types=point,linestring",
            "-o", waterways, filtered)

    valhalla = VALHALLA_CONFIG.parent
    tiles = valhalla / "tiles.tar"
    if newer(tiles, [trip]):
        valhalla.mkdir(parents=True, exist_ok=True)
        metres = str(int(O.max_route_km * 1000))
        config = subprocess.run(
            [VENV_BIN / "valhalla_build_config", "--mjolnir-tile-dir", valhalla / "tiles",
             "--mjolnir-tile-extract", tiles, "--mjolnir-admin", valhalla / "admins.sqlite",
             "--mjolnir-timezone", valhalla / "timezones.sqlite",
             "--service-limits-bicycle-max-distance", metres, "--service-limits-pedestrian-max-distance", metres],
            check=True, capture_output=True, text=True).stdout
        json.loads(config)  # it's JSON, or the step failed
        VALHALLA_CONFIG.write_text(config)
        # pyvalhalla's commands look for themselves on PATH
        env = {**os.environ, "PATH": f"{VENV_BIN}:{os.environ['PATH']}"}
        run("valhalla_build_admins", "-c", VALHALLA_CONFIG, trip, env=env)
        run("valhalla_build_tiles", "-c", VALHALLA_CONFIG, trip, env=env)
        run(VENV_BIN / "valhalla_build_extract", "-c", VALHALLA_CONFIG, "-v", "--overwrite", env=env)
        subprocess.run(["rm", "-rf", str(valhalla / "tiles")], check=True)
    print(f"OSM up to date: {len(O.regions)} regions, {OSM / 'trip.osm.pbf'}")


if __name__ == "__main__":
    main()

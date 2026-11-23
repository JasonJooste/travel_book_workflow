"""The Route view's data: the route to draw, its anchors, and one list of things to look at.

  GET /api/route/line      every point of the route (recorded ones thinned) as [lat*1e5, lon*1e5,
                           minutes since 1970 UTC, class index], with the classes and their colours
  GET /api/route/anchors   the photos, known places and stays the route was drawn through, each with
                           the row it came from
  GET /api/route/items     what to look at, in time order: every finding of make check, every gap leg
                           (a stretch with no recording, routed or drawn straight) and every run of hops
                           (short steps between fixed points). Each has its span, in UTC and local time,
                           its facts and its status:
                             todo       still to look at
                             labelled   a travel mode row now covers it (gap legs, hops, findings that
                                        suggest a label)
                             dismissed  you said it looks fine
                             pending    a row it's about changed since make check: rebuild to see
"""
import bisect
from datetime import datetime, timedelta, timezone

from common.geo import distance_km
from common.tables import read_json, read_rows
from common.times import parse
from repo import DISMISSED_CSV, FINDINGS, KNOWN_PLACES_CSV, ROUTE, STAYS_CSV
from route import covers
from settings import settings
from shared import cached, when
from store import rows

SPACING_KM = 0.03  # recorded points closer together than this are drawn as one
CLASSES = settings.classes
BUILT_WITH = ROUTE / "findings_built_with.json"


def minutes(t):
    return int(t.timestamp() // 60)


def line():
    def load():
        kept, last = [], None
        for r in read_rows(ROUTE / "route.csv"):
            lat, lon, cls = float(r["lat"]), float(r["lon"]), CLASSES.index(r["class"])
            if (last and r["source"] == "recorded" and cls == last[3]
                    and distance_km(last[0] / 1e5, last[1] / 1e5, lat, lon) < SPACING_KM):
                continue
            last = [round(lat * 1e5), round(lon * 1e5), minutes(parse(r["utc"])), cls]
            kept.append(last)
        return {"classes": CLASSES, "colours": settings.colours, "modes": list(settings.modes), "points": kept}
    return cached([ROUTE / "route.csv"], load)


def anchors():
    def load():
        places = {r["id"]: r for r in rows("known_places")}
        stays = {r["id"]: r for r in rows("stays")}
        out = []
        for r in read_rows(ROUTE / "route.csv"):
            if r["source"] not in ("photo", "known_place", "stay"):
                continue
            a = {"lat": float(r["lat"]), "lon": float(r["lon"]), "t": minutes(parse(r["utc"])), "utc": r["utc"],
                 "source": r["source"], "ref": r["ref"]}
            if r["source"] == "known_place" and r["ref"] in places:
                a["row"] = places[r["ref"]]
            elif r["source"] == "stay" and r["ref"] in stays:
                s = stays[r["ref"]]
                a["row"] = {k: s[k] for k in ("id", "town", "first_night", "leaving")}
            out.append(a)
        return out
    return cached([ROUTE / "route.csv", KNOWN_PLACES_CSV, STAYS_CSV], load)


def hop_runs(route, legs):
    """Runs of hops: steps of up to route.gap_km between fixed points (photos, known places, stays) that
    aren't gap legs, so they're drawn straight, and that go somewhere. Runs split at stops and gap legs."""
    spans = {(g["start_utc"], g["end_utc"]) for g in legs}
    runs, run = [], []
    for p, q in zip(route, route[1:]):
        hop = ("routed" not in (p["source"], q["source"]) and not p["source"] == q["source"] == "recorded"
               and (p["utc"], q["utc"]) not in spans)
        km = distance_km(float(p["lat"]), float(p["lon"]), float(q["lat"]), float(q["lon"])) if hop else 0
        if not hop or km < settings.route.still_km or (run and run[-1][1]["utc"] != p["utc"]):
            if run:
                runs.append(run)
            run = []
        if hop and km >= settings.route.still_km:
            run.append((p, q, km))
    if run:
        runs.append(run)
    return runs


def mode_rows():
    """(start, end, mode, note, id) of the travel mode rows now, as make route reads them."""
    out = []
    for r in rows("travel_modes"):
        try:
            start = datetime.fromisoformat(r["start"]).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(r["end"] or r["start"]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if "T" not in (r["end"] or r["start"]):
            end += timedelta(days=1)
        out.append((start, end, r["mode"], r["note"], r["id"]))
    return out


def static_items():
    """The items as built, without their status: that depends on the rows now."""
    def load():
        legs = read_rows(ROUTE / "legs.csv")
        route = read_rows(ROUTE / "route.csv")
        items = []
        for f in read_json(FINDINGS, []):
            items.append({**f, "kind": "finding", "start": f["start_utc"], "end": f["end_utc"]})
        for g in legs:
            km, hours = float(g["routed_km"]), float(g["hours"])
            start, end = parse(g["start_utc"]), parse(g["end_utc"])
            p = next((r for r in route if r["utc"] >= g["start_utc"]), route[0])
            items.append({"id": f"leg:{g['start_utc']}", "kind": "leg", "check": "leg",
                          "title": f"{g['from']} → {g['to']}", "start": g["start_utc"], "end": g["end_utc"],
                          "lat": float(p["lat"]), "lon": float(p["lon"]),
                          "facts": {k: v for k, v in {
                              "km": km, "straight_km": float(g["straight_km"]), "hours": hours,
                              "kmh": round(km / max(hours, 1 / 60)), "class": g["class"], "router": g["router"],
                              "mode_note": g["mode_note"], "flags": g["flags"], "from": g["from"], "to": g["to"]}.items()
                              if v not in ("", None)},
                          "flagged": bool(g["flags"]),
                          "fix": {"action": "label", "start": g["start_utc"][:-1], "end": g["end_utc"][:-1],
                                  "mode": g["mode"] or "cycled", "note": g["mode_note"] or f"{g['from']} to {g['to']}"},
                          "minutes": (end - start).total_seconds() / 60})
        for run in hop_runs(route, legs):
            p, q = run[0][0], run[-1][1]
            km = sum(k for *_, k in run)
            items.append({"id": f"hops:{p['utc']}", "kind": "hops", "check": "hops",
                          "title": f"{len(run)} short hop{'s' if len(run) > 1 else ''} between fixed points",
                          "start": p["utc"], "end": q["utc"], "lat": float(p["lat"]), "lon": float(p["lon"]),
                          "facts": {"km": round(km, 1), "hops": len(run), "drawn": "straight, each under "
                                    f"{settings.route.gap_km:g} km"},
                          "parts": [[a["utc"], b["utc"]] for a, b, _ in run],
                          "fix": {"action": "label", "start": p["utc"][:-1], "end": q["utc"][:-1], "mode": "cycled",
                                  "note": ""}})
        for item in items:
            item["when"] = {"start": when(item["start"], item["lat"], item["lon"]),
                            "end": when(item["end"], item["lat"], item["lon"])}
            item["t"] = [minutes(parse(item["start"])), minutes(parse(item["end"]))]
        items.sort(key=lambda i: (i["start"], i["end"], i["kind"]))
        return items
    return cached([FINDINGS, ROUTE / "legs.csv", ROUTE / "route.csv"], load)


def changed_spans():
    """(start, end) of the travel mode rows added, changed or deleted since make check, and the days
    of the known places likewise."""
    built = read_json(BUILT_WITH, {"travel_modes": {}, "known_places": {}})
    now_modes = {r["id"]: [r["start"], r["end"], r["mode"], r["note"]] for r in rows("travel_modes")}
    spans = []
    for key in set(built["travel_modes"]) | set(now_modes):
        a, b = built["travel_modes"].get(key), now_modes.get(key)
        if a != b:
            for row in (a, b):
                if row:
                    try:
                        start = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
                        end = datetime.fromisoformat(row[1] or row[0]).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    spans.append((start, end + (timedelta(days=1) if "T" not in (row[1] or row[0]) else timedelta())))
    now_places = {r["id"]: [r["start_date"], r["end_date"], r["time"], r["lat"], r["lon"]] for r in rows("known_places")}
    for key in set(built["known_places"]) | set(now_places):
        a, b = built["known_places"].get(key), now_places.get(key)
        if a != b:
            for row in (a, b):
                if row:
                    first = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
                    last = datetime.fromisoformat(row[1] or row[0]).replace(tzinfo=timezone.utc)
                    spans.append((first - timedelta(hours=14), last + timedelta(hours=38)))
    return spans


def near(modes, starts, a, b):
    """The rows that may cover a to b: those starting before b (rows are sorted by start), and ending after a."""
    i = bisect.bisect_right(starts, b)
    return [r for r in modes[:i] if r[1] >= a]


def items():
    """Every item with its status now."""
    modes = sorted(mode_rows())
    starts = [r[0] for r in modes]
    dismissed = {r["id"] for r in read_rows(DISMISSED_CSV)}
    changed = changed_spans()
    out = []
    for item in static_items():
        start, end = parse(item["start"]), parse(item["end"])
        if item.get("dismissed") in dismissed:
            status = "dismissed"
        elif item["kind"] == "hops":
            parts = [(parse(a), parse(b)) for a, b in item["parts"]]
            status = ("labelled" if all(any(covers(r, (a,), (b,)) for r in near(modes, starts, a, b)) for a, b in parts)
                      else "todo")
        elif item["kind"] == "leg":
            status = "labelled" if any(covers(r, (start,), (end,)) for r in near(modes, starts, start, end)) else "todo"
        elif (item.get("fix") or {}).get("action") == "label" and any(
                covers(r, (start,), (end,)) for r in near(modes, starts, start, end)):
            status = "labelled"
        elif any(a <= end and start <= b for a, b in changed):
            status = "pending"
        else:
            status = "todo"
        out.append({**item, "status": status})
    return out


def handle(method, parts, query, body):
    if method == "GET" and parts == ["line"]:
        return line()
    if method == "GET" and parts == ["anchors"]:
        return anchors()
    if method == "GET" and parts == ["items"]:
        return items()
    return None


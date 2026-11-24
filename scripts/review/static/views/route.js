// The Route view: how each stretch was travelled, and what looks wrong.
//
// The list holds everything to look at: make check's findings (river crossings, suggested modes, legs
// too fast, spikes...), every gap leg (no recording: routed or drawn straight) and every run of short
// hops. Each shows its span in local time, its facts as fields, the travel mode rows it's about, and
// the actions that settle it. Rows: the travel mode rows themselves, to find and edit.
// On the map: click the route twice to select a stretch and label it; click a photo, known place or
// stay dot to see it and drag it somewhere else.
import {
  Action, Facts, MapView, ModeChip, Pill, Queue, SETTINGS, api, change, colour, dot, fmtKm, fmtMinutes, fmtOffset,
  go, html, plain, step, useData, useEffect, useKeys, useLayer, useMemo, useRef, useState,
} from "../lib.js";

const toMin = (text, end = false) => {
  if (!text) return null;
  const t = Date.parse((text.length === 10 ? text + "T00:00" : text) + ":00Z") / 60000;
  return isNaN(t) ? null : text.length === 10 && end ? t + 1440 : t;
};
const utcText = m => new Date(m * 60000).toISOString().slice(0, 16);
const STATUS = { todo: "to do", labelled: "labelled", dismissed: "fine", pending: "wait for rebuild" };
const SOURCES = { photo: ["photo", "#ff7f0e"], known_place: ["known place", "#555"], stay: ["stay", "#1f77b4"] };

// Local times of minutes picked on the map, from the UTC offsets through the trip
function useLocal() {
  const offsets = useData("offsets");
  return useMemo(() => {
    const table = offsets.data || [];
    return m => {
      let lo = 0, hi = table.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (table[mid][0] < m) lo = mid + 1; else hi = mid; }
      const near = [table[lo - 1], table[lo]].filter(Boolean).sort((a, b) => Math.abs(a[0] - m) - Math.abs(b[0] - m))[0];
      const offset = near ? Math.round(near[1] / 15) * 15 : 0;
      return { utc: utcText(m) + "Z", local: utcText(m + offset), offset };
    };
  }, [offsets.data]);
}

function When({ a, b }) {
  if (!a) return null;
  const minutes = b ? toMin(b.utc.slice(0, 16)) - toMin(a.utc.slice(0, 16)) : 0;
  const day = l => { const d = new Date(Date.parse(l.slice(0, 10))); return d.toUTCString().slice(0, 16); };
  const same = b && a.local.slice(0, 10) === b.local.slice(0, 10);
  return html`<div class="when" title=${`UTC ${a.utc}${b ? " to " + b.utc : ""}`}>
    ${day(a.local)}, ${a.local.slice(11, 16)}${b && html` → ${same ? "" : day(b.local) + ", "}${b.local.slice(11, 16)}`}
    <span> · ${b ? fmtMinutes(minutes) + " · " : ""}local time, ${fmtOffset(a.offset)}</span></div>`;
}

function RowCard({ row, local, onShow, children }) {
  const s = toMin(row.start), e = toMin(row.end || row.start, true);
  return html`<div class="rowcard"><${ModeChip} mode=${row.mode} />
    <div class="grow"><a onClick=${onShow}>${local(s).local.replace("T", " ")} → ${local(e).local.replace("T", " ")}</a>
      ${row.note && html`<div class="muted small">${row.note}</div>`}</div>${children}</div>`;
}

// Adding a travel mode row: the span (UTC, as the file has it; local shown), the mode and a note
function LabelForm({ start, end, mode: given, note: givenNote, local, why, onDone }) {
  const [mode, setMode] = useState(given || "cycled"), [note, setNote] = useState(givenNote || "");
  const [s, setS] = useState(start), [e, setE] = useState(end);
  useEffect(() => { setMode(given || "cycled"); setNote(givenNote || ""); setS(start); setE(end); }, [start, end, given, givenNote]);
  const save = async () => {
    await change(`Label ${local(toMin(s)).local.replace("T", " ")} as ${mode}`,
      [{ table: "travel_modes", op: "add", row: { start: s, end: e, mode, note } }]);
    onDone && onDone();
  };
  useKeys({ Enter: save, ...Object.fromEntries(Object.keys(SETTINGS.modes).map((m, i) => [String(i + 1), () => setMode(m)])) });
  return html`<div class="action main" style="flex-direction:column;align-items:stretch">
    <div class="form">
      <label>Mode</label><div class="row">${Object.keys(SETTINGS.modes).map((m, i) => html`<button
        class=${m === mode ? "primary" : ""} onClick=${() => setMode(m)} title=${`key ${i + 1}`}>
        <span class="swatch" style=${`background:${colour(m)}`}></span>${m}</button>`)}</div>
      <label>From</label><div><input value=${s} onInput=${x => setS(x.target.value)} size="16" />
        <span class="muted small"> UTC · ${local(toMin(s) ?? 0).local.slice(11)} local</span></div>
      <label>To</label><div><input value=${e} onInput=${x => setE(x.target.value)} size="16" />
        <span class="muted small"> UTC · ${local(toMin(e) ?? 0).local.slice(11)} local</span></div>
      <label>Note</label><input value=${note} onInput=${x => setNote(x.target.value)} placeholder="optional: the boat, the bus..." />
    </div>
    <div class="row" style="margin-top:8px"><button class="primary" onClick=${save}>Add this row</button>
      <span class="why grow">${why || "Saved to travel_modes.csv; the route takes it in when it's rebuilt."}</span><kbd>Enter</kbd></div>
  </div>`;
}

function moveOps(m) {
  const what = m.source.replace("_", " "), time = m.utc.slice(11, 16);
  if (m.row) return [{ table: "known_places", op: "update", id: m.row, row: { lat: String(m.to_lat), lon: String(m.to_lon) } }];
  return [{ table: "known_places", op: "add", row: { start_date: m.utc.slice(0, 10), time: `${time}:00Z`,
    note: `moved ${what} ${time}`, lat: String(m.to_lat), lon: String(m.to_lon) } }];
}

function ItemInspector({ item, rows, local, next }) {
  const ids = (item.rows && item.rows.travel_modes) || [];
  const byId = Object.fromEntries(rows.map(r => [r.id, r]));
  const involved = ids.map(id => byId[id]).filter(Boolean);
  const [a, b] = item.t;
  const now = rows.filter(r => { const s = toMin(r.start), e = toMin(r.end || r.start, true);
    return s <= b && a <= e && !ids.includes(r.id); });
  const fix = item.fix || {};
  const dismiss = () => change(`${item.title}: looks fine`, [{ table: "dismissed", op: "add",
    row: { check: item.check, start_utc: item.start_utc, end_utc: item.end_utc, lat: String(item.lat), lon: String(item.lon),
           note: item.title } }]).then(next);
  const del = (list, why) => change(why, list.map(r => ({ table: "travel_modes", op: "delete", id: r.id, base: r }))).then(next);
  const isFinding = item.kind === "finding";
  const showSpan = r => go("route", "row:" + r.id);
  useKeys(isFinding && item.status !== "dismissed" && fix.action !== "label" ? { Enter: dismiss } : {});

  return html`<div>
    <div class="row"><${Pill} status=${item.status} label=${STATUS[item.status]} />
      <span class="pill">${item.kind === "finding" ? item.check.replace("_", " ") : item.kind === "leg" ? "gap leg" : "hops"}</span>
      ${item.flagged && html`<span class="pill todo">flagged</span>`}</div>
    <h2>${item.title}</h2>
    <${When} a=${item.when.start} b=${item.when.end} />
    ${item.status === "pending" && html`<p class="note">A row this is about changed since make check: rebuild to see
      whether it's settled.</p>`}
    ${item.status === "labelled" && html`<p class="note">A travel mode row now covers this stretch.</p>`}
    <h3>Facts</h3>
    <${Facts} facts=${item.facts} bad=${item.check === "fast" ? ["kmh"] : item.check === "long_day" ? ["km"] : []}
      order=${["from", "to", "mode", "class", "km", "straight_km", "hours", "kmh", "limit_kmh", "limit_km", "factor",
               "minutes", "river", "waterway", "kind", "tour", "router", "mode_note", "flags", "steps", "hops", "points",
               "point", "at_utc", "days", "legs", "modes", "between", "day", "places", "note", "why", "problem", "drawn",
               "same_minute"]} />
    ${involved.length > 0 && html`<h3>The rows it's about</h3>${involved.map(r => html`<${RowCard} row=${r} local=${local}
      onShow=${() => showSpan(r)}>${fix.action === "keep_one"
        ? html`<button onClick=${() => del(involved.filter(x => x !== r), `Keep the ${r.mode} row, delete the other`)}>Keep this one</button>`
        : html`<button class="danger" onClick=${() => del([r], `Delete the ${r.mode} row`)}>Delete</button>`}<//>`)}`}
    ${now.length > 0 && html`<h3>Other rows on this stretch now</h3>${now.map(r => html`<${RowCard} row=${r} local=${local}
      onShow=${() => showSpan(r)}><button class="danger" onClick=${() => del([r], `Delete the ${r.mode} row`)}>Delete</button><//>`)}`}
    <h3>What to do</h3>
    <div class="actions">
      ${fix.action === "label" && item.status !== "labelled" && html`<${LabelForm} start=${fix.start} end=${fix.end}
        mode=${fix.mode} note=${fix.note} local=${local} onDone=${next} />`}
      ${fix.action === "move" && html`<${Action} main label=${`Move it onto the route (${fmtKm(fix.move.km)})`}
        why=${fix.move.row ? "Its known place gets the new position." : "A known place at its time takes its place on the route, at the base of the spike (the hollow dot)."}
        onClick=${() => change(`Move the ${fix.move.source.replace("_", " ")} at ${fix.move.utc.slice(11, 16)}Z onto the route`, moveOps(fix.move)).then(next)} />`}
      ${fix.action === "fast_leg" && (fix.moves || []).map(m => html`<${Action} label=${`Put the ${m.source.replace("_", " ")} at the other end (${fmtKm(m.km)})`}
        why="If that point is in the wrong place: the leg becomes a stop."
        onClick=${() => change(`Move the ${m.source.replace("_", " ")} at ${m.utc.slice(11, 16)}Z to the leg's other end`, moveOps(m)).then(next)} />`)}
      ${fix.action === "remove_places" && html`<${Action} label=${`Remove ${(item.rows.known_places || []).length > 1 ? "these known places" : "this known place"}`}
        why="It isn't on the route anyway." danger
        onClick=${() => change(`Remove a known place not on the route`, item.rows.known_places.map(id => ({ table: "known_places", op: "delete", id }))).then(next)} />`}
      ${fix.action === "delete" && involved.length > 0 && html`<${Action} label="Delete the row" danger why="It labels nothing."
        onClick=${() => del(involved, `Delete the ${involved[0].mode} row that labels nothing`)} />`}
      ${isFinding && item.status !== "dismissed" && html`<${Action} main=${fix.action !== "label"} label="Looks fine"
        why="Dismissed in dismissed.csv: make check leaves it out from now on." keyName=${fix.action !== "label" ? "Enter" : ""}
        onClick=${dismiss} />`}
      ${item.status === "dismissed" && html`<${Action} label="Not fine after all" why="Takes the dismissal back."
        onClick=${() => change(`${item.title}: not dismissed`, [{ table: "dismissed", op: "delete", id: item.dismissed }])} />`}
    </div>
  </div>`;
}

function RowInspector({ row, local }) {
  const [edit, setEdit] = useState(row);
  useEffect(() => setEdit(row), [row]);
  const s = toMin(row.start), e = toMin(row.end || row.start, true);
  const dirty = ["start", "end", "mode", "note"].some(k => edit[k] !== row[k]);
  const save = () => change(`Change the ${edit.mode} row of ${row.start}`, [{ table: "travel_modes", op: "update", id: row.id,
    base: row, row: { start: edit.start, end: edit.end, mode: edit.mode, note: edit.note } }]);
  useKeys({ Enter: () => dirty && save() });
  return html`<div><span class="pill">travel mode row</span><h2><${ModeChip} mode=${row.mode} /> ${row.note || ""}</h2>
    <${When} a=${local(s)} b=${local(e)} />
    <h3>Edit</h3><div class="form">
      <label>Start (UTC)</label><input value=${edit.start} onInput=${x => setEdit({ ...edit, start: x.target.value })} />
      <label>End (UTC)</label><input value=${edit.end} placeholder="empty: the start's day or minute"
        onInput=${x => setEdit({ ...edit, end: x.target.value })} />
      <label>Mode</label><select value=${edit.mode} onChange=${x => setEdit({ ...edit, mode: x.target.value })}>
        ${Object.keys(SETTINGS.modes).map(m => html`<option value=${m} selected=${m === edit.mode}>${m}</option>`)}</select>
      <label>Note</label><input value=${edit.note} onInput=${x => setEdit({ ...edit, note: x.target.value })} /></div>
    <p class="muted small">YYYY-MM-DD for a whole day, or YYYY-MM-DDTHH:MM, in UTC as the file keeps them.</p>
    <div class="actions"><${Action} main label="Save" disabled=${!dirty} onClick=${save} keyName="Enter" why="Saved to travel_modes.csv." />
      <${Action} danger label="Delete the row" why="Its stretch goes back to what the route predicts."
        onClick=${() => change(`Delete the ${row.mode} row of ${row.start}`, [{ table: "travel_modes", op: "delete", id: row.id, base: row }]).then(() => go("route"))} /></div>
  </div>`;
}

function AnchorInspector({ anchor, moved, local, onSave, onCancel }) {
  const [name] = SOURCES[anchor.source];
  const r = anchor.row || {};
  return html`<div><span class="pill">${name}</span>
    <h2>${anchor.source === "stay" ? r.town : anchor.source === "known_place" ? (r.town || r.note || "Your point") : anchor.ref.split("/").pop()}</h2>
    <${When} a=${local(anchor.t)} />
    ${anchor.source === "photo" && html`<img src=${"/api/thumb?f=" + encodeURIComponent(anchor.ref)} style="max-width:100%;border-radius:6px;margin-top:8px" />`}
    ${anchor.source === "known_place" && html`<${Facts} facts=${{ dates: r.end_date && r.end_date !== r.start_date ? `${r.start_date} to ${r.end_date}` : r.start_date,
      time: r.time, town: r.town, country: r.country, note: r.note, point: r.lat ? `${r.lat}, ${r.lon}` : "looked up" }} />`}
    ${anchor.source === "stay" && html`<${Facts} facts=${{ "first night": r.first_night, leaving: r.leaving }} />
      <p><a href=${"#/stays/stay:" + r.id}>Open it in Stays</a></p>`}
    <h3>Move it</h3>
    ${moved ? html`<div class="actions"><${Action} main label="Save the new position" keyName="Enter"
        why=${anchor.source === "known_place" && r.lat ? "Its row in known_places.csv gets the new position." : "A known place of your own at its time takes its place on the route."}
        onClick=${onSave} /><${Action} label="Cancel" onClick=${onCancel} /></div>`
      : html`<p class="muted">Drag the handle on the map to where it really was.</p>`}
    ${anchor.source === "known_place" && html`<${Action} danger label="Delete this known place" why="Every point it puts on the route goes."
      onClick=${() => change(`Delete the known place ${r.town || r.note}`, [{ table: "known_places", op: "delete", id: r.id }]).then(onCancel)} />`}
  </div>`;
}

export function RouteView({ rest }) {
  const line = useData("route/line"), items = useData("route/items"), anchors = useData("route/anchors");
  const modeRows = useData("rows/travel_modes");
  const local = useLocal();
  const [map, setMap] = useState(null);
  const [tab, setTab] = useState("todo"), [search, setSearch] = useState("");
  const [sel, setSel] = useState({ start: null, end: null });
  const [anchor, setAnchor] = useState(null), [moved, setMoved] = useState(null);
  const selected = rest[0] || null;
  const P = line.data ? line.data.points : null;
  const T = useMemo(() => P ? P.map(p => p[2]) : [], [P]);
  const rows = modeRows.data || [];

  const all = items.data || [];
  const rowItems = useMemo(() => rows.map(r => ({ ...r, key: "row:" + r.id, isRow: true }))
    .sort((a, b) => a.start.localeCompare(b.start)), [rows]);
  const tabs = [
    { key: "todo", label: "To do", test: i => i.status === "todo" },
    { key: "pending", label: "Rebuild", test: i => i.status === "pending" },
    { key: "findings", label: "Findings", test: i => i.kind === "finding" },
    { key: "legs", label: "Legs & hops", test: i => i.kind !== "finding" },
    { key: "done", label: "Done", test: i => i.status === "labelled" || i.status === "dismissed" },
    { key: "rows", label: "Rows" },
  ].map(t => ({ ...t, count: t.key === "rows" ? rows.length : all.filter(t.test).length }));
  const current = tabs.find(t => t.key === tab);
  const q = plain(search);
  const list = tab === "rows"
    ? rowItems.filter(r => !q || plain(`${r.start} ${r.mode} ${r.note}`).includes(q))
    : all.filter(current.test).map(i => ({ ...i, key: i.id }))
      .filter(i => !q || plain(`${i.title} ${i.start} ${JSON.stringify(i.facts)}`).includes(q));
  const item = all.find(i => i.id === selected);
  const row = selected && selected.startsWith("row:") ? rows.find(r => "row:" + r.id === selected) : null;
  const span = item ? item.t : row ? [toMin(row.start), toMin(row.end || row.start, true)] : sel.start != null && sel.end != null ? [sel.start, sel.end] : null;
  const select = key => { setAnchor(null); setMoved(null); setSel({ start: null, end: null }); go("route", key); };
  const next = () => { const keys = list.map(i => i.key); const n = step(keys, selected, 1); if (n && n !== selected) select(n); };
  useKeys({ j: next, k: () => { const n = step(list.map(i => i.key), selected, -1); if (n) select(n); },
    Escape: () => { setSel({ start: null, end: null }); setAnchor(null); setMoved(null); } });

  // The route: one line per run of a class. A point's class is that of the stretch arriving at it
  // (route.csv), so the segment from P[i-1] to P[i] takes P[i]'s
  useLayer(map, g => {
    if (!P || P.length < 2) return;
    const ll = p => [p[0] / 1e5, p[1] / 1e5];
    const draw = (run, c) => {
      const cls = line.data.classes[c];
      L.polyline(run, { color: colour(cls), weight: cls === "cycled" ? 2 : 3, dashArray: cls === "predicted" ? "6 5" : null,
                        interactive: false }).addTo(g);
    };
    let run = [ll(P[0]), ll(P[1])], c = P[1][3];
    for (let i = 2; i < P.length; i++) {
      if (P[i][3] !== c) { draw(run, c); run = [ll(P[i - 1])]; c = P[i][3]; }
      run.push(ll(P[i]));
    }
    draw(run, c);
  }, [P]);
  useEffect(() => { if (map && P && !selected) map.fitBounds(L.latLngBounds(P.map(p => [p[0] / 1e5, p[1] / 1e5])), { padding: [20, 20] }); }, [map, P]);
  // Photos, known places and stays the route goes through: shown when zoomed in
  const [zoom, setZoom] = useState(3);
  useEffect(() => { if (map) { const f = () => setZoom(map.getZoom()); map.on("zoomend", f); return () => map.off("zoomend", f); } }, [map]);
  useLayer(map, g => {
    if (!anchors.data || zoom < 11) return;
    const bounds = map.getBounds().pad(0.5);
    for (const a of anchors.data) {
      if (!bounds.contains([a.lat, a.lon])) continue;
      dot(a.lat, a.lon, { colour: SOURCES[a.source][1], radius: 4 })
        .bindTooltip(`${SOURCES[a.source][0]} ${local(a.t).local.replace("T", " ")}`)
        .on("click", () => { setAnchor(a); setMoved(null); go("route"); }).addTo(g);
    }
  }, [anchors.data, zoom, map && map.getCenter().toString()]);
  // What's selected: its stretch in black, its place in red, a move as a dashed arrow
  useLayer(map, g => {
    if (!P) return;
    if (span) {
      let lo = 0; while (lo < T.length && T[lo] < span[0]) lo++;
      const pts = [];
      for (let i = Math.max(lo - 1, 0); i < P.length && T[i] <= span[1]; i++) pts.push([P[i][0] / 1e5, P[i][1] / 1e5]);
      if (pts.length) {
        L.polyline(pts, { color: "#000", opacity: .45, weight: 9, interactive: false }).addTo(g);
        dot(...pts[0], { colour: "#2ca02c", radius: 6 }).addTo(g);
        dot(...pts[pts.length - 1], { colour: "#d62728", radius: 6 }).addTo(g);
        if (!anchor) map.fitBounds(L.latLngBounds(pts.concat(item ? [[item.lat, item.lon]] : [])), { padding: [60, 60], maxZoom: 15 });
      }
    }
    if (item) L.circleMarker([item.lat, item.lon], { radius: 11, color: "#d00", weight: 2, fill: false }).addTo(g);
    const m = item && item.fix && item.fix.move;
    if (m) {
      L.polyline([[m.lat, m.lon], [m.to_lat, m.to_lon]], { color: "#d00", weight: 2, dashArray: "4 6" }).addTo(g);
      dot(m.to_lat, m.to_lon, { colour: "#fff", stroke: "#d00", weight: 2 }).bindTooltip("Moved onto the route, it goes here").addTo(g);
    }
    if (anchor) {
      const h = L.marker(moved || [anchor.lat, anchor.lon], { draggable: true, icon: L.divIcon({ className: "", iconSize: [18, 18],
        html: '<div style="width:18px;height:18px;border-radius:9px;border:3px solid #000;background:#fff"></div>' }) }).addTo(g);
      h.on("dragend", () => { const ll = h.getLatLng(); setMoved([+ll.lat.toFixed(5), +ll.lng.toFixed(5)]); });
    }
  }, [P, selected, item && item.id, row && row.id, span && span.join(), anchor, moved]);
  // Clicking the route: the start, then the end, of a stretch to label
  useEffect(() => {
    if (!map || !P) return;
    const click = e => {
      const at = map.latLngToContainerPoint(e.latlng), bounds = map.getBounds().pad(0.1);
      let best = -1, bestD = 25 * 25;
      for (let i = 0; i < P.length; i++) {
        const ll = [P[i][0] / 1e5, P[i][1] / 1e5];
        if (!bounds.contains(ll)) continue;
        const p = map.latLngToContainerPoint(ll), d = (p.x - at.x) ** 2 + (p.y - at.y) ** 2;
        if (d < bestD) { bestD = d; best = i; }
      }
      if (best < 0) return;
      setAnchor(null);
      setSel(s => s.start != null && s.end == null ? { start: Math.min(s.start, T[best]), end: Math.max(s.start, T[best]) }
                                                     : { start: T[best], end: null });
      go("route");
    };
    map.on("click", click);
    return () => map.off("click", click);
  }, [map, P]);

  const saveMove = () => {
    const r = anchor.row || {}, what = SOURCES[anchor.source][0], time = anchor.utc.slice(11, 16);
    const ops = anchor.source === "known_place" && r.lat
      ? [{ table: "known_places", op: "update", id: r.id, row: { lat: String(moved[0]), lon: String(moved[1]) } }]
      : [{ table: "known_places", op: "add", row: { start_date: anchor.utc.slice(0, 10), time: `${time}:00Z`,
          note: `moved ${what} ${time}`, lat: String(moved[0]), lon: String(moved[1]) } }];
    change(`Move the ${what} at ${time}Z`, ops).then(() => { setAnchor(null); setMoved(null); });
  };

  let inspector;
  if (anchor) inspector = html`<${AnchorInspector} anchor=${anchor} moved=${moved} local=${local} onSave=${saveMove}
    onCancel=${() => { setAnchor(null); setMoved(null); }} />`;
  else if (item) inspector = html`<${ItemInspector} item=${item} rows=${rows} local=${local} next=${next} />`;
  else if (row) inspector = html`<${RowInspector} row=${row} local=${local} />`;
  else if (sel.start != null) inspector = sel.end == null
    ? html`<div><h2>Selecting a stretch</h2><${When} a=${local(sel.start)} /><p>Now click where it ends. <kbd>Esc</kbd> cancels.</p></div>`
    : html`<div><span class="pill">your selection</span><h2>A stretch of the route</h2><${When} a=${local(sel.start)} b=${local(sel.end)} />
        <h3>Label it</h3><${LabelForm} start=${utcText(sel.start)} end=${utcText(sel.end)} local=${local}
          onDone=${() => setSel({ start: null, end: null })} /></div>`;
  else inspector = html`<div class="empty">Pick something from the list (<kbd>j</kbd> for the next), or click the route
    twice to select a stretch and label it. Zoomed in, the photos, known places and stays the route goes through show as dots:
    click one to see it or move it.</div>`;

  return html`<div class="view">
    <${Queue} items=${list} selected=${selected} onSelect=${select} tabs=${tabs} tab=${tab} setTab=${setTab}
      search=${search} setSearch=${setSearch} empty=${items.loading ? "Loading…" : tab === "todo" ? "Nothing left to do." : "None."}
      row=${i => i.isRow ? html`<div class="t"><${ModeChip} mode=${i.mode} /><b>${i.note || i.mode}</b></div>
          <div class="s">${local(toMin(i.start)).local.replace("T", " ")} → ${local(toMin(i.end || i.start, true)).local.replace("T", " ")}</div>`
        : html`<div class="t"><b>${i.title}</b><${Pill} status=${i.status} label=${STATUS[i.status]} /></div>
          <div class="s">${i.when.start.local.replace("T", " ")} · ${i.kind === "finding" ? i.check.replace("_", " ") : i.kind === "leg" ? "gap leg" : "hops"}
            ${i.facts.km != null ? " · " + fmtKm(i.facts.km) : ""}${i.facts.mode ? " · " + i.facts.mode : i.facts.class ? " · " + i.facts.class : ""}</div>`}
      foot=${html`<kbd>j</kbd>/<kbd>k</kbd> step · <kbd>Enter</kbd> act · <kbd>u</kbd> undo`} />
    <main class="main"><${MapView} onReady=${setMap}>
      <div class="legend">${(line.data ? line.data.classes : []).map(c => html`<span><span class="swatch" style=${`background:${colour(c)}`}></span>${c}</span>`)}
        ${Object.values(SOURCES).map(([n, c]) => html`<span><span class="swatch" style=${`background:${c};border-radius:5px`}></span>${n}</span>`)}</div>
      ${sel.start != null && html`<div class="mapbar"><span class="mapchip on">${sel.end == null ? "Click where the stretch ends · Esc cancels" : "Stretch selected"}</span></div>`}
    <//></main>
    <aside class="inspector">${inspector}</aside>
  </div>`;
}

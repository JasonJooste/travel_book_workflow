// The Stays view: your stays (manual/stays.csv, which make route uses) beside the ones make stays
// found from rides and photos. Each stay shows how it compares, night by night, and what each night's
// evidence was. Edit a stay's dates, town and notes in place; drag its pin, or search for the place.
import {
  Action, MapView, PlaceSearch, Pill, Queue, SETTINGS, addDays, change, dot, fmtDay, fmtKm, go, html, nightsBetween,
  plain, plusCode, step, thumbUrl, useData, useEffect, useKeys, useLayer, useState,
} from "../lib.js";

const STATUS = { differs: "differs", new: "not in yours", confirmed: "confirmed", matches: "matches",
                 yours: "yours only", dismissed: "not a stay" };
const EVIDENCE = { ride: ["ride", "#2ca02c"], photo: ["photo", "#ff7f0e"], day: ["any fix", "#888"], bridged: ["nothing recorded", "#ccc"] };
const today = () => new Date().toISOString().slice(0, 10);

function span(first, leaving) {
  return html`${fmtDay(first)} → ${fmtDay(leaving, { year: first.slice(0, 4) !== leaving.slice(0, 4) })}
    <span class="muted"> · ${nightsBetween(first, leaving)} night${nightsBetween(first, leaving) === 1 ? "" : "s"}</span>`;
}

function km(a, b) {
  const r = Math.PI / 180, x = Math.sin((b[0] - a[0]) * r / 2) ** 2 +
    Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin((b[1] - a[1]) * r / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}

function Compare({ item }) {
  const r = item.row, f = item.found, d = item.diff;
  if (!f) return html`<p class="note">make stays found no stay over these nights: rides and photos don't place you
    in one spot for them. This one is yours alone.</p>`;
  if (!r) return null;
  const cell = (ok, text) => html`<td class=${ok ? "" : "diff"}>${text}</td>`;
  return html`<table class="grid"><tr><th></th><th>Yours</th><th>Found</th></tr>
    <tr><td class="muted">First night</td><td>${fmtDay(r.first_night)}</td>${cell(!d.first_night_days, fmtDay(f.first_night))}</tr>
    <tr><td class="muted">Leaving</td><td>${fmtDay(r.leaving)}</td>${cell(!d.leaving_days, fmtDay(f.leaving))}</tr>
    <tr><td class="muted">Nights</td><td>${nightsBetween(r.first_night, r.leaving)}</td><td>${f.nights}</td></tr>
    <tr><td class="muted">Town</td><td>${r.town}</td><td>${f.town}</td></tr>
    <tr><td class="muted">Place</td><td>${r.plus_code}</td>${cell(d.km != null && d.km <= SETTINGS.stay_radius_km,
      html`${f.plus_code}${d.km != null ? html`<div class="small">${fmtKm(d.km)} from yours</div>` : ""}`)}</tr></table>`;
}

function Evidence({ item, nights, at, onNight }) {
  const f = item.found;
  if (!f) return null;
  const list = f.night_dates.map(n => {
    const c = (nights[n] || []), chosen = c.find(x => x.chosen) || null;
    return { night: n, chosen, others: c.length - (chosen ? 1 : 0), away: f.away.find(a => a.night === n) };
  });
  return html`<h3>Each night, as found</h3>
    <div class="row small" style="margin-bottom:6px">${Object.entries(f.evidence).map(([k, n]) => html`<span class="chip">
      <span class="swatch" style=${`background:${EVIDENCE[k][1]}`}></span>${EVIDENCE[k][0]}: ${n}</span>`)}</div>
    <table class="grid"><tr><th>Night of</th><th>Placed by</th><th class="num">From your pin</th><th></th></tr>
      ${list.map(n => html`<tr class="click" onClick=${() => n.chosen && onNight(n.chosen)}>
        <td>${fmtDay(n.night, { year: false })}</td>
        <td>${n.away ? html`<span class="diff">away: ${n.away.town}</span>` : n.chosen ? EVIDENCE[n.chosen.evidence][0] : html`<span class="muted">nothing recorded</span>`}</td>
        <td class="num">${n.chosen && at ? fmtKm(km(at, [n.chosen.lat, n.chosen.lon])) : ""}</td>
        <td class="muted small">${n.others ? `+${n.others} other` : ""}</td></tr>`)}</table>
    ${f.others.length > 0 && html`<p class="small muted">Close by on other nights, maybe the real room:
      ${f.others.map(o => html`<span class="chip">${o.plus_code} · ${o.nights.length} night${o.nights.length > 1 ? "s" : ""}</span>`)}</p>`}`;
}

function Editor({ row, pin }) {
  const [edit, setEdit] = useState(row);
  useEffect(() => setEdit(row), [row]);
  const save = (field, value) => {
    if (value === row[field]) return;
    change(`${row.town}: ${field.replace("_", " ")} ${value || "cleared"}`,
      [{ table: "stays", op: "update", id: row.id, base: row, row: { [field]: value } }]).catch(() => setEdit(row));
  };
  const field = (name, type = "text", attrs = {}) => html`<input type=${type} value=${edit[name]} ...${attrs}
    onInput=${e => setEdit({ ...edit, [name]: e.target.value })} onChange=${e => save(name, e.target.value)} />`;
  return html`<div class="form">
    <label>Town</label>${field("town")}
    <label>First night</label>${field("first_night", "date")}
    <label>Leaving</label>${field("leaving", "date")}
    <label>Plus code</label><div>${field("plus_code", "text", { size: 14 })}${pin && html`<span class="muted small"> or drag the pin</span>`}</div>
    <label>Notes</label><textarea rows="2" value=${edit.notes} onInput=${e => setEdit({ ...edit, notes: e.target.value })}
      onChange=${e => save("notes", e.target.value)} placeholder="yours: who, where, anything" /></div>`;
}

export function StaysView({ rest }) {
  const state = useData("stays");
  const [tab, setTab] = useState("todo"), [search, setSearch] = useState("");
  const [map, setMap] = useState(null);
  const items = state.data ? state.data.items : [];
  const selected = rest[0] || null;
  const item = items.find(i => i.key === selected);
  const days = useData(item ? `stays/days?first=${item.first_night}&last=${item.leaving}` : null, [item && item.key]);
  const tabs = [
    { key: "todo", label: "To check", test: i => i.status === "differs" || i.status === "new" },
    { key: "ok", label: "Agreed", test: i => ["confirmed", "matches", "yours"].includes(i.status) },
    { key: "dismissed", label: "Not stays", test: i => i.status === "dismissed" },
    { key: "all", label: "All", test: () => true },
  ].map(t => ({ ...t, count: items.filter(t.test).length }));
  const q = plain(search);
  const list = items.filter(tabs.find(t => t.key === tab).test)
    .filter(i => !q || plain(`${i.town} ${i.first_night} ${i.row ? i.row.notes + " " + i.row.plus_code : ""}`).includes(q));
  const select = key => go("stays", key);
  const next = () => { const n = step(list.map(i => i.key), selected, 1); if (n && n !== selected) select(n); };
  const r = item && item.row, f = item && item.found;
  const at = item && item.lat != null ? [item.lat, item.lon] : null;

  const confirm = () => change(`${r.town}, ${r.first_night}: confirmed`,
    [{ table: "stays", op: "update", id: r.id, base: r, row: { checked: today() } }]).then(next);
  const add = () => change(`Add the stay in ${f.town} from ${f.first_night}`, [{ table: "stays", op: "add", row: {
    first_night: f.first_night, leaving: f.leaving, town: f.town, plus_code: f.plus_code, checked: today(),
    found: Object.entries(f.evidence).map(([k, n]) => `${k} ${n}`).join(", ") } }]).then(next);
  const notStay = () => change(`${f.town} from ${f.first_night}: not a stay`, [{ table: "dismissed", op: "add", row: {
    check: "found_stay", start_utc: f.first_night, end_utc: f.leaving, lat: String(f.lat), lon: String(f.lon), note: f.town } }]).then(next);
  const movePin = async (lat, lon, why) => {
    const code = await plusCode(lat, lon);
    change(`${r.town}: ${why}`, [{ table: "stays", op: "update", id: r.id, base: r, row: { plus_code: code } }]);
  };
  const primary = !item ? null : item.status === "new" ? add : (item.status === "differs" || item.status === "matches" || item.status === "yours") && r && !r.checked ? confirm : null;
  useKeys({ j: next, k: () => { const n = step(list.map(i => i.key), selected, -1); if (n) select(n); }, Enter: primary || undefined });

  // The map: the track of those days, photos, every night's candidates, the found place, your pin
  useLayer(map, g => {
    if (!item) {
      for (const i of items) if (i.lat != null) dot(i.lat, i.lon, { colour: i.status === "differs" || i.status === "new" ? "#e08a00" : "#1f77b4", radius: 4 })
        .bindTooltip(`${i.town} · ${i.first_night}`).on("click", () => select(i.key)).addTo(g);
      return;
    }
    const d = days.data;
    if (d) {
      const nightsOf = new Set(f ? f.night_dates : []);
      const first = item.first_night, last = item.leaving;
      let seg = [], kind = null;
      const flush = () => { if (seg.length > 1) L.polyline(seg, { color: kind, weight: 2.5, opacity: .8, interactive: false }).addTo(g); };
      for (const [lat, lon, , local] of d.track) {
        const day = local.slice(0, 10), c = day === first ? "#9467bd" : day === last ? "#e377c2" : day > first && day < last ? "#1f77b4" : "#aaa";
        if (c !== kind) { flush(); seg = seg.length ? [seg[seg.length - 1]] : []; kind = c; }
        seg.push([lat, lon]);
      }
      flush();
      for (const p of d.photos) dot(p.lat, p.lon, { colour: "#ff7f0e", radius: 3 })
        .bindPopup(`<img src="${thumbUrl(p.file)}" width="200"><br>${p.local.replace("T", " ")}`).addTo(g);
      for (const [night, cands] of Object.entries(d.nights)) for (const c of cands) {
        const inside = nightsOf.has(night);
        dot(c.lat, c.lon, { colour: EVIDENCE[c.evidence][1], radius: c.chosen ? 7 : 4, stroke: inside ? "#000" : "#fff",
          weight: inside ? 1.5 : 1, dashArray: inside ? null : "2 2" })
          .bindTooltip(`night of ${fmtDay(night)}: ${EVIDENCE[c.evidence][0]}${c.chosen ? ", chosen" : ""}${inside ? "" : " (outside the stay)"}`)
          .on("click", () => r && movePin(c.lat, c.lon, `place from the night of ${night}`)).addTo(g);
      }
    }
    if (f) L.circle([f.lat, f.lon], { radius: SETTINGS.stay_radius_km * 1000, color: "#2ca02c", weight: 2, fill: false })
      .bindTooltip(`found: ${f.town}`).addTo(g);
    if (at) {
      const pin = L.marker(at, { draggable: !!r }).addTo(g);
      if (r) pin.on("dragend", () => { const ll = pin.getLatLng(); movePin(ll.lat, ll.lng, "place moved on the map"); });
    }
    const pts = [at, f && [f.lat, f.lon]].filter(Boolean);
    if (pts.length) map.setView(pts[0], Math.max(map.getZoom(), 14));
  }, [item && item.key, item && item.lat, days.data, items.length]);

  let inspector = html`<div class="empty">${items.length ? html`Pick a stay (<kbd>j</kbd> for the next). The ones to check
    are where your stays and the found ones disagree, and found stays that aren't in yours.` : "Loading…"}</div>`;
  if (item) inspector = html`<div>
    <div class="row"><${Pill} status=${item.status} label=${STATUS[item.status]} />${r && r.checked && html`<span class="muted small">confirmed ${r.checked}</span>`}</div>
    <h2>${item.town}</h2>
    <div class="when">${span(item.first_night, item.leaving)}</div>
    <h3>Yours and found</h3><${Compare} item=${item} />
    ${r && html`<h3>Your stay</h3><${Editor} row=${r} pin=${true} />
      <div style="margin-top:8px"><${PlaceSearch} near=${at} onPick=${p => movePin(p.lat, p.lon, `place set to ${p.name}`)} /></div>`}
    ${r && r.found && html`<p class="note">When it was first found: ${r.found}</p>`}
    <h3>What to do</h3><div class="actions">
      ${item.status === "new" && html`<${Action} main label="Add to your stays" keyName="Enter" onClick=${add}
        why="As found: make route then puts you here every night of it." />
        <${Action} label="Not a stay" onClick=${notStay} why="Left out from now on: a place you passed through more than once, say." />`}
      ${r && !r.checked && html`<${Action} main label="Confirm" keyName="Enter" onClick=${confirm}
        why="You've checked it: it moves out of the list to check." />`}
      ${r && r.checked && html`<${Action} label="Unconfirm" onClick=${() => change(`${r.town}: unconfirmed`,
        [{ table: "stays", op: "update", id: r.id, base: r, row: { checked: "" } }])} why="Back to the list to check." />`}
      ${r && f && item.diff && (item.diff.first_night_days || item.diff.leaving_days) ? html`<${Action} label="Use the found dates"
        onClick=${() => change(`${r.town}: dates as found`, [{ table: "stays", op: "update", id: r.id, base: r,
          row: { first_night: f.first_night, leaving: f.leaving } }])} why=${`${fmtDay(f.first_night)} to ${fmtDay(f.leaving)}`} />` : ""}
      ${r && f && item.diff && item.diff.km > SETTINGS.stay_radius_km ? html`<${Action} label="Use the found place"
        onClick=${() => change(`${r.town}: place as found`, [{ table: "stays", op: "update", id: r.id, base: r,
          row: { plus_code: f.plus_code } }])} why=${`${f.plus_code}, ${fmtKm(item.diff.km)} from yours`} />` : ""}
      ${item.status === "dismissed" && html`<${Action} label="It is a stay after all" onClick=${() => change(`${f.town}: a stay after all`,
        [{ table: "dismissed", op: "delete", id: item.dismissed }])} why="Back in the list to check." />`}
      ${r && html`<${Action} danger label="Remove this stay" onClick=${() => change(`Remove the stay in ${r.town} from ${r.first_night}`,
        [{ table: "stays", op: "delete", id: r.id, base: r }]).then(() => go("stays"))} why="make route no longer puts you here." />`}
      ${r && html`<${Action} label="Split off the last night" disabled=${nightsBetween(r.first_night, r.leaving) < 2}
        onClick=${() => change(`${r.town}: one night shorter`, [{ table: "stays", op: "update", id: r.id, base: r,
          row: { leaving: addDays(r.leaving, -1) } }])} why="Leaving a day earlier." />`}
    </div>
    <${Evidence} item=${item} nights=${(days.data || {}).nights || {}} at=${at}
      onNight=${c => map && map.setView([c.lat, c.lon], 17)} />
  </div>`;

  return html`<div class="view">
    <${Queue} items=${list} selected=${selected} onSelect=${select} tabs=${tabs} tab=${tab} setTab=${setTab}
      search=${search} setSearch=${setSearch} empty=${tab === "todo" ? "Every stay agrees with what was found, or you've checked it." : "None."}
      row=${i => html`<div class="t"><b>${i.town}</b><${Pill} status=${i.status} label=${STATUS[i.status]} /></div>
        <div class="s">${span(i.first_night, i.leaving)}</div>`}
      top=${html`<div class="row"><button onClick=${async () => {
        const c = map ? map.getCenter() : { lat: 0, lng: 0 };
        const code = await plusCode(c.lat, c.lng);
        const out = await change("Add a stay at the map's centre", [{ table: "stays", op: "add", row: {
          first_night: today(), leaving: addDays(today(), 1), town: "?", plus_code: code } }]);
        go("stays", "stay:" + out.results[0].id); setTab("all"); }}>New stay at the map's centre</button></div>`}
      foot=${html`<kbd>j</kbd>/<kbd>k</kbd> step · <kbd>Enter</kbd> confirm or add · <kbd>u</kbd> undo`} />
    <main class="main"><${MapView} onReady=${setMap}>
      ${item && html`<div class="legend"><span><span class="swatch" style="background:#9467bd"></span>arriving</span>
        <span><span class="swatch" style="background:#1f77b4"></span>during</span><span><span class="swatch" style="background:#e377c2"></span>leaving</span>
        ${Object.values(EVIDENCE).slice(0, 3).map(([n, c]) => html`<span><span class="swatch" style=${`background:${c};border-radius:5px`}></span>night by ${n}</span>`)}
        <span>○ found place</span><span>📍 yours: drag it, or click a night's dot to use it</span></div>`}
    <//></main>
    <aside class="inspector">${inspector}</aside></div>`;
}


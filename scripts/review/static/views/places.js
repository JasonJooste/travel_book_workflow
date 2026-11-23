// The Places view: where the trip was when no GPS says.
//   Questions   a known place whose town matched several places, or none: pick one on the map, or click
//               where it was. Saved in manual/place_picks.csv; make places uses it
//   Gaps        runs of days with no ride, no photo with GPS, no known place and no stay: their photos and
//               diary entries may say where you were. Click the map to add a known place for them
//   Known       every known place: edit or delete it
import {
  Action, Facts, MapView, PlaceSearch, Pill, Queue, change, dot, fmtDay, go, html, plain, step, thumbUrl, useData,
  useEffect, useKeys, useLayer, useState,
} from "../lib.js";

const WHY = { ambiguous: "Several places have this name", no_match: "No place of this name in that country",
              unknown_country: "The country isn't one GeoNames knows" };

function dates(r) { return r.end_date && r.end_date !== r.start_date ? `${fmtDay(r.start_date)} → ${fmtDay(r.end_date)}` : fmtDay(r.start_date); }

function QuestionInspector({ q, clicked, next }) {
  const pick = (p, why) => change(`${q.row.town}: ${why}`, [{ table: "place_picks", op: "add", row: {
    town: q.row.town, country: q.country_code || q.row.country, geonameid: p.id || "", name: p.name || q.row.town,
    lat: String(p.lat), lon: String(p.lon) } }]).then(next);
  useKeys({ ...Object.fromEntries(q.options.slice(0, 9).map((p, i) => [String(i + 1), () => pick(p, `it's ${p.name}, ${p.region}`)])) });
  return html`<div><div class="row"><${Pill} status=${q.answered ? "answered" : "question"} label=${q.answered ? "answered" : "to settle"} /></div>
    <h2>${q.row.town}, ${q.row.country}</h2><div class="when">${dates(q.row)}${q.row.time ? ", " + q.row.time : ""}</div>
    ${q.row.note && html`<p class="note">${q.row.note}</p>`}
    <p>${WHY[q.reason]}.${q.answered ? " You've answered: make places takes it in when it's rebuilt." : ""}</p>
    <h3>Where you were around then</h3>
    <table class="grid"><tr><th></th><th>When</th><th>Near</th></tr>${q.neighbours.map(n => html`<tr>
      <td>${n.label}</td><td>${n.when.replace("T", " ")}</td><td>${n.name}</td></tr>`)}</table>
    ${q.options.length > 0 && html`<h3>The places it could be</h3><div class="actions">${q.options.map((p, i) => html`<${Action}
      main=${i === 0} label=${`${i + 1}. ${p.name}`} keyName=${String(i + 1)} onClick=${() => pick(p, `it's ${p.name}, ${p.region}`)}
      why=${[p.region, p.population ? `pop. ${p.population.toLocaleString()}` : "", p.feature,
             Object.entries(p.km_from || {}).map(([k, v]) => `${v} km from ${k}`).join(", ")].filter(Boolean).join(" · ")} />`)}</div>`}
    <h3>Or somewhere else</h3>
    ${clicked ? html`<${Action} main label="Use the point you clicked" why=${`${clicked[0].toFixed(5)}, ${clicked[1].toFixed(5)}`}
        onClick=${() => pick({ lat: clicked[0], lon: clicked[1] }, "a point of your own")} />`
      : html`<p class="muted">Click the map where it was, or search:</p>`}
    <${PlaceSearch} onPick=${p => pick({ lat: p.lat, lon: p.lon, name: q.row.town }, `at ${p.name}`)} />
  </div>`;
}

function GapInspector({ gap, clicked }) {
  const [town, setTown] = useState(""), [country, setCountry] = useState(""), [note, setNote] = useState("");
  const add = (row, why) => change(why, [{ table: "known_places", op: "add", row: {
    start_date: gap.first, end_date: gap.last !== gap.first ? gap.last : "", note, ...row } }]);
  return html`<div><${Pill} status="gap" label="no position" />
    <h2>${gap.days} day${gap.days > 1 ? "s" : ""} with nothing to place you</h2>
    <div class="when">${fmtDay(gap.first)}${gap.days > 1 ? " → " + fmtDay(gap.last) : ""}</div>
    <h3>Diary entries of those days</h3>
    ${gap.entries.length ? html`<table class="grid">${gap.entries.map(e => html`<tr class="click"
        onClick=${() => go("diary", e.kind, e.stem)}><td>${e.kind}</td><td>${e.stem}</td><td class="num">${e.words} words</td></tr>`)}</table>`
      : html`<p class="muted">None.</p>`}
    <h3>Photos of those days (no GPS)</h3>
    ${gap.photos.length ? html`<div class="photos" style="padding:0">${gap.photos.slice(0, 24).map(p => html`<figure>
        <img loading="lazy" src=${thumbUrl(p.file)} title=${p.name} /></figure>`)}</div>` : html`<p class="muted">None.</p>`}
    <h3>Say where you were</h3>
    <div class="form"><label>Note</label><input value=${note} onInput=${e => setNote(e.target.value)} placeholder="optional" /></div>
    <div class="actions" style="margin-top:8px">
      ${clicked ? html`<${Action} main label="A known place at the point you clicked" why=${`${clicked[0].toFixed(5)}, ${clicked[1].toFixed(5)}, every day of the gap`}
          onClick=${() => add({ lat: String(clicked[0]), lon: String(clicked[1]) }, `Known place for ${gap.first}`)} />`
        : html`<p class="muted">Click the map where you were, or name the town:</p>`}
      <div class="action"><input placeholder="Town" value=${town} onInput=${e => setTown(e.target.value)} size="12" />
        <input placeholder="Country" value=${country} onInput=${e => setCountry(e.target.value)} size="10" />
        <button disabled=${!town || !country} onClick=${() => add({ town, country }, `Known place ${town} for ${gap.first}`)}>Add</button>
        <span class="why">Looked up in GeoNames by make places.</span></div></div>
  </div>`;
}

function KnownInspector({ row }) {
  const [edit, setEdit] = useState(row);
  const save = (k, v) => v !== row[k] && change(`Known place ${row.town || row.note}: ${k.replace("_", " ")}`,
    [{ table: "known_places", op: "update", id: row.id, base: row, row: { [k]: v } }]).catch(() => setEdit(row));
  const field = k => html`<input value=${edit[k]} onInput=${e => setEdit({ ...edit, [k]: e.target.value })}
    onChange=${e => save(k, e.target.value)} />`;
  return html`<div><span class="pill">known place</span><h2>${row.town || row.note || "Your point"}</h2>
    <div class="when">${dates(row)}${row.time ? ", " + row.time : ""}</div>
    ${row.found && html`<h3>As looked up</h3><${Facts} facts=${{ name: row.found.geoname, region: row.found.region,
      feature: row.found.feature, point: row.found.lat ? `${(+row.found.lat).toFixed(5)}, ${(+row.found.lon).toFixed(5)}` : "not found" }} />`}
    <h3>Edit</h3><div class="form">
      <label>Start date</label>${field("start_date")}<label>End date</label>${field("end_date")}
      <label>Time</label>${field("time")}<label>Town</label>${field("town")}<label>Country</label>${field("country")}
      <label>Note</label>${field("note")}<label>Lat</label>${field("lat")}<label>Lon</label>${field("lon")}</div>
    <p class="muted small">Time: local HH:MM:SS, or UTC with a Z. With its own lat and lon the town isn't looked up.</p>
    <${Action} danger label="Delete" why="Every point it puts on the route goes."
      onClick=${() => change(`Delete the known place ${row.town || row.note}`, [{ table: "known_places", op: "delete", id: row.id, base: row }]).then(() => go("places"))} />
  </div>`;
}

export function PlacesView({ rest }) {
  const state = useData("places");
  const [tab, setTab] = useState("questions"), [search, setSearch] = useState("");
  const [map, setMap] = useState(null), [clicked, setClicked] = useState(null);
  const d = state.data || { questions: [], gaps: [], known: [] };
  const all = [
    ...d.questions.map(q => ({ ...q, key: "q:" + q.row.id, kind: "question", sort: q.row.start_date })),
    ...d.gaps.map(g => ({ ...g, kind: "gap", sort: g.first })),
    ...d.known.map(k => ({ ...k, key: "k:" + k.id, kind: "known", sort: k.start_date })),
  ];
  const tabs = [
    { key: "questions", label: "To settle", test: i => i.kind === "question" && !i.answered },
    { key: "gaps", label: "Gaps", test: i => i.kind === "gap" },
    { key: "known", label: "Known places", test: i => i.kind === "known" },
  ].map(t => ({ ...t, count: all.filter(t.test).length }));
  const q = plain(search);
  const list = all.filter(tabs.find(t => t.key === tab).test).sort((a, b) => a.sort.localeCompare(b.sort))
    .filter(i => !q || plain(JSON.stringify(i.row || i)).includes(q));
  const selected = rest[0] || null, item = all.find(i => i.key === selected);
  // Open on the selected one's tab, or else the first with anything in it
  useEffect(() => {
    if (!state.data) return;
    if (item) setTab(item.kind === "question" ? "questions" : item.kind === "gap" ? "gaps" : "known");
    else if (!tabs.find(t => t.key === tab).count) setTab((tabs.find(t => t.count) || tabs[0]).key);
  }, [state.data, selected]);
  const select = key => { setClicked(null); go("places", key); };
  const next = () => { const n = step(list.map(i => i.key), selected, 1); if (n && n !== selected) select(n); };
  useKeys({ j: next, k: () => { const n = step(list.map(i => i.key), selected, -1); if (n) select(n); } });

  useLayer(map, g => {
    if (!map) return;
    const pts = [];
    if (item && item.kind === "question") {
      item.neighbours.forEach(n => { dot(n.lat, n.lon, { colour: "#888" }).bindTooltip(`${n.label}: ${n.name} ${n.when}`, { permanent: true }).addTo(g); pts.push([n.lat, n.lon]); });
      item.options.forEach((p, i) => { L.marker([p.lat, p.lon]).bindTooltip(`${i + 1}. ${p.name}`, { permanent: true }).addTo(g); pts.push([p.lat, p.lon]); });
    } else if (item && item.kind === "known" && (item.lat || (item.found && item.found.lat))) {
      const p = item.lat ? [+item.lat, +item.lon] : [+item.found.lat, +item.found.lon];
      L.marker(p).addTo(g); pts.push(p);
    } else if (item && item.kind === "gap") {
      for (const p of item.photos) if (p.lat) { dot(+p.lat, +p.lon, { colour: "#ff7f0e", radius: 4 }).bindTooltip(`guessed for ${p.name}`).addTo(g); pts.push([+p.lat, +p.lon]); }
    }
    if (clicked) dot(clicked[0], clicked[1], { colour: "#d00", radius: 7 }).addTo(g);
    if (pts.length && !clicked) map.fitBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 13 });
  }, [map, selected, clicked, state.data]);
  useEffect(() => {
    if (!map) return;
    const f = e => setClicked([e.latlng.lat, e.latlng.lng]);
    map.on("click", f);
    return () => map.off("click", f);
  }, [map]);

  let inspector = html`<div class="empty">Pick something from the list.</div>`;
  if (item && item.kind === "question") inspector = html`<${QuestionInspector} q=${item} clicked=${clicked} next=${next} />`;
  if (item && item.kind === "gap") inspector = html`<${GapInspector} gap=${item} clicked=${clicked} key=${item.key} />`;
  if (item && item.kind === "known") inspector = html`<${KnownInspector} row=${item} key=${item.key} />`;
  return html`<div class="view">
    <${Queue} items=${list} selected=${selected} onSelect=${select} tabs=${tabs} tab=${tab} setTab=${setTab}
      search=${search} setSearch=${setSearch} empty=${tab === "questions" ? "Every known place is settled." : "None."}
      row=${i => i.kind === "gap" ? html`<div class="t"><b>${fmtDay(i.first)}${i.days > 1 ? " → " + fmtDay(i.last, { year: false }) : ""}</b>
          <span class="pill gap">${i.days} day${i.days > 1 ? "s" : ""}</span></div>
          <div class="s">${i.entries.length} entries · ${i.photos.length} photos</div>`
        : i.kind === "question" ? html`<div class="t"><b>${i.row.town}, ${i.row.country}</b><span class="pill question">${i.options.length} options</span></div>
          <div class="s">${dates(i.row)}</div>`
        : html`<div class="t"><b>${i.town || i.note || "your point"}</b>${i.lat ? html`<span class="pill">point</span>` : ""}</div>
          <div class="s">${dates(i)}${i.time ? " · " + i.time : ""}${i.note && i.town ? " · " + i.note : ""}</div>`}
      foot=${html`<kbd>j</kbd>/<kbd>k</kbd> step · <kbd>1</kbd>–<kbd>9</kbd> pick an option · <kbd>u</kbd> undo`} />
    <main class="main"><${MapView} onReady=${setMap} /></main>
    <aside class="inspector">${inspector}</aside></div>`;
}

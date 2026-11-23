// The Story view: a story beside everything the trip left from its days. The story is only read (edit
// it in your editor: the text here follows within seconds); its days are its Start time and Stop time in
// story_plans/*.csv. Beside it: the route on a map, a table day by day, the photos, the events, the diary
// entries, and Claude's suggestions from comparing the story with them.
import { marked } from "../vendor/marked.js";
import {
  Action, Facts, MapView, Pill, Queue, api, colour, dot, fmtDay, fmtKm, go, html, photoUrl, plain, step, thumbUrl,
  toast, useData, useEffect, useKeys, useLayer, useState,
} from "../lib.js";
import { EntryPlayer } from "./diary.js";

const TABS = [["text", "Story"], ["map", "Map"], ["days", "Days"], ["photos", "Photos"], ["events", "Events"],
              ["entries", "Entries"], ["suggestions", "Suggestions"]];
const KIND = { inconsistency: "Inconsistency", addition: "Something to add", note: "An answer to a note" };

function StoryText({ name }) {
  const [text, setText] = useState(null);
  useEffect(() => {
    let live = true, tag = "";
    const load = async () => {
      const r = await fetch(`/api/story/${encodeURIComponent(name)}/text`, { headers: tag ? { "If-None-Match": tag } : {} });
      if (r.status === 200) { tag = r.headers.get("ETag"); const t = await r.text(); if (live) setText(t); }
      else if (r.status === 404 && live) setText("");
    };
    load();
    const t = setInterval(load, 3000);
    return () => { live = false; clearInterval(t); };
  }, [name]);
  if (text === null) return html`<div class="empty">Loading…</div>`;
  if (!text) return html`<div class="empty">No raw/stories/${name}.md yet.</div>`;
  const body = text.replace(/^---\n[\s\S]*?\n---\n/, "")
    .replace(/\{\{([\s\S]*?)\}\}/g, (_, n) => `<span class="note-mark">{{${n.replace(/</g, "&lt;")}}}</span>`);
  return html`<div class="story-text" dangerouslySetInnerHTML=${{ __html: marked.parse(body) }}></div>`;
}

function Profile({ ride, onPick }) {
  const S = ride.samples;
  if (!S || S.length < 2) return null;
  const w = 1000, h = 140, max = S[S.length - 1][0] || 1;
  const eles = S.map(s => s[1]).filter(x => x != null);
  const lo = Math.min(...eles), hi = Math.max(...eles) || 1;
  const pts = S.filter(s => s[1] != null).map(s => `${(s[0] / max * w).toFixed(1)},${(h - (s[1] - lo) / (hi - lo || 1) * (h - 10) - 5).toFixed(1)}`);
  return html`<svg class="profile" viewBox=${`0 0 ${w} ${h}`} preserveAspectRatio="none"
    onClick=${e => { const r = e.currentTarget.getBoundingClientRect(); const km = (e.clientX - r.left) / r.width * max;
      const s = S.reduce((a, b) => Math.abs(b[0] - km) < Math.abs(a[0] - km) ? b : a); onPick([s[3], s[4]]); }}>
    <polyline points=${pts.join(" ")} fill="none" stroke="#2ca02c" stroke-width="1.5" vector-effect="non-scaling-stroke" /></svg>
    <div class="row small muted"><span>${Math.round(lo)} m</span><span class="grow"></span><span>${fmtKm(max)} ridden, highest ${Math.round(hi)} m</span></div>`;
}

function Suggestions({ name, pad }) {
  const check = useData(`story/${encodeURIComponent(name)}/check`);
  const [running, setRunning] = useState(false), [model, setModel] = useState("opus"), [shown, setShown] = useState("open");
  const run = async () => {
    setRunning(true);
    try { await api(`story/${encodeURIComponent(name)}/check?pad=${pad}`, { method: "POST", body: { model } }); }
    catch (e) { toast(e.message, { error: true }); }
    setRunning(false);
  };
  const dismiss = async (s, dismissed) => {
    await api(`story/${encodeURIComponent(name)}/check/dismiss`, { method: "POST", body: { id: s.id, dismissed } });
    check.data.suggestions = check.data.suggestions.map(x => x.id === s.id ? { ...x, dismissed } : x);
    setShown(shown);
  };
  const c = check.data;
  const list = c ? c.suggestions.filter(s => shown === "all" || !s.dismissed) : [];
  return html`<div style="padding:14px 20px">
    <div class="row"><select value=${model} onChange=${e => setModel(e.target.value)}>${["opus", "sonnet", "haiku"].map(m => html`<option>${m}</option>`)}</select>
      <button class="primary" disabled=${running} onClick=${run}>${running ? "Claude is reading…" : c ? "Check again" : "Ask Claude to check the story"}</button>
      <span class="muted small grow">${c ? `Last checked ${c.at.replace("T", " ")} by ${c.model}, in ${c.seconds} s` : "It compares the story with the sources of its days."}</span>
      ${c && html`<div class="tabs"><button class=${shown === "open" ? "on" : ""} onClick=${() => setShown("open")}>Open</button>
        <button class=${shown === "all" ? "on" : ""} onClick=${() => setShown("all")}>All</button></div>`}</div>
    ${list.map(s => html`<div class="event" style=${s.dismissed ? "opacity:.5" : ""}>
      <div class="row"><span class="pill ${s.kind === "inconsistency" ? "todo" : "pending"}">${KIND[s.kind]}</span><span class="grow"></span>
        <button onClick=${() => dismiss(s, !s.dismissed)}>${s.dismissed ? "Restore" : "Dismiss"}</button></div>
      ${s.story_quote && html`<p class="note">“${s.story_quote}”</p>`}
      <p><b>${s.claim}</b></p><p>${s.suggestion}</p>
      ${s.evidence.length > 0 && html`<table class="grid">${s.evidence.map(e => html`<tr><td class="small">${e.ref}</td>
        <td class="small muted">${e.quote}</td></tr>`)}</table>`}</div>`)}
  </div>`;
}

export function StoryView({ rest }) {
  const stories = useData("story/list");
  const [name, tabName] = rest;
  const [pad, setPad] = useState(0), [search, setSearch] = useState("");
  const [map, setMap] = useState(null), [pick, setPick] = useState(null);
  const data = useData(name ? `story/${encodeURIComponent(name)}?pad=${pad}` : null, [name, pad]);
  const tab = tabName || "text";
  const list = (stories.data || []).map(s => ({ ...s, key: s.name }))
    .filter(s => !search || plain(`${s.name} ${s.description}`).includes(plain(search)));
  const select = key => { setPick(null); go("story", key, tab); };
  useKeys({ j: () => { const n = step(list.map(s => s.key), name, 1); if (n) select(n); },
            k: () => { const n = step(list.map(s => s.key), name, -1); if (n) select(n); } });
  const d = data.data;
  const entry = useData(pick && pick.type === "entry" ? `story/entry/${pick.key}` : null, [pick && pick.key]);

  useLayer(map, g => {
    if (!d || !map) return;
    let run = [], cls = null;
    const flush = () => run.length > 1 && L.polyline(run, { color: colour(cls), weight: 3, dashArray: cls === "predicted" ? "6 5" : null }).addTo(g);
    for (const p of d.route) { if (p[3] !== cls) { flush(); run = run.length ? [run[run.length - 1]] : []; cls = p[3]; } run.push([p[0], p[1]]); }
    flush();
    d.stays.forEach(s => s.lat != null && dot(s.lat, s.lon, { colour: "#1f77b4", radius: 7 }).bindTooltip(`Stay: ${s.town}, ${s.first_night} → ${s.leaving}`).addTo(g));
    d.photos.forEach((p, i) => p.lat && dot(+p.lat, +p.lon, { colour: "#ff7f0e", radius: 4 })
      .bindTooltip(`${p.local_date} ${p.local_time} · ${p.town}`).on("click", () => setPick({ type: "photo", i })).addTo(g));
    d.entries.forEach(e => e.lat && dot(+e.lat, +e.lon, { colour: "#9467bd", radius: 5 })
      .bindTooltip(`${e.kind} ${e.local_date} ${e.local_time}`).on("click", () => setPick({ type: "entry", key: e.key })).addTo(g));
    if (d.route.length) map.fitBounds(L.latLngBounds(d.route.map(p => [p[0], p[1]])), { padding: [30, 30] });
  }, [d, map, tab]);

  let side = html`<div class="empty">Pick a photo, an entry or a day to see it here.</div>`;
  if (pick && pick.type === "photo" && d) {
    const p = d.photos[pick.i];
    side = html`<div><img src=${photoUrl(p.show)} style="max-width:100%;border-radius:6px" />
      <${Facts} facts=${{ day: fmtDay(p.local_date), time: p.local_time, town: `${p.town} ${p.country}`, "placed by": p.position_source.replace(/_/g, " "),
        "timed by": p.time_source.replace(/_/g, " "), file: p.file, ignored: p.ignored }} /></div>`;
  }
  if (pick && pick.type === "entry" && entry.data) {
    const e = entry.data;
    side = html`<div><h2>${e.stem}</h2><p><a href=${`#/diary/${e.kind}/${e.stem}`}>Review it in Diary</a></p>
      ${(e.events || []).map(ev => html`<div class="event"><b>${ev.title}</b><div class="small muted">${ev.date} ${ev.place}</div><div class="small">${ev.summary}</div></div>`)}
      <${EntryPlayer} entry=${e} quotes=${(e.events || []).map(x => x.quote).filter(Boolean)} /></div>`;
  }
  if (pick && pick.type === "day" && d) {
    const day = d.days.find(x => x.date === pick.date);
    const rd = d.ride.days.find(x => x.date === pick.date);
    side = html`<div><h2>${fmtDay(day.date)}</h2>
      <${Facts} facts=${{ from: day.first ? `${day.first.town} at ${day.first.time}` : "", to: day.last ? `${day.last.town} at ${day.last.time}` : "",
        ...Object.fromEntries(Object.entries(day.km).map(([k, v]) => [k, fmtKm(v)])), photos: day.photos, events: day.events, entries: day.entries,
        ...(rd ? { "ridden": fmtKm(rd.km), "moving": `${Math.round(rd.moving_s / 60)} min`, "climbed": rd.gain_m != null ? `${rd.gain_m} m` : "",
                   "average": rd.avg_kmh ? `${rd.avg_kmh} km/h` : "" } : {}) }} />
      ${day.legs.map(n => { const l = d.legs[n]; return html`<div class="rowcard"><span class="swatch" style=${`background:${colour(l.class)}`}></span>
        <div class="grow">${l.mode || l.class} ${l.local_start.slice(11)} · ${l.from} → ${l.to} · ${l.routed_km} km</div></div>`; })}
      ${day.stays.map(n => html`<div class="rowcard">🛏 ${d.stays[n].town}</div>`)}</div>`;
  }

  const story = list.find(s => s.key === name) || (stories.data || []).find(s => s.name === name);
  let main = html`<div class="empty">Pick a story. Its days are its Start time and Stop time in story_plans/*.csv.</div>`;
  if (name && data.error) main = html`<div class="empty">${data.error.message}</div>`;
  else if (name) main = html`<div style="display:flex;flex-direction:column;height:100%">
    <div class="row" style="padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel)">
      <div class="tabs">${TABS.map(([k, l]) => html`<button class=${k === tab ? "on" : ""} onClick=${() => go("story", name, k)}>${l}</button>`)}</div>
      <span class="grow"></span><label class="small muted">days either side <input type="number" min="0" max="30" value=${pad} style="width:52px"
        onChange=${e => setPad(+e.target.value)} /></label></div>
    ${d && d.missing.length > 0 && html`<div class="banner">Missing: ${d.missing.join(", ")}</div>`}
    <div style="flex:1;position:relative;overflow:auto">
      ${tab === "text" && html`<${StoryText} name=${name} />`}
      ${tab === "map" && html`<${MapView} onReady=${setMap}><div class="legend"><span>● stay</span><span style="color:#ff7f0e">● photo</span><span style="color:#9467bd">● entry</span></div><//>`}
      ${tab === "days" && d && html`<div style="padding:14px 20px"><table class="grid"><tr><th>Day</th><th>From → to</th><th>Travelled</th>
          <th class="num">Photos</th><th class="num">Events</th><th class="num">Entries</th></tr>
        ${d.days.map(x => html`<tr class="click" onClick=${() => setPick({ type: "day", date: x.date })}><td>${fmtDay(x.date, { year: false })}</td>
          <td>${x.first ? `${x.first.town} → ${x.last.town}` : html`<span class="muted">nothing recorded</span>`}</td>
          <td>${Object.entries(x.km).map(([k, v]) => html`<span class="chip"><span class="swatch" style=${`background:${colour(k)}`}></span>${fmtKm(v)}</span>`)}</td>
          <td class="num">${x.photos || ""}</td><td class="num">${x.events || ""}</td><td class="num">${x.entries || ""}</td></tr>`)}</table>
        ${d.ride.total && html`<h3>The rides</h3><${Profile} ride=${d.ride} onPick=${ll => { go("story", name, "map"); setTimeout(() => map && map.setView(ll, 14), 300); }} />
          <${Facts} facts=${{ ridden: fmtKm(d.ride.total.km), moving: `${(d.ride.total.moving_s / 3600).toFixed(1)} h`,
            "average speed": `${d.ride.total.avg_kmh} km/h`, "top speed": `${d.ride.total.max_kmh} km/h`,
            climbed: d.ride.total.gain_m != null ? `${d.ride.total.gain_m} m` : "", rides: d.ride.total.rides }} />`}</div>`}
      ${tab === "photos" && d && html`<div class="photos">${d.photos.map((p, i) => html`<figure onClick=${() => setPick({ type: "photo", i })}>
        <img loading="lazy" src=${thumbUrl(p.file)} /><figcaption>${fmtDay(p.local_date, { year: false })} ${p.local_time} · ${p.town}</figcaption></figure>`)}</div>`}
      ${tab === "events" && d && html`<div style="padding:14px 20px">${d.events.map(e => html`<div class="event">
        <div class="row"><b class="grow">${e.title}</b><span class="muted small">${fmtDay(e.day, { year: false })}${e.date_guessed === "yes" ? " (a guess)" : ""}</span></div>
        <div class="small muted">${[e.place, e.people.join(", ")].filter(Boolean).join(" · ")}</div>
        <div>${e.summary}</div>${e.tags.map(t => html`<span class="chip">${t}</span>`)}
        <div class="small"><a onClick=${() => setPick({ type: "entry", key: e.entry })}>from ${e.entry}</a>${e.reviewed ? html` · <${Pill} status=${e.reviewed} />` : ""}</div></div>`)}</div>`}
      ${tab === "entries" && d && html`<div style="padding:14px 20px"><table class="grid"><tr><th>Made</th><th>Kind</th><th>Where</th><th class="num">Words</th><th class="num">Events</th></tr>
        ${d.entries.map(e => html`<tr class="click" onClick=${() => setPick({ type: "entry", key: e.key })}><td>${fmtDay(e.local_date, { year: false })} ${e.local_time}${e.later ? " (recalls these days)" : ""}</td>
          <td>${e.kind}</td><td>${e.town}</td><td class="num">${e.words}</td><td class="num">${e.events || ""}</td></tr>`)}</table></div>`}
      ${tab === "suggestions" && html`<${Suggestions} name=${name} pad=${pad} />`}
    </div></div>`;

  return html`<div class="view wide-main">
    <${Queue} items=${list} selected=${name} onSelect=${select} search=${search} setSearch=${setSearch}
      row=${s => html`<div class="t"><b>${s.name}</b>${s.problem ? html`<span class="pill todo" title=${s.problem}>no dates</span>` : ""}</div>
        <div class="s">${s.start ? `${fmtDay(s.start, { year: false })} → ${fmtDay(s.stop)}` : s.problem || "no dates in its plan"} · ${s.words || 0} words · ${s.plan.replace(".csv", "")}</div>`}
      empty=${stories.loading ? "Loading…" : "No stories."} />
    <main class="main">${main}</main>
    <aside class="inspector">${story && html`<div><h2>${story.name}</h2><p class="small">${story.description}</p></div>`}${side}</aside></div>`;
}

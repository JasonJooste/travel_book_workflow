// What every view shares: talking to the server, saving with undo, formatting, and the parts every
// view is built from (the queue, the facts grid, the map, the place search, dialogs).
import { html, useEffect, useMemo, useRef, useState } from "./vendor/preact-htm.js";

export { html, useEffect, useMemo, useRef, useState };

// ---- events between the parts of the page

const listeners = {};
export function on(name, fn) { (listeners[name] ||= new Set()).add(fn); return () => listeners[name].delete(fn); }
export function emit(name, data) { for (const fn of listeners[name] || []) fn(data); }
export function useEvent(name, fn) { useEffect(() => on(name, fn), [name, fn]); }

// ---- the server

export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}

export async function api(path, { method = "GET", body } = {}) {
  const r = await fetch("/api/" + path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!r.ok) throw new ApiError(r.status, (data && data.error) || `${r.status}`, data);
  return data;
}

// Data from a GET, again whenever something is saved or rebuilt
export function useData(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEvent("changed", useMemo(() => () => setTick(t => t + 1), []));
  useEvent("rebuilt", useMemo(() => () => setTick(t => t + 1), []));
  useEffect(() => {
    if (!path) return;
    let live = true;
    setState(s => ({ ...s, loading: true }));
    api(path).then(data => live && setState({ data, error: null, loading: false }))
      .catch(error => live && setState({ data: null, error, loading: false }));
    return () => { live = false; };
  }, [path, tick, ...deps]);
  return state;
}

// Save a change to manual/: ops are applied together, as one step for Undo
export async function change(why, ops, { quiet = false } = {}) {
  try {
    const out = await api("change", { method: "POST", body: { why, ops } });
    if (!quiet && out.id) toast(why, { undo: true });
    emit("changed");
    return out;
  } catch (e) {
    if (e.status === 409) dialog({ title: "That changed since you loaded it",
      body: `${e.message}. It's been reloaded: look again, and make your change once more if it's still needed.` });
    else toast(e.message, { error: true });
    emit("changed");
    throw e;
  }
}

export async function undo() {
  try {
    const out = await api("undo", { method: "POST" });
    toast(`Undone: ${out.why}`);
    emit("changed");
  } catch (e) { toast(e.message, { error: true }); }
}

// ---- toasts and dialogs

export function toast(text, opts = {}) { emit("toast", { text, ...opts, id: Math.random() }); }
export function dialog(d) { emit("dialog", d); }

// ---- formatting. Times come from the server as {utc, local, offset}; local is shown, UTC on hover

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parts(iso) {  // "2024-09-18T12:05" or "2024-09-18" -> pieces, as written (no time zones)
  const [d, t] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, day)).getUTCDay();
  return { y, m, day, wd, time: t ? t.slice(0, 5) : "" };
}
export function fmtDay(iso, { year = true, weekday = true } = {}) {
  if (!iso) return "";
  const p = parts(iso);
  return `${weekday ? DAYS[p.wd] + " " : ""}${p.day} ${MONTHS[p.m - 1]}${year ? " " + p.y : ""}`;
}
export function fmtOffset(min) {
  const s = min < 0 ? "−" : "+", a = Math.abs(min);
  return `UTC${s}${Math.floor(a / 60)}${a % 60 ? ":" + String(a % 60).padStart(2, "0") : ""}`;
}
export function fmtWhen(w, opts) {
  if (!w) return "";
  const p = parts(w.local);
  return html`<span title=${`${w.utc} (${fmtOffset(w.offset)})`}>${fmtDay(w.local, opts)}${p.time ? ", " + p.time : ""}</span>`;
}
export function fmtSpan(a, b) {
  if (!a) return "";
  const minutes = (Date.parse(b.utc.replace("Z", ":00Z")) - Date.parse(a.utc.replace("Z", ":00Z"))) / 60000;
  const sameDay = a.local.slice(0, 10) === b.local.slice(0, 10);
  return html`${fmtWhen(a)} → ${sameDay ? html`<span title=${b.utc}>${b.local.slice(11, 16)}</span>` : fmtWhen(b)}
    <span class="muted"> · ${fmtMinutes(minutes)} · ${fmtOffset(a.offset)}</span>`;
}
export function fmtMinutes(m) {
  if (m < 1) return "no time";
  if (m < 60) return `${Math.round(m)} min`;
  const h = Math.floor(m / 60), r = Math.round(m % 60);
  if (h < 48) return `${h} h${r ? " " + r + " min" : ""}`;
  return `${(h / 24).toFixed(1)} days`;
}
export const fmtKm = v => v == null ? "" : `${Number(v) >= 100 ? Math.round(v) : Number(v).toFixed(1)} km`;
export function nightsBetween(first, leaving) { return Math.round((Date.parse(leaving) - Date.parse(first)) / 864e5); }
export function addDays(iso, n) { const d = new Date(Date.parse(iso) + n * 864e5); return d.toISOString().slice(0, 10); }
export function plain(s) { return (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

// ---- the settings, loaded once

export let SETTINGS = null;
export async function loadSettings() { SETTINGS = await api("settings"); return SETTINGS; }
export function colour(cls) { return (SETTINGS && SETTINGS.colours[cls]) || "#000"; }
export function ModeChip({ mode }) {
  return html`<span class="chip"><span class="swatch" style=${`background:${colour(mode)}`}></span>${mode}</span>`;
}

// ---- facts: values shown as a grid, each with its label and unit

const FACTS = {
  km: ["Distance", fmtKm], straight_km: ["Straight line", fmtKm], hours: ["Time", h => fmtMinutes(h * 60)],
  kmh: ["Speed", v => `${v} km/h`], limit_kmh: ["Limit for the mode", v => `${v} km/h`], limit_km: ["Limit", fmtKm],
  mode: ["Mode", v => html`<${ModeChip} mode=${v} />`], class: ["Class", v => html`<${ModeChip} mode=${v} />`],
  from: ["From"], to: ["To"], router: ["Routed as"], mode_note: ["Row's note"], flags: ["Flags"],
  river: ["River"], waterway: ["Waterway"], kind: ["Kind"], minutes: ["Stopped", v => fmtMinutes(v)],
  tour: ["Komoot tour"], steps: ["Steps"], hops: ["Hops"], drawn: ["Drawn"], points: ["Points"], why: ["Why"],
  note: ["Note"], days: ["Days", v => `${v}`], legs: ["Gap legs it labels"], modes: ["Modes"],
  between: ["Between runs of"], day: ["Day (UTC)"], places: ["Known places"], factor: ["Detour", v => `${v}× the straight line`],
  point: ["Point"], at_utc: ["Point's time (UTC)"], problem: ["Problem"], same_minute: ["Ends", () => "in the same minute"],
};
export function Facts({ facts, order, bad = [] }) {
  const keys = order ? order.filter(k => facts[k] != null && facts[k] !== "") : Object.keys(facts);
  if (!keys.length) return null;
  return html`<dl class="facts">${keys.map(k => {
    const [label, fmt] = FACTS[k] || [k.replace(/_/g, " ")];
    return html`<dt>${label}</dt><dd class=${bad.includes(k) ? "bad" : ""}>${fmt ? fmt(facts[k]) : String(facts[k])}</dd>`;
  })}</dl>`;
}

// ---- the queue: what to look at, filtered and searched, one selected

export function Queue({ items, selected, onSelect, tabs, tab, setTab, search, setSearch, row, empty, foot, top }) {
  const ref = useRef();
  useEffect(() => {  // keep the selected one in view
    const el = ref.current && ref.current.querySelector("li.on");
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [selected]);
  return html`<aside class="queue">
    <div class="tools">
      ${top}
      ${tabs && html`<div class="tabs">${tabs.map(t => html`<button class=${t.key === tab ? "on" : ""}
        onClick=${() => setTab(t.key)}>${t.label}<span class="n">${t.count ?? ""}</span></button>`)}</div>`}
      ${setSearch && html`<input placeholder="Search  ( / )" value=${search} data-search
        onInput=${e => setSearch(e.target.value)} />`}
    </div>
    <ul ref=${ref}>
      ${items.length ? items.map(it => html`<li key=${it.key} class=${it.key === selected ? "on" : ""}
        onClick=${() => onSelect(it.key)}>${row(it)}</li>`) : html`<div class="empty">${empty || "Nothing here."}</div>`}
    </ul>
    ${foot && html`<div class="foot">${foot}</div>`}
  </aside>`;
}

// Step through a list with j and k: the key after or before the one selected
export function step(keys, selected, by) {
  if (!keys.length) return null;
  const i = keys.indexOf(selected);
  if (i < 0) return keys[by > 0 ? 0 : keys.length - 1];
  return keys[Math.max(0, Math.min(keys.length - 1, i + by))];
}

// ---- keys: the view in front says what each does; typing in a field is left alone

// Each part of the page that wants keys registers them; where two want the same key, the inner, more
// specific part has it (parts are numbered as they first render, outer before inner)
const registered = new Map();
let nextId = 0;
export function useKeys(map) {
  const id = useRef(null);
  if (id.current === null) id.current = nextId++;
  registered.set(id.current, map);  // the latest functions, every render
  useEffect(() => () => registered.delete(id.current), []);
}
function keyFor(key) {
  for (const [, map] of [...registered.entries()].sort((a, b) => b[0] - a[0])) if (map[key]) return map[key];
  return null;
}
document.addEventListener("keydown", e => {
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if (e.key === "Escape") { (keyFor("Escape") || (() => document.activeElement.blur()))(e); return; }
  if (typing && !(e.key === "Enter" && (e.ctrlKey || e.metaKey))) return;
  if (e.altKey || (e.ctrlKey && e.key !== "Enter") || e.metaKey && e.key !== "Enter") return;
  const key = e.key === "Enter" && (e.ctrlKey || e.metaKey) ? "Enter" : e.key;
  const fn = keyFor(key) || { u: undo, "?": () => emit("help"), "/": () => document.querySelector("[data-search]")?.focus() }[key];
  if (fn) { e.preventDefault(); fn(e); }
});

// ---- the map

const TILES = {
  "Map": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png", "&copy; OpenStreetMap contributors"],
  "Streets": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", "Tiles &copy; Esri"],
  "Satellite": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Tiles &copy; Esri"],
};
// A Leaflet map in a div; onReady gets it once. The same tiles and chooser in every view
export function MapView({ onReady, children }) {
  const div = useRef();
  useEffect(() => {
    const map = L.map(div.current, { preferCanvas: true, zoomControl: true }).setView([10, 10], 3);
    const layers = Object.fromEntries(Object.entries(TILES).map(([k, [url, attribution]]) =>
      [k, L.tileLayer(url, { maxZoom: 19, attribution })]));
    let base = "Map";
    try { base = localStorage.getItem("tiles") || "Map"; } catch {}
    (layers[base] || layers.Map).addTo(map);
    L.control.layers(layers, {}, { position: "topright" }).addTo(map);
    map.on("baselayerchange", e => { try { localStorage.setItem("tiles", e.name); } catch {} });
    onReady(map);
    return () => map.remove();
  }, []);
  return html`<div class="map-fill"><div ref=${div} class="map-fill"></div>${children}</div>`;
}

// A layer group that's redrawn from scratch whenever deps change
export function useLayer(map, draw, deps) {
  const group = useRef(null);
  useEffect(() => {
    if (!map) return;
    if (!group.current) group.current = L.layerGroup().addTo(map);
    group.current.clearLayers();
    draw(group.current);
  }, [map, ...deps]);
}

export function dot(lat, lon, { colour: c = "#333", radius = 5, fill = 1, weight = 1, stroke = "#fff", ...rest } = {}) {
  return L.circleMarker([lat, lon], { radius, color: stroke, weight, fillColor: c, fillOpacity: fill,
    bubblingMouseEvents: false, ...rest });
}

// A plus code from a position, and back: asked of the server, which has the library
export async function plusCode(lat, lon) { return (await api(`pluscode?lat=${lat}&lon=${lon}`)).code; }

// ---- searching for a place (Photon: OpenStreetMap's places, typos forgiven), or a lat,lon pasted

export function PlaceSearch({ onPick, near, placeholder = "Search for a place, or paste lat, lon" }) {
  const [q, setQ] = useState(""), [found, setFound] = useState([]);
  useEffect(() => {
    const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (m) { setFound([{ name: `${m[1]}, ${m[2]}`, lat: +m[1], lon: +m[2] }]); return; }
    if (q.trim().length < 3) { setFound([]); return; }
    const t = setTimeout(async () => {
      const bias = near ? `&lat=${near[0]}&lon=${near[1]}` : "";
      try {
        const r = await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=8${bias}`);
        const data = await r.json();
        setFound(data.features.map(f => ({ name: [f.properties.name, f.properties.city, f.properties.country]
          .filter((x, i, a) => x && a.indexOf(x) === i).join(", "), lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] })));
      } catch { setFound([{ name: "Place search needs a connection", lat: null }]); }
    }, 350);
    return () => clearTimeout(t);
  }, [q]);
  return html`<div class="searchbox"><input style="width:100%" placeholder=${placeholder} value=${q}
      onInput=${e => setQ(e.target.value)} />
    ${found.length > 0 && html`<ul>${found.map(f => html`<li onClick=${() => { if (f.lat != null) { onPick(f); setQ(""); setFound([]); } }}>
      ${f.name}</li>`)}</ul>`}</div>`;
}

// ---- small parts

export function Pill({ status, label }) { return html`<span class="pill ${status}">${label || status}</span>`; }

export function Action({ main, label, why, onClick, keyName, danger, disabled }) {
  return html`<div class="action ${main ? "main" : ""}">
    <button class=${main ? "primary" : danger ? "danger" : ""} onClick=${onClick} disabled=${disabled}>${label}</button>
    <span class="why">${why}</span>${keyName && html`<kbd>${keyName}</kbd>`}</div>`;
}

export function Loading({ state, children }) {
  if (state.error) return html`<div class="empty">Couldn't load: ${state.error.message}</div>`;
  if (!state.data) return html`<div class="empty">Loading…</div>`;
  return children;
}

export function photoUrl(file) { return "/files/" + file.split("/").map(encodeURIComponent).join("/"); }
export function thumbUrl(file) { return "/api/thumb?f=" + encodeURIComponent(file); }

// The hash: #/view/rest/of/it
export function route() {
  const [view, ...rest] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  return { view: view || "route", rest };
}
export function go(view, ...rest) {
  const hash = "#/" + [view, ...rest.filter(x => x != null && x !== "")].map(encodeURIComponent).join("/");
  if (location.hash !== hash) history.replaceState(null, "", hash);
  emit("hash");
}
export function useHash() {
  const [h, setH] = useState(route());
  useEvent("hash", useMemo(() => () => setH(route()), []));
  useEffect(() => { const f = () => setH(route()); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return h;
}

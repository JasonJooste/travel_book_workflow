// The Diary view: each entry's events, checked against its audio and text.
// The entry plays in the middle, its transcript following along; its events are on the right, as Claude
// gave them or as you left them. Every edit saves as you go (to manual/events/), and make events then
// keeps your version and never asks Claude about the entry again. Mark verified when it's right.
import {
  Action, DayInput, Facts, Pill, Queue, change, fmtDay, go, html, plain, step, useData, useEffect, useKeys, useMemo,
  useRef, useState,
} from "../lib.js";

const STATUS = { "": "to review", edited: "edited", verified: "verified" };
const KIND = { audio: "🎙", written: "✎", blog: "📰", komoot: "🚲" };
const blank = () => ({ title: "", summary: "", date: "", date_guessed: false, place: "", people: [], tags: [], quote: "" });

// Pieces of the text a quote is from, by its words
function quoteSegs(segments, quote) {
  const words = plain(quote).replace(/[^\w\s]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const flat = segments.map(s => plain(s[2]).replace(/[^\w\s]/g, " "));
  const probe = words.slice(0, Math.min(5, words.length)).join(" ");
  const hits = [];
  flat.forEach((t, i) => { if (t.replace(/\s+/g, " ").includes(probe)) hits.push(i); });
  if (!hits.length) {  // spread over two pieces
    for (let i = 0; i + 1 < flat.length; i++) if ((flat[i] + " " + flat[i + 1]).replace(/\s+/g, " ").includes(probe)) return [i, i + 1];
  }
  return hits;
}

export function EntryPlayer({ entry, quotes = [], flash }) {
  const audio = useRef(), [now, setNow] = useState(-1), [follow, setFollow] = useState(true);
  const segs = entry.segments;
  const quoted = useMemo(() => new Set(quotes.flatMap(q => quoteSegs(segs, q))), [entry, quotes.join("|")]);
  useEffect(() => {
    if (flash == null) return;
    const i = quoteSegs(segs, flash.quote)[0];
    if (i == null) return;
    const el = document.getElementById("seg" + i);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1500); }
    if (audio.current && segs[i][0] != null) audio.current.currentTime = segs[i][0];
  }, [flash]);
  const tick = () => {
    const t = audio.current.currentTime;
    const i = segs.findIndex(s => s[0] != null && s[0] <= t && t < s[1]);
    if (i !== now) {
      setNow(i);
      const el = follow && document.getElementById("seg" + i);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
  };
  const seek = s => { if (audio.current && s[0] != null) { audio.current.currentTime = s[0]; audio.current.play(); } };
  useKeys({ " ": () => audio.current && (audio.current.paused ? audio.current.play() : audio.current.pause()) });
  return html`<div>
    ${entry.audio && html`<div class="player"><audio ref=${audio} src=${entry.audio} controls preload="metadata" onTimeUpdate=${tick} />
      <div class="row small muted">
        ${[1, 1.25, 1.5, 2].map(r => html`<button onClick=${() => { audio.current.playbackRate = r; }}>${r}×</button>`)}
        <label><input type="checkbox" checked=${follow} onChange=${e => setFollow(e.target.checked)} /> follow along</label>
        <span class="grow"></span><kbd>space</kbd> play/pause
        ${entry.timing === "approximate" && html`<span class="pill pending" title="The transcript has no timings: each piece's time is guessed from its length">times approximate</span>`}
      </div></div>`}
    <div class="transcript">${segs.map((s, i) => html`<span id=${"seg" + i}
      class=${`seg ${s[0] != null ? "timed" : ""} ${quoted.has(i) ? "q" : ""} ${i === now ? "now" : ""}`}
      onClick=${() => seek(s)}>${s[2]} </span>`)}${entry.timing === "" && html`<p class="muted small">Written text: no audio.</p>`}</div>
  </div>`;
}

function ListInput({ values, onChange, options, placeholder, suggested = [], onSuggested }) {
  const [text, setText] = useState("");
  const add = v => { v = v.trim(); if (v && !values.includes(v)) onChange([...values, v]); setText(""); };
  const id = useMemo(() => "dl" + Math.random().toString(36).slice(2), []);
  return html`<div>${values.map(v => html`<span class="chip">${v}<button title="Remove"
      onClick=${() => onChange(values.filter(x => x !== v))}>×</button></span>`)}
    ${suggested.filter(s => !values.includes(s.name)).map(s => html`<span class="chip suggested" title=${`Suggested by Claude: ${s.description}. Click to add it to the tag list and to this event`}
      onClick=${() => onSuggested(s)}>+ ${s.name}</span>`)}
    <input list=${options ? id : null} value=${text} placeholder=${placeholder} size="14"
      onInput=${e => { setText(e.target.value); if (options && options.includes(e.target.value)) add(e.target.value); }}
      onKeyDown=${e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(text); } }} onBlur=${() => text && !options && add(text)} />
    ${options && html`<datalist id=${id}>${options.map(o => html`<option value=${o} />`)}</datalist>`}</div>`;
}

function EventCard({ ev, n, count, tags, suggested, onChange, onMove, onDelete, onFind, onSuggested }) {
  const set = (k, v) => onChange({ ...ev, [k]: v });
  return html`<div class="event">
    <div class="head"><span class="muted">${n + 1}</span><input value=${ev.title} placeholder="Title" onInput=${e => set("title", e.target.value)} />
      <button disabled=${n === 0} onClick=${() => onMove(-1)} title="Up">↑</button>
      <button disabled=${n === count - 1} onClick=${() => onMove(1)} title="Down">↓</button>
      <button class="danger" onClick=${onDelete} title="Delete this event">✕</button></div>
    <div class="form">
      <label>Summary</label><textarea rows="3" value=${ev.summary} onInput=${e => set("summary", e.target.value)} />
      <label>Date</label><div class="row"><${DayInput} value=${ev.date} onChange=${v => set("date", v)} />
        <label class="small"><input type="checkbox" checked=${ev.date_guessed} onChange=${e => set("date_guessed", e.target.checked)} /> a guess</label></div>
      <label>Place</label><input value=${ev.place} onInput=${e => set("place", e.target.value)} />
      <label>People</label><${ListInput} values=${ev.people} onChange=${v => set("people", v)} placeholder="add a name" />
      <label>Tags</label><${ListInput} values=${ev.tags} options=${tags} onChange=${v => set("tags", v)} placeholder="add a tag"
        suggested=${suggested} onSuggested=${s => onSuggested(s, n)} />
      <label>Quote</label><div class="row"><input class="grow" value=${ev.quote} onInput=${e => set("quote", e.target.value)} />
        ${ev.quote && html`<button onClick=${onFind} title="Show it in the text">Find</button>`}</div>
    </div></div>`;
}

function Editor({ entry, tags, next, setQuotes, setFlash }) {
  const [rec, setRec] = useState(null);
  const saving = useRef(null);
  useEffect(() => setRec({ events: entry.events.map(e => ({ ...blank(), ...e })), note: entry.note, verified: entry.verified,
                           language: entry.language }), [entry.stem, entry.kind]);
  const save = (r, why) => change(why || `Review ${entry.stem}`, [{ entry: [entry.kind, entry.stem], op: "put", record: r }],
                                  { quiet: !why });
  const update = r => {  // saved a moment after the last keystroke
    setRec(r);
    clearTimeout(saving.current);
    saving.current = setTimeout(() => save(r), 1200);
  };
  useEffect(() => () => clearTimeout(saving.current), [entry.stem]);
  useEffect(() => { if (rec) setQuotes(rec.events.map(e => e.quote).filter(Boolean)); }, [rec]);
  if (!rec) return null;
  const setEvent = (i, ev) => update({ ...rec, events: rec.events.map((x, j) => j === i ? ev : x) });
  const move = (i, by) => { const ev = [...rec.events]; [ev[i], ev[i + by]] = [ev[i + by], ev[i]]; update({ ...rec, events: ev }); };
  const verify = () => { clearTimeout(saving.current); setRec({ ...rec, verified: true });
    save({ ...rec, verified: true }, `${entry.stem}: verified`).then(next); };
  const addSuggested = (s, i) => change(`New tag ${s.name}, on ${entry.stem}`, [
    { table: "tags", op: "add", row: { tag: s.name, description: s.description } },
    { entry: [entry.kind, entry.stem], op: "put", record: { ...rec, events: rec.events.map((x, j) => j === i ? { ...x, tags: [...x.tags, s.name] } : x) } },
  ]).then(() => setRec({ ...rec, events: rec.events.map((x, j) => j === i ? { ...x, tags: [...x.tags, s.name] } : x) }));
  useKeys({ Enter: verify });
  return html`<div>
    <div class="row"><${Pill} status=${entry.status} label=${STATUS[entry.status]} />
      ${entry.has_llm && html`<span class="muted small">events by Claude (${entry.model})</span>`}</div>
    <h2>${KIND[entry.kind]} ${entry.stem}</h2>
    <div class="when">${entry.info.local_date ? fmtDay(entry.info.local_date) : "no date"}${entry.info.town ? ` · ${entry.info.town}, ${entry.info.country}` : ""}</div>
    <h3>The entry</h3>
    <${Facts} facts=${{ kind: entry.kind_name, words: entry.info.words, "length": entry.info.duration_min ? `${entry.info.duration_min} min` : "",
      language: rec.language || entry.info.language, "dated by": (entry.info.date_source || "").replace("_", " "),
      "placed by": (entry.info.position_source || "").replace(/_/g, " "), transcript: entry.info.transcript_source,
      file: entry.text_file }} />
    <p class="muted small">Its date and place come from make locate: to correct them, add a known place in Places.</p>
    <h3>Events (${rec.events.length})</h3>
    ${rec.events.map((ev, i) => html`<${EventCard} ev=${ev} n=${i} count=${rec.events.length} tags=${tags}
      suggested=${entry.suggested} onChange=${e => setEvent(i, e)} onMove=${by => move(i, by)}
      onDelete=${() => update({ ...rec, events: rec.events.filter((_, j) => j !== i) })} onFind=${() => setFlash({ quote: ev.quote, at: Date.now() })}
      onSuggested=${addSuggested} />`)}
    <button onClick=${() => update({ ...rec, events: [...rec.events, blank()] })}>+ Add an event</button>
    <h3>Your note on the entry</h3>
    <textarea rows="2" value=${rec.note} onInput=${e => update({ ...rec, note: e.target.value })} />
    <h3>What to do</h3><div class="actions">
      <${Action} main label=${rec.verified ? "Verified ✓ — next" : "Mark verified"} keyName="Ctrl+Enter" onClick=${verify}
        why="Your edits are saved as you make them; this says the events are right, and moves on." />
      ${entry.status && entry.has_llm && html`<${Action} label="Back to Claude's events" danger
        onClick=${() => change(`${entry.stem}: back to Claude's events`, [{ entry: [entry.kind, entry.stem], op: "drop" }])}
        why="Drops your version (Undo brings it back)." />`}
    </div>
  </div>`;
}

export function DiaryView({ rest }) {
  const list = useData("diary"), tagsData = useData("tags");
  const [tab, setTab] = useState("todo"), [search, setSearch] = useState("");
  const [quotes, setQuotes] = useState([]), [flash, setFlash] = useState(null);
  const [kind, stem] = rest;
  const key = kind && stem ? `${kind}/${stem}` : null;
  const entry = useData(key ? `diary/${key}` : null, [key]);
  const items = (list.data || []).map(e => ({ ...e, key: `${e.kind}/${e.stem}` }));
  const tabs = [
    { key: "todo", label: "To review", test: e => !e.status && e.events },
    { key: "edited", label: "Edited", test: e => e.status === "edited" },
    { key: "verified", label: "Verified", test: e => e.status === "verified" },
    { key: "none", label: "No events yet", test: e => !e.events },
    { key: "all", label: "All", test: () => true },
  ].map(t => ({ ...t, count: items.filter(t.test).length }));
  const q = plain(search);
  const shown = items.filter(tabs.find(t => t.key === tab).test)
    .filter(e => !q || plain(`${e.stem} ${e.town} ${e.date} ${e.titles.join(" ")}`).includes(q));
  const select = k => go("diary", ...k.split("/"));
  const next = () => { const n = step(shown.map(e => e.key), key, 1); if (n && n !== key) select(n); };
  useKeys({ j: next, "]": next, k: () => { const n = step(shown.map(e => e.key), key, -1); if (n) select(n); },
            "[": () => { const n = step(shown.map(e => e.key), key, -1); if (n) select(n); } });
  const tags = (tagsData.data ? tagsData.data.tags : []).map(t => t.tag);
  const e = entry.data;
  return html`<div class="view wide-main">
    <${Queue} items=${shown} selected=${key} onSelect=${select} tabs=${tabs} tab=${tab} setTab=${setTab}
      search=${search} setSearch=${setSearch} empty=${list.loading ? "Loading…" : "None."}
      row=${i => html`<div class="t"><span>${KIND[i.kind]}</span><b>${i.stem}</b><${Pill} status=${i.status} label=${STATUS[i.status]} /></div>
        <div class="s">${i.date ? fmtDay(i.date) : "no date"}${i.town ? " · " + i.town : ""} · ${i.words} words · ${i.events ?? "no"} events</div>
        ${i.titles.length > 0 && html`<div class="s" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${i.titles.join(" · ")}</div>`}`}
      foot=${html`<kbd>j</kbd>/<kbd>k</kbd> step · <kbd>Ctrl+Enter</kbd> verified · <kbd>u</kbd> undo`} />
    <main class="main">${e ? html`<${EntryPlayer} entry=${e} quotes=${quotes} flash=${flash} key=${key} />`
      : html`<div class="empty">Pick an entry.</div>`}</main>
    <aside class="inspector">${e ? html`<${Editor} entry=${e} tags=${tags} next=${next} key=${key} setQuotes=${setQuotes} setFlash=${setFlash} />`
      : html`<div class="empty">Each entry's events, as Claude gave them: check them against the audio and text,
          correct them, and mark the entry verified. <kbd>j</kbd> for the next.</div>`}</aside></div>`;
}


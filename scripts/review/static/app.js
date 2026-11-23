// The review app's frame: the views along the top, a banner when what you're looking at was built
// before your latest answers (with a button to rebuild it), toasts with Undo, dialogs, and the keys.
import { api, emit, html, loadSettings, on, undo, useData, useEffect, useEvent, useHash, useMemo, useState } from "./lib.js";
import { render } from "./vendor/preact-htm.js";
import { RouteView } from "./views/route.js";
import { StaysView } from "./views/stays.js";
import { PlacesView } from "./views/places.js";
import { DiaryView } from "./views/diary.js";
import { TagsView } from "./views/tags.js";
import { StoryView } from "./views/story.js";

const VIEWS = [
  { key: "stays", label: "Stays", view: StaysView, outputs: ["route"],
    help: "Where you slept: check each stay against what the rides and photos say." },
  { key: "route", label: "Route", view: RouteView, outputs: ["route", "findings"],
    help: "How each stretch was travelled, and what looks wrong in the route." },
  { key: "places", label: "Places", view: PlacesView, outputs: ["places"],
    help: "Towns that matched more than one place, days with nothing to say where you were, and your known places." },
  { key: "diary", label: "Diary", view: DiaryView, outputs: ["events"],
    help: "Each entry's events, checked against its audio and text." },
  { key: "tags", label: "Tags", view: TagsView, outputs: ["events"], help: "The tags events can carry." },
  { key: "story", label: "Story", view: StoryView, outputs: [],
    help: "A story beside everything the trip left from its days." },
];

const KEYS = [
  ["j / k", "next / previous in the list"], ["Enter", "the highlighted action (Ctrl+Enter while typing)"],
  ["u", "undo the last change"], ["/", "search the list"], ["Esc", "cancel, or leave a field"], ["?", "this sheet"],
];

function Banner({ outputs }) {
  const status = useData("status");
  const [job, setJob] = useState(null);
  // While a rebuild runs, follow its output; when it ends, everything reloads
  useEffect(() => {
    let live = true, since = 0, lines = [];
    const poll = async () => {
      const j = await api(`rebuild?since=${since}`).catch(() => null);
      if (!live || !j) return;
      lines = lines.concat(j.lines); since = j.line_count;
      setJob({ ...j, lines });
      if (j.running) setTimeout(poll, 800);
      else if (j.code === 0 && j.finished && Date.now() / 1000 - j.finished < 5) emit("rebuilt");
    };
    const off = on("rebuild", () => { since = 0; lines = []; poll(); });
    poll();
    return () => { live = false; off(); };
  }, []);
  if (job && job.running) return html`<div class="banner running"><b>make ${job.target}</b> is running…
    <pre>${job.lines.slice(-6).join("\n")}</pre></div>`;
  if (job && job.code && job.code !== 0) return html`<div class="banner failed"><b>make ${job.target} failed</b>
    <pre>${job.lines.slice(-12).join("\n")}</pre><button onClick=${() => setJob(null)}>Close</button></div>`;
  if (!status.data) return null;
  const stale = outputs.map(k => status.data[k]).filter(s => s && s.stale);
  if (!stale.length) return null;
  const s = stale[0], n = stale.reduce((a, x) => a + x.changes.length, 0);
  const rebuild = async () => {
    try { await api("rebuild", { method: "POST", body: { target: s.target } }); emit("rebuild"); }
    catch (e) { emit("toast", { text: e.message, error: true, id: Math.random() }); }
  };
  return html`<div class="banner">
    <span><b>${stale.map(x => x.name).join(" and ")}</b> ${stale.length > 1 ? "were" : "was"} built
      ${s.built ? s.built.replace("T", " at ") : "never"}${n ? `, before ${n} change${n > 1 ? "s" : ""} of yours` : ""}
      (${[...new Set(stale.flatMap(x => x.newer))].join(", ")}): what's shown may be out of date.</span>
    <span class="grow"></span>
    <button class="primary" onClick=${rebuild}>Rebuild (make ${s.target})</button></div>`;
}

function Toasts() {
  const [list, setList] = useState([]);
  useEvent("toast", useMemo(() => t => {
    setList(l => [...l.slice(-2), t]);
    setTimeout(() => setList(l => l.filter(x => x.id !== t.id)), t.error ? 8000 : 5000);
  }, []));
  return html`<div class="toasts">${list.map(t => html`<div class="toast ${t.error ? "error" : ""}">
    <span>${t.error ? "" : "Saved: "}${t.text}</span>
    ${t.undo && html`<button onClick=${() => { undo(); setList(l => l.filter(x => x.id !== t.id)); }}>Undo <kbd>u</kbd></button>`}
  </div>`)}</div>`;
}

function Dialogs() {
  const [d, setD] = useState(null);
  useEvent("dialog", useMemo(() => x => setD(x), []));
  useEvent("help", useMemo(() => () => setD({ help: true }), []));
  if (!d) return null;
  const close = () => setD(null);
  return html`<div class="overlay" onClick=${e => e.target === e.currentTarget && close()}><div class="dialog">
    ${d.help ? html`<h2>Keys</h2><div class="keys">${KEYS.map(([k, v]) => html`<kbd>${k}</kbd><span>${v}</span>`)}</div>
      <h2 style="margin-top:18px">Views</h2>${VIEWS.map(v => html`<p><b>${v.label}</b>: ${v.help}</p>`)}
      <p class="muted small">Every change saves to manual/ as you make it, and Undo puts it back. The rows' earlier
        versions are kept in manual/.history, and manual/ is in git.</p>`
      : html`<h2>${d.title}</h2><p>${d.body}</p>`}
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="primary" onClick=${close}>OK</button></div>
  </div></div>`;
}

function Changes({ onClose }) {
  const list = useData("changes");
  return html`<div class="overlay" onClick=${e => e.target === e.currentTarget && onClose()}><div class="dialog">
    <h2>Your recent changes</h2>
    ${list.data && html`<table class="grid"><tr><th>When</th><th>What</th><th>Files</th></tr>
      ${list.data.map(c => html`<tr class=${c.undone ? "muted" : ""}><td>${c.at.replace("T", " ")}</td>
        <td>${c.why}${c.undone ? " (undone)" : ""}</td><td class="small">${c.files.map(f => f.path).join(", ")}</td></tr>`)}</table>`}
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button onClick=${undo}>Undo the last</button>
      <button class="primary" onClick=${onClose}>Close</button></div></div></div>`;
}

function App() {
  const hash = useHash();
  const [changes, setChanges] = useState(false);
  const current = VIEWS.find(v => v.key === hash.view) || VIEWS[1];
  const View = current.view;
  return html`
    <header class="top">
      <span class="brand">Travel book</span>
      <nav>${VIEWS.map(v => html`<a href=${"#/" + v.key} class=${v === current ? "on" : ""} title=${v.help}>${v.label}</a>`)}</nav>
      <span class="grow"></span>
      <button onClick=${() => setChanges(true)} title="What you've changed, newest first">History</button>
      <button onClick=${undo} title="Undo the last change (u)">Undo</button>
      <button onClick=${() => emit("help")} title="Keys and views (?)">?</button>
    </header>
    <${Banner} outputs=${current.outputs} key=${current.key} />
    <${View} key=${current.key} rest=${hash.rest} />
    <${Toasts} /><${Dialogs} />${changes && html`<${Changes} onClose=${() => setChanges(false)} />`}`;
}

loadSettings().then(() => render(html`<${App} />`, document.getElementById("app")))
  .catch(e => { document.getElementById("app").textContent = "Couldn't reach the review server: " + e.message; });

// The Tags view: the tags events can carry (manual/tags.csv), how many events carry each, the tags
// Claude would add, and which tags overlap. A description is edited in place and saved as you leave
// it; a tag still on events you reviewed can't be deleted until it's off them.
import { Action, api, change, html, plain, toast, useData, useState } from "../lib.js";

function TagRow({ t, reviewed }) {
  const [text, setText] = useState(t.description);
  const save = () => text.trim() !== t.description && change(`Tag ${t.tag}: new description`,
    [{ table: "tags", op: "update", key: t.tag, base: { description: t.description }, row: { description: text.trim() } }]);
  return html`<tr><td><b>${t.tag}</b></td>
    <td><input style="width:100%" value=${text} onInput=${e => setText(e.target.value)} onChange=${save} /></td>
    <td class="num">${t.events}</td>
    <td><button class="danger" disabled=${reviewed} title=${reviewed ? "On events you reviewed: take it off them first" : "Delete the tag"}
      onClick=${() => change(`Delete the tag ${t.tag}`, [{ table: "tags", op: "delete", key: t.tag }])}>✕</button></td></tr>`;
}

export function TagsView() {
  const state = useData("tags");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState(""), [desc, setDesc] = useState("");
  const [overlap, setOverlap] = useState(null), [asking, setAsking] = useState(false);
  if (!state.data) return html`<div class="empty">Loading…</div>`;
  const d = state.data, q = plain(search);
  const add = (name, description) => change(`New tag ${name}`, [{ table: "tags", op: "add", row: { tag: name, description } }])
    .then(() => { setTag(""); setDesc(""); });
  const ask = async candidate => {
    setAsking(true);
    try { setOverlap({ ...(await api("tags/overlap", { method: "POST", body: { candidate } })), candidate }); }
    catch (e) { toast(e.message, { error: true }); }
    setAsking(false);
  };
  return html`<div class="view" style="grid-template-columns: 1fr 440px">
    <main class="main" style="padding:16px 20px">
      <div class="row"><h2 style="margin:0" class="grow">${d.tags.length} tags, on ${d.events} events</h2>
        <input placeholder="Filter" value=${search} onInput=${e => setSearch(e.target.value)} data-search /></div>
      <table class="grid" style="margin-top:10px"><tr><th>Tag</th><th>Description</th><th class="num">Events</th><th></th></tr>
        ${d.tags.filter(t => !q || plain(t.tag + " " + t.description).includes(q))
          .map(t => html`<${TagRow} key=${t.tag + t.description} t=${t} reviewed=${d.reviewed.includes(t.tag)} />`)}</table>
      <h3>Add a tag</h3>
      <div class="row"><input placeholder="name_like_this" value=${tag} onInput=${e => setTag(e.target.value)} />
        <input class="grow" placeholder="what it's for, in the list's style" value=${desc} onInput=${e => setDesc(e.target.value)} />
        <button disabled=${!tag || !desc || asking} onClick=${() => ask({ tag, description: desc })}>Check for overlap</button>
        <button class="primary" disabled=${!tag || !desc} onClick=${() => add(tag, desc)}>Add</button></div>
      <p class="muted small">Events only carry a new tag once make events runs again with --redo-stale, or as you add it in Diary.</p>
    </main>
    <aside class="inspector">
      <h3>Suggested by Claude</h3>
      ${d.suggested.length ? d.suggested.map(s => html`<div class="rowcard"><div class="grow"><b>${s.tag}</b> · ${s.count} entries
          <div class="muted small">${s.description}</div></div>
        <button onClick=${() => add(s.tag, s.description)}>Add</button></div>`) : html`<p class="muted">None waiting.</p>`}
      <h3>Overlaps</h3>
      <${Action} label=${asking ? "Asking Claude…" : "Ask Claude which tags overlap"} disabled=${asking} onClick=${() => ask(null)}
        why="Pairs where an event that fits one nearly always fits the other." />
      ${overlap && html`<div style="margin-top:8px">${overlap.pairs.length ? overlap.pairs.map(p => html`<div class="rowcard"><div class="grow">
          <b>${p.a}</b> and <b>${p.b}</b><div class="small">${p.reason}</div><div class="small muted">${p.suggestion}</div></div></div>`)
        : html`<p class="muted">${overlap.candidate ? `${overlap.candidate.tag} overlaps no tag in the list.` : "No overlaps."}</p>`}</div>`}
      <h3>Tags that go together most</h3>
      <table class="grid">${d.pairs.slice(0, 20).map(([a, b, n]) => html`<tr><td>${a}</td><td>${b}</td><td class="num">${n}</td></tr>`)}</table>
    </aside></div>`;
}

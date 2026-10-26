"""A self-contained index.html for browsing an export offline (no network needed)."""
from __future__ import annotations

import json
import html
from datetime import datetime

from ..models.taxonomy import AXES

_TEMPLATE = r"""<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#f4f7fc; --panel:#fff; --text:#17233d; --muted:#64748b; --line:#dfe7f1; --accent:#3157d5;
        --ok:#15803d; --okbg:#dcfce7; --chip:#e8edff; --chiptext:#30439a; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:"Noto Sans Bengali","Nirmala UI","Hind Siliguri","Segoe UI",system-ui,sans-serif; }
header { position:sticky; top:0; z-index:5; background:linear-gradient(105deg,#142b63,#334fc5 70%,#486ddf);
         color:#fff; padding:16px 22px; display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
         box-shadow:0 5px 20px rgba(25,45,100,.14); }
header h1 { font-size:20px; margin:0; font-weight:700; letter-spacing:.01em; }
header .meta { font-size:13px; opacity:.85; }
.filters { display:flex; flex-wrap:wrap; gap:8px; padding:12px 20px; background:var(--panel);
           border-bottom:1px solid var(--line); position:sticky; top:44px; z-index:4; }
.search { min-width:220px; max-width:410px; flex:1; border:1px solid var(--line); border-radius:10px;
          padding:8px 11px; color:var(--text); font:inherit; background:#fbfcff; }
.search:focus { outline:2px solid #b7c6ff; border-color:var(--accent); }
#filters { display:flex; flex:4; flex-wrap:wrap; gap:6px; align-items:center; }
.chip { border:1px solid #c7d2fe; background:var(--chip); color:var(--chiptext); border-radius:999px;
        padding:4px 10px; font-size:13px; cursor:pointer; }
.chip.on { background:var(--accent); color:#fff; border-color:var(--accent); }
.layout { display:grid; grid-template-columns: 244px 1fr; min-height:calc(100vh - 100px); }
nav { border-right:1px solid var(--line); background:var(--panel); padding:8px; overflow:auto;
      max-height:calc(100vh - 100px); position:sticky; top:100px; }
nav .doc { font-weight:600; margin:10px 6px 4px; font-size:14px; display:flex; justify-content:space-between; }
nav .doc a.file { font-weight:500; font-size:12px; padding:0 4px; color:var(--accent); }
.page h2 a { color:var(--accent); text-decoration:none; }
.page h2 a:hover { text-decoration:underline; }
nav a { display:flex; justify-content:space-between; padding:5px 8px; border-radius:6px; color:var(--text);
        text-decoration:none; font-size:14px; }
nav a:hover { background:#eef2ff; }
nav a.cur { background:var(--accent); color:#fff; }
nav a span { color:inherit; opacity:.7; }
main { padding:20px; display:flex; flex-direction:column; gap:18px; max-width:1600px; width:100%; margin:auto; }
.page { display:grid; grid-template-columns: minmax(280px, 45%) 1fr; gap:16px; background:var(--panel);
        border:1px solid var(--line); border-radius:14px; padding:17px; box-shadow:0 5px 22px rgba(36,57,108,.055); }
.page h2 { grid-column:1/-1; margin:0; font-size:16px; }
.page img { width:100%; border:1px solid var(--line); border-radius:6px; cursor:zoom-in; }
.qs { display:flex; flex-direction:column; gap:12px; }
.q { border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.q .head { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:6px; font-size:12px; }
.badge { background:var(--chip); color:var(--chiptext); border-radius:4px; padding:2px 6px; font-weight:600; }
.badge.sub { background:#f3f4f6; color:#374151; font-weight:500; }
.badge.edit { background:#fef3c7; color:#92400e; }
.badge.saved { background:#dcfce7; color:#16633a; }
.badge.draft { background:#f1f5f9; color:#475569; }
.q .text { font-size:16px; margin:2px 0 8px; line-height:1.5; }
.opt { padding:5px 8px; border-radius:6px; margin:2px 0; font-size:15px; }
.opt.ok { background:var(--okbg); color:var(--ok); font-weight:600; }
.opt b { display:inline-block; width:22px; }
.ev { font-size:13px; color:var(--muted); margin-top:6px; }
.empty { color:var(--muted); font-style:italic; }
.kind { font-size:12px; font-weight:500; background:#f3f4f6; color:#374151; border-radius:4px; padding:2px 6px; }
.kind.pending { background:#fff5dc; color:#895d11; }
.kind.failed { background:#fee8e8; color:#a12727; }
.kind.done { background:#e3f7e9; color:#16633a; }
#zoom { position:fixed; inset:0; background:rgba(0,0,0,.8); display:none; align-items:center;
        justify-content:center; z-index:10; cursor:zoom-out; }
#zoom img { max-width:96vw; max-height:96vh; background:#fff; }
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; } nav { display:none; }
  .page { grid-template-columns: 1fr; } .filters { top:0; position:static; }
}
</style>
</head>
<body>
<header><h1>__TITLE__</h1><div class="meta" id="meta"></div></header>
<div class="filters"><input class="search" id="search" type="search"
  placeholder="Search documents, questions, answers…" aria-label="Search current data">
  <div id="filters"></div></div>
<div class="layout"><nav id="nav"></nav><main id="main"></main></div>
<div id="zoom" onclick="this.style.display='none'"><img alt=""></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const AXES = D.axes;
let filter = 'all';
let search = '';
const byPage = {};
D.questions.forEach(q => (byPage[q.page_id] = byPage[q.page_id] || []).push(q));
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function axisVisible(q) { return filter === 'all' || q.primary_axis === filter; }
function questionMatches(q) {
  return !search || [q.question_bn, q.answer_bn, q.question_id, q.source_file,
    q.evidence_snippet, ...(q.source_pages || []).flatMap(p => [p.page_id, p.evidence_snippet, p.used_for]),
    ...(q.reasoning_steps || [])].some(v => String(v || '').toLocaleLowerCase().includes(search));
}
function pageMatches(p) {
  return !search || [p.page_id, p.document_id, p.content_type, p.content_note,
    D.documents[p.document_id]].some(v => String(v || '').toLocaleLowerCase().includes(search));
}
function shownQuestions(p) {
  return (byPage[p.page_id] || []).filter(q => axisVisible(q) && (pageMatches(p) || questionMatches(q)));
}
function renderFilters() {
  const counts = {}; D.questions.forEach(q => counts[q.primary_axis] = (counts[q.primary_axis] || 0) + 1);
  const chips = [['all', 'All', D.questions.length]].concat(
    Object.keys(AXES).filter(a => counts[a]).map(a => [a, a, counts[a]]));
  document.getElementById('filters').innerHTML = chips.map(([k, label, n]) =>
    `<button class="chip ${filter === k ? 'on' : ''}" title="${esc(AXES[k] || 'All questions')}"
      onclick="setFilter('${k}')">${label} (${n})</button>`).join('');
}
function setFilter(k) { filter = k; renderFilters(); renderMain(); renderNav(); }
function renderNav() {
  let html = '', lastDoc = '';
  D.pages.forEach(p => {
    if (p.document_id !== lastDoc) {
      const f = D.documents[p.document_id];
      html += `<div class="doc">${esc(p.document_id)}${f ? ` <a class="file" href="${esc(f)}" target="_blank"
        title="Open the original document">open ↗</a>` : ''}</div>`;
      lastDoc = p.document_id;
    }
    const n = shownQuestions(p).length;
    if (search && !pageMatches(p) && !n) return;
    html += `<a href="#${p.page_id}">Page ${p.page_number} <span>${n}</span></a>`;
  });
  document.getElementById('nav').innerHTML = html;
}
function renderQ(q) {
  const opts = Object.entries(q.options).map(([lb, t]) =>
    `<div class="opt ${lb === q.correct_option ? 'ok' : ''}"><b>${lb}.</b>${esc(t)}</div>`).join('');
  const subs = q.sub_axes.map(a => `<span class="badge sub" title="${esc(AXES[a])}">${a}</span>`).join('');
  const sources = (q.source_pages || []).map(p => `<div class="ev"><a href="#${esc(p.page_id)}">Page ${esc(p.page_number)}</a>` +
    `${p.used_for ? ` · ${esc(p.used_for)}` : ''}: ${esc(p.evidence_snippet)}</div>`).join('');
  const steps = (q.reasoning_steps || []).length ? `<div class="ev"><b>Reasoning:</b><ol>` +
    q.reasoning_steps.map(s => `<li>${esc(s)}</li>`).join('') + '</ol></div>' : '';
  return `<div class="q"><div class="head"><span class="badge" title="${esc(q.axis_name)}">${q.primary_axis}</span>
    ${subs}${q.reviewed ? '<span class="badge saved">Saved for export</span>' : '<span class="badge draft">Draft</span>'}
    ${q.edited ? '<span class="badge edit">edited</span>' : ''}
    <span style="color:#6b7280">${esc(q.question_id)}</span></div>
    <div class="text">${esc(q.question_bn)}</div>${opts}
    ${sources || (q.evidence_snippet ? `<div class="ev">প্রমাণ: ${esc(q.evidence_snippet)}</div>` : '')}${steps}</div>`;
}
function renderMain() {
  const html = D.pages.map(p => {
    const qs = shownQuestions(p);
    if (filter !== 'all' && !qs.length) return '';
    if (search && !pageMatches(p) && !qs.length) return '';
    const kind = (p.content_type || '').replace(/_/g, ' ');
    const why = p.status === 'pending' ? 'Not processed yet' :
      p.status === 'failed' ? `Processing failed: ${esc(p.error || 'unknown error')}` :
      `No saved questions${kind ? ' — ' + esc(kind) : ''}${p.content_note ? ': ' + esc(p.content_note) : ''}`;
    const f = D.documents[p.document_id];
    const docLink = f ? `<a href="${esc(f)}" target="_blank" title="Open the original document">${esc(p.document_id)}</a>`
                      : esc(p.document_id);
    return `<section class="page" id="${p.page_id}"><h2>${docLink} · Page ${p.page_number}
      · ${qs.length} question(s) <span class="kind ${esc(p.status || '')}">${esc(p.status || 'unknown')}</span>
      ${kind ? ` <span class="kind">${esc(kind)}</span>` : ''}</h2>
      <img loading="lazy" src="${esc(p.image_path)}" alt="${esc(p.page_id)}"
      onclick="zoom(this.src)"><div class="qs">${qs.map(renderQ).join('') ||
      `<div class="empty">${why}</div>`}</div></section>`;
  }).join('');
  document.getElementById('main').innerHTML = html || '<div class="empty">No questions for this filter.</div>';
}
function zoom(src) { const z = document.getElementById('zoom'); z.querySelector('img').src = src; z.style.display = 'flex'; }
document.getElementById('meta').textContent =
  `${new Set(D.pages.map(p => p.document_id)).size} documents · ${D.pages.length} pages · ` +
  `${D.questions.length} saved questions · __TIME_LABEL__ ${D.exported_at}`;
document.getElementById('search').addEventListener('input', e => {
  search = e.target.value.trim().toLocaleLowerCase(); renderNav(); renderMain();
});
renderFilters(); renderNav(); renderMain();
</script>
</body>
</html>
"""


def render_viewer(records: list[dict], pages: list[dict], exported_at: datetime,
                  documents: dict[str, str] | None = None,
                  title: str = "Bangla DocVQA Export", time_label: str = "exported") -> str:
    data = {"questions": records, "pages": pages, "exported_at": f"{exported_at:%Y-%m-%d %H:%M}",
            "documents": documents or {},
            "axes": {a.code: f"{a.code} — {a.name}" for a in AXES}}
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (_TEMPLATE.replace("__DATA__", payload)
            .replace("__TITLE__", html.escape(title))
            .replace("__TIME_LABEL__", html.escape(time_label)))

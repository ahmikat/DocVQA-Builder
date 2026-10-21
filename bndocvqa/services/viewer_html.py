"""A self-contained index.html for browsing an export offline (no network needed)."""
from __future__ import annotations

import json
from datetime import datetime

from ..models.taxonomy import AXES

_TEMPLATE = r"""<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bangla DocVQA Export</title>
<style>
:root { --bg:#f6f7fb; --panel:#fff; --text:#111827; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb;
        --ok:#15803d; --okbg:#dcfce7; --chip:#e0e7ff; --chiptext:#3730a3; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:"Noto Sans Bengali","Nirmala UI","Hind Siliguri","Segoe UI",system-ui,sans-serif; }
header { position:sticky; top:0; z-index:5; background:#1e3a8a; color:#fff; padding:10px 16px;
         display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; }
header h1 { font-size:17px; margin:0; font-weight:600; }
header .meta { font-size:13px; opacity:.85; }
.filters { display:flex; flex-wrap:wrap; gap:6px; padding:10px 16px; background:var(--panel);
           border-bottom:1px solid var(--line); position:sticky; top:44px; z-index:4; }
.chip { border:1px solid #c7d2fe; background:var(--chip); color:var(--chiptext); border-radius:999px;
        padding:4px 10px; font-size:13px; cursor:pointer; }
.chip.on { background:var(--accent); color:#fff; border-color:var(--accent); }
.layout { display:grid; grid-template-columns: 220px 1fr; min-height:calc(100vh - 100px); }
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
main { padding:16px; display:flex; flex-direction:column; gap:18px; }
.page { display:grid; grid-template-columns: minmax(280px, 45%) 1fr; gap:16px; background:var(--panel);
        border:1px solid var(--line); border-radius:10px; padding:14px; }
.page h2 { grid-column:1/-1; margin:0; font-size:16px; }
.page img { width:100%; border:1px solid var(--line); border-radius:6px; cursor:zoom-in; }
.qs { display:flex; flex-direction:column; gap:12px; }
.q { border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.q .head { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:6px; font-size:12px; }
.badge { background:var(--chip); color:var(--chiptext); border-radius:4px; padding:2px 6px; font-weight:600; }
.badge.sub { background:#f3f4f6; color:#374151; font-weight:500; }
.badge.edit { background:#fef3c7; color:#92400e; }
.q .text { font-size:16px; margin:2px 0 8px; line-height:1.5; }
.opt { padding:5px 8px; border-radius:6px; margin:2px 0; font-size:15px; }
.opt.ok { background:var(--okbg); color:var(--ok); font-weight:600; }
.opt b { display:inline-block; width:22px; }
.ev { font-size:13px; color:var(--muted); margin-top:6px; }
.empty { color:var(--muted); font-style:italic; }
.kind { font-size:12px; font-weight:500; background:#f3f4f6; color:#374151; border-radius:4px; padding:2px 6px; }
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
<header><h1>Bangla DocVQA Export</h1><div class="meta" id="meta"></div></header>
<div class="filters" id="filters"></div>
<div class="layout"><nav id="nav"></nav><main id="main"></main></div>
<div id="zoom" onclick="this.style.display='none'"><img alt=""></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const AXES = D.axes;
let filter = 'all';
const byPage = {};
D.questions.forEach(q => (byPage[q.page_id] = byPage[q.page_id] || []).push(q));
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function visible(q) { return filter === 'all' || q.primary_axis === filter; }
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
    const n = (byPage[p.page_id] || []).filter(visible).length;
    html += `<a href="#${p.page_id}">Page ${p.page_number} <span>${n}</span></a>`;
  });
  document.getElementById('nav').innerHTML = html;
}
function renderQ(q) {
  const opts = Object.entries(q.options).map(([lb, t]) =>
    `<div class="opt ${lb === q.correct_option ? 'ok' : ''}"><b>${lb}.</b>${esc(t)}</div>`).join('');
  const subs = q.sub_axes.map(a => `<span class="badge sub" title="${esc(AXES[a])}">${a}</span>`).join('');
  return `<div class="q"><div class="head"><span class="badge" title="${esc(q.axis_name)}">${q.primary_axis}</span>
    ${subs}${q.edited ? '<span class="badge edit">edited</span>' : ''}
    <span style="color:#6b7280">${esc(q.question_id)}</span></div>
    <div class="text">${esc(q.question_bn)}</div>${opts}
    ${q.evidence_snippet ? `<div class="ev">প্রমাণ: ${esc(q.evidence_snippet)}</div>` : ''}</div>`;
}
function renderMain() {
  const html = D.pages.map(p => {
    const qs = (byPage[p.page_id] || []).filter(visible);
    if (filter !== 'all' && !qs.length) return '';
    const kind = (p.content_type || '').replace(/_/g, ' ');
    const why = `No questions${kind ? ' — ' + esc(kind) : ''}${p.content_note ? ': ' + esc(p.content_note) : ''}`;
    const f = D.documents[p.document_id];
    const docLink = f ? `<a href="${esc(f)}" target="_blank" title="Open the original document">${esc(p.document_id)}</a>`
                      : esc(p.document_id);
    return `<section class="page" id="${p.page_id}"><h2>${docLink} · Page ${p.page_number}
      · ${qs.length} question(s)${kind ? ` <span class="kind">${esc(kind)}</span>` : ''}</h2>
      <img loading="lazy" src="${esc(p.image_path)}" alt="${esc(p.page_id)}"
      onclick="zoom(this.src)"><div class="qs">${qs.map(renderQ).join('') ||
      `<div class="empty">${why}</div>`}</div></section>`;
  }).join('');
  document.getElementById('main').innerHTML = html || '<div class="empty">No questions for this filter.</div>';
}
function zoom(src) { const z = document.getElementById('zoom'); z.querySelector('img').src = src; z.style.display = 'flex'; }
document.getElementById('meta').textContent =
  `${new Set(D.pages.map(p => p.document_id)).size} documents · ${D.pages.length} pages · ` +
  `${D.questions.length} questions · exported ${D.exported_at}`;
renderFilters(); renderNav(); renderMain();
</script>
</body>
</html>
"""


def render_viewer(records: list[dict], pages: list[dict], exported_at: datetime,
                  documents: dict[str, str] | None = None) -> str:
    data = {"questions": records, "pages": pages, "exported_at": f"{exported_at:%Y-%m-%d %H:%M}",
            "documents": documents or {},
            "axes": {a.code: f"{a.code} — {a.name}" for a in AXES}}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", payload)

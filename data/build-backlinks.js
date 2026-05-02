#!/usr/bin/env node
// Builds "упоминается в" backlinks blocks on every node page.
// Idempotent: if a backlinks section is already present, it will be replaced.
//
// Usage:  node data/build-backlinks.js
//
// Reads:  data/links.json (relative to repo root)
// Writes: in-place edits to each node.url html file

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SITE_PREFIX = '/null/';

const TYPE_RU = {
  constant:   'константа',
  type:       'тип',
  special:    'особенное',
  theorem:    'теорема',
  hypothesis: 'гипотеза',
  operator:   'оператор',
  problem:    'задача',
  curious:    'любопытное',
  essay:      'эссе',
  visual:     'визуал'
};

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'links.json'), 'utf8'));
const byId = Object.fromEntries(data.nodes.map(n => [n.id, n]));

// reverse adjacency
const incoming = {};
for (const n of data.nodes) incoming[n.id] = new Set();
for (const e of data.edges) {
  if (incoming[e.to] && byId[e.from]) incoming[e.to].add(e.from);
}

const urlToFs = (url) => {
  if (!url.startsWith(SITE_PREFIX)) throw new Error(`bad url: ${url}`);
  return path.join(ROOT, url.slice(SITE_PREFIX.length));
};

const renderBacklinks = (sourceIds) => {
  if (sourceIds.size === 0) return null;
  // sort by type order, then by title
  const typeOrder = ['constant','type','special','theorem','hypothesis','operator','problem','curious','essay','visual'];
  const list = [...sourceIds].map(id => byId[id]).filter(Boolean).sort((a, b) => {
    const ta = typeOrder.indexOf(a.type), tb = typeOrder.indexOf(b.type);
    if (ta !== tb) return ta - tb;
    return a.title.localeCompare(b.title, 'ru');
  });

  const links = list.map(n =>
    `      <div class="related-link"><span class="related-link-type">${TYPE_RU[n.type] || n.type}</span><a href="${n.url}">${n.title} →</a></div>`
  ).join('\n');

  return `<section class="backlinks">
  <hr class="section-divider-soft">
  <div class="related-label">упоминается в</div>
  <div class="related-links">
${links}
  </div>
</section>`;
};

let updated = 0, skipped = 0, missing = 0;

for (const n of data.nodes) {
  const fsPath = urlToFs(n.url);
  if (!fs.existsSync(fsPath)) {
    console.warn(`[skip] missing file: ${fsPath}`);
    missing++;
    continue;
  }
  const block = renderBacklinks(incoming[n.id]);
  if (!block) {
    skipped++;
    continue;
  }

  let html = fs.readFileSync(fsPath, 'utf8');

  // Remove any existing backlinks section first (idempotency)
  const existingRe = /\n\n<section class="backlinks">[\s\S]*?<\/section>/;
  html = html.replace(existingRe, '');

  // Find the closing </section> of the related block, then insert after it
  // Match: <section class="related"> ... </section>
  const relatedRe = /(<section class="related">[\s\S]*?<\/section>)/;
  if (!relatedRe.test(html)) {
    console.warn(`[skip] no related section in ${n.url}`);
    skipped++;
    continue;
  }
  html = html.replace(relatedRe, (m) => `${m}\n\n${block}`);

  fs.writeFileSync(fsPath, html, 'utf8');
  updated++;
}

console.log(`done: ${updated} updated, ${skipped} skipped, ${missing} missing.`);

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split generated shop markup into small files so the main page stays responsive."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
OUT = ROOT / "products"
CHUNK_SIZE = 15

html = INDEX.read_text(encoding="utf-8")
start = html.find('<div class="stores">')
if start < 0:
    raise SystemExit("Could not find generated .stores block")

# In the template, the stores block is immediately followed by the shop card and wrapper closes.
marker = '</div>\n  </div>\n\n</div>\n<script>'
marker_at = html.find(marker, start)
if marker_at < 0:
    raise SystemExit("Could not find the end of the generated stores block")
stores_end = marker_at + len('</div>')
stores_html = html[start:stores_end]

# Each store column ends with its grid, store-box, and store-col closing tags.
columns = []
pos = 0
while True:
    col_start = stores_html.find('<div class="store-col">', pos)
    if col_start < 0:
        break
    col_end = stores_html.find('</div></div></div>', col_start)
    if col_end < 0:
        raise SystemExit("Could not find end of a store column")
    col_end += len('</div></div></div>')
    columns.append(stores_html[col_start:col_end])
    pos = col_end

if len(columns) != 3:
    raise SystemExit(f"Expected 3 shop columns, found {len(columns)}")

OUT.mkdir(exist_ok=True)
# Clear old chunks so removed products do not leave stale files.
for old in OUT.glob("*.html"):
    old.unlink()

# BOOTH and FANSKY columns are separate requests, not part of initial HTML parsing.
(OUT / "booth.html").write_text(columns[0], encoding="utf-8")
(OUT / "fansky.html").write_text(columns[1], encoding="utf-8")

# The pictSPACE column has the most embedded thumbnail data. Keep its shell separate,
# then stream card batches into its grid to give the browser time to process user input.
pict = columns[2]
cards = list(re.finditer(r'<a class="shop-card".*?</a>', pict, re.S))
if cards:
    head = pict[:cards[0].start()]
    tail = pict[cards[-1].end():]
    (OUT / "pictspace-head.html").write_text(head, encoding="utf-8")
    (OUT / "pictspace-tail.html").write_text(tail, encoding="utf-8")
    for chunk_no, offset in enumerate(range(0, len(cards), CHUNK_SIZE), 1):
        chunk = ''.join(m.group(0) for m in cards[offset:offset + CHUNK_SIZE])
        (OUT / f"pictspace-{chunk_no:03d}.html").write_text(chunk, encoding="utf-8")
else:
    (OUT / "pictspace.html").write_text(pict, encoding="utf-8")

placeholder = '''<div class="stores" id="stores">
      <div class="store-col" id="store-booth"><p>BOOTH 商品載入中…</p></div>
      <div class="store-col" id="store-fansky"><p>FANSKY 商品載入中…</p></div>
      <div class="store-col" id="store-pict"><p>pictSPACE 商品載入中…</p></div>
    </div>'''
html = html[:start] + placeholder + html[stores_end:]

loader = r"""
<script>
(async function loadShopSections() {
  const base = 'products/';
  async function getText(path) {
    const response = await fetch(base + path + '?v=' + Date.now());
    if (!response.ok) throw new Error('HTTP ' + response.status + ': ' + path);
    return await response.text();
  }
  async function loadColumn(id, file) {
    const el = document.getElementById(id);
    try { el.innerHTML = await getText(file); }
    catch (err) { el.innerHTML = '<p>商品載入失敗，請重新整理頁面。</p>'; console.error(err); }
  }
  await loadColumn('store-booth', 'booth.html');
  await new Promise(resolve => requestAnimationFrame(resolve));
  await loadColumn('store-fansky', 'fansky.html');
  await new Promise(resolve => requestAnimationFrame(resolve));

  const pict = document.getElementById('store-pict');
  try {
    const head = await getText('pictspace-head.html');
    pict.innerHTML = head;
    const grid = document.getElementById('grid-pict');
    const files = await (async () => {
      const index = await getText('manifest.json');
      return JSON.parse(index);
    })();
    for (const file of files) {
      const batch = await getText(file);
      grid.insertAdjacentHTML('beforeend', batch);
      await new Promise(resolve => requestAnimationFrame(resolve));
    }
    const tail = await getText('pictspace-tail.html');
    pict.insertAdjacentHTML('beforeend', tail);
  } catch (err) {
    pict.innerHTML = '<p>pictSPACE 商品載入失敗，請重新整理頁面。</p>';
    console.error(err);
  }
})();
</script>
"""
# Manifest lists the generated pictSPACE chunks in order.
manifest = sorted(p.name for p in OUT.glob("pictspace-[0-9][0-9][0-9].html"))
(OUT / "manifest.json").write_text(__import__("json").dumps(manifest, ensure_ascii=False), encoding="utf-8")
html = html.replace("</body>", loader + "\n</body>")
INDEX.write_text(html, encoding="utf-8")
print(f"Split products into {len(manifest)} pictSPACE batches; index.html is now lightweight.")

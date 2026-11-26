"""Offline interactive HTML Gallery + Contact Sheet builder for image batches/DAGs.

Generates a single self-contained `gallery.html` with zero external CDN requests:
  * Filter by stage, status, provider, tag/matrix dimension, or free-text search
  * Backdrop toggle (Checkerboard / Light / Dark) to inspect RGBA transparency edges
  * Fullscreen lightbox showing compiled prompt, refs, model, dimensions, GIF frames
  * One-click Keep (★) / Reject (✕) curation with copyable kept-file list and
    ready-to-run `--only id1,id2 --resume` rerun command for outliers
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from . import board, probe

_IMAGE_EXTS = {".png", ".gif", ".jpg", ".jpeg", ".webp"}


def _rel_src(img_path: str | None, out_dir: Path) -> str | None:
    if not img_path:
        return None
    p = Path(img_path)
    try:
        return p.resolve().relative_to(out_dir.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def build_gallery(items: list[dict], out_dir: Path, *,
                  title: str = "generate-image Gallery",
                  filename: str = "gallery.html") -> Path:
    """Write a self-contained offline interactive HTML gallery to `out_dir / filename`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[dict] = []
    for idx, item in enumerate(items):
        p = item.get("path")
        normalized.append({
            "id": str(item.get("id") or f"img_{idx + 1}"),
            "status": str(item.get("status") or ("success" if item.get("ok") else "failed")),
            "src": _rel_src(p, out_dir),
            "path": str(p or ""),
            "provider": item.get("provider") or "",
            "model": item.get("model") or "",
            "ratio": item.get("ratio") or "",
            "width": item.get("width") or 0,
            "height": item.get("height") or 0,
            "stage": item.get("stage") or "",
            "tags": item.get("tags") or {},
            "prompt": item.get("prompt") or "",
            "refs": item.get("refs") or [],
            "error": item.get("error") or "",
            "frames": item.get("frames") or 0,
        })

    data_json = json.dumps(normalized, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html.escape(title)

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{safe_title}</title>
<style>
  :root {{ --bg:#0f1117; --card:#171a23; --border:#2a2f3d; --text:#e8ecf4; --muted:#9aa3b2; --accent:#5b8cff; --keep:#22c55e; --reject:#ef4444; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); }}
  header {{ position:sticky; top:0; z-index:20; background:rgba(15,17,23,.94); backdrop-filter:blur(8px); border-bottom:1px solid var(--border); padding:12px 20px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
  header h1 {{ font-size:15px; margin:0 12px 0 0; font-weight:600; }}
  .ctrl {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; flex:1; }}
  input, select, button {{ background:#1f2430; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px 10px; font-size:12px; }}
  button {{ cursor:pointer; }}
  button:hover {{ border-color:var(--accent); }}
  button.active {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  .stats {{ font-size:12px; color:var(--muted); margin-left:auto; }}
  main {{ padding:16px 20px 60px; display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; transition:border-color .15s; }}
  .card.keep {{ border-color:var(--keep); box-shadow:0 0 0 1px var(--keep); }}
  .card.reject {{ border-color:var(--reject); opacity:.55; }}
  .thumb-wrap {{ position:relative; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center; overflow:hidden; cursor:zoom-in; }}
  .bg-checker {{ background-image:linear-gradient(45deg,#2a2e39 25%,transparent 25%),linear-gradient(-45deg,#2a2e39 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#2a2e39 75%),linear-gradient(-45deg,transparent 75%,#2a2e39 75%); background-size:20px 20px; background-position:0 0,0 10px,10px -10px,-10px 0; background-color:#1e212a; }}
  .bg-light {{ background:#f5f6f8; }}
  .bg-dark {{ background:#090a0e; }}
  .thumb-wrap img {{ max-width:100%; max-height:100%; object-fit:contain; display:block; }}
  .meta {{ padding:10px 12px; display:flex; flex-direction:column; gap:6px; font-size:12px; }}
  .row {{ display:flex; justify-content:space-between; align-items:center; gap:6px; }}
  .id {{ font-weight:600; word-break:break-all; }}
  .badge {{ font-size:10px; padding:2px 6px; border-radius:99px; background:#252a38; color:var(--muted); }}
  .badge.ok {{ color:#86efac; background:#143322; }}
  .badge.cached {{ color:#93c5fd; background:#172554; }}
  .badge.err {{ color:#fca5a5; background:#3b1419; }}
  .tags {{ display:flex; flex-wrap:wrap; gap:4px; }}
  .tag {{ font-size:10px; padding:1px 6px; border-radius:4px; background:#232836; color:#b8c1d1; }}
  .prompt-preview {{ color:var(--muted); font-size:11px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .actions {{ display:flex; gap:6px; margin-top:4px; }}
  .actions button {{ flex:1; padding:4px 6px; font-size:11px; }}
  .actions button.k.on {{ background:var(--keep); border-color:var(--keep); color:#041a0d; font-weight:600; }}
  .actions button.r.on {{ background:var(--reject); border-color:var(--reject); color:#fff; font-weight:600; }}
  #lightbox {{ position:fixed; inset:0; background:rgba(5,7,11,.9); z-index:50; display:none; align-items:center; justify-content:center; padding:24px; }}
  #lightbox.open {{ display:flex; }}
  .lb-box {{ max-width:1100px; width:100%; max-height:92vh; background:var(--card); border:1px solid var(--border); border-radius:12px; display:grid; grid-template-columns:1.4fr 1fr; overflow:hidden; }}
  @media (max-width:860px) {{ .lb-box {{ grid-template-columns:1fr; overflow-y:auto; }} }}
  .lb-img {{ display:flex; align-items:center; justify-content:center; padding:16px; min-height:320px; }}
  .lb-img img {{ max-width:100%; max-height:80vh; object-fit:contain; }}
  .lb-info {{ padding:16px; border-left:1px solid var(--border); overflow-y:auto; font-size:12px; display:flex; flex-direction:column; gap:10px; }}
  .lb-info pre {{ white-space:pre-wrap; word-break:break-word; background:#10131a; padding:10px; border-radius:6px; border:1px solid var(--border); margin:0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; }}
  .toast {{ position:fixed; bottom:20px; right:20px; background:#22c55e; color:#041a0d; padding:8px 14px; border-radius:8px; font-size:12px; font-weight:600; display:none; z-index:60; }}
</style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <div class="ctrl">
    <input id="q" placeholder="搜索 id / prompt / tag..." />
    <select id="fStage"><option value="">全部 Stage</option></select>
    <select id="fTag"><option value="">全部维度标签</option></select>
    <select id="fCurate">
      <option value="">全部筛选状态</option>
      <option value="keep">★ 已选中 (Keep)</option>
      <option value="reject">✕ 已淘汰 (Reject)</option>
      <option value="unmarked">未标记</option>
    </select>
    <button id="bgBtn" title="切换底色以便检查透明通道边缘">底色: 棋盘格</button>
    <button id="copyKept">复制选中路径</button>
    <button id="copyRerun">复制淘汰重跑命令</button>
  </div>
  <div class="stats" id="stats"></div>
</header>
<main id="grid"></main>

<div id="lightbox">
  <div class="lb-box">
    <div class="lb-img bg-checker" id="lbImgWrap"><img id="lbImg" alt="" /></div>
    <div class="lb-info">
      <div class="row"><strong id="lbTitle"></strong><button id="lbClose">关闭 (Esc)</button></div>
      <div id="lbMeta" style="color:var(--muted)"></div>
      <div><strong>Compiled Prompt</strong><pre id="lbPrompt"></pre></div>
      <div id="lbRefsWrap" style="display:none"><strong>Refs</strong><pre id="lbRefs"></pre></div>
      <div id="lbErrWrap" style="display:none"><strong>Error</strong><pre id="lbErr"></pre></div>
      <div class="actions">
        <button id="lbKeep" class="k">★ Keep</button>
        <button id="lbReject" class="r">✕ Reject</button>
        <button id="lbCopyPrompt">复制 Prompt</button>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const ITEMS = {data_json};
const state = {{}}; // id -> 'keep' | 'reject'
const BGS = [['bg-checker','棋盘格'],['bg-light','浅色底'],['bg-dark','深色底']];
let bgIdx = 0;
let activeId = null;

function toast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  clearTimeout(toast._t); toast._t = setTimeout(() => el.style.display = 'none', 1800);
}}

// Populate filter dropdowns
const stages = [...new Set(ITEMS.map(i => i.stage).filter(Boolean))];
stages.forEach(s => {{
  const o = document.createElement('option'); o.value = s; o.textContent = 'Stage: ' + s;
  document.getElementById('fStage').appendChild(o);
}});
const tagPairs = [...new Set(ITEMS.flatMap(i => Object.entries(i.tags || {{}}).map(([k,v]) => `${{k}}=${{v}}`)))];
tagPairs.forEach(t => {{
  const o = document.createElement('option'); o.value = t; o.textContent = t;
  document.getElementById('fTag').appendChild(o);
}});

function matches(item) {{
  const q = document.getElementById('q').value.trim().toLowerCase();
  const st = document.getElementById('fStage').value;
  const tg = document.getElementById('fTag').value;
  const cu = document.getElementById('fCurate').value;
  if (st && item.stage !== st) return false;
  if (tg) {{
    const pairs = Object.entries(item.tags || {{}}).map(([k,v]) => `${{k}}=${{v}}`);
    if (!pairs.includes(tg)) return false;
  }}
  if (cu === 'keep' && state[item.id] !== 'keep') return false;
  if (cu === 'reject' && state[item.id] !== 'reject') return false;
  if (cu === 'unmarked' && state[item.id]) return false;
  if (q) {{
    const hay = [item.id, item.prompt, item.model, item.provider, item.stage, JSON.stringify(item.tags)].join(' ').toLowerCase();
    if (!hay.includes(q)) return false;
  }}
  return true;
}}

function render() {{
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  const visible = ITEMS.filter(matches);
  const kept = ITEMS.filter(i => state[i.id] === 'keep').length;
  const rej = ITEMS.filter(i => state[i.id] === 'reject').length;
  document.getElementById('stats').textContent = `显示 ${{visible.length}}/${{ITEMS.length}} · ★ ${{kept}} · ✕ ${{rej}}`;

  for (const item of visible) {{
    const card = document.createElement('div');
    card.className = 'card ' + (state[item.id] || '');
    const wrap = document.createElement('div');
    wrap.className = 'thumb-wrap ' + BGS[bgIdx][0];
    if (item.src) {{
      const img = document.createElement('img');
      img.src = item.src; img.loading = 'lazy'; img.alt = item.id;
      wrap.appendChild(img);
    }} else {{
      wrap.textContent = item.status || 'failed';
    }}
    wrap.onclick = () => openLB(item);
    card.appendChild(wrap);

    const meta = document.createElement('div');
    meta.className = 'meta';
    const stCls = item.status === 'success' ? 'ok' : (item.status === 'cached' ? 'cached' : 'err');
    const dims = item.width && item.height ? `${{item.width}}×${{item.height}}` : '';
    const extra = item.frames > 1 ? ` · ${{item.frames}}f GIF` : '';
    meta.innerHTML = `
      <div class="row"><span class="id"></span><span class="badge ${{stCls}}">${{item.status}}</span></div>
      <div class="row" style="color:var(--muted)"><span>${{item.provider}} ${{item.model}}</span><span>${{dims}}${{extra}}</span></div>
      <div class="tags"></div>
      <div class="prompt-preview"></div>
      <div class="actions">
        <button class="k ${{state[item.id]==='keep'?'on':''}}">★ Keep</button>
        <button class="r ${{state[item.id]==='reject'?'on':''}}">✕ Reject</button>
      </div>`;
    meta.querySelector('.id').textContent = item.id;
    meta.querySelector('.prompt-preview').textContent = item.prompt || item.error || '';
    const tagsEl = meta.querySelector('.tags');
    if (item.stage) {{
      const sp = document.createElement('span'); sp.className = 'tag'; sp.textContent = '#' + item.stage; tagsEl.appendChild(sp);
    }}
    for (const [k,v] of Object.entries(item.tags || {{}})) {{
      const sp = document.createElement('span'); sp.className = 'tag'; sp.textContent = `${{k}}:${{v}}`; tagsEl.appendChild(sp);
    }}
    meta.querySelector('.k').onclick = () => {{ state[item.id] = state[item.id] === 'keep' ? '' : 'keep'; render(); }};
    meta.querySelector('.r').onclick = () => {{ state[item.id] = state[item.id] === 'reject' ? '' : 'reject'; render(); }};
    card.appendChild(meta);
    grid.appendChild(card);
  }}
}}

function openLB(item) {{
  activeId = item.id;
  document.getElementById('lbTitle').textContent = item.id;
  document.getElementById('lbImg').src = item.src || '';
  document.getElementById('lbImgWrap').className = 'lb-img ' + BGS[bgIdx][0];
  document.getElementById('lbMeta').textContent = `${{item.provider}} / ${{item.model}} · ratio=${{item.ratio}} · ${{item.width}}×${{item.height}} · ${{item.path}}`;
  document.getElementById('lbPrompt').textContent = item.prompt || '(empty)';
  const rw = document.getElementById('lbRefsWrap');
  if (item.refs && item.refs.length) {{ rw.style.display = 'block'; document.getElementById('lbRefs').textContent = item.refs.join('\\n'); }} else {{ rw.style.display = 'none'; }}
  const ew = document.getElementById('lbErrWrap');
  if (item.error) {{ ew.style.display = 'block'; document.getElementById('lbErr').textContent = item.error; }} else {{ ew.style.display = 'none'; }}
  document.getElementById('lightbox').classList.add('open');
}}

document.getElementById('lbClose').onclick = () => document.getElementById('lightbox').classList.remove('open');
document.getElementById('lightbox').onclick = e => {{ if (e.target.id === 'lightbox') e.target.classList.remove('open'); }};
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') document.getElementById('lightbox').classList.remove('open'); }});
document.getElementById('lbKeep').onclick = () => {{ if (activeId) {{ state[activeId] = 'keep'; render(); toast('已标记 Keep'); }} }};
document.getElementById('lbReject').onclick = () => {{ if (activeId) {{ state[activeId] = 'reject'; render(); toast('已标记 Reject'); }} }};
document.getElementById('lbCopyPrompt').onclick = () => {{
  const item = ITEMS.find(i => i.id === activeId);
  if (item) navigator.clipboard.writeText(item.prompt).then(() => toast('已复制 Prompt'));
}};
document.getElementById('bgBtn').onclick = () => {{
  bgIdx = (bgIdx + 1) % BGS.length;
  document.getElementById('bgBtn').textContent = '底色: ' + BGS[bgIdx][1];
  render();
}};
document.getElementById('copyKept').onclick = () => {{
  const kept = ITEMS.filter(i => state[i.id] === 'keep' && i.path).map(i => i.path);
  if (!kept.length) {{ toast('请先点击 ★ Keep 选图'); return; }}
  navigator.clipboard.writeText(kept.join('\\n')).then(() => toast(`已复制 ${{kept.length}} 个选中文件路径`));
}};
document.getElementById('copyRerun').onclick = () => {{
  const rej = ITEMS.filter(i => state[i.id] === 'reject').map(i => i.id);
  if (!rej.length) {{ toast('请先点击 ✕ Reject 标记需重跑项'); return; }}
  navigator.clipboard.writeText(`--only ${{rej.join(',')}}`).then(() => toast(`已复制 ${{rej.length}} 个重跑参数`));
}};
['q','fStage','fTag','fCurate'].forEach(id => document.getElementById(id).addEventListener('input', render));
render();
</script>
</body>
</html>
"""
    target = out_dir / filename
    target.write_text(page, encoding="utf-8")
    return target


def scan_output_dir(directory: Path) -> list[dict]:
    """Collect image files + sibling `.json` sidecars from `directory`."""
    items: list[dict] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS:
            continue
        if p.stem.startswith("contact_sheet"):
            continue
        meta: dict = {}
        sidecar = p.with_suffix(".json")
        if sidecar.is_file():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        w, h = meta.get("width") or 0, meta.get("height") or 0
        if not (w and h):
            try:
                w, h, _ = probe.image_dims(p.read_bytes())
            except OSError:
                w, h = 0, 0
        items.append({
            "id": p.stem,
            "status": "success",
            "ok": True,
            "path": str(p),
            "provider": meta.get("provider", ""),
            "model": meta.get("model", ""),
            "ratio": meta.get("ratio", ""),
            "width": w,
            "height": h,
            "prompt": meta.get("prompt", ""),
            "refs": meta.get("refs", []),
            "frames": meta.get("frames", 0),
            "tags": meta.get("tags", {}),
            "stage": meta.get("stage", ""),
        })
    return items


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="generate-image-gallery",
        description="Build contact_sheet.png and interactive gallery.html from an image directory.",
    )
    ap.add_argument("directory", help="directory containing generated images and optional .json sidecars")
    ap.add_argument("--title", default=None, help="gallery title (default: directory name)")
    ap.add_argument("--cols", type=int, default=4, help="contact sheet columns (default: 4)")
    ap.add_argument("--no-sheet", action="store_true", help="skip contact_sheet.png generation")
    args = ap.parse_args(argv)

    d = Path(args.directory).expanduser()
    if not d.is_dir():
        sys.exit(f"error: directory not found: {args.directory}")
    items = scan_output_dir(d)
    if not items:
        sys.exit(f"error: no images found in {d}")

    title = args.title or d.name
    gal = build_gallery(items, d, title=title)
    print(f"gallery: {gal}")
    if not args.no_sheet:
        sheets = board.build_contact_sheet(items, d / "contact_sheet.png",
                                           cols=args.cols, title=title)
        for s in sheets:
            print(f"sheet:   {s}")


if __name__ == "__main__":
    main()

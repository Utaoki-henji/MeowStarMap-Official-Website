#!/usr/bin/env python3
"""生成「多文件版」站点到 site/（本分支无视单文件自包含约束）。

产物结构：
  site/index.html            仅 shell（HTML/CSS/JS/图标），约 0.45 MB
  site/data/tutorial.js      window.__TUT__ = {...}（图片改为相对路径，约 30 KB）
  site/data/dev-docs.js      window.__DEV__ = {...}（约 1.5 MB，进入 #/dev 才加载）
  site/assets/shots/*.webp   48 张截图
  site/assets/fonts/*.woff2  Inter（已子集化）+ Noto Sans SC

加载策略：均为 classic script（非 module）+ <img>，故 file:// 直开与 HTTP 均可。
用法：python perf/tools/split_site.py
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "Meow Star Map 官网.html"
SITE = REPO / "site"
SHOTS = SITE / "assets" / "shots"
FONTS = SITE / "assets" / "fonts"
DATA = SITE / "data"

WEBP_RE = re.compile(r"data:image/webp;base64,([A-Za-z0-9+/=]+)")


def crlf(s: str) -> str:
    return s.replace("\n", "\r\n")


def main() -> int:
    for d in (SHOTS, FONTS, DATA):
        d.mkdir(parents=True, exist_ok=True)

    raw = SRC.read_bytes()
    text = raw.decode("utf-8")
    print(f"源文件 {len(raw):,} B")

    # ── 1. 取出两个数据块 ──
    m_tut = re.search(r'<script id="tut-data" type="application/json">(.*?)</script>', text, re.S)
    m_dev = re.search(r'<script id="dev-data" type="application/json">(.*?)</script>', text, re.S)
    if not m_tut or not m_dev:
        print("FAIL: 未找到数据块")
        return 1
    tut = json.loads(m_tut.group(1))
    dev_text = m_dev.group(1)

    # ── 2. 截图落地 + 路径替换 ──
    by_sha: dict[str, str] = {}
    written = 0

    def harvest(html: str, owner: str) -> str:
        nonlocal written
        seq = [0]

        def repl(m):
            nonlocal written
            data = base64.b64decode(m.group(1))
            import hashlib
            sha = hashlib.sha256(data).hexdigest()
            if sha in by_sha:
                return by_sha[sha]
            seq[0] += 1
            name = f"{owner}-{seq[0]:02d}.webp"
            (SHOTS / name).write_bytes(data)
            by_sha[sha] = f"assets/shots/{name}"
            written += 1
            return by_sha[sha]

        return WEBP_RE.sub(repl, html)

    for mod in tut["modules"]:
        if isinstance(mod.get("overview"), str):
            mod["overview"] = harvest(mod["overview"], mod["id"])
    for page in tut["pages"]:
        if isinstance(page.get("html"), str):
            page["html"] = harvest(page["html"], page["id"])

    tut_js = json.dumps(tut, ensure_ascii=False, separators=(",", ":")).replace("</script", "<\\/script")
    (DATA / "tutorial.js").write_text("window.__TUT__=" + tut_js + ";\n", encoding="utf-8", newline="")

    dev_js = dev_text.replace("</script", "<\\/script")
    (DATA / "dev-docs.js").write_text("window.__DEV__=" + dev_js + ";\n", encoding="utf-8", newline="")

    # ── 3. 字体外置 ──
    shell = text
    font_names = ["inter", "noto-sans-sc"]
    hits = list(re.finditer(r'url\("data:font/woff2;base64,([A-Za-z0-9+/=]+)"\)', shell))
    if len(hits) != 2:
        print(f"FAIL: 期望 2 条字体载荷，实际 {len(hits)}")
        return 1
    for hit, name in zip(hits, font_names):
        (FONTS / f"{name}.woff2").write_bytes(base64.b64decode(hit.group(1)))

    def font_repl(m):
        return 'url("assets/fonts/inter.woff2")'

    shell = re.sub(r'url\("data:font/woff2;base64,[A-Za-z0-9+/=]+"\)',
                   lambda m, c=[0]: (c.__setitem__(0, c[0] + 1),
                                     f'url("assets/fonts/{font_names[c[0] - 1]}.woff2")')[1],
                   shell)

    # ── 3b. 图标外置（favicon 64 / apple-touch 180 / app-icon 256）──
    ASSETS = SITE / "assets"
    ASSETS.mkdir(parents=True, exist_ok=True)
    m_ico = re.search(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"', shell)
    if m_ico:
        (ASSETS / "favicon-64.png").write_bytes(base64.b64decode(m_ico.group(1)))
        shell = shell.replace(m_ico.group(0), 'href="assets/favicon-64.png"', 1)
    m_touch = re.search(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"', shell)
    if m_touch:
        (ASSETS / "apple-touch-icon-180.png").write_bytes(base64.b64decode(m_touch.group(1)))
        shell = shell.replace(m_touch.group(0), 'href="assets/apple-touch-icon-180.png"', 1)
    m_app = re.search(r'url\("data:image/webp;base64,([A-Za-z0-9+/=]+)"\)', shell)
    if m_app:
        (ASSETS / "app-icon.webp").write_bytes(base64.b64decode(m_app.group(1)))
        shell = shell.replace(m_app.group(0), 'url("assets/app-icon.webp")', 1)

    # ── 4. 去掉两个内联数据块 ──
    shell = shell.replace(m_tut.group(0), "")
    shell = shell.replace(m_dev.group(0), "")

    # ── 5. JS 数据层改外置加载 ──
    start = shell.index("var DATA=null, MODS=null")
    end = shell.index("var lowCache={};")
    new_layer = r"""/* ═══ 多文件版数据层（本分支无视单文件约束）
   教程数据 data/tutorial.js 与开发文档 data/dev-docs.js 全部外置，落地页只加载 shell。
   两者都是 classic script（非 module）+ 普通 <img src>，因此 file:// 直开与 HTTP 均可用。 */
var DATA=null, MODS=null, ORDER=[], byId={}, modById={}, DEV=null;
var _tutState=0, _devState=0;
function needsTut(){var h=(location.hash||'#/').slice(1).split('@')[0];return h==='/all'||h==='/tutorial'||/^\/m\d+(\/|$)/.test(h);}
function needsDev(){var h=(location.hash||'#/').slice(1).split('@')[0];return h==='/dev'||h.indexOf('/dev/')===0;}
function loadScriptOnce(src,onOk,onErr){
  var s=document.createElement('script');
  s.src=src; s.async=true;
  s.onload=onOk;
  s.onerror=onErr;
  document.head.appendChild(s);
}
function ensureTut(){
  if(DATA) return true;
  if(_tutState===1) return false;
  _tutState=1;
  loadScriptOnce('data/tutorial.js',function(){
    DATA=window.__TUT__||null;
    if(!DATA){ _tutState=0; return; }
    MODS=DATA.modules;
    MODS.forEach(function(m){modById[m.id]=m;});
    MODS.forEach(function(m){m.pages.forEach(function(pid){ORDER.push({m:m,pid:pid,p:DATA.pages.find(function(x){return x.id===pid;})});});});
    ORDER.forEach(function(o){byId[o.pid]=o;});
    USER_SB=null; sbFamily=''; _tutState=2;
    if(needsTut()) render();
  },function(){ _tutState=0; });
  return false;
}
function ensureDev(){
  if(DEV) return true;
  if(_devState===1) return false;
  _devState=1;
  loadScriptOnce('data/dev-docs.js',function(){
    DEV=window.__DEV__||null;
    if(!DEV){ _devState=0; return; }
    buildDevIndexes();
    DEV_SB=buildDevSb(); _devState=2;
    if(needsDev()) render();
  },function(){ _devState=0; });
  return false;
}
"""
    shell = shell[:start] + crlf(new_layer) + shell[end:]

    # buildUserSb：数据未就绪时返回空串（由 render 的占位兜底）
    shell = shell.replace(
        crlf("  if(USER_SB!==null) return USER_SB;\n  ensureTut();"),
        crlf("  if(USER_SB!==null) return USER_SB;\n  if(!DATA) return '';"),
    )

    # DEV_SB：IIFE -> 惰性函数
    s = shell.index("var DEV_SB=(function(){")
    e = shell.index("var sbFamily='';")
    body = shell[s:e]
    inner = body[len("var DEV_SB=(function(){\n"): body.rindex("})();")]
    new_dev_sb = (
        "/* 多文件版：开发者侧栏同样惰性构建（DEV 数据按需加载） */\n"
        "var DEV_SB=null;\n"
        "function buildDevSb(){\n"
        "  if(DEV_SB!==null) return DEV_SB;\n"
        "  if(!DEV) return '';\n"
        + inner.replace("if(!DEV)return '';", "", 1).rstrip()
        + "\n  DEV_SB=h;\n  return h;\n}\n\n"
    )
    shell = shell[:s] + crlf(new_dev_sb) + shell[e:]

    # 开发者索引：加载期 if(DEV) -> buildDevIndexes()
    s = shell.index("var devCatById={}, devGrpById={}, devDocById={};")
    e = shell.index("function devFlatDocs(")
    new_idx = r"""var devCatById={}, devGrpById={}, devDocById={};
function buildDevIndexes(){
  if(!DEV) return;
  DEV.cats.forEach(function(c){
    devCatById[c.id]=c;
    (c.pages||[]).forEach(function(pid){ devDocById[pid]={d:DEV.docs[pid],cat:c,grp:null}; });
    (c.groups||[]).forEach(function(g){
      devGrpById[g.id]=g;
      (g.pages||[]).forEach(function(pid){ devDocById[pid]={d:DEV.docs[pid],cat:c,grp:g}; });
    });
  });
}
"""
    shell = shell[:s] + crlf(new_idx) + shell[e:]

    # render：数据未就绪时占位 + 提前返回
    old_guard = crlf("  /* R46：仅教程路由需要 #tut-data（连路由校验本身都依赖 byId/modById） */\n"
                     "  if(h==='/all'||h==='/tutorial'||/^\\/m\\d+(\\/|$)/.test(h)) ensureTut();")
    new_guard = crlf("  /* 多文件版：教程数据 / 开发文档按需加载；未就绪先渲染占位，数据到达后自动重渲 */\n"
                     "  if((h==='/all'||h==='/tutorial'||/^\\/m\\d+(\\/|$)/.test(h)) && !ensureTut()){ renderPending('教程数据加载中…'); return; }\n"
                     "  if((h==='/dev'||h.indexOf('/dev/')===0) && !ensureDev()){ renderPending('开发者文档加载中…'); return; }")
    if old_guard not in shell:
        print("FAIL: render 守卫未匹配")
        return 1
    shell = shell.replace(old_guard, new_guard)

    # 搜索：依赖已加载数据
    old_search = crlf("  ensureTut();  /* R46：搜索读 MODS/ORDER，首次输入时才解析数据 */")
    if old_search not in shell:
        print("FAIL: 搜索守卫未匹配")
        return 1
    shell = shell.replace(old_search, crlf("  if(!DATA) return;  /* 多文件版：搜索依赖已加载的教程数据 */"))

    # 占位渲染 + 入口预取，插在末尾 render() 之前
    idx = shell.rindex("render();")
    extra = crlf(r"""/* ── 多文件版：加载占位 + 入口预取 ── */
function renderPending(msg){
  document.body.dataset.view='loading';
  app.innerHTML='<div class="wrap"><div class="empty-ill"><b>'+esc(msg)+'</b>'
    +'<span>数据在首次进入对应模块时按需加载，之后由浏览器缓存。</span></div></div>';
}
document.addEventListener('mouseover',function(e){
  var t=e.target;
  var a=t&&t.closest?t.closest('a[href="#/identity"],a[href="#/tutorial"],a[href="#/all"],a[href="#/dev"]'):null;
  if(!a)return;
  if(a.getAttribute('href')==='#/dev') ensureDev(); else ensureTut();
},true);

""")
    shell = shell[:idx] + extra + shell[idx:]

    # ── 6. 写出 ──
    (SITE / "index.html").write_bytes(shell.encode("utf-8"))

    shell_bytes = (SITE / "index.html").stat().st_size
    tut_bytes = (DATA / "tutorial.js").stat().st_size
    dev_bytes = (DATA / "dev-docs.js").stat().st_size
    shots_bytes = sum(f.stat().st_size for f in SHOTS.glob("*.webp"))
    fonts_bytes = sum(f.stat().st_size for f in FONTS.glob("*.woff2"))

    print(f"\nindex.html      {shell_bytes:,} B ({shell_bytes / 1048576:.2f} MiB)")
    print(f"data/tutorial.js {tut_bytes:,} B")
    print(f"data/dev-docs.js {dev_bytes:,} B（首访 #/dev 才加载）")
    print(f"assets/shots     {len(list(SHOTS.glob('*.webp')))} 张，{shots_bytes:,} B（按需、可缓存）")
    print(f"assets/fonts     {fonts_bytes:,} B（font-display:swap）")
    print(f"\n落地页首屏 = index.html + 两张字体 = {shell_bytes + fonts_bytes:,} B "
          f"({(shell_bytes + fonts_bytes) / 1048576:.2f} MiB)")
    print(f"教程页额外 = data/tutorial.js {tut_bytes:,} B + 该页 1~3 张截图")
    print(f"\n产物: {SITE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""perf 工具链公共模块：源文件定位、`#tut-data` 切分、内嵌截图枚举与体积换算。

硬约束（所有脚本共同遵守）：
  源文件 `Meow Star Map 官网.html` 只读；一切产物写入 perf/assets 与 perf/dist。
  这条约束由 build_optimized.py 在运行前后各校验一次 sha256 来兜底。

口径说明：
  - `#tut-data` 是单行巨型 JSON（约 30.9M 字符），其中教程截图以
    `data:image/png;base64,...` 内联。本工具链只处理这一种 URI。
  - 源文件的 JSON 不含 `\\/` 与 `\\u003c` 转义（已实测），因此可以直接在
    原始文本层面用正则替换，无需重新序列化整个 JSON。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Iterator

PERF_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PERF_DIR.parent
HTML_PATH = REPO_DIR / "Meow Star Map 官网.html"
ASSETS_DIR = PERF_DIR / "assets"
SHOTS_DIR = ASSETS_DIR / "shots"
WEBP_DIR = ASSETS_DIR / "webp"
DIST_DIR = PERF_DIR / "dist"
REPORTS_DIR = PERF_DIR / "reports"
MANIFEST_PATH = ASSETS_DIR / "manifest.json"

TUT_OPEN = '<script id="tut-data" type="application/json">'
TUT_CLOSE = "</script>"
PNG_URI_RE = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=]+)")

# 零外链不变量：优化版必须与原件逐项相等（R31/R37/R43 口径）
INVARIANT_PATTERNS = {
    "link(全部)": r"<link\b",
    "script src": r"<script[^>]*\bsrc=",
    "iframe": r"<iframe\b",
    "img src=http": r'<img[^>]*\bsrc="https?:',
    "css url(http)": r"url\(\s*['\"]?https?:",
    "@font-face{": r"@font-face\s*\{",
    "<img": r"<img\b",
    "<style": r"<style\b",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def source_sha256() -> str:
    return sha256_bytes(HTML_PATH.read_bytes())


def read_source() -> str:
    """按字节读入再解码：不做换行归一化，保证源文件的 CRLF 原样保留。

    用 `Path.read_text()` 会把 CRLF 归一化成 LF（本文件 5026 行 → 少 5026 字节），
    那样重建出来的产物就不是「除图片载荷外逐字节不变」了。
    """
    return HTML_PATH.read_bytes().decode("utf-8")


def split_tut(text: str) -> tuple[str, str, str]:
    """切成 (head, json_body, tail)；head 不含起始标记，tail 以 `</script>` 开头。"""
    start = text.index(TUT_OPEN) + len(TUT_OPEN)
    pos = start
    while True:
        end = text.index(TUT_CLOSE, pos)
        body = text[start:end]
        try:
            json.loads(body)
        except json.JSONDecodeError:
            # 说明该 </script> 落在字符串内容里（当前源文件不会发生），继续往后找
            pos = end + len(TUT_CLOSE)
            continue
        return text[:start], body, text[end:]


def iter_doc_images(doc: dict) -> Iterator[tuple[str, str, str]]:
    """按文档顺序产出 (owner, field, base64)，与源文本里 PNG_URI_RE 的匹配顺序一致。

    owner 取最近的 `"id"`（`m1` / `m2p4` 之类），用于给原图起可读文件名。
    """

    def walk(node, owner: str, field: str):
        if isinstance(node, dict):
            if isinstance(node.get("id"), str):
                owner = node["id"]
            for key, value in node.items():
                yield from walk(value, owner, key)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item, owner, field)
        elif isinstance(node, str):
            for match in PNG_URI_RE.finditer(node):
                yield owner, field, match.group(1)

    yield from walk(doc, "root", "")


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def decode_b64(b64: str) -> bytes:
    return base64.b64decode(b64)


def b64_of(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def human_bytes(n: int) -> str:
    return f"{n:,} B ({n / 1048576:.2f} MiB)"


def pct(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}%"


def ensure_dirs() -> None:
    for d in (ASSETS_DIR, SHOTS_DIR, WEBP_DIR, DIST_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"缺少 {MANIFEST_PATH}，请先运行 tools/extract_shots.py")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

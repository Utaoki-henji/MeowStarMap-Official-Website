#!/usr/bin/env python3
"""校验「优化版」与源文件除图片载荷外完全等价，并复核零外链不变量。

设计原则：不依赖浏览器（本工作树未装 playwright），全部为源码级断言。
任何一项失败即非零退出，可作 CI 门禁。

用法：python perf/tools/verify.py [--level q90]
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from common import (
    DIST_DIR,
    HTML_PATH,
    INVARIANT_PATTERNS,
    PNG_URI_RE,
    read_source,
    split_tut,
)

IMG_ANY_RE = re.compile(r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
WEBP_URI_RE = re.compile(r"data:image/webp;base64,([A-Za-z0-9+/=]+)")


class Checker:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self.rows.append((ok, name, detail))
        return ok

    def report(self) -> int:
        failed = sum(1 for ok, _, _ in self.rows if not ok)
        for ok, name, detail in self.rows:
            print(f"{'PASS' if ok else 'FAIL'}  {name:<34}{detail}")
        print("-" * 72)
        print(f"合计 {len(self.rows)} 项：{len(self.rows) - failed} PASS / {failed} FAIL")
        return 0 if failed == 0 else 1


def normalize(text: str) -> str:
    return IMG_ANY_RE.sub("<IMG>", text)


def diff_docs(a, b, path: str, diffs: list[str]) -> None:
    if len(diffs) >= 20:
        return
    if type(a) is not type(b):
        diffs.append(f"{path}: 类型不同 {type(a).__name__} vs {type(b).__name__}")
        return
    if isinstance(a, dict):
        if set(a) != set(b):
            diffs.append(f"{path}: 键集合不同 ({set(a) ^ set(b)})")
            return
        for key in a:
            diff_docs(a[key], b[key], f"{path}.{key}", diffs)
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append(f"{path}: 长度不同 {len(a)} vs {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            diff_docs(x, y, f"{path}[{i}]", diffs)
    elif isinstance(a, str):
        if normalize(a) != normalize(b):
            diffs.append(f"{path}: 去掉图片载荷后仍不同")
    elif a != b:
        diffs.append(f"{path}: 值不同 {a!r} vs {b!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", default="q90")
    args = parser.parse_args()

    out_path = DIST_DIR / f"{HTML_PATH.stem}.webp-{args.level}.html"
    c = Checker()
    if not c.check(out_path.exists(), "优化版文件存在", str(out_path)):
        return c.report()

    src_text = read_source()
    opt_text = out_path.read_bytes().decode("utf-8")

    # —— 编码与整体结构 ——
    c.check("\ufffd" not in opt_text, "无 U+FFFD 替换字符")
    src_lines, opt_lines = src_text.count("\n"), opt_text.count("\n")
    c.check(src_lines == opt_lines, "换行符计数不变", f"{src_lines} → {opt_lines}")
    c.check(
        src_text.count("</script>") == opt_text.count("</script>"),
        "</script> 计数不变",
        f"{src_text.count('</script>')} → {opt_text.count('</script>')}",
    )

    # —— 图片载荷 ——
    src_head, src_body, src_tail = split_tut(src_text)
    opt_head, opt_body, opt_tail = split_tut(opt_text)
    c.check(src_head == opt_head, "tut-data 之前的内容逐字节相同")
    c.check(src_tail == opt_tail, "tut-data 之后的内容逐字节相同")
    png_in_src = len(PNG_URI_RE.findall(src_body))
    png_left = len(PNG_URI_RE.findall(opt_body))
    c.check(png_left == 0, "tut-data 内 PNG 已全部替换", f"残留 {png_left} 处（原 {png_in_src}）")
    c.check(png_in_src == len(WEBP_URI_RE.findall(opt_body)),
            "WebP 数量与原 PNG 数量一致", f"{len(WEBP_URI_RE.findall(opt_body))} / {png_in_src}")

    # —— JSON 结构等价 ——
    src_doc, opt_doc = json.loads(src_body), json.loads(opt_body)
    diffs: list[str] = []
    diff_docs(src_doc, opt_doc, "tut", diffs)
    c.check(not diffs, "tut-data 结构等价（仅图片载荷）", diffs[0] if diffs else "")
    c.check(len(src_doc["pages"]) == len(opt_doc["pages"]) == 36,
            "教程页数量", f"{len(opt_doc['pages'])} 页")
    c.check(len(src_doc["modules"]) == len(opt_doc["modules"]) == 9,
            "模块数量", f"{len(opt_doc['modules'])} 个")
    c.check([p["id"] for p in src_doc["pages"]] == [p["id"] for p in opt_doc["pages"]],
            "教程页 id 与顺序一致")

    # —— 零外链不变量 ——
    for name, pattern in INVARIANT_PATTERNS.items():
        src_n = len(re.findall(pattern, src_text))
        opt_n = len(re.findall(pattern, opt_text))
        c.check(src_n == opt_n, f"不变量：{name}", f"{src_n} → {opt_n}")
    c.check(not re.findall(r'<script[^>]*\bsrc=', opt_text), "优化版无 script src")
    c.check(not re.findall(r'<link\b[^>]*href="https?:', opt_text), "优化版无外链 link")
    c.check(not re.findall(r'url\(\s*[\'"]?https?:', opt_text), "优化版无 css url(http)")
    c.check(len(re.findall(r'<link\b(?![^>]*href=["\']data:)', opt_text)) == 0,
            "优化版外链 link 计数为 0")
    c.check(len(re.findall(r"@font-face\s*\{", opt_text)) == 2, "@font-face 恒为 2")

    # —— 体积 ——
    src_bytes = len(src_text.encode("utf-8"))
    opt_bytes = out_path.stat().st_size
    c.check(opt_bytes < src_bytes, "体积下降",
            f"{src_bytes / 1048576:.2f} → {opt_bytes / 1048576:.2f} MiB "
            f"({100 * (1 - opt_bytes / src_bytes):.1f}%)")

    return c.report()


if __name__ == "__main__":
    sys.exit(main())

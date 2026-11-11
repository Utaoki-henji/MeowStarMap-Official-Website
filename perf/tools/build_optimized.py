#!/usr/bin/env python3
"""用已转换好的 WebP 重建一份「优化版」HTML，写到 perf/dist/。

源文件不被修改：运行前后各校验一次 sha256，只要不一致立即报错退出。
重建方式为等位置换（只替换 `data:image/png;base64,...` 这一段载荷），
因此除图片载荷外，HTML/CSS/JS/JSON 结构逐字节不变。

用法：python perf/tools/build_optimized.py [--level q90]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from common import (
    ASSETS_DIR,
    DIST_DIR,
    HTML_PATH,
    PNG_URI_RE,
    REPORTS_DIR,
    WEBP_DIR,
    b64_of,
    decode_b64,
    ensure_dirs,
    human_bytes,
    load_manifest,
    read_source,
    sha256_bytes,
    sha256_text,
    source_sha256,
    split_tut,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", default="q90", help="WebP 档位：lossless/q95/q90/q85")
    args = parser.parse_args()
    level = args.level

    webp_dir = WEBP_DIR / level
    if not webp_dir.exists():
        print(f"缺少 {webp_dir}，请先运行 tools/convert_webp.py")
        return 1

    ensure_dirs()
    manifest = load_manifest()

    # sha256(PNG) -> WebP 的 base64
    by_sha: dict[str, str] = {}
    for rec in manifest["shots"]:
        webp_path = webp_dir / (rec["file"][:-4] + ".webp")
        by_sha[rec["sha256"]] = b64_of(webp_path.read_bytes())

    sha_before = source_sha256()
    text = read_source()
    head, body, tail = split_tut(text)

    replaced = 0
    missing: list[str] = []

    def repl(match):
        nonlocal replaced
        b64 = match.group(1)
        new = by_sha.get(sha256_bytes(decode_b64(b64)))
        if new is None:
            missing.append(b64[:32] + "...")
            return match.group(0)
        replaced += 1
        return "data:image/webp;base64," + new

    new_body = PNG_URI_RE.sub(repl, body)
    if missing:
        print(f"FAIL: {len(missing)} 张图片未找到对应 WebP：{missing[:3]}")
        return 1

    expected = len(PNG_URI_RE.findall(body))
    if replaced != expected:
        print(f"FAIL: 替换 {replaced} 处 ≠ 原文 {expected} 处")
        return 1

    out_path = DIST_DIR / f"{HTML_PATH.stem}.webp-{level}.html"
    new_text = head + new_body + tail
    out_path.write_bytes(new_text.encode("utf-8"))

    sha_after = source_sha256()
    if sha_before != sha_after:
        print("FAIL: 源文件在构建过程中被修改！")
        return 1

    old_bytes = len(text.encode("utf-8"))
    new_bytes = out_path.stat().st_size
    meta = {
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "level": level,
        "source": {"file": HTML_PATH.name, "bytes": old_bytes, "sha256": sha_before},
        "output": {"file": out_path.name, "bytes": new_bytes, "sha256": sha256_bytes(out_path.read_bytes())},
        "images_replaced": replaced,
        "delta_bytes": new_bytes - old_bytes,
        "saving": round(1 - new_bytes / old_bytes, 4),
        "tut_data_chars": {"before": len(body), "after": len(new_body)},
    }
    (REPORTS_DIR / f"build-{level}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"源文件（未改动）: {human_bytes(old_bytes)}  sha256={sha_before[:16]}…")
    print(f"优化版输出      : {human_bytes(new_bytes)}  降幅 {100 * (1 - new_bytes / old_bytes):.1f}%")
    print(f"替换图片        : {replaced} 处（{level}）")
    print(f"输出路径        : {out_path}")
    print(f"构建元数据      : {REPORTS_DIR / f'build-{level}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""把提取出的 PNG 截图转成 WebP（无损 / q95 / q90 / q85），并给出整文件体积预测。

只读 perf/assets/shots 的 PNG；产物写 perf/assets/webp/<档位>/。
不触碰源文件。整文件预测口径：
    新文件字节 ≈ 原文件字节 - 原 base64 总字符 + 新 base64 总字符
（替换是等位置换，除图片载荷外一切字符不变，故可用字符数差直接推算）

用法：python perf/tools/convert_webp.py [--levels lossless,q95,q90,q85]
"""

from __future__ import annotations

import argparse
import io
import json
import sys

from common import (
    ASSETS_DIR,
    HTML_PATH,
    SHOTS_DIR,
    WEBP_DIR,
    b64_of,
    ensure_dirs,
    human_bytes,
    load_manifest,
)

DEFAULT_LEVELS = ["lossless", "q95", "q90", "q85"]


def encode(img, level: str) -> bytes:
    buf = io.BytesIO()
    if level == "lossless":
        img.save(buf, "WEBP", lossless=True, method=4, quality=100)
    else:
        quality = int(level.lstrip("q"))
        img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default=",".join(DEFAULT_LEVELS))
    args = parser.parse_args()
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]

    from PIL import Image

    ensure_dirs()
    manifest = load_manifest()
    shots = manifest["shots"]
    source_bytes = manifest["source"]["source_bytes"]
    total_b64_in = manifest["totals"]["base64_chars"]

    results: dict[str, dict] = {}
    for level in levels:
        out_dir = WEBP_DIR / level
        out_dir.mkdir(parents=True, exist_ok=True)
        per_image = []
        total_bytes = 0
        total_b64_out = 0
        for rec in shots:
            src = SHOTS_DIR / rec["file"]
            with Image.open(src) as img:
                raw = encode(img, level)
            (out_dir / (rec["file"][:-4] + ".webp")).write_bytes(raw)
            b64_chars = len(b64_of(raw))
            total_bytes += len(raw)
            total_b64_out += b64_chars * rec["occurrences"]
            per_image.append(
                {
                    "file": rec["file"],
                    "png_bytes": rec["bytes"],
                    "webp_bytes": len(raw),
                    "ratio": round(rec["bytes"] / len(raw), 2),
                }
            )
        projected = source_bytes - total_b64_in + total_b64_out
        results[level] = {
            "images": len(shots),
            "webp_bytes": total_bytes,
            "base64_chars_out": total_b64_out,
            "projected_html_bytes": projected,
            "projected_saving": 1 - projected / source_bytes,
            "per_image": per_image,
        }

    report = {
        "source": manifest["source"],
        "levels": results,
    }
    (ASSETS_DIR / "webp-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    png_bytes = manifest["totals"]["png_bytes"]
    print(f"原文件      : {human_bytes(source_bytes)}")
    print(f"PNG 截图    : {human_bytes(png_bytes)}（对应 base64 {total_b64_in:,} 字符）")
    print()
    mib = 1048576
    print(f"{'档位':<10}{'图片 MiB':>10}{'占 PNG':>9}{'预测整文件 MiB':>16}{'降幅':>9}")
    print("-" * 58)
    for level in levels:
        r = results[level]
        print(
            f"{level:<10}{r['webp_bytes'] / mib:>10.2f}"
            f"{100 * r['webp_bytes'] / png_bytes:>8.1f}%"
            f"{r['projected_html_bytes'] / mib:>16.2f}"
            f"{100 * r['projected_saving']:>8.1f}%"
        )
    print()
    base = results.get("q90") or results[levels[-1]]
    worst = sorted(base["per_image"], key=lambda x: -x["png_bytes"])[:3]
    print("q90 档最大的三张（PNG → WebP）:")
    for item in worst:
        print(f"  {item['file']:<16}{human_bytes(item['png_bytes']):>22} → "
              f"{human_bytes(item['webp_bytes'])}  ×{item['ratio']}")
    print()
    print(f"产物: {WEBP_DIR}")
    print(f"报告: {ASSETS_DIR / 'webp-report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

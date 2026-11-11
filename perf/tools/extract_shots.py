#!/usr/bin/env python3
"""把 `#tut-data` 里内联的 PNG 截图原样落到 perf/assets/shots/。

只读源文件；产物写 perf/assets。按内容 sha256 去重，重复出现只存一份，
manifest.json 记录全部出现位置（owner/field），供后续转换与重建使用。

用法：python perf/tools/extract_shots.py
"""

from __future__ import annotations

import json
import sys

from common import (
    ASSETS_DIR,
    HTML_PATH,
    MANIFEST_PATH,
    PNG_URI_RE,
    SHOTS_DIR,
    decode_b64,
    ensure_dirs,
    human_bytes,
    iter_doc_images,
    png_dimensions,
    read_source,
    sha256_bytes,
    split_tut,
)


def main() -> int:
    ensure_dirs()
    text = read_source()
    head, body, _tail = split_tut(text)
    doc = json.loads(body)

    claims = list(iter_doc_images(doc))
    raw = [m.group(1) for m in PNG_URI_RE.finditer(body)]
    if len(claims) != len(raw):
        print(f"FAIL: 结构化枚举 {len(claims)} 张 vs 原文正则 {len(raw)} 张，顺序映射不可靠")
        return 1
    for i, ((_, _, b64), raw_b64) in enumerate(zip(claims, raw)):
        if b64 != raw_b64:
            print(f"FAIL: 第 {i + 1} 张结构化枚举与原文不一致，放弃顺序映射")
            return 1

    per_owner_seq: dict[str, int] = {}
    by_sha: dict[str, dict] = {}
    shots: list[dict] = []

    for index, (owner, field, b64) in enumerate(claims, start=1):
        data = decode_b64(b64)
        digest = sha256_bytes(data)
        record = by_sha.get(digest)
        if record is None:
            seq = per_owner_seq.get(owner, 0) + 1
            per_owner_seq[owner] = seq
            filename = f"{owner}-{seq:02d}.png"
            (SHOTS_DIR / filename).write_bytes(data)
            dims = png_dimensions(data)
            record = {
                "file": filename,
                "sha256": digest,
                "bytes": len(data),
                "width": dims[0] if dims else None,
                "height": dims[1] if dims else None,
                "base64_chars": len(b64),
                "occurrences": 0,
                "where": [],
            }
            by_sha[digest] = record
            shots.append(record)
        record["occurrences"] += 1
        record["where"].append({"owner": owner, "field": field, "index": index})

    total_bytes = sum(r["bytes"] for r in shots)
    total_b64 = sum(r["base64_chars"] * r["occurrences"] for r in shots)
    manifest = {
        "source": {
            "file": HTML_PATH.name,
            "source_bytes": HTML_PATH.stat().st_size,
            "tut_data_chars": len(body),
            "html_head_chars": len(head),
        },
        "shots": shots,
        "totals": {
            "occurrences": len(claims),
            "unique_images": len(shots),
            "png_bytes": total_bytes,
            "base64_chars": total_b64,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    dupes = [r for r in shots if r["occurrences"] > 1]
    print(f"源文件      : {HTML_PATH.name} ({human_bytes(manifest['source']['source_bytes'])})")
    print(f"截图出现次数: {len(claims)}    去重后图片: {len(shots)}   重复引用: {len(dupes)} 张")
    print(f"PNG 原始总量: {human_bytes(total_bytes)}")
    print(f"base64 总量 : {total_b64:,} 字符 ({total_b64 / 1048576:.2f} MiB)")
    sizes = sorted(shots, key=lambda r: -r["bytes"])
    worst = sizes[0]
    print(f"最大一张    : {worst['file']} {human_bytes(worst['bytes'])} "
          f"{worst['width']}x{worst['height']}")
    dims = {(r["width"], r["height"]) for r in shots}
    print(f"尺寸集合    : {sorted(dims)}")
    print(f"原图输出    : {SHOTS_DIR}")
    print(f"清单        : {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

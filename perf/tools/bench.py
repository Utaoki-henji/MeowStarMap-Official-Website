#!/usr/bin/env python3
"""体积与传输基准：源文件 vs 优化版，含 gzip/brotli 后体积与带宽换算矩阵。

只测「传输层」，不含浏览器解析/渲染（本工作树无 playwright，无法无头实测）。
产物：perf/reports/bench.md

用法：python perf/tools/bench.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zlib
from datetime import datetime, timezone

from common import DIST_DIR, HTML_PATH, REPORTS_DIR, read_source, split_tut

SPEEDS_MBPS = [1, 5, 10, 20, 50, 100, 1000]
MB = 1048576


def gzip_size(data: bytes) -> int:
    cmp = zlib.compressobj(9, zlib.DEFLATED, 31)  # 31 = gzip 容器
    return len(cmp.compress(data) + cmp.flush())


def brotli_size(path) -> tuple[int | None, str]:
    try:
        import brotli  # type: ignore

        return len(brotli.compress(path.read_bytes(), quality=11)), "python-brotli"
    except Exception:
        pass
    node = shutil.which("node")
    if not node:
        return None, "跳过（无 brotli 模块且无 node）"
    script = (
        "const z=require('zlib'),f=require('fs');"
        "const b=f.readFileSync(process.argv[1]);"
        "process.stdout.write(String(z.brotliCompressSync(b,{params:{"
        "[z.constants.BROTLI_PARAM_QUALITY]:11}}).length))"
    )
    try:
        out = subprocess.run(
            [node, "-e", script, str(path)],
            capture_output=True, text=True, timeout=600, check=True,
        )
        return int(out.stdout.strip()), "node-zlib"
    except Exception as exc:  # noqa: BLE001
        return None, f"跳过（{type(exc).__name__}）"


def first_paint_bytes() -> int:
    """落地页 #/ 真正需要的字节：剥掉两个数据块与全部 data: 载荷后的标记量。"""
    text = read_source()
    head, _body, tail = split_tut(text)
    # 去掉 dev-data 整块
    text2 = head + tail
    start = text2.index('<script id="dev-data" type="application/json">')
    end = text2.index("</script>", start)
    text2 = text2[:start] + text2[end:]
    text2 = re.sub(r"data:[a-z0-9/+.;=-]+,[A-Za-z0-9+/=%]+", "DATAURI", text2)
    return len(text2.encode("utf-8"))


def fmt_size(n: int) -> str:
    return f"{n / MB:.2f} MiB"


def transfer_seconds(nbytes: int, mbps: float) -> float:
    return nbytes * 8 / (mbps * 1_000_000)


def main() -> int:
    artifacts: list[dict] = []
    src_bytes = HTML_PATH.stat().st_size
    artifacts.append({"label": "源文件（现状）", "path": HTML_PATH, "bytes": src_bytes})

    for path in sorted(DIST_DIR.glob("*.html")):
        level = re.search(r"webp-(.+?)\.html$", path.name)
        artifacts.append({
            "label": f"优化版 {level.group(1) if level else path.stem}",
            "path": path,
            "bytes": path.stat().st_size,
        })

    if len(artifacts) == 1:
        print("perf/dist 下没有优化版，请先运行 build_optimized.py")
        return 1

    for art in artifacts:
        data = art["path"].read_bytes()
        art["gzip"] = gzip_size(data)
        art["brotli"], art["brotli_by"] = brotli_size(art["path"])

    needed = first_paint_bytes()

    lines: list[str] = []
    add = lines.append
    add("# 体积与传输基准（自动生成）")
    add("")
    add(f"生成时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}")
    add(f"源文件：`{HTML_PATH.name}`，{src_bytes:,} 字节（{fmt_size(src_bytes)}）")
    add("")
    add("## 一、压缩后体积")
    add("")
    add("| 资产 | 原始 | gzip -9 | brotli q11 | 压缩后占比 |")
    add("|---|---|---|---|---|")
    for art in artifacts:
        br = fmt_size(art["brotli"]) if art["brotli"] else "—"
        ratio = f"{100 * art['brotli'] / art['bytes']:.1f}%" if art["brotli"] else "—"
        add(f"| {art['label']} | {fmt_size(art['bytes'])} | {fmt_size(art['gzip'])} | {br} | {ratio} |")
    add("")
    add(f"> brotli 测量后端：{artifacts[-1]['brotli_by']}；gzip 为 Python zlib level 9。")
    add("")
    add("## 二、带宽换算（下载耗时，秒）")
    add("")
    add("> 口径：耗时 = 字节 × 8 ÷ (带宽 Mbps × 10⁶)，仅传输时间，不含 TTFB、解析与渲染。")
    add("")
    header = "| 带宽 | " + " | ".join(art["label"] for art in artifacts) + " |"
    add(header)
    add("|" + "---|" * (len(artifacts) + 1))
    for mbps in SPEEDS_MBPS:
        cells = [f"{transfer_seconds(a['bytes'], mbps):.1f} s" for a in artifacts]
        add(f"| {mbps} Mbps | " + " | ".join(cells) + " |")
    add("")
    add("压缩后（brotli）同一矩阵：")
    add("")
    add(header.replace("原始", "brotli"))
    add("|" + "---|" * (len(artifacts) + 1))
    for mbps in SPEEDS_MBPS:
        cells = []
        for a in artifacts:
            n = a["brotli"] if a["brotli"] else a["bytes"]
            cells.append(f"{transfer_seconds(n, mbps):.1f} s")
        add(f"| {mbps} Mbps | " + " | ".join(cells) + " |")
    add("")
    add("## 三、关键对照")
    add("")
    add(f"- 落地页 `#/` 真正需要的标记量：**{needed:,} 字节（{fmt_size(needed)}）**，"
        f"仅占源文件 {100 * needed / src_bytes:.2f}%。")
    best = min(artifacts[1:], key=lambda a: a["bytes"])
    add(f"- {best['label']}：{fmt_size(best['bytes'])}，"
        f"为源文件的 {100 * best['bytes'] / src_bytes:.1f}%。")
    if best["brotli"]:
        add(f"- {best['label']} + brotli：{fmt_size(best['brotli'])}，"
            f"为源文件未压缩的 {100 * best['brotli'] / src_bytes:.1f}%。")
    add("- 注意：PNG 已是压缩格式，brotli 只能回收 base64 的 33% 膨胀与文本冗余，"
        "源文件 brotli 后仍 >20 MiB 就是直接证据。")
    add("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "bench.md"
    out.write_text("\n".join(lines), encoding="utf-8")

    (REPORTS_DIR / "bench.json").write_text(
        json.dumps(
            [
                {k: (str(v) if k == "path" else v) for k, v in a.items()}
                for a in artifacts
            ],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    print("\n".join(lines))
    print(f"\n报告已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

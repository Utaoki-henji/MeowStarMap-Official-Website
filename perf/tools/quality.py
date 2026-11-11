#!/usr/bin/env python3
"""量化 WebP 各档位相对原 PNG 的画质损失（PSNR / 最大通道误差 / 超阈像素占比）。

目的：给「q90 视觉近无损」这句话提供可复核的数字，而不是只靠肉眼。
产物：perf/reports/quality.md；加 --montage <档位> 时另出一张三联对照图
      （原 PNG / WebP / 8 倍放大差异），取该档位 PSNR 最低的那张。

用法：python perf/tools/quality.py [--levels q95,q90,q85] [--montage q90]
"""

from __future__ import annotations

import argparse
import math
import sys

import numpy as np

from common import REPORTS_DIR, SHOTS_DIR, WEBP_DIR, load_manifest

DEFAULT_LEVELS = ["q95", "q90", "q85"]
MONTAIG_CROP = (300, 150, 1100, 650)  # 800x500，含文字与渐变


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    if mse == 0:
        return float("inf")
    return 10 * math.log10(255.0 ** 2 / mse)


def montage(level: str, name: str) -> None:
    from PIL import Image

    png = Image.open(SHOTS_DIR / name).convert("RGB")
    webp = Image.open(WEBP_DIR / level / (name[:-4] + ".webp")).convert("RGB")
    a = png.crop(MONTAIG_CROP)
    b = webp.crop(MONTAIG_CROP)
    diff = np.abs(np.asarray(a, np.int16) - np.asarray(b, np.int16))
    amp = np.clip(diff.astype(np.int16) * 8, 0, 255).astype(np.uint8)
    d = Image.fromarray(amp)
    cw, ch = a.size
    canvas = Image.new("RGB", (cw * 3 + 16, ch), (30, 30, 30))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (cw + 8, 0))
    canvas.paste(d, (cw * 2 + 16, 0))
    out = REPORTS_DIR / f"quality-compare-{level}.png"
    canvas.save(out)
    print(f"三联对照图：{out}（左=PNG / 中={level} WebP / 右=差异×8）")
    print(f"  裁剪区平均绝对差 {diff.mean():.2f}，最大 {int(diff.max())}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default=",".join(DEFAULT_LEVELS))
    parser.add_argument("--montage", default="", help="为指定档位 PSNR 最低的图生成三联对照图")
    args = parser.parse_args()
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]

    from PIL import Image

    manifest = load_manifest()
    rows: list[str] = ["# WebP 画质对照（相对原 PNG）", ""]
    rows.append("PSNR 越高越接近原图；>40 dB 通常认为肉眼不可辨，>35 dB 一般仍难辨。")
    rows.append("")
    rows.append("| 档位 | 图片数 | PSNR 均值 | PSNR 最低 | 最大通道误差 | 误差>8 的像素占比 |")
    rows.append("|---|---|---|---|---|---|")

    details: list[str] = []
    worst_by_level: dict[str, str] = {}
    for level in levels:
        scores: list[tuple[float, str]] = []
        worst_err = 0
        far_pixels = 0
        total_pixels = 0
        for rec in manifest["shots"]:
            png_path = SHOTS_DIR / rec["file"]
            webp_path = WEBP_DIR / level / (rec["file"][:-4] + ".webp")
            with Image.open(png_path) as pimg, Image.open(webp_path) as wimg:
                a = np.asarray(pimg.convert("RGB"), dtype=np.int16)
                b = np.asarray(wimg.convert("RGB"), dtype=np.int16)
            diff = np.abs(a - b)
            scores.append((psnr(a, b), rec["file"]))
            worst_err = max(worst_err, int(diff.max()))
            far_pixels += int((diff.max(axis=2) > 8).sum())
            total_pixels += diff.shape[0] * diff.shape[1]

        scores.sort()
        mean_score = sum(s for s, _ in scores) / len(scores)
        rows.append(
            f"| {level} | {len(scores)} | {mean_score:.2f} dB | {scores[0][0]:.2f} dB | "
            f"{worst_err} | {100 * far_pixels / total_pixels:.3f}% |"
        )
        details.append(f"- **{level}** 最低的三张：" + "，".join(
            f"{name}（{score:.2f} dB）" for score, name in scores[:3]
        ))
        worst_by_level[level] = scores[0][1]

    rows.append("")
    rows.append("## 最低分样本")
    rows.append("")
    rows.extend(details)
    rows.append("")
    rows.append("> 判定口径：误差为逐通道绝对差；「误差>8 的像素占比」按单像素三通道最大差计。")
    rows.append("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "quality.md"
    out.write_text("\n".join(rows), encoding="utf-8")
    print("\n".join(rows))
    print(f"报告已写入 {out}")

    if args.montage:
        level = args.montage
        if level not in worst_by_level:
            print(f"--montage {level} 需要同时测该档位（--levels 里包含它）")
            return 1
        montage(level, worst_by_level[level])
    return 0


if __name__ == "__main__":
    sys.exit(main())

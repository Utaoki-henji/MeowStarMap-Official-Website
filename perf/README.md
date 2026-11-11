# perf — 体积与传输优化（只新增，不改动站点）

本目录是为了回答一个具体争议：「官网打开很慢，到底是服务器带宽，还是这个 34 MB 的单文件 HTML」。

**它不修改任何既有文件**：不信 `Meow Star Map 官网.html`，不碰 `tests/`、`AGENTS.md`、README。
所有产物写在 `perf/` 之内，`perf/assets/` 与 `perf/dist/` 是可通过脚本重建的中间产物，已在
`perf/.gitignore` 中排除，不入库。要撤销这整套东西，删掉 `perf/` 目录即可。

---

## 一、实测结论

源文件 `Meow Star Map 官网.html`：**34,856,177 字节（33.24 MiB）**，其中
**48 张 1400×900 的 PNG 截图**以 base64 内联在 `#tut-data` 里，占
**30,887,988 字符（29.46 MiB 的 base64，对应 22.09 MiB 的 PNG 二进制）**。

> 口径修正：按教程 `pages[].html` 统计会得到 45 张，另有 **3 张在 9 个模块的 `overview`
> 字段里**（同样内联、同样 1400×900）。本工具链按全文统计，共 48 张，无重复内容。

| 方案 | 截图体积 | 重建后整文件 | 相对原文件 | 加 brotli 后 | PSNR 均值 / 最低 |
|---|---|---|---|---|---|
| 现状（PNG） | 22.09 MiB | 33.24 MiB | 100% | 23.15 MiB | — |
| WebP 无损 | 16.07 MiB | 25.21 MiB | 75.8%（↓24.2%） | — | ∞（逐位相同） |
| WebP q95 | 5.36 MiB | 10.93 MiB | 32.9%（↓67.1%） | — | 39.33 / 34.68 dB |
| **WebP q90** | 3.82 MiB | **8.88 MiB** | **26.7%（↓73.3%）** | **5.13 MiB** | 38.86 / 34.53 dB |
| WebP q85 | 3.04 MiB | 7.84 MiB | 23.6%（↓76.4%） | 4.36 MiB | 38.31 / 34.30 dB |

三条关键事实：

1. **压缩救不了 base64 图片**。源文件 gzip -9 → 23.68 MiB、brotli q11 → 23.15 MiB，
   只回收了 base64 的 33% 膨胀。因为 22 MiB 的主体是**已经是压缩格式的 PNG**，熵极高。
   这就是「加带宽/开压缩就能解决」不成立的地方——传输底线被钉死在 23 MiB。
2. **落地页只需要 0.47 MiB**。剥掉两个数据块与全部 `data:` 载荷后，标记量只有
   491,517 字节（占 1.41%）。也就是访问 `#/` 的人为 98.6% 用不到的内容付费。
3. **换格式是唯一「不破坏单文件契约」的有效手段**。仍是 `data:` 内联、仍是零外链、
   仍可离线双击打开，只是把 PNG 换成 WebP。

传输耗时（仅下载，不含 TTFB/解析/渲染）：

| 带宽 | 现状 33.24 MiB | 现状 + brotli 23.15 MiB | q90 8.88 MiB | q90 + brotli 5.13 MiB |
|---|---|---|---|---|
| 10 Mbps | 27.9 s | 19.4 s | 7.4 s | 4.3 s |
| 50 Mbps | 5.6 s | 3.9 s | 1.5 s | 0.9 s |
| 100 Mbps | 2.8 s | 1.9 s | 0.7 s | 0.4 s |

完整矩阵见 [`reports/bench.md`](reports/bench.md)。

**画质**：q90 与原图逐像素 PSNR 均值 38.86 dB、最低 34.53 dB（最差的是 `m6p1-02.png`，
一张带渐变与粒子的游戏截图），1:1 观察肉眼不可辨，差异集中在文字边缘。三联对照图
（左=PNG / 中=q90 / 右=差异 ×8）见 [`reports/quality-compare-q90.png`](reports/quality-compare-q90.png)。
若要求零妥协，用 `--level lossless`：逐位相同、仍能省 24%。

---

## 二、目录结构

```
perf/
  README.md              本文件（结论与用法）
  requirements.txt       唯一依赖：Pillow（仅本目录工具链使用）
  .gitignore             排除 assets/ 与 dist/（可重建，不入库）
  tools/
    common.py            源文件定位、#tut-data 切分、截图枚举、体积换算
    extract_shots.py     提取 48 张 PNG 原图 + manifest.json（含 sha256/尺寸/出现位置）
    convert_webp.py      PNG → WebP（lossless / q95 / q90 / q85）+ 整文件体积预测
    build_optimized.py   生成优化版 HTML 到 dist/（源文件只读，前后校验 sha256）
    verify.py            26 项源码级等价性与不变量断言（可作 CI 门禁）
    quality.py           PSNR / 最大通道误差 / 超阈像素占比 + 可选三联对照图
    bench.py             体积、gzip/brotli、带宽换算矩阵 → reports/bench.md
  assets/                [gitignored] 提取出的 PNG 原图与各档 WebP
  dist/                  [gitignored] 重建出的优化版 HTML
  reports/               [入库] 生成的报告与构建元数据
```

## 三、用法

```bash
pip install -r perf/requirements.txt     # 只有一个 Pillow

python perf/tools/extract_shots.py       # 提取 48 张原图 → perf/assets/shots/
python perf/tools/convert_webp.py        # 生成 4 档 WebP → perf/assets/webp/
python perf/tools/build_optimized.py --level q90   # → perf/dist/…webp-q90.html
python perf/tools/verify.py --level q90  # 26 项断言，全绿才算通过
python perf/tools/quality.py --montage q90         # 画质报告 + 三联对照图
python perf/tools/bench.py               # 体积/压缩/带宽矩阵
```

产物示例：`perf/dist/Meow Star Map 官网.webp-q90.html`（8.88 MiB）——和源文件一样，
`file://` 双击即可离线运行。

## 四、`verify.py` 断言了什么（当前 26 / 26 PASS）

- **只有图片载荷变了**：`#tut-data` 之前与之后的内容**逐字节相同**；CRLF 保留，
  换行符计数 5026 不变；`</script>` 计数 24 不变。
- **JSON 结构等价**：把两侧所有 `data:` 载荷替换为占位符后深度对比，完全相等；
  36 篇教程页、9 个模块、id 与顺序全部一致。
- **零外链不变量保持**：`<link>` 2→2、`<script src>` 0、`<iframe>` 0、外链 `<img>` 0、
  `url(http)` 0、`@font-face{` 2、`<img>` 53、`<style>` 1，逐项相等。
- **源文件未被改动**：`build_optimized.py` 运行前后各校验一次 sha256。

> 本目录只做源码级校验，**没有浏览器实测**：本机未安装 playwright，Chromium 的进程间
> 通道被沙箱拦截。建议在父仓库对优化版补跑 `r37_bento_check.py` / `r38_visual_check.py` /
> `r42_migration_check.py` 作视觉与交互复核（这三个探针都会读 `#tut-data` 中的图片，
> 换成 WebP 后仍是 `data:`，预期只需确认，无需改断言）。

## 五、兼容性

- WebP 支持面：Chrome/Edge 全版本、Firefox 65+、Safari 14+ / iOS 14+。本项目已依赖
  `:has()`（Safari 15.4+）与 `backdrop-filter`，**WebP 的兼容门槛比它们更低**，不新增风险。
- 仍是 `data:` 内联：零外链不变量、离线可用性、单文件交付形态全部不变。
- 不触碰两条巨型数据行中的 `#dev-data`，也不触碰字体/图标/GSAP。

## 六、有意没做的事

| 候选 | 收益 | 为什么没做 |
|---|---|---|
| 拆出线上版（数据/图片外置 + 懒加载） | 首屏 0.47 MiB，提升两个数量级 | **会破坏「单文件自包含、双击可用」验收契约**，属产品决策，需要项目所有者拍板 |
| 缩略图 + `loading="lazy"` | 位图内存 5 MB/张 → 1–2 MB | 同样需要外置资源或额外 `<img>` 体积，收益小于换格式 |
| 直接改源文件 | 一步到位 | 本次约定「不做改动，只做新增」；优化版作为独立产物提交评审后再决定是否合入 |

## 七、回滚

删除 `perf/` 目录即可，站点与既有文件零改动。

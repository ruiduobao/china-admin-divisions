# Changelog

All notable changes to `china-admin-divisions` are documented here.
The skill follows [Semantic Versioning](https://semver.org/).

## [0.1.2] — 2026-07-21

### Added
- **PNG 输出（纯形状、无文字）** — 新增 `--format png`，使用 Pillow
  在客户端把 GeoJSON 渲染成 PNG。无任何文字标注、图例、经纬网，
  默认 1024px 长边，浅蓝填充 + 深蓝边框，保持 bbox 长宽比。
  需要 `pip install Pillow`；缺 Pillow 时给出明确错误。
- `admin_core.render_geojson_to_png(geojson, size=1024, ...)` 暴露为
  公共 API，颜色 / 画布 / 描边宽度均可调。
- `examples/preview_jinjiang.png` 与 `preview_chaoyang.png` 示例图。

### Changed
- 测试规模 25 → 28（新增 PNG 单文件下载、PNG↔GeoJSON 长宽比一致性、
  PNG 公开性检查）；`_run` 默认 timeout 由 60s 提到 180s 应对网络抖动。

## [0.1.1] — 2026-07-21

### Changed
- **`--format` 公共名从 `gson` 改为 `geojson`**。`gson` 仍作为别名接受，
  旧脚本无需改动。
- `info` 命令对 9/12 位乡/村级 code 不再硬错误：API 无面边界时返回部分
  结果（`bbox_*` / `area_*` 为 `null`，并附 `vector_available: false`
  + `vector_error`）。退出码仍为 0。
- `info` / `bbox` 新增 `--no-geojson` 选项，可完全跳过矢量拉取。
- 清理未使用的 stdlib import（`io`、`sys`、`zipfile`）和误导性的
  `_no_proxy_ssl_context()` 死代码。
- `admin_core.__all__` 新增 `FORMAT_ALIASES` / `FORMAT_EXTENSIONS`。
- 测试规模从 20 扩到 25，新增对 `gson` 兼容、9 位级 `--no-geojson`、
  import 干净度的回归用例。

### Fixed
- `pick_admin_result` 对 `province` 部分匹配的不对称行为依然存在，
  但 README/SKILL 已注明使用全称（如 `四川省` 而非 `四川`）。

## [0.1.0] — 2026-07-20

### Added
- 首次发布：支持省/市/县/乡/村五级搜索、树状下钻、单区划 / 批量下载。
- 支持 GeoJSON / Shapefile / KML / GeoPackage / SVG 5 种输出格式。
- bbox + 1 km 扩展 + flat-earth 面积估算。
- 纯标准库实现，无第三方依赖。
- 20 项 e2e 测试全部通过。

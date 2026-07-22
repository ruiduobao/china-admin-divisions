---
name: china-admin-divisions
display_name: 中国行政区划下载
version: 0.1.3
author: Mavis
description: |
  Download Chinese administrative-division vector data (province / city /
  county / town / village) from the public map.ruiduobao.com API.
  Supports GeoJSON / Shapefile / KML / GeoPackage / SVG / PNG (shape-only),
  tree-style drill-down, single + batch download, bbox and area
  calculation with a 1 km buffer. No credentials required.
runtime: python>=3.9
tags: [gis, china, admin-divisions, vector, shapefile, geojson, png, svg]
---

# 中国行政区划下载（china-admin-divisions）

通过瑞朵豹 `map.ruiduobao.com` 的免费公开 API，下载中国**五级**行政区划矢量数据
（省/市/县/乡/村）。无需任何凭据。

## Quickstart

```bash
# 1) 搜索
python scripts/china_admin_divisions.py search 锦江
python scripts/china_admin_divisions.py search 510104 --level xian

# 2) 树状下钻
python scripts/china_admin_divisions.py cities --province 四川省
python scripts/china_admin_divisions.py counties --province 四川省 --city 成都市
python scripts/china_admin_divisions.py towns --province 四川省 --city 成都市 --county 锦江区
python scripts/china_admin_divisions.py villages \
    --province 四川省 --city 成都市 --county 锦江区 --town 锦华路街道

# 3) 元信息（含 bbox + 1 km 扩展）
python scripts/china_admin_divisions.py info --code 510104 --expand-km 1
python scripts/china_admin_divisions.py bbox --name 海淀区 --province 北京市 --expand-km 2

# 4) 下载单个矢量
python scripts/china_admin_divisions.py download --code 510104 --format geojson
python scripts/china_admin_divisions.py download --code 510104 --format shp --out jinjiang.zip
python scripts/china_admin_divisions.py download --code 510104 --format kml

# 4b) 乡/村级 code 没有 geojson 边界？跳过拉取，仅返回元信息
python scripts/china_admin_divisions.py info --code 510104017 --no-geojson

# 5) 批量下载某省所有市
python scripts/china_admin_divisions.py download-children \
    --province 四川省 --level shi --format shp --out ./sichuan_shp
```

## 子命令

| 子命令 | 用途 | 主要参数 |
|---|---|---|
| `search` | 模糊搜索 | `keyword` [--province] [--level] [--limit] |
| `cities` | 列出某省所有市 | `--province` |
| `counties` | 列出某市所有县 | `--province --city` |
| `towns` | 列出某县所有乡 | `--province --city --county` |
| `villages` | 列出某乡所有村 | `--province --city --county --town` |
| `info` | 单个区划元信息 | `--code` 或 `--name [--province] [--city] [--level]` |
| `bbox` | 仅看 bbox + 面积 | 同上 + `--expand-km` |
| `download` | 下载单个矢量 | `--code` 或 `--name` + `--format` + `--out` |
| `download-children` | 批量下辖下载 | `--province` + `--level` + `[--city] [--county] [--out]` |

## 支持的下载格式

| `--format` | 输出后缀 | 备注 |
|---|---|---|
| `geojson` | `.geojson` | 标准 GeoJSON，单文件（`gson` 是历史别名，仍可用） |
| `shp` | `.zip` | ESRI Shapefile（zip 内含 .shp/.shx/.dbf/.prj） |
| `kml` | `.kml` | Google Earth |
| `gpkg` | `.gpkg` | GeoPackage，OGC 标准 |
| `svg` | `.svg` | 矢量图 |
| `png` | `.png` | **纯形状 PNG**（无任何文字标注），需要 Pillow |

不同用户群体怎么选：
- **GIS / 数据分析**：`geojson` 或 `shp`（最通用，QGIS / ArcGIS / GeoPandas 直接吃）
- **前端可视化 / Web 制图**：`svg`（矢量缩放无损，可在浏览器内交互）
- **日常看图 / 报告插图**：`png`（位图，PPT / Word 直接贴，**纯形状不标文字**）
- **OGC 互操作 / 数据库**：`gpkg`

## Permissions

- **网络出口**：`https://map.ruiduobao.com`（国内主机，默认直连绕过代理）。
  通过 `RUIDUOBAO_USE_PROXY=1` 强制走系统代理。
- **环境变量读取**：
  - `RUIDUOBAO_USE_PROXY`（决定是否使用系统代理）
- **文件读取**：无（除脚本自身）。
- **文件写入**：CLI 输出目录（`--out` 指定的路径或当前目录）。

## Notes

- 1 km bbox 扩展使用平面近似（`1° lat ≈ 110.574 km`，`1° lon ≈ 111.320·cos(mid_lat) km`）。
  极地 / 跨 180° 经线会失真，五级区划范围通常不会触发。
- 乡/村级 code（9/12 位）在上游 API 端**可能没有面边界**。默认情况下
  `info` 仍会返回 `name/code/level/province/city/...` 元信息，但
  `bbox_wgs84` / `area_km2` 为 `null`，并带 `vector_available: false`
  + `vector_error` 字段。也可以用 `--no-geojson` 完全跳过矢量拉取。
- 瑞朵豹 API 是免费公共服务，调用请勿过频。
- 默认所有网络调用**不走代理**（瑞朵豹在国内 + VPN 不稳）。如确实需要代理请设置
  `RUIDUOBAO_USE_PROXY=1`。
- `--format` 历史别名：`gson` 等价于 `geojson`，仍可继续使用以兼容旧脚本。

## Output Contract

`info` / `bbox` 子命令返回的 JSON 字段：

```json
{
  "name": "锦江区",
  "code": "510104",
  "level": "xian",
  "province": "四川省",
  "city": "成都市",
  "year": 2023,
  "source": "ruiduobao",
  "bbox_wgs84": [104.05, 30.62, 104.16, 30.71],
  "bbox_wgs84_expanded": [104.04, 30.61, 104.17, 30.72],
  "area_km2": 60.32,
  "area_km2_expanded": 76.18,
  "vector_available": true
}
```

乡/村级（无矢量边界）时：`bbox_wgs84` / `area_km2` 为 `null`，并附
`vector_available: false` 与 `vector_error: "..."` 字段；退出码仍为 0。

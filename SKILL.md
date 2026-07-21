---
name: china-admin-divisions
display_name: 中国行政区划下载
version: 0.1.0
author: Mavis
description: |
  Download Chinese administrative-division vector data (province / city /
  county / town / village) from the public map.ruiduobao.com API.
  Supports GeoJSON / Shapefile / KML / GeoPackage / SVG, tree-style
  drill-down, single + batch download, bbox and area calculation with a
  1 km buffer. No credentials required.
runtime: python>=3.9
tags: [gis, china, admin-divisions, vector, shapefile, geojson]
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
python scripts/china_admin_divisions.py download --code 510104 --format gson
python scripts/china_admin_divisions.py download --code 510104 --format shp --out jinjiang.zip
python scripts/china_admin_divisions.py download --code 510104 --format kml

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
| `gson` | `.geojson` | 标准 GeoJSON，单文件 |
| `shp` | `.zip` | ESRI Shapefile（zip 内含 .shp/.shx/.dbf/.prj） |
| `kml` | `.kml` | Google Earth |
| `gpkg` | `.gpkg` | GeoPackage，OGC 标准 |
| `svg` | `.svg` | 矢量图 |

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
- 乡/村级 API 不一定提供 gsonDB（12 位编码），元信息会回退到
  `downloadVector` 通道；如该区在 API 端没有面边界，`info` 会报错。
- 瑞朵豹 API 是免费公共服务，调用请勿过频。
- 默认所有网络调用**不走代理**（瑞朵豹在国内 + VPN 不稳）。如确实需要代理请设置
  `RUIDUOBAO_USE_PROXY=1`。

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
  "area_km2_expanded": 76.18
}
```

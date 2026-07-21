# china-admin-divisions · 中国行政区划下载

Download Chinese administrative-division vector data (province / city /
county / town / village) from the public **map.ruiduobao.com** API.

> 全部用 Python 标准库实现，无第三方依赖；支持 GeoJSON / Shapefile / KML
> / GeoPackage / SVG 五种格式输出；无需任何凭据。

## Quickstart

```bash
# 搜索
python scripts/china_admin_divisions.py search 锦江

# 树状下钻
python scripts/china_admin_divisions.py cities --province 四川省
python scripts/china_admin_divisions.py counties --province 四川省 --city 成都市

# 元信息（含 bbox + 1 km 扩展）
python scripts/china_admin_divisions.py info --code 510104 --expand-km 1

# 下载单个矢量
python scripts/china_admin_divisions.py download --code 510104 --format shp --out jinjiang.zip

# 批量下载某省所有市
python scripts/china_admin_divisions.py download-children \
    --province 四川省 --level shi --format shp --out ./sichuan_shp
```

## 子命令

| 子命令 | 用途 |
|---|---|
| `search` | 模糊搜索 |
| `cities` / `counties` / `towns` / `villages` | 树状下钻 |
| `info` | 单个区划元信息 |
| `bbox` | bbox + 面积 + 可选扩展 |
| `download` | 单个下载 |
| `download-children` | 批量下辖下载 |

## 数据源

所有数据来自 [锐多宝地图](https://map.ruiduobao.com) 的免费公开 API。详见
[API 文档](https://map.ruiduobao.com/others/API%E6%96%87%E6%A1%A3.html)。

## License

本 skill 仅做 API 客户端封装；原始行政区划数据版权归原网站所有，仅供学术
研究、教育学习等非商业用途使用。

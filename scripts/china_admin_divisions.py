"""CLI entry-point for the china-admin-divisions skill.

Run with::

    python scripts/china_admin_divisions.py <subcommand> [...]

Subcommands:
    search              Fuzzy search by name or code.
    cities / counties / towns / villages
                        Tree-style listing of a level under a parent.
    info                Resolve one admin division to rich metadata.
    bbox                Show bbox + area, optionally expanded by N km.
    download            Download a single vector in a chosen format.
    download-children   Download every child at a level under a parent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import admin_core as ac  # noqa: E402


def _emit(payload: Any, *, as_json: bool = True) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if isinstance(payload, (list, dict)):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload)
    return 0


def _err(message: str, *, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> int:
    try:
        results = ac._ruiduobao_search(
            args.keyword,
            province=args.province,
            level=args.level,
            limit=args.limit,
        )
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit({"count": len(results), "results": results}, as_json=not args.plain)


def cmd_cities(args: argparse.Namespace) -> int:
    try:
        rows = ac.list_cities(args.province, year=args.year)
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit({"province": args.province, "count": len(rows), "cities": rows},
                 as_json=not args.plain)


def cmd_counties(args: argparse.Namespace) -> int:
    try:
        rows = ac.list_counties(args.province, args.city, year=args.year)
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit(
        {"province": args.province, "city": args.city, "count": len(rows),
         "counties": rows},
        as_json=not args.plain,
    )


def cmd_towns(args: argparse.Namespace) -> int:
    try:
        rows = ac.list_towns(args.province, args.city, args.county, year=args.year)
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit(
        {"province": args.province, "city": args.city, "county": args.county,
         "count": len(rows), "towns": rows},
        as_json=not args.plain,
    )


def cmd_villages(args: argparse.Namespace) -> int:
    try:
        rows = ac.list_villages(
            args.province, args.city, args.county, args.town, year=args.year
        )
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit(
        {"province": args.province, "city": args.city, "county": args.county,
         "town": args.town, "count": len(rows), "villages": rows},
        as_json=not args.plain,
    )


def _common_admin_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--year", type=int, default=ac.DEFAULT_YEAR,
                   help=f"行政区划年份，默认 {ac.DEFAULT_YEAR}")
    p.add_argument("--plain", action="store_true",
                   help="输出纯文本而非 JSON 包装")


def cmd_info(args: argparse.Namespace) -> int:
    if not args.name and not args.code:
        return _err("Provide --name or --code")
    if args.name and args.code:
        return _err("Pass only one of --name or --code")
    try:
        meta = ac.resolve_admin(
            name=args.name,
            code=args.code,
            province=args.province,
            city=args.city,
            level=args.level,
            year=args.year,
            expand_km=args.expand_km,
            fetch_geojson=not args.no_geojson,
        )
    except ac.AdminApiError as e:
        return _err(str(e))
    return _emit(meta, as_json=not args.plain)


def cmd_bbox(args: argparse.Namespace) -> int:
    if not args.name and not args.code:
        return _err("Provide --name or --code")
    try:
        meta = ac.resolve_admin(
            name=args.name,
            code=args.code,
            province=args.province,
            city=args.city,
            level=args.level,
            year=args.year,
            expand_km=args.expand_km,
            fetch_geojson=not args.no_geojson,
        )
    except ac.AdminApiError as e:
        return _err(str(e))
    if not meta.get("bbox_wgs84"):
        return _err("No bbox available for this division")
    return _emit(
        {
            "name": meta["name"],
            "code": meta["code"],
            "level": meta["level"],
            "expand_km": args.expand_km,
            "bbox_wgs84": meta["bbox_wgs84"],
            "bbox_wgs84_expanded": meta["bbox_wgs84_expanded"],
            "area_km2": meta["area_km2"],
            "area_km2_expanded": meta["area_km2_expanded"],
        },
        as_json=not args.plain,
    )


def _normalize_format(fmt: str) -> str:
    """Resolve legacy aliases (e.g. gson -> geojson) and validate."""
    fmt = (fmt or "geojson").lower()
    fmt = ac.FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in ac.SUPPORTED_FORMATS:
        raise ac.AdminApiError(
            f"Unsupported format {fmt!r}; supported={list(ac.SUPPORTED_FORMATS)}"
        )
    return fmt


def cmd_download(args: argparse.Namespace) -> int:
    try:
        fmt = _normalize_format(args.format or "geojson")
    except ac.AdminApiError as e:
        return _err(str(e))
    if not args.name and not args.code:
        return _err("Provide --name or --code")
    try:
        meta = ac.resolve_admin(
            name=args.name,
            code=args.code,
            province=args.province,
            city=args.city,
            level=args.level,
            year=args.year,
            expand_km=0.0,
            fetch_geojson=False,
        )
    except ac.AdminApiError as e:
        return _err(f"resolve: {e}")
    try:
        body = ac.download_vector(meta["code"], fmt=fmt, year=args.year)
    except ac.AdminApiError as e:
        return _err(f"download: {e}")

    out_path = args.out
    if not out_path:
        suffix = ac.FORMAT_EXTENSIONS[fmt]
        slug = _safe_slug(meta.get("name") or meta["code"])
        out_path = f"{slug}_{meta['code']}_{args.year}.{suffix}"
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(body)
    return _emit(
        {
            "ok": True,
            "code": meta["code"],
            "name": meta["name"],
            "format": fmt,
            "path": out_path,
            "size_bytes": len(body),
        },
        as_json=not args.plain,
    )


def cmd_download_children(args: argparse.Namespace) -> int:
    try:
        fmt = _normalize_format(args.format or "shp")
    except ac.AdminApiError as e:
        return _err(str(e))
    try:
        rows = ac.list_children(
            province=args.province,
            level=args.level,
            city=args.city,
            county=args.county,
            year=args.year,
        )
    except ac.AdminApiError as e:
        return _err(f"list: {e}")
    if not rows:
        return _err(f"No children for level={args.level} under given parent")

    out_dir = os.path.abspath(args.out or f"./admin_{args.level}_{args.year}")
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for r in rows:
        code = r.get("code")
        name = r.get("name") or code
        if not code:
            continue
        try:
            body = ac.download_vector(code, fmt=fmt, year=args.year)
        except ac.AdminApiError as e:
            failures.append({"code": code, "name": name, "error": str(e)})
            continue
        suffix = ac.FORMAT_EXTENSIONS[fmt]
        slug = _safe_slug(name)
        path = os.path.join(out_dir, f"{slug}_{code}_{args.year}.{suffix}")
        with open(path, "wb") as f:
            f.write(body)
        results.append(
            {"code": code, "name": name, "path": path, "size_bytes": len(body)}
        )

    return _emit(
        {
            "ok": len(failures) == 0,
            "format": fmt,
            "level": args.level,
            "out_dir": out_dir,
            "downloaded": len(results),
            "failed": len(failures),
            "results": results,
            "failures": failures,
        },
        as_json=not args.plain,
    )


def _safe_slug(text: str) -> str:
    """Filesystem-safe slug. Keeps CJK + ASCII alnum/dash/underscore."""
    out = []
    for ch in text or "":
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
        else:
            out.append("_")
    return ("".join(out).strip("_") or "admin")[:80]


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="china-admin-divisions",
        description="Download Chinese administrative-division vector data "
                    "from map.ruiduobao.com (no credentials required).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # search
    sp = sub.add_parser("search", help="模糊搜索区划")
    sp.add_argument("keyword", help="搜索关键词（名称或编码）")
    sp.add_argument("--province", help="限定省份")
    sp.add_argument("--level", help="限定级别（sheng/shi/xian/xiang/cun）")
    sp.add_argument("--limit", type=int, default=ac.DEFAULT_LIMIT)
    sp.add_argument("--plain", action="store_true")
    sp.set_defaults(func=cmd_search)

    # cities / counties / towns / villages
    for sub_name, sub_help, sub_args, sub_handler in [
        (
            "cities",
            "列出某省所有地级市",
            [("province", str)],
            cmd_cities,
        ),
        (
            "counties",
            "列出某市所有县/区",
            [("province", str), ("city", str)],
            cmd_counties,
        ),
        (
            "towns",
            "列出某县所有乡镇",
            [("province", str), ("city", str), ("county", str)],
            cmd_towns,
        ),
        (
            "villages",
            "列出某乡镇所有村",
            [("province", str), ("city", str), ("county", str), ("town", str)],
            cmd_villages,
        ),
    ]:
        sp = sub.add_parser(sub_name, help=sub_help)
        for arg_name, arg_type in sub_args:
            sp.add_argument(f"--{arg_name}", required=True, type=arg_type)
        _common_admin_args(sp)
        sp.set_defaults(func=sub_handler)

    # info
    sp = sub.add_parser("info", help="查询单个区划的元信息（含 bbox、面积）")
    sp.add_argument("--name", help="区划名称（与 --code 互斥）")
    sp.add_argument("--code", help="区划编码（与 --name 互斥）")
    sp.add_argument("--province")
    sp.add_argument("--city")
    sp.add_argument("--level")
    sp.add_argument("--expand-km", type=float, default=ac.DEFAULT_EXPAND_KM,
                    help=f"扩展 bbox 的距离（km），默认 {ac.DEFAULT_EXPAND_KM}")
    sp.add_argument("--no-geojson", action="store_true",
                    help="不下载 geojson（仅返回元信息；乡/村级 code 适用）")
    _common_admin_args(sp)
    sp.set_defaults(func=cmd_info)

    # bbox
    sp = sub.add_parser("bbox", help="仅显示 bbox 与面积（可指定扩展 km）")
    sp.add_argument("--name")
    sp.add_argument("--code")
    sp.add_argument("--province")
    sp.add_argument("--city")
    sp.add_argument("--level")
    sp.add_argument("--expand-km", type=float, default=ac.DEFAULT_EXPAND_KM)
    sp.add_argument("--no-geojson", action="store_true",
                    help="不下载 geojson（仅返回元信息）")
    _common_admin_args(sp)
    sp.set_defaults(func=cmd_bbox)

    # download
    # `choices` includes the legacy `gson` alias so existing scripts don't
    # break. The actual download normalises it to `geojson`.
    sp = sub.add_parser("download", help="下载单个区划矢量")
    sp.add_argument("--name")
    sp.add_argument("--code")
    sp.add_argument("--province")
    sp.add_argument("--city")
    sp.add_argument("--level")
    sp.add_argument("--format", choices=list(ac.SUPPORTED_FORMATS) + list(ac.FORMAT_ALIASES),
                    default="geojson")
    sp.add_argument("--out", help="输出文件路径")
    _common_admin_args(sp)
    sp.set_defaults(func=cmd_download)

    # download-children
    sp = sub.add_parser(
        "download-children",
        help="下载某父级下所有某级子区划的矢量",
    )
    sp.add_argument("--province", required=True)
    sp.add_argument("--city", help="列出 xian 时必填")
    sp.add_argument("--county", help="列出 xiang 时必填")
    sp.add_argument(
        "--level", required=True,
        choices=["shi", "xian", "xiang", "cun"],
    )
    sp.add_argument("--format",
                    choices=list(ac.SUPPORTED_FORMATS) + list(ac.FORMAT_ALIASES),
                    default="shp")
    sp.add_argument("--out", help="输出目录")
    _common_admin_args(sp)
    sp.set_defaults(func=cmd_download_children)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

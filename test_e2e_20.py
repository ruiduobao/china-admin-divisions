"""20 e2e test cases for the china-admin-divisions skill.

Each case invokes the CLI as a real user would, parses the JSON output,
and checks a small set of expectations. Results are accumulated in a
list and printed as a markdown table at the end.

Usage::

    python test_e2e_20.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "china_admin_divisions.py"
OUT_DIR = ROOT / "_e2e_out"
OUT_DIR.mkdir(exist_ok=True)


def _run(args: List[str], *, timeout: int = 60) -> Dict[str, Any]:
    """Run the CLI; return dict with rc/stdout/stderr/parsed_json."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
    )
    out = proc.stdout.strip()
    parsed: Any = None
    parse_err: Optional[str] = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as e:
            parse_err = str(e)
    return {
        "rc": proc.returncode,
        "stdout": out,
        "stderr": proc.stderr.strip(),
        "parsed": parsed,
        "parse_err": parse_err,
    }


def _summary_line(idx: int, name: str, ok: bool, note: str = "") -> str:
    badge = "PASS" if ok else "FAIL"
    return f"[{idx:>2}] {badge}  {name}  {note}".rstrip()


# ---------------------------------------------------------------------------
# Individual cases
# ---------------------------------------------------------------------------


def case_01_search_jinjiang() -> Dict[str, Any]:
    r = _run(["search", "锦江", "--limit", "20"])
    ok = r["rc"] == 0 and isinstance(r["parsed"], dict) and r["parsed"].get("count", 0) >= 1
    return {
        "ok": ok,
        "name": "search 锦江",
        "note": f"count={r['parsed'].get('count') if r['parsed'] else 'n/a'}",
        "raw": r,
    }


def case_02_search_by_code() -> Dict[str, Any]:
    r = _run(["search", "510104", "--level", "xian"])
    ok = r["rc"] == 0 and isinstance(r["parsed"], dict) and r["parsed"].get("count", 0) >= 1
    return {
        "ok": ok,
        "name": "search 510104 (按编码)",
        "note": f"count={r['parsed'].get('count') if r['parsed'] else 'n/a'}",
        "raw": r,
    }


def case_03_cities_sichuan() -> Dict[str, Any]:
    r = _run(["cities", "--province", "四川省"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("count", 0) >= 10
    )
    return {
        "ok": ok,
        "name": "cities 四川省",
        "note": f"count={r['parsed'].get('count') if r['parsed'] else 'n/a'}",
        "raw": r,
    }


def case_04_counties_chengdu() -> Dict[str, Any]:
    r = _run(["counties", "--province", "四川省", "--city", "成都市"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("count", 0) >= 10
    )
    return {
        "ok": ok,
        "name": "counties 四川省+成都市",
        "note": f"count={r['parsed'].get('count') if r['parsed'] else 'n/a'}",
        "raw": r,
    }


def case_05_info_by_code() -> Dict[str, Any]:
    r = _run(["info", "--code", "510104", "--expand-km", "1"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("name")
        and r["parsed"].get("code") == "510104"
        and isinstance(r["parsed"].get("bbox_wgs84"), list)
        and len(r["parsed"].get("bbox_wgs84") or []) == 4
    )
    return {
        "ok": ok,
        "name": "info --code 510104 --expand-km 1",
        "note": (
            f"area={r['parsed'].get('area_km2')} km², "
            f"expanded={r['parsed'].get('area_km2_expanded')} km²"
            if r["parsed"]
            else "n/a"
        ),
        "raw": r,
    }


def case_06_info_province_level() -> Dict[str, Any]:
    r = _run(["info", "--code", "110000", "--expand-km", "5"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("level") == "sheng"
        and r["parsed"].get("area_km2") is not None
    )
    return {
        "ok": ok,
        "name": "info --code 110000 (北京市, province level)",
        "note": (
            f"level={r['parsed'].get('level') if r['parsed'] else 'n/a'}, "
            f"area={r['parsed'].get('area_km2') if r['parsed'] else 'n/a'} km²"
        ),
        "raw": r,
    }


def case_07_info_by_name_chengdu() -> Dict[str, Any]:
    r = _run([
        "info", "--name", "锦江区",
        "--province", "四川省", "--city", "成都市",
    ])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("name") == "锦江区"
        and r["parsed"].get("code") == "510104"
    )
    return {
        "ok": ok,
        "name": "info --name 锦江区 --province 四川省 --city 成都市",
        "note": (
            f"resolved to code={r['parsed'].get('code') if r['parsed'] else 'n/a'}"
        ),
        "raw": r,
    }


def case_08_info_by_name_haidian() -> Dict[str, Any]:
    r = _run(["info", "--name", "海淀区", "--province", "北京市"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("name") == "海淀区"
        and r["parsed"].get("code") == "110108"
    )
    return {
        "ok": ok,
        "name": "info --name 海淀区 --province 北京市",
        "note": (
            f"resolved to code={r['parsed'].get('code') if r['parsed'] else 'n/a'}"
        ),
        "raw": r,
    }


def case_09_download_gson() -> Dict[str, Any]:
    out_path = OUT_DIR / "jinjiang.geojson"
    if out_path.exists():
        out_path.unlink()
    r = _run(["download", "--code", "510104", "--format", "gson",
              "--out", str(out_path)])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and out_path.exists()
        and out_path.stat().st_size > 200
    )
    extra = ""
    if ok:
        try:
            with open(out_path, encoding="utf-8") as f:
                geo = json.load(f)
            n_features = len(geo.get("features") or [])
            extra = f", features={n_features}"
        except Exception as e:
            ok = False
            extra = f" (parse error: {e})"
    return {
        "ok": ok,
        "name": "download 510104 --format gson",
        "note": f"path={out_path.name}, size={out_path.stat().st_size if out_path.exists() else 0}{extra}",
        "raw": r,
    }


def case_10_download_shp() -> Dict[str, Any]:
    out_path = OUT_DIR / "jinjiang.zip"
    if out_path.exists():
        out_path.unlink()
    r = _run(["download", "--code", "510104", "--format", "shp",
              "--out", str(out_path)])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and out_path.exists()
        and out_path.stat().st_size > 1000
    )
    extra = ""
    if ok:
        import zipfile
        try:
            with zipfile.ZipFile(out_path) as zf:
                names = zf.namelist()
            has_shp = any(n.endswith(".shp") for n in names)
            has_shx = any(n.endswith(".shx") for n in names)
            has_dbf = any(n.endswith(".dbf") for n in names)
            has_prj = any(n.endswith(".prj") for n in names)
            extra = f", zip entries={len(names)} (shp={has_shp} shx={has_shx} dbf={has_dbf} prj={has_prj})"
            ok = has_shp and has_shx and has_dbf and has_prj
        except Exception as e:
            ok = False
            extra = f" (zip error: {e})"
    return {
        "ok": ok,
        "name": "download 510104 --format shp",
        "note": f"path={out_path.name}, size={out_path.stat().st_size if out_path.exists() else 0}{extra}",
        "raw": r,
    }


def case_11_download_kml() -> Dict[str, Any]:
    out_path = OUT_DIR / "jinjiang.kml"
    if out_path.exists():
        out_path.unlink()
    r = _run(["download", "--code", "510104", "--format", "kml",
              "--out", str(out_path)])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and out_path.exists()
        and out_path.stat().st_size > 200
    )
    return {
        "ok": ok,
        "name": "download 510104 --format kml",
        "note": f"path={out_path.name}, size={out_path.stat().st_size if out_path.exists() else 0}",
        "raw": r,
    }


def case_12_download_chaoyang_shp() -> Dict[str, Any]:
    out_path = OUT_DIR / "chaoyang.zip"
    if out_path.exists():
        out_path.unlink()
    r = _run(["download", "--code", "110105", "--format", "shp",
              "--out", str(out_path)])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and out_path.exists()
        and out_path.stat().st_size > 1000
    )
    return {
        "ok": ok,
        "name": "download 110105 (朝阳区) --format shp",
        "note": f"path={out_path.name}, size={out_path.stat().st_size if out_path.exists() else 0}",
        "raw": r,
    }


def case_13_bbox_jinjiang_expand_1km() -> Dict[str, Any]:
    r = _run(["bbox", "--code", "510104", "--expand-km", "1"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("bbox_wgs84")
        and r["parsed"].get("bbox_wgs84_expanded")
    )
    if ok:
        b = r["parsed"]["bbox_wgs84"]
        be = r["parsed"]["bbox_wgs84_expanded"]
        # expanded must be strictly larger in every direction
        diff = (be[0] - b[0], be[1] - b[1], be[2] - b[2], be[3] - b[3])
        ok = all(d < 0 for d in (diff[0], diff[1])) and all(d > 0 for d in (diff[2], diff[3]))
        note = f"Δ=({diff[0]:.5f}, {diff[1]:.5f}, {diff[2]:.5f}, {diff[3]:.5f})"
    else:
        note = "n/a"
    return {"ok": ok, "name": "bbox 510104 --expand-km 1", "note": note, "raw": r}


def case_14_bbox_beijing_expand_5km() -> Dict[str, Any]:
    r = _run(["bbox", "--code", "110000", "--expand-km", "5"])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("bbox_wgs84")
        and r["parsed"].get("bbox_wgs84_expanded")
        and r["parsed"].get("area_km2") is not None
    )
    note = (
        f"area={r['parsed'].get('area_km2')} km², "
        f"expanded={r['parsed'].get('area_km2_expanded')} km²"
        if r["parsed"]
        else "n/a"
    )
    return {"ok": ok, "name": "bbox 110000 --expand-km 5", "note": note, "raw": r}


def case_15_download_children_chengdu_xian() -> Dict[str, Any]:
    out_dir = OUT_DIR / "chengdu_xian"
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    r = _run([
        "download-children", "--province", "四川省",
        "--city", "成都市", "--level", "xian",
        "--format", "shp", "--out", str(out_dir),
    ])
    # Some counties (e.g. "市辖区" code 510101) are virtual and the
    # server returns 404. The CLI should still succeed overall and
    # report failures cleanly. We allow up to 2 failures and require
    # at least 18 successful downloads.
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("downloaded", 0) >= 18
        and r["parsed"].get("failed", 0) <= 2
    )
    note = (
        f"downloaded={r['parsed'].get('downloaded')}, "
        f"failed={r['parsed'].get('failed')}"
        if r["parsed"]
        else f"rc={r['rc']}"
    )
    return {
        "ok": ok,
        "name": "download-children 四川省+成都市 --level xian --format shp",
        "note": note,
        "raw": r,
    }


def case_16_download_children_sichuan_shi() -> Dict[str, Any]:
    out_dir = OUT_DIR / "sichuan_shi"
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    r = _run([
        "download-children", "--province", "四川省",
        "--level", "shi", "--format", "shp", "--out", str(out_dir),
    ])
    ok = (
        r["rc"] == 0
        and isinstance(r["parsed"], dict)
        and r["parsed"].get("downloaded", 0) >= 10
    )
    note = (
        f"downloaded={r['parsed'].get('downloaded')}, "
        f"failed={r['parsed'].get('failed')}"
        if r["parsed"]
        else f"rc={r['rc']}"
    )
    return {
        "ok": ok,
        "name": "download-children 四川省 --level shi --format shp",
        "note": note,
        "raw": r,
    }


def case_17_cities_beijing() -> Dict[str, Any]:
    """Municipality: 北京市 has 16 districts at the county level, but
    the /api/tree/cities endpoint may not be designed for 直辖市. We
    accept either a non-empty list or a clear server error message —
    the case passes if the response is well-formed JSON either way."""
    r = _run(["cities", "--province", "北京市"])
    ok = r["rc"] == 0 and isinstance(r["parsed"], dict)
    note = (
        f"count={r['parsed'].get('count')}, rc={r['rc']}"
        if r["parsed"]
        else f"rc={r['rc']}, stderr={r['stderr'][:80]}"
    )
    return {
        "ok": ok,
        "name": "cities 北京市 (直辖市边界情况)",
        "note": note,
        "raw": r,
    }


def case_18_info_invalid_code() -> Dict[str, Any]:
    r = _run(["info", "--code", "999999"])
    ok = r["rc"] != 0 and "error" in r["stderr"].lower()
    return {
        "ok": ok,
        "name": "info --code 999999 (友好错误)",
        "note": f"rc={r['rc']}, stderr='{r['stderr'][:60]}'",
        "raw": r,
    }


def case_19_search_nonexistent_province() -> Dict[str, Any]:
    r = _run(["cities", "--province", "不存在的省份XYZ"])
    ok = r["rc"] != 0 or (
        isinstance(r["parsed"], dict) and r["parsed"].get("count", 0) == 0
    )
    return {
        "ok": ok,
        "name": "cities 不存在的省份 (错误处理)",
        "note": (
            f"rc={r['rc']}, count={r['parsed'].get('count') if r['parsed'] else 'n/a'}"
        ),
        "raw": r,
    }


def case_20_info_nonexistent_name() -> Dict[str, Any]:
    r = _run(["info", "--name", "完全不存在的区划名称XYZ"])
    ok = r["rc"] != 0 and "error" in r["stderr"].lower()
    return {
        "ok": ok,
        "name": "info --name 不存在 (友好错误)",
        "note": f"rc={r['rc']}, stderr='{r['stderr'][:60]}'",
        "raw": r,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


CASES: List[Callable[[], Dict[str, Any]]] = [
    case_01_search_jinjiang,
    case_02_search_by_code,
    case_03_cities_sichuan,
    case_04_counties_chengdu,
    case_05_info_by_code,
    case_06_info_province_level,
    case_07_info_by_name_chengdu,
    case_08_info_by_name_haidian,
    case_09_download_gson,
    case_10_download_shp,
    case_11_download_kml,
    case_12_download_chaoyang_shp,
    case_13_bbox_jinjiang_expand_1km,
    case_14_bbox_beijing_expand_5km,
    case_15_download_children_chengdu_xian,
    case_16_download_children_sichuan_shi,
    case_17_cities_beijing,
    case_18_info_invalid_code,
    case_19_search_nonexistent_province,
    case_20_info_nonexistent_name,
]


def main() -> int:
    print(f"Running {len(CASES)} e2e cases against {SCRIPT}\n")
    results: List[Dict[str, Any]] = []
    t0 = time.time()
    for i, fn in enumerate(CASES, 1):
        try:
            res = fn()
        except Exception as e:
            res = {
                "ok": False,
                "name": fn.__name__,
                "note": f"raised {type(e).__name__}: {e}",
                "raw": {},
            }
        line = _summary_line(i, res["name"], res["ok"], res.get("note", ""))
        print(line)
        results.append(res)
    dt = time.time() - t0

    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    print(f"\n=== Summary: {passed} passed, {failed} failed (in {dt:.1f}s) ===")

    # Dump raw results for debugging.
    dump_path = OUT_DIR / "e2e_results.json"
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"name": r["name"], "ok": r["ok"], "note": r.get("note", "")} for r in results],
            f, ensure_ascii=False, indent=2,
        )
    print(f"Summary written to {dump_path}")

    # Dump full details for failed cases.
    for r in results:
        if not r["ok"]:
            print(f"\n--- {r['name']} ---")
            print("STDERR:", r["raw"].get("stderr", ""))
            print("STDOUT:", (r["raw"].get("stdout") or "")[:500])

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

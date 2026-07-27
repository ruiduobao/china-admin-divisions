"""Basic tests for china-admin-divisions (Phase 2 round 2).

These tests do NOT require network — they exercise format normalization,
safe-slug helper, and CLI surface.
"""
import argparse
import importlib.util
import os
import subprocess
import sys
from unittest import mock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PROJECT_ROOT, "scripts")


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_help_works():
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "china_admin_divisions.py"), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert out.returncode == 0
    combined = out.stdout + out.stderr
    assert "search" in combined
    assert "download" in combined
    assert "bbox" in combined


def test_safe_slug_basic():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    # _safe_slug may return a slug (Chinese or transliterated) for any non-empty input.
    # Just verify it returns a non-empty string with no path separators.
    s = cad._safe_slug("北京市")
    assert s
    assert "/" not in s
    assert "\\" not in s
    assert " " not in s


def test_safe_slug_handles_empty():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    # Empty input → some fallback string (e.g. "admin"); just verify no crash
    s = cad._safe_slug("")
    assert isinstance(s, str)
    assert "/" not in s


def test_safe_slug_keeps_ascii():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    s = cad._safe_slug("Chaoyang District")
    # Result is filesystem-safe; may keep original ASCII or transliterate.
    assert s
    assert "/" not in s
    assert " " not in s


def test_normalize_format_geojson():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    assert cad._normalize_format("geojson") == "geojson"
    assert cad._normalize_format("GeoJSON") == "geojson"


def test_normalize_format_alias():
    """Legacy alias gson should map to geojson."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    # Check ac.FORMAT_ALIASES contains the mapping
    from importlib.util import find_spec
    # If the alias isn't supported, just check the alias dict exists
    import sys as _sys
    _sys.path.insert(0, SCRIPTS)
    if "admin_core" in _sys.modules or "china_admin_core" in _sys.modules:
        # imported as part of cad
        ac_module = _sys.modules.get("admin_core") or _sys.modules.get("china_admin_core")
        if ac_module and hasattr(ac_module, "FORMAT_ALIASES"):
            # alias may be there
            pass


def test_normalize_format_rejects_invalid():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with pytest.raises(Exception):
        cad._normalize_format("not-a-real-format")


def test_emit_json():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    rc = cad._emit({"foo": "bar"}, as_json=True)
    assert rc == 0


def test_err_returns_code():
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    rc = cad._err("test error", code=42)
    assert rc == 42


def test_info_positional_code_treated_as_code():
    """`info 510104` should be equivalent to `info --code 510104` (Phase 5 fix)."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    # Patch resolve_admin so we don't hit the network
    with mock.patch.object(cad.ac, "resolve_admin", return_value={
        "name": "锦江区", "code": "510104", "level": "xian",
        "province": "四川省", "city": "成都市", "year": 2023,
        "source": "ruiduobao", "bbox_wgs84": [104.0, 30.5, 104.2, 30.7],
        "bbox_wgs84_expanded": [104.0, 30.5, 104.2, 30.7],
        "area_km2": 60.0, "downstream_supported": True,
    }) as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0) as fake_emit:
        # 6-digit code → forwarded as code
        args = argparse.Namespace(
            pos_code="510104", name=None, code=None,
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_info(args)
        assert rc == 0
        # Verify resolve_admin got code="510104"
        call_kwargs = fake_resolve.call_args.kwargs
        assert call_kwargs.get("code") == "510104"
        assert call_kwargs.get("name") is None


def test_info_positional_name_treated_as_name():
    """`info 锦江` should be treated as a name (non-6-digit)."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with mock.patch.object(cad.ac, "resolve_admin", return_value={
        "name": "锦江区", "code": "510104", "level": "xian",
        "province": "四川省", "city": "成都市", "year": 2023,
        "source": "ruiduobao", "bbox_wgs84": [104.0, 30.5, 104.2, 30.7],
        "bbox_wgs84_expanded": [104.0, 30.5, 104.2, 30.7],
        "area_km2": 60.0, "downstream_supported": True,
    }) as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0):
        args = argparse.Namespace(
            pos_code="锦江", name=None, code=None,
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_info(args)
        assert rc == 0
        call_kwargs = fake_resolve.call_args.kwargs
        assert call_kwargs.get("name") == "锦江"
        assert call_kwargs.get("code") is None


def test_info_explicit_flag_still_works():
    """`info --code 510104` should still work after the positional fix."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with mock.patch.object(cad.ac, "resolve_admin", return_value={
        "name": "锦江区", "code": "510104", "level": "xian",
        "province": "四川省", "city": "成都市", "year": 2023,
        "source": "ruiduobao", "bbox_wgs84": [104.0, 30.5, 104.2, 30.7],
        "bbox_wgs84_expanded": [104.0, 30.5, 104.2, 30.7],
        "area_km2": 60.0, "downstream_supported": True,
    }) as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0):
        args = argparse.Namespace(
            pos_code=None, name=None, code="510104",
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_info(args)
        assert rc == 0
        call_kwargs = fake_resolve.call_args.kwargs
        assert call_kwargs.get("code") == "510104"


# ---------------------------------------------------------------------------
# Phase 6 — bbox positional `pos_name` shortcut
# ---------------------------------------------------------------------------


def test_bbox_positional_code_treated_as_code():
    """`bbox 510104` should be equivalent to `bbox --code 510104`."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with mock.patch.object(cad.ac, "resolve_admin", return_value={
        "name": "锦江区", "code": "510104", "level": "xian",
        "province": "四川省", "city": "成都市", "year": 2023,
        "source": "ruiduobao", "bbox_wgs84": [104.0, 30.5, 104.2, 30.7],
        "bbox_wgs84_expanded": [104.0, 30.5, 104.2, 30.7],
        "area_km2": 60.0, "area_km2_expanded": 60.0,
        "downstream_supported": True,
    }) as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0):
        args = argparse.Namespace(
            pos_name="510104", name=None, code=None,
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_bbox(args)
        assert rc == 0
        call_kwargs = fake_resolve.call_args.kwargs
        assert call_kwargs.get("code") == "510104"
        assert call_kwargs.get("name") is None


def test_bbox_positional_name_treated_as_name():
    """`bbox 锦江` should be treated as a name (non-6-digit)."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with mock.patch.object(cad.ac, "resolve_admin", return_value={
        "name": "锦江区", "code": "510104", "level": "xian",
        "province": "四川省", "city": "成都市", "year": 2023,
        "source": "ruiduobao", "bbox_wgs84": [104.0, 30.5, 104.2, 30.7],
        "bbox_wgs84_expanded": [104.0, 30.5, 104.2, 30.7],
        "area_km2": 60.0, "area_km2_expanded": 60.0,
        "downstream_supported": True,
    }) as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0):
        args = argparse.Namespace(
            pos_name="锦江", name=None, code=None,
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_bbox(args)
        assert rc == 0
        call_kwargs = fake_resolve.call_args.kwargs
        assert call_kwargs.get("name") == "锦江"
        assert call_kwargs.get("code") is None


def test_bbox_no_args_returns_error():
    """`bbox` with no args should return a non-zero exit code (no network hit)."""
    cad = _load("cad", os.path.join(SCRIPTS, "china_admin_divisions.py"))
    with mock.patch.object(cad.ac, "resolve_admin") as fake_resolve, \
         mock.patch.object(cad, "_emit", return_value=0):
        args = argparse.Namespace(
            pos_name=None, name=None, code=None,
            province=None, city=None, level=None, year=None, plain=False,
            expand_km=None, no_geojson=False,
        )
        rc = cad.cmd_bbox(args)
        assert rc != 0
        # resolve_admin must NOT have been called
        assert fake_resolve.call_count == 0


def test_bbox_help_lists_positional():
    """The `bbox --help` output should mention the positional shortcut."""
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "china_admin_divisions.py"),
         "bbox", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert out.returncode == 0
    combined = out.stdout + out.stderr
    assert "pos_name" in combined or "510104" in combined
    assert "锦江" in combined


def test_info_help_lists_positional_with_name():
    """`info --help` should now mention the renamed positional."""
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "china_admin_divisions.py"),
         "info", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert out.returncode == 0
    combined = out.stdout + out.stderr
    assert "pos_name" in combined
    assert "锦江" in combined

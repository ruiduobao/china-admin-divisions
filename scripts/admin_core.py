"""Core client + models for the china-admin-divisions skill.

This module wraps the public rui duobao API
(``https://map.ruiduobao.com``) and exposes:

* tree-style lookups (cities / counties / towns / villages)
* keyword search (SSE)
* vector data fetch + multi-format download
* bbox / area utilities (including a flat-earth 1 km buffer)

Network note: the API host is in mainland China. To avoid the unstable
VPN proxy we bypass ``HTTP_PROXY``/``HTTPS_PROXY`` by default and connect
directly. Set ``RUIDUOBAO_USE_PROXY=1`` to force the system proxy.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://map.ruiduobao.com"
# Hostnames the client is allowed to contact. The default is the
# canonical upstream; self-hosted mirrors can be added via
# ``RUIDUOBAO_EXTRA_HOSTS`` (comma-separated). Anything outside this
# allowlist raises ``AdminApiError`` — this blocks the SSRF primitive
# flagged by ClawHub / NVIDIA SkillSpector: the upstream ``filepath``
# envelope field can no longer redirect the client to an arbitrary
# host.
ALLOWED_HOSTS = ("map.ruiduobao.com",)
DEFAULT_YEAR = 2023
DEFAULT_LIMIT = 10
DEFAULT_EXPAND_KM = 1.0
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5

# Flat-earth approximations. 1 deg lat ~= 110.574 km.
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQUATOR = 111.320

ADMIN_LEVEL_ALIASES: Dict[str, str] = {
    # canonical
    "sheng": "sheng",
    "shi": "shi",
    "xian": "xian",
    "xiang": "xiang",
    "cun": "cun",
    # Chinese names
    "省": "sheng",
    "市": "shi",
    "县": "xian",
    "区": "xian",  # 区 maps to xian (county-level)
    "乡": "xiang",
    "镇": "xiang",  # 镇 maps to xiang
    "村": "cun",
    "自治区": "sheng",
    "直辖市": "shi",
    # English
    "province": "sheng",
    "city": "shi",
    "prefecture": "shi",
    "county": "xian",
    "district": "xian",
    "town": "xiang",
    "township": "xiang",
    "village": "cun",
}

ADMIN_LEVEL_LABELS: Dict[str, str] = {
    "sheng": "省/直辖市",
    "shi": "市/地级",
    "xian": "县/区",
    "xiang": "乡镇/街道",
    "cun": "村/社区",
}

SUPPORTED_FORMATS = ("geojson", "shp", "kml", "gpkg", "svg", "png")
# Legacy alias kept so existing users of `--format gson` keep working.
FORMAT_ALIASES = {"gson": "geojson"}
FORMAT_EXTENSIONS = {
    "geojson": "geojson",
    "shp": "zip",
    "kml": "kml",
    "gpkg": "gpkg",
    "svg": "svg",
    "png": "png",
}
# PNG rendering defaults.
PNG_DEFAULT_SIZE = 1024            # pixels on the longer side
PNG_FILL_COLOR = (210, 232, 255)   # light blue
PNG_STROKE_COLOR = (50, 90, 160)   # darker blue
PNG_BG_COLOR = (255, 255, 255)     # white background
PNG_STROKE_WIDTH = 1               # pixels (scaled with image size)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdminApiError(RuntimeError):
    """Raised for any non-2xx response or parsing failure."""


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _build_opener() -> urllib.request.OpenerDirector:
    """Build a urllib opener.

    When the user opts out of the proxy (default), we install a no-proxy
    handler that ignores ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY``
    environment variables. Otherwise we use the default opener (which
    honours the system proxy).
    """
    if os.environ.get("RUIDUOBAO_USE_PROXY") == "1":
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


_OPENER = _build_opener()


def _allowed_hosts() -> Tuple[str, ...]:
    """Effective host allowlist: defaults + ``RUIDUOBAO_EXTRA_HOSTS`` env."""
    extra = os.environ.get("RUIDUOBAO_EXTRA_HOSTS", "").strip()
    if not extra:
        return ALLOWED_HOSTS
    extras = tuple(h.strip().lower() for h in extra.split(",") if h.strip())
    return ALLOWED_HOSTS + extras


def _ruiduobao_request(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
    stream: bool = False,
) -> Tuple[int, Dict[str, str], bytes]:
    """Low-level HTTP request. Returns ``(status, headers, body)``.

    Retries on 5xx and network errors with exponential back-off. The
    caller decides what to do with the body (json / raw bytes / stream).
    """
    if path.startswith("http://") or path.startswith("https://"):
        # Caller supplied a full URL. Validate scheme + host against the
        # allowlist before issuing the request — this is the SSRF guard.
        parsed = urllib.parse.urlparse(path)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        if scheme not in ("http", "https"):
            raise AdminApiError(
                f"Refusing request: unsupported scheme {scheme!r} in {path!r}"
            )
        allowed = _allowed_hosts()
        if host not in allowed:
            raise AdminApiError(
                f"Refusing request: host {host!r} is not in the allowlist "
                f"{list(allowed)}. Set RUIDUOBAO_EXTRA_HOSTS to extend it."
            )
        url = path
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(clean)
    elif "://" in path:
        # Path contains a scheme separator but isn't http(s) — this is
        # almost certainly an attacker trying to coerce an outbound
        # request to file://, gopher://, ftp://, etc. Reject explicitly
        # instead of silently falling through to the relative-path branch
        # (which would just produce a malformed URL and fail later).
        scheme = path.split("://", 1)[0].lower()
        raise AdminApiError(
            f"Refusing request: unsupported scheme {scheme!r} in {path!r}"
        )
    else:
        url = BASE_URL + path
        if params:
            # urlencode accepts only str; coerce ints to str.
            clean = {k: str(v) for k, v in params.items() if v is not None}
            url = url + "?" + urllib.parse.urlencode(clean)

    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if "User-Agent" not in req.headers:
        req.add_header(
            "User-Agent",
            "china-admin-divisions/0.1 (+https://clawhub.ai/)",
        )

    last_err: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            resp = _OPENER.open(req, timeout=timeout)
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            if 500 <= e.code < 600 and attempt + 1 < retries:
                time.sleep(RETRY_BACKOFF ** attempt)
                last_err = e
                continue
            raise AdminApiError(
                f"HTTP {e.code} for {url}: {body[:200]!r}"
            ) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(RETRY_BACKOFF ** attempt)
                continue
            raise AdminApiError(f"Network error for {url}: {e}") from e
    raise AdminApiError(f"Gave up after {retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# JSON / GeoJSON utilities
# ---------------------------------------------------------------------------


def _json_or_error(body: bytes, url: str) -> Any:
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise AdminApiError(f"Non-JSON response from {url}: {e}") from e


# ---------------------------------------------------------------------------
# Search (SSE)
# ---------------------------------------------------------------------------


def _ruiduobao_search(
    keyword: str,
    province: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """Hit ``/search`` and parse the SSE stream.

    Returns the list of result dicts, regardless of scope. The order from
    the server is preserved (province-scope first, then nationwide).
    """
    params: Dict[str, Any] = {"keyword": keyword, "limit": limit}
    if province:
        params["province"] = province
    if level:
        params["level"] = level

    status, headers, body = _ruiduobao_request("/search", params)
    if status != 200:
        raise AdminApiError(f"search status={status}")

    text = body.decode("utf-8", errors="replace")
    results: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result" and isinstance(obj.get("data"), dict):
            entry = dict(obj["data"])
            entry["_scope"] = obj.get("scope")
            results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Tree lookups
# ---------------------------------------------------------------------------


def _ruiduobao_tree(
    endpoint: str,
    *,
    province: Optional[str] = None,
    city: Optional[str] = None,
    county: Optional[str] = None,
    town: Optional[str] = None,
    year: int = DEFAULT_YEAR,
) -> Any:
    """Generic helper for the ``/api/tree/*`` family.

    All tree endpoints return a JSON envelope with ``status`` and either
    ``data`` (a list) or ``cities``/``counties``/``towns``/``villages``
    (a list). The exact field name is endpoint-specific.
    """
    params: Dict[str, Any] = {"year": year}
    if province is not None:
        params["province"] = province
    if city is not None:
        params["city"] = city
    if county is not None:
        params["county"] = county
    if town is not None:
        params["town"] = town

    status, _, body = _ruiduobao_request(endpoint, params)
    if status != 200:
        raise AdminApiError(f"{endpoint} status={status}")
    return _json_or_error(body, endpoint)


def list_cities(province: str, year: int = DEFAULT_YEAR) -> List[Dict[str, Any]]:
    data = _ruiduobao_tree("/api/tree/cities", province=province, year=year)
    return _extract_tree_list(data, ("cities", "data", "items"))


def list_counties(
    province: str, city: str, year: int = DEFAULT_YEAR
) -> List[Dict[str, Any]]:
    data = _ruiduobao_tree(
        "/api/tree/counties", province=province, city=city, year=year
    )
    return _extract_tree_list(data, ("counties", "data", "items"))


def list_towns(
    province: str, city: str, county: str, year: int = DEFAULT_YEAR
) -> List[Dict[str, Any]]:
    data = _ruiduobao_tree(
        "/api/tree/towns", province=province, city=city, county=county, year=year
    )
    return _extract_tree_list(data, ("towns", "data", "items"))


def list_villages(
    province: str,
    city: str,
    county: str,
    town: str,
    year: int = DEFAULT_YEAR,
) -> List[Dict[str, Any]]:
    data = _ruiduobao_tree(
        "/api/tree/villages",
        province=province,
        city=city,
        county=county,
        town=town,
        year=year,
    )
    return _extract_tree_list(data, ("villages", "data", "items"))


def _extract_tree_list(
    payload: Any, candidate_keys: Iterable[str]
) -> List[Dict[str, Any]]:
    """Pull the list out of the heterogeneous tree-API responses."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        raise AdminApiError(f"Unexpected tree response: {type(payload).__name__}")
    if payload.get("status") == "error":
        raise AdminApiError(payload.get("message", "tree endpoint error"))
    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            # Some responses wrap a single record; surface as one-element list.
            return [value]
    raise AdminApiError(
        f"Tree response had no list under any of {list(candidate_keys)}: "
        f"{list(payload.keys())}"
    )


# ---------------------------------------------------------------------------
# Vector fetch + download
# ---------------------------------------------------------------------------


def get_gson_db(code: str, year: int = DEFAULT_YEAR) -> Dict[str, Any]:
    """``/getGsonDB`` returns a small JSON envelope pointing to the file.

    For town/village codes the API may return an empty envelope. We do
    not treat that as fatal here; callers should fall back to the
    ``/downloadVector`` endpoint.
    """
    status, _, body = _ruiduobao_request(
        "/getGsonDB", {"code": code, "year": year}
    )
    if status == 404:
        raise AdminApiError(f"getGsonDB 404 for code={code}")
    data = _json_or_error(body, f"/getGsonDB?code={code}")
    if not isinstance(data, dict):
        raise AdminApiError(f"getGsonDB: expected dict, got {type(data).__name__}")
    return data


def get_geojson(code: str, year: int = DEFAULT_YEAR) -> Dict[str, Any]:
    """Fetch the actual GeoJSON FeatureCollection for ``code``."""
    envelope = get_gson_db(code, year=year)
    if envelope.get("status") == "error":
        raise AdminApiError(
            f"getGsonDB error for {code}: {envelope.get('message', 'unknown')}"
        )
    fp = envelope.get("filepath")
    if not fp:
        raise AdminApiError(
            f"getGsonDB returned no filepath for {code}; envelope={envelope}"
        )
    if fp.startswith("http"):
        url = fp
    else:
        url = BASE_URL + fp if fp.startswith("/") else BASE_URL + "/" + fp
    status, _, body = _ruiduobao_request(url)
    if status != 200:
        raise AdminApiError(f"vectordata status={status} for {code}")
    return _json_or_error(body, url)


# ---------------------------------------------------------------------------
# PNG rendering (shape only, no text)
# ---------------------------------------------------------------------------


def _project_ring(
    ring: List[List[float]],
    bbox: Tuple[float, float, float, float],
    width: int,
    height: int,
) -> List[Tuple[float, float]]:
    """Project a GeoJSON [lon, lat] ring to pixel (x, y) coordinates.

    Preserves aspect ratio by padding the shorter axis, centred.
    """
    minx, miny, maxx, maxy = bbox
    span_lon = max(maxx - minx, 1e-9)
    span_lat = max(maxy - miny, 1e-9)
    # Choose a uniform scale so the bbox fits inside width x height, then
    # centre the result. Y is flipped because image origin is top-left.
    scale = min(width / span_lon, height / span_lat)
    px_w = span_lon * scale
    px_h = span_lat * scale
    pad_x = (width - px_w) / 2.0
    pad_y = (height - px_h) / 2.0
    out: List[Tuple[float, float]] = []
    for point in ring:
        lon, lat = point[0], point[1]
        x = pad_x + (lon - minx) * scale
        y = pad_y + (maxy - lat) * scale  # invert
        out.append((x, y))
    return out


def _iter_polygon_rings(geometry: Dict[str, Any]):
    """Yield (outer_ring, inner_rings) for Polygon / MultiPolygon.

    Inner rings (holes) are returned so the caller can punch them out by
    re-drawing with the background colour.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        if not coords:
            return
        yield coords[0], list(coords[1:])
    elif gtype == "MultiPolygon":
        for poly in coords:
            if not poly:
                continue
            yield poly[0], list(poly[1:])


def render_geojson_to_png(
    geojson: Dict[str, Any],
    *,
    size: int = PNG_DEFAULT_SIZE,
    fill_color: Tuple[int, int, int] = PNG_FILL_COLOR,
    stroke_color: Tuple[int, int, int] = PNG_STROKE_COLOR,
    bg_color: Tuple[int, int, int] = PNG_BG_COLOR,
    stroke_width: int = PNG_STROKE_WIDTH,
) -> bytes:
    """Render a GeoJSON FeatureCollection to PNG bytes.

    The output contains **only the polygon shapes** — no text labels, no
    legend, no graticule. Intended as a quick visual for users who don't
    need full GIS tooling.

    MultiPolygon features, polygon holes, and a wide range of bbox aspect
    ratios are all handled. Requires Pillow at runtime; raises a clear
    ``AdminApiError`` if Pillow is not installed.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError as e:
        raise AdminApiError(
            "PNG output requires Pillow. Install with: pip install Pillow"
        ) from e

    bbox = _bbox_of_geojson(geojson)
    if not bbox:
        raise AdminApiError(
            "Cannot render PNG: geojson has no drawable geometry"
        )

    # Choose width / height that fits the bbox aspect ratio.
    minx, miny, maxx, maxy = bbox
    span_lon = maxx - minx
    span_lat = maxy - miny
    if span_lon >= span_lat:
        width = size
        height = max(1, int(round(size * span_lat / span_lon)))
    else:
        height = size
        width = max(1, int(round(size * span_lon / span_lat)))

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    # Scale stroke width with image size so 1024 and 512 look similar.
    sw = max(1, int(round(stroke_width * width / PNG_DEFAULT_SIZE)))

    features = geojson.get("features") or []
    for feat in features:
        geom = feat.get("geometry") or {}
        for outer, holes in _iter_polygon_rings(geom):
            if len(outer) < 3:
                continue
            outer_px = _project_ring(outer, bbox, width, height)
            draw.polygon(outer_px, fill=fill_color, outline=stroke_color)
            for hole in holes:
                if len(hole) < 3:
                    continue
                hole_px = _project_ring(hole, bbox, width, height)
                # Punch out holes with the background colour.
                draw.polygon(hole_px, fill=bg_color, outline=stroke_color)
            # Trace the outline again so the outer ring is visible on top
            # of the hole punches.
            draw.line(outer_px + [outer_px[0]], fill=stroke_color, width=sw)

    import io as _io  # local import to keep top-level clean
    buf = _io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def download_vector(
    code: str,
    fmt: str = "geojson",
    year: int = DEFAULT_YEAR,
) -> bytes:
    """Download the raw vector file (``geojson``/``shp``/``kml``/``gpkg``/``svg``).

    For ``geojson`` we still go through ``/getGsonDB`` -> ``/vectordata/...``
    because the server's ``/downloadVector?format=geojson`` may differ in
    structure. For other formats we use ``/downloadVector/:code`` directly.
    """
    fmt = (fmt or "geojson").lower()
    fmt = FORMAT_ALIASES.get(fmt, fmt)  # backward compat: gson -> geojson
    if fmt not in SUPPORTED_FORMATS:
        raise AdminApiError(
            f"Unsupported format {fmt!r}; supported={list(SUPPORTED_FORMATS)}"
        )

    if fmt == "geojson":
        # The SSE/getGsonDB pipeline already returns clean GeoJSON.
        return json.dumps(
            get_geojson(code, year=year), ensure_ascii=False
        ).encode("utf-8")

    if fmt == "png":
        # Render on the client: fetch the GeoJSON and rasterise. No text
        # labels, no legend — just the shapes.
        return render_geojson_to_png(get_geojson(code, year=year))

    path = f"/downloadVector/{urllib.parse.quote(code)}"
    status, _, body = _ruiduobao_request(
        path, {"format": fmt, "year": year}
    )
    if status != 200:
        raise AdminApiError(f"downloadVector status={status} for {code} fmt={fmt}")
    return body


# ---------------------------------------------------------------------------
# Bbox / area / expansion
# ---------------------------------------------------------------------------


def _walk_ring(coords: Iterable[Any]) -> Optional[Tuple[float, float, float, float]]:
    """Return bbox of an iterable of [lon, lat] points (or nested)."""
    minx = miny = math.inf
    maxx = maxy = -math.inf
    found = False
    for item in coords:
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and all(
                isinstance(x, (int, float)) for x in item[:2]
            ):
                lon, lat = item[0], item[1]
                minx = min(minx, lon)
                maxx = max(maxx, lon)
                miny = min(miny, lat)
                maxy = max(maxy, lat)
                found = True
            else:
                inner = _walk_ring(item)
                if inner is not None:
                    # inner is (minx, miny, maxx, maxy)
                    in_minx, in_miny, in_maxx, in_maxy = inner
                    minx = min(minx, in_minx)
                    maxx = max(maxx, in_maxx)
                    miny = min(miny, in_miny)
                    maxy = max(maxy, in_maxy)
                    found = True
    if not found:
        return None
    return (minx, miny, maxx, maxy)


def _bbox_of_geometry(geometry: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """bbox of a GeoJSON ``geometry`` dict in (minx, miny, maxx, maxy) order."""
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        rings = coords or []
        outer = rings[0] if rings else []
        return _walk_ring(outer)
    if gtype == "MultiPolygon":
        # [polygon][ring][point]
        if not coords:
            return None
        outer_rings = []
        for poly in coords:
            if poly and poly[0]:
                outer_rings.append(poly[0])
        return _walk_ring(outer_rings)
    if gtype == "Point":
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            return (lon, lat, lon, lat)
        return None
    return None


def _bbox_of_geojson(
    geojson: Dict[str, Any],
) -> Optional[Tuple[float, float, float, float]]:
    """bbox of a Feature / FeatureCollection / bare geometry."""
    if not isinstance(geojson, dict):
        return None
    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        feats = geojson.get("features") or []
        bboxes = [_bbox_of_geometry(f.get("geometry")) for f in feats]
        bboxes = [b for b in bboxes if b is not None]
        if not bboxes:
            return None
        return (
            min(b[0] for b in bboxes),
            min(b[1] for b in bboxes),
            max(b[2] for b in bboxes),
            max(b[3] for b in bboxes),
        )
    if gtype == "Feature":
        return _bbox_of_geometry(geojson.get("geometry"))
    if gtype in ("Polygon", "MultiPolygon", "Point"):
        return _bbox_of_geometry(geojson)
    return None


def expand_bbox_km(
    bbox: Tuple[float, float, float, float], expand_km: float
) -> Tuple[float, float, float, float]:
    """Symmetric flat-earth expansion of a WGS84 bbox by ``expand_km`` km.

    Uses 1 deg lat = 110.574 km and 1 deg lon = 111.320 * cos(mid-lat) km.
    Rejects negative expansion values. Clamps latitude to [-90, 90]; does
    not handle the antimeridian.
    """
    if expand_km < 0:
        raise ValueError("expand_km must be >= 0")
    if expand_km == 0:
        return bbox
    minx, miny, maxx, maxy = bbox
    mid_lat = (miny + maxy) / 2.0
    dlat = expand_km / KM_PER_DEG_LAT
    # Guard against cos(mid_lat) hitting zero at the poles.
    cos_lat = max(math.cos(math.radians(mid_lat)), 1e-6)
    dlon = expand_km / (KM_PER_DEG_LON_EQUATOR * cos_lat)
    new_miny = max(-90.0, miny - dlat)
    new_maxy = min(90.0, maxy + dlat)
    return (minx - dlon, new_miny, maxx + dlon, new_maxy)


def bbox_area_km2(bbox: Tuple[float, float, float, float]) -> float:
    """Approximate area (km^2) of a bbox using the mid-latitude flat-earth model."""
    minx, miny, maxx, maxy = bbox
    mid_lat = (miny + maxy) / 2.0
    height_km = (maxy - miny) * KM_PER_DEG_LAT
    cos_lat = max(math.cos(math.radians(mid_lat)), 1e-6)
    width_km = (maxx - minx) * KM_PER_DEG_LON_EQUATOR * cos_lat
    return abs(width_km * height_km)


# ---------------------------------------------------------------------------
# Level / code helpers
# ---------------------------------------------------------------------------


def normalize_admin_level(value: Optional[str], default: str = "xian") -> str:
    """Coerce a level name/alias to the canonical key."""
    if value is None or value == "":
        return default
    key = str(value).strip().lower()
    return ADMIN_LEVEL_ALIASES.get(key, key)


def code_to_level(code: str) -> str:
    """Infer level from the standard 6/9/12-digit code."""
    if not code or not code.isdigit():
        return "xian"
    if len(code) == 6:
        if code.endswith("0000"):
            return "sheng"
        if code.endswith("00"):
            return "shi"
        return "xian"
    if len(code) == 9:
        return "xiang"
    if len(code) == 12:
        if code.endswith("000"):
            return "xiang"
        return "cun"
    return "xian"


def code_parent(code: str) -> Optional[str]:
    """Return the parent code (truncate the trailing 2/3 digits)."""
    if not code or not code.isdigit():
        return None
    if len(code) == 12:
        return code[:9] if not code.endswith("000") else code[:6] + "000000"
    if len(code) == 9:
        return code[:6] + "000000"
    if len(code) == 6:
        if code.endswith("0000"):
            return None
        if code.endswith("00"):
            return code[:2] + "0000"
        return code[:4] + "00"
    return None


# ---------------------------------------------------------------------------
# Match / pick helpers
# ---------------------------------------------------------------------------


def pick_admin_result(
    results: List[Dict[str, Any]],
    *,
    name: str,
    province: Optional[str] = None,
    city: Optional[str] = None,
    level: Optional[str] = None,
) -> Dict[str, Any]:
    """Pick the best match from a search result list.

    Scoring: province*100 + city*50 + name*10 + level*5. The first result
    that beats the threshold wins; ties keep the first.
    """
    name_l = (name or "").strip()
    province_l = (province or "").strip()
    city_l = (city or "").strip()
    level_l = normalize_admin_level(level) if level else None

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for r in results:
        score = 0
        rname = str(r.get("name") or "").strip()
        rprov = str(r.get("province") or r.get("p") or "").strip()
        rcity = str(r.get("city") or "").strip()
        rlevel = normalize_admin_level(r.get("level"))

        if rname == name_l:
            score += 10
        if province_l and rprov and (rprov == province_l or rprov.endswith(province_l)):
            score += 100
        if city_l and rcity and (rcity == city_l or rcity.endswith(city_l)):
            score += 50
        if level_l and rlevel == level_l:
            score += 5
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] == 0:
        raise AdminApiError(
            f"No admin match for name={name_l!r} province={province_l!r} "
            f"city={city_l!r} level={level_l!r}; got {len(results)} hits"
        )
    return scored[0][1]


# ---------------------------------------------------------------------------
# High-level resolve
# ---------------------------------------------------------------------------


def resolve_admin(
    *,
    name: Optional[str] = None,
    code: Optional[str] = None,
    province: Optional[str] = None,
    city: Optional[str] = None,
    level: Optional[str] = None,
    year: int = DEFAULT_YEAR,
    expand_km: float = DEFAULT_EXPAND_KM,
    fetch_geojson: bool = True,
) -> Dict[str, Any]:
    """Resolve a single admin division to a metadata dict.

    Returns a dict with: ``name``, ``code``, ``level``, ``province``,
    ``city``, ``bbox_wgs84``, ``bbox_wgs84_expanded``, ``area_km2``,
    ``area_km2_expanded``, ``year``, ``source``.

    When ``fetch_geojson=True`` (default) and the upstream API has no
    vector boundary for the requested code (typical for 9/12-digit 乡/村
    codes), the function still returns the resolved metadata — the
    ``bbox_*`` and ``area_*`` fields are ``None`` and an extra
    ``vector_available: false`` field is added so callers can detect
    the partial result without it being a hard error.
    """
    if not name and not code:
        raise AdminApiError("resolve_admin requires --name or --code")
    if name and code:
        raise AdminApiError("Pass only one of --name or --code, not both")

    chosen: Optional[Dict[str, Any]] = None
    if code:
        # Direct path: we still need name / province / city. Cheap format
        # check first — anything outside the 6/9/12-digit admin-code shape
        # is definitely bogus and we can fail fast without an API call.
        if not code.isdigit() or len(code) not in (6, 9, 12):
            raise AdminApiError(
                f"Invalid admin code {code!r}: expected 6/9/12 digits"
            )
        chosen = {
            "name": name or "",
            "code": code,
            "level": normalize_admin_level(level) if level else code_to_level(code),
            "province": province or "",
            "city": city or "",
        }
    else:
        # Path 1: cheap tree lookup when level is shi/xian and we have
        # province+city(county). Path 2: full-text search otherwise.
        results: List[Dict[str, Any]] = []
        try:
            lv = normalize_admin_level(level) if level else "xian"
            if lv in ("shi",) and province:
                results = list_cities(province, year=year)
                # Each result is a dict; we synthesise a search-style shape.
                results = [
                    {
                        "name": r.get("name") or r.get("city") or "",
                        "code": r.get("code") or "",
                        "level": "shi",
                        "province": province,
                    }
                    for r in results
                ]
            elif lv == "xian" and province and city:
                results = list_counties(province, city, year=year)
                results = [
                    {
                        "name": r.get("name") or r.get("county") or "",
                        "code": r.get("code") or "",
                        "level": "xian",
                        "province": province,
                        "city": city,
                    }
                    for r in results
                ]
        except AdminApiError:
            results = []
        if not results:
            results = _ruiduobao_search(
                name or "", province=province, level=level, limit=20
            )
        chosen = pick_admin_result(
            results, name=name or "", province=province, city=city, level=level
        )

    if not chosen or not chosen.get("code"):
        raise AdminApiError(f"Could not resolve a code for name={name!r}")

    # Now fetch the actual GeoJSON so we have a real bbox + (if missing)
    # name / province / city from the server's properties. Town / village
    # codes often have no vector boundary — we surface that as a partial
    # result, not a hard error.
    geojson: Optional[Dict[str, Any]] = None
    vector_available = True
    if fetch_geojson:
        try:
            geojson = get_geojson(chosen["code"], year=year)
        except AdminApiError as e:
            geojson = None
            vector_available = False
            # Stash the underlying reason so the caller can see it.
            chosen["_vector_error"] = str(e)
            # If we have no other metadata (caller gave only --code and
            # nothing else resolved), treat this as "no such admin code"
            # rather than "real code without vector" — the user almost
            # certainly mistyped.
            if (
                not chosen.get("name")
                and not chosen.get("province")
                and not chosen.get("city")
            ):
                raise AdminApiError(
                    f"No admin record matches code={chosen['code']!r}: {e}"
                ) from e

    if geojson:
        # Fill in name / province / city from the GeoJSON properties when
        # the caller did not specify them. Properties carry the
        # authoritative Chinese names plus the parent-level codes.
        props = (
            (geojson.get("features") or [{}])[0].get("properties") or {}
        )
        if not chosen.get("name"):
            chosen["name"] = (
                props.get("name_3")
                or props.get("县级")
                or props.get("name")
                or props.get("name_2")
                or props.get("name_1")
                or chosen.get("code", "")
            )
        if not chosen.get("province"):
            chosen["province"] = (
                props.get("省级") or props.get("name_1") or ""
            )
        if not chosen.get("city"):
            chosen["city"] = (
                props.get("地级") or props.get("name_2") or ""
            )
        # Province / city codes are useful for downstream consumers.
        chosen.setdefault("province_code", props.get("省级码") or props.get("code_1") or "")
        chosen.setdefault("city_code", props.get("地级码") or props.get("code_2") or "")

    bbox = _bbox_of_geojson(geojson) if geojson else None
    bbox_expanded: Optional[Tuple[float, float, float, float]] = None
    if bbox is not None and expand_km > 0:
        bbox_expanded = expand_bbox_km(bbox, expand_km)

    result: Dict[str, Any] = {
        "name": chosen.get("name", name or ""),
        "code": chosen.get("code", code or ""),
        "level": normalize_admin_level(chosen.get("level")),
        "province": chosen.get("province") or province or "",
        "city": chosen.get("city") or city or "",
        "year": year,
        "source": "ruiduobao",
        "bbox_wgs84": list(bbox) if bbox else None,
        "bbox_wgs84_expanded": list(bbox_expanded) if bbox_expanded else None,
        "area_km2": round(bbox_area_km2(bbox), 3) if bbox else None,
        "area_km2_expanded": (
            round(bbox_area_km2(bbox_expanded), 3) if bbox_expanded else None
        ),
        "vector_available": vector_available,
    }
    if not vector_available and chosen.get("_vector_error"):
        result["vector_error"] = chosen["_vector_error"]
    return result


# ---------------------------------------------------------------------------
# Children (used by download-children)
# ---------------------------------------------------------------------------


def list_children(
    *,
    province: str,
    level: str,
    city: Optional[str] = None,
    county: Optional[str] = None,
    year: int = DEFAULT_YEAR,
) -> List[Dict[str, Any]]:
    """Return a flat list of children at ``level`` under the given parent."""
    lv = normalize_admin_level(level)
    if lv == "shi":
        return list_cities(province, year=year)
    if lv == "xian":
        if not city:
            raise AdminApiError("city is required to list counties")
        return list_counties(province, city, year=year)
    if lv == "xiang":
        if not (province and city and county):
            raise AdminApiError("province/city/county are required to list towns")
        return list_towns(province, city, county, year=year)
    if lv == "cun":
        if not (province and city and county):
            raise AdminApiError("province/city/county/town are required to list villages")
        # The villages endpoint also needs town. We iterate towns first
        # if the caller did not provide one.
        if not (province and city and county):
            raise AdminApiError("province/city/county/town are required to list villages")
        towns = list_towns(province, city, county, year=year)
        all_villages: List[Dict[str, Any]] = []
        for t in towns:
            tname = t.get("name") or t.get("town") or ""
            if not tname:
                continue
            try:
                vs = list_villages(province, city, county, tname, year=year)
            except AdminApiError:
                continue
            for v in vs:
                v = dict(v)
                v["_town"] = tname
                all_villages.append(v)
        return all_villages
    raise AdminApiError(f"Unsupported level for children: {level!r}")


__all__ = [
    "BASE_URL",
    "ALLOWED_HOSTS",
    "DEFAULT_YEAR",
    "SUPPORTED_FORMATS",
    "FORMAT_EXTENSIONS",
    "FORMAT_ALIASES",
    "AdminApiError",
    "expand_bbox_km",
    "bbox_area_km2",
    "code_to_level",
    "code_parent",
    "normalize_admin_level",
    "get_geojson",
    "get_gson_db",
    "download_vector",
    "render_geojson_to_png",
    "PNG_DEFAULT_SIZE",
    "list_cities",
    "list_counties",
    "list_towns",
    "list_villages",
    "list_children",
    "pick_admin_result",
    "resolve_admin",
    "_ruiduobao_search",
    "_bbox_of_geojson",
    "_bbox_of_geometry",
]


if __name__ == "__main__":
    # Minimal manual smoke test.
    print(json.dumps(resolve_admin(code="510104"), ensure_ascii=False, indent=2))

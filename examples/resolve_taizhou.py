"""Example: programatically resolve + download a county.

This file shows how to use ``admin_core`` from a Python script (not the
CLI). Run it from the repo root::

    python examples/resolve_taizhou.py

It downloads 椒江区 (a coastal district of 台州市, 浙江省) as Shapefile
and prints the resolved metadata + the bbox + area.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import admin_core as ac  # noqa: E402


def main() -> int:
    meta = ac.resolve_admin(
        name="椒江区",
        province="浙江省",
        city="台州市",
        expand_km=1.0,
    )
    print("Resolved:", meta)
    if not meta["vector_available"]:
        print("(no vector boundary available; skip download)")
        return 0

    body = ac.download_vector(meta["code"], fmt="shp", year=meta["year"])
    out_path = os.path.join(HERE, f"jiaojiang_{meta['code']}_{meta['year']}.zip")
    with open(out_path, "wb") as f:
        f.write(body)
    print(f"Wrote {out_path} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

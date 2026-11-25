# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Check the forest reference datasets and their layout over a test area (no login needed).

    python scripts/probe_forest_data.py --bbox 82.55 22.70 82.85 22.95

* Hansen et al. Global Forest Change (tree cover 2000, loss year), 10-degree tiles on Google Cloud Storage
* ESA CCI Biomass (above-ground biomass maps), on the CEDA archive
* ESA WorldCover (10 m land cover; class 10 = tree cover), 3-degree tiles on AWS
"""

from __future__ import annotations

import argparse
import math
import re

import requests

S = requests.Session()
S.headers["User-Agent"] = "OpenSAR-Explorer data check"
GDAL = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.nc",
            GDAL_HTTP_MAX_RETRY="3")


def head(url):
    try:
        r = S.head(url, timeout=60, allow_redirects=True)
        return r.status_code, r.headers.get("Content-Length"), r.headers.get("Accept-Ranges")
    except requests.RequestException as e:
        return type(e).__name__, None, None


def links(url):
    try:
        r = S.get(url, timeout=60)
    except requests.RequestException as e:
        print(f"  {url} -> {type(e).__name__}")
        return []
    print(f"  {url} -> {r.status_code}, {len(r.text)} bytes")
    return [h for h in re.findall(r'href="([^"?#]+)"', r.text) if not h.startswith(("/", "http", ".."))]


def window_stats(url, bbox, what):
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    try:
        with rasterio.Env(**GDAL), rasterio.open("/vsicurl/" + url) as src:
            win = from_bounds(*bbox, transform=src.transform)
            arr = src.read(1, window=win)
            print(f"    {what}: crs {src.crs}, res {src.res}, dtype {src.dtypes[0]}, nodata {src.nodata}, "
                  f"blocks {src.block_shapes[0]}, tiled {src.profile.get('tiled')}, window {arr.shape}")
            vals, counts = np.unique(arr, return_counts=True)
            if vals.size <= 40:
                print("    values:", dict(zip(vals.tolist(), counts.tolist())))
            else:
                print("    percentiles p2/p25/p50/p75/p98:", np.percentile(arr, [2, 25, 50, 75, 98]).round(1).tolist(),
                      "max", float(arr.max()))
            return arr
    except Exception as e:
        print(f"    {what}: could not read ({type(e).__name__}: {e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, default=[82.55, 22.70, 82.85, 22.95])
    a = ap.parse_args()
    w, s, e, n = a.bbox
    print(f"Test area {a.bbox}")

    # Hansen GFC: tiles named by their top-left corner, 10 degrees
    top = int(math.ceil(n / 10) * 10)
    left = int(math.floor(w / 10) * 10)
    tile = f"{abs(top):02d}{'N' if top >= 0 else 'S'}_{abs(left):03d}{'E' if left >= 0 else 'W'}"
    for version in ("GFC-2025-v1.13", "GFC-2024-v1.12"):
        print(f"\n=== Hansen {version}, tile {tile}")
        for layer in ("lossyear", "treecover2000", "datamask"):
            url = (f"https://storage.googleapis.com/earthenginepartners-hansen/{version}/"
                   f"Hansen_{version}_{layer}_{tile}.tif")
            print(f"  {layer}: {head(url)}")
            if version.endswith("1.13"):
                window_stats(url, a.bbox, layer)

    # ESA CCI Biomass on CEDA
    base = "https://dap.ceda.ac.uk/neodc/esacci/biomass/data/agb/maps/"
    print("\n=== ESA CCI Biomass on CEDA")
    versions = [v.strip("/") for v in links(base)]
    print("  versions:", versions)
    for v in sorted(versions)[-2:]:
        sub = [x.strip("/") for x in links(f"{base}{v}/")]
        print(f"  {v}: {sub}")
        for fmt in ("geotiff",):
            if fmt in sub:
                years = [x.strip("/") for x in links(f"{base}{v}/{fmt}/")]
                print(f"    {fmt} years: {years}")
                if years:
                    y = sorted(years)[-1]
                    files = links(f"{base}{v}/{fmt}/{y}/")
                    print(f"    {y}: {len(files)} files, e.g. {files[:4]}")
                    hits = [f for f in files if f.upper().startswith(f"N{top:02d}E{left:03d}")]
                    print(f"    tile for the test area: {hits}")
                    for f in hits[:2]:
                        url = f"{base}{v}/{fmt}/{y}/{f}"
                        print(f"    {f}: {head(url)}")
                        window_stats(url, a.bbox, f)

    # ESA WorldCover: 3-degree tiles named by their lower-left corner
    lat3, lon3 = int(math.floor(s / 3) * 3), int(math.floor(w / 3) * 3)
    for ver, year in (("v200", 2021), ("v100", 2020)):
        name = f"ESA_WorldCover_10m_{year}_{ver}_N{lat3:02d}E{lon3:03d}_Map.tif"
        url = f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/{ver}/{year}/map/{name}"
        print(f"\n=== ESA WorldCover {ver} {year}: {name}: {head(url)}")
        if ver == "v200":
            window_stats(url, a.bbox, "land cover classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

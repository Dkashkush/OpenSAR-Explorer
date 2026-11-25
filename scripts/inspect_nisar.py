# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Search ASF for NISAR products over an area and print one file's layout and values (read remotely).

    python scripts/inspect_nisar.py --type GCOV --bbox 82.55 22.70 82.85 22.95 --start 2026-06-01

Used to check product layouts (dataset paths, units, polarisations) against real files before writing a
reader. Needs an Earthdata login (EARTHDATA_TOKEN), like the rest of the app.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def describe_tree(h5, max_items: int = 400) -> None:
    import h5py

    shown = 0

    def visit(name, obj):
        nonlocal shown
        if shown >= max_items:
            return
        if "metadata/" in name and name.count("/") > 4:
            return  # deep metadata cubes: skipped to keep the listing readable
        if isinstance(obj, h5py.Dataset):
            attrs = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in obj.attrs.items()
                     if k in ("units", "description", "long_name", "_FillValue", "grid_mapping", "valid_min",
                              "valid_max")}
            print(f"  {name}  {obj.shape} {obj.dtype}  {attrs if attrs else ''}"[:300])
        else:
            print(f"  {name}/")
        shown += 1

    h5.visititems(visit)


def sample(h5, aoi) -> None:
    import numpy as np
    from pyproj import Transformer

    grids = None
    for cand in ("/science/LSAR/GCOV/grids/frequencyA", "/science/SSAR/GCOV/grids/frequencyA"):
        if cand in h5:
            grids = h5[cand]
            print(f"\nGrid group: {cand}; members: {sorted(grids.keys())}")
            break
    if grids is None:
        print("No GCOV grid group found")
        return
    x, y = grids["xCoordinates"][()], grids["yCoordinates"][()]
    epsg = None
    if "projection" in grids:
        p = grids["projection"]
        epsg = int(np.asarray(p[()]).ravel()[0]) if p.shape in ((), (1,)) else None
        print("projection attrs:", {k: (v.decode() if isinstance(v, bytes) else v) for k, v in p.attrs.items()
                                    if k in ("epsg_code", "spatial_ref", "grid_mapping_name")}, "value:", epsg)
    print(f"x: {x[0]:.1f} .. {x[-1]:.1f} ({x.size}, step {x[1] - x[0]:.2f}); y: {y[0]:.1f} .. {y[-1]:.1f} "
          f"({y.size}, step {y[1] - y[0]:.2f})")
    lon, lat = aoi.center
    if epsg:
        cx, cy = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(lon, lat)
    else:
        cx, cy = lon, lat
    col, row = int(np.argmin(np.abs(x - cx))), int(np.argmin(np.abs(y - cy)))
    inside = x[0] <= cx <= x[-1] or x[-1] <= cx <= x[0]
    print(f"area centre at column {col}, row {row} (inside the grid in x: {inside})")
    r0, c0 = max(0, row - 150), max(0, col - 150)
    for name in sorted(grids.keys()):
        ds = grids[name]
        if len(getattr(ds, "shape", ())) != 2 or name in ("xCoordinates", "yCoordinates"):
            continue
        win = ds[r0:r0 + 300, c0:c0 + 300]
        if np.iscomplexobj(win):
            win = np.abs(win)
        win = win.astype("float64")
        ok = np.isfinite(win) & (win > 0)
        stats = ""
        if ok.any():
            db = 10 * np.log10(win[ok])
            stats = "dB p5/p50/p95 " + " / ".join(f"{v:.1f}" for v in np.percentile(db, [5, 50, 95]))
        print(f"  {name}: window {win.shape}, valid>0 {ok.mean():.0%}, linear median "
              f"{np.nanmedian(win[ok]) if ok.any() else float('nan'):.4g}; {stats}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="GCOV")
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--open", type=int, default=1, help="how many files to open (newest first)")
    a = ap.parse_args()

    import asf_search as asf
    import h5py

    from sarcompare.aoi import AOI
    from sarcompare.download import make_session
    from sarcompare.remote import open_remote
    from sarcompare.search import _window
    from datetime import date

    aoi = AOI.from_bbox(*a.bbox)
    kw = dict(dataset=asf.DATASET.NISAR, processingLevel=a.type, intersectsWith=aoi.wkt, maxResults=500,
              **_window(date.fromisoformat(a.start) if a.start else None,
                        date.fromisoformat(a.end) if a.end else None))
    results = list(asf.search(**kw))
    print(f"{len(results)} NISAR {a.type} products over {a.bbox}")
    if not results:
        return 0
    props = [r.properties for r in results]
    print("property keys:", sorted(props[0].keys()))
    for key in ("flightDirection", "pathNumber", "frameNumber", "polarization", "processingLevel", "platform",
                "beamModeType", "productionConfiguration"):
        vals = Counter(str(p.get(key)) for p in props)
        print(f"  {key}: {dict(vals.most_common(8))}")
    dates = sorted(str(p.get("startTime"))[:10] for p in props)
    print(f"  dates: {dates[0]} .. {dates[-1]} ({len(set(dates))} distinct)")
    results.sort(key=lambda r: str(r.properties.get("startTime")), reverse=True)
    for r in results[:6]:
        p = r.properties
        print(f"  {p.get('startTime')} {p.get('flightDirection')} track {p.get('pathNumber')} frame "
              f"{p.get('frameNumber')} pol {p.get('polarization')} {p.get('fileID') or p.get('sceneName')}")
        print(f"     url {p.get('url')}; additional {[u for u in (p.get('additionalUrls') or []) if u.endswith('.h5')][:2]}")
    session = make_session()
    for r in results[: a.open]:
        url = r.properties.get("url")
        if not str(url).endswith(".h5"):
            url = next((u for u in r.properties.get("additionalUrls") or [] if u.endswith(".h5")), url)
        print(f"\n=== {url}")
        with open_remote(url, session) as f, h5py.File(f, "r") as h5:
            describe_tree(h5)
            sample(h5, aoi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""NISAR L2 GCOV (Geocoded polarimetric COVariance): search on ASF and read the backscatter over an area.

Layout checked against a real file (November 2026, CRID P05036, with scripts/inspect_nisar.py)::

    /science/LSAR/GCOV/grids/frequencyA/HHHH, HVHV     float32, linear power, NaN fill. Radiometrically terrain
                                                       corrected backscatter (gamma-naught); rtcGammaToSigmaFactor
                                                       converts to sigma-naught
    /science/LSAR/GCOV/grids/frequencyA/mask           uint8: sub-swath number of valid samples, 0 = invalid,
                                                       255 = fill
    /science/LSAR/GCOV/grids/frequencyA/numberOfLooks  float32
    /science/LSAR/GCOV/grids/frequencyA/xCoordinates, yCoordinates   pixel centres in metres (10 m spacing)
    /science/LSAR/GCOV/grids/frequencyA/projection     EPSG code (value, and attribute ``epsg_code``), UTM
    /science/LSAR/identification/zeroDopplerStartTime, orbitPassDirection, trackNumber, frameNumber

Frequency B (the 5 MHz side band, when acquired) is posted at 80 m. A frame is about 340 km wide, so a layer is
over 4 GB; only the window over the area is read, then averaged to the analysis grid (100 m by default), which
also removes most of the speckle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import xarray as xr

from ..aoi import AOI
from ..notes import INFO, WARN, Note
from ..products import NISAR, Product
from ..readers.base import aoi_slices, apply_fill, decode, make_da, source_name

# NISAR_L2_PR_GCOV_035_149_D_077_4005_DHDH_A_20261115T130813_20261115T130847_P05036_N_F_J_001
GCOV_NAME = re.compile(
    r"NISAR_L2_(?P<config>[A-Z]{2})_GCOV_(?P<cycle>\d{3})_(?P<track>\d{3})_(?P<dir>[AD])_(?P<frame>\d{3})_"
    r"(?P<mode>\d{4})_(?P<pols>[A-Z]{2,4})_[A-Z]_(?P<start>\d{8}T\d{6})_\d{8}T\d{6}_(?P<crid>[A-Z]\d{5})_")
CROSS_POL = ("HVHV", "VHVH")
CO_POL = ("HHHH", "VVVV")


def parse_gcov_name(name: str) -> dict:
    m = GCOV_NAME.search(name or "")
    if not m:
        return {}
    g = m.groupdict()
    start = datetime.strptime(g["start"], "%Y%m%dT%H%M%S")
    return {"config": g["config"], "cycle": int(g["cycle"]), "track": int(g["track"]),
            "direction": {"A": "ASCENDING", "D": "DESCENDING"}[g["dir"]], "frame": int(g["frame"]),
            "pols": g["pols"], "crid": g["crid"], "start": start, "date": start.date()}


def _product(name: str, url: str | None, props: dict | None = None, extra: dict | None = None,
             local_path: Path | None = None) -> Product:
    props = props or {}
    info = parse_gcov_name(Path(str(url)).name if url else name) or parse_gcov_name(name)
    d = info.get("date")
    if d is None and props.get("startTime"):
        d = date.fromisoformat(str(props["startTime"])[:10])
    return Product(NISAR, "GCOV", name, url=url, date1=d, date2=d,
                   flight_direction=info.get("direction") or (props.get("flightDirection") or "").upper() or None,
                   track=info.get("track") or props.get("pathNumber"),
                   frame=info.get("frame") or props.get("frameNumber"), local_path=local_path,
                   extra={"config": info.get("config") or props.get("productionConfiguration"),
                          "crid": info.get("crid") or props.get("crid"), "pols": info.get("pols"),
                          "start": info.get("start"), **(extra or {})})


def search_gcov(aoi: AOI, start=None, end=None, flight_direction=None, max_results=500) -> list[Product]:
    """NISAR L2 GCOV images intersecting the area, one per acquisition (see ``dedupe``)."""
    from ..search import _asf, _cover, _size_mb, _window

    asf = _asf()
    kw = dict(dataset=asf.DATASET.NISAR, processingLevel="GCOV", intersectsWith=aoi.wkt, maxResults=max_results,
              **_window(start, end))
    if flight_direction:
        kw["flightDirection"] = flight_direction
    out = []
    for r in asf.search(**kw):
        p = r.properties
        url = p.get("url")
        if not str(url).lower().endswith(".h5"):
            url = next((u for u in p.get("additionalUrls") or [] if str(u).lower().endswith(".h5")), url)
        name = p.get("fileID") or p.get("sceneName") or Path(str(url)).stem
        prod = _product(name, url, p, _cover(r, aoi))
        prod.size_mb = _size_mb(p)
        out.append(prod)
    return dedupe(out)


def scan_gcov(folder: str | Path) -> list[Product]:
    """GCOV .h5 files already on disk."""
    files = sorted(Path(folder).expanduser().glob("**/*GCOV*.h5")) if folder else []
    return dedupe([_product(f.stem, None, local_path=f) for f in files])


def dedupe(products: list[Product]) -> list[Product]:
    """One image per acquisition. ASF lists some acquisitions twice: the standard product (PR) and an urgent-
    response copy (UR), sometimes from different processor versions (CRID); the standard, newest one is kept."""
    best: dict[tuple, Product] = {}
    for p in products:
        key = (p.flight_direction, p.track, p.frame, p.date1)
        rank = (p.extra.get("config") == "PR", str(p.extra.get("crid") or ""))
        old = best.get(key)
        if old is None or rank > (old.extra.get("config") == "PR", str(old.extra.get("crid") or "")):
            best[key] = p
    return sorted(best.values(), key=lambda p: (p.date1 or date.min, p.track or 0))


def choose_geometry(products: list[Product]) -> tuple[list[Product], list[Note]]:
    """Images from one viewing geometry (pass direction, track, frame): changes in backscatter are only
    comparable from the same geometry. The group with the most dates, weighted by how much of the area it
    covers, is used."""
    from ..search import coverage

    groups: dict[tuple, list[Product]] = {}
    for p in products:
        groups.setdefault((p.flight_direction, p.track, p.frame), []).append(p)
    if not groups:
        return [], []

    def score(item):
        cov = coverage(item[1])
        return len({p.date1 for p in item[1]}) * (cov if cov is not None else 1.0), cov or 0

    ranked = sorted(groups.items(), key=score, reverse=True)
    (direction, track, frame), chosen = ranked[0]
    cov = coverage(chosen)
    text = (f"Using {len(chosen)} NISAR images from track {track} ({(direction or '?').lower()}), frame {frame}"
            + (f", covering {cov:.0%} of the area" if cov is not None else "") + ".")
    if len(ranked) > 1:
        others = ", ".join(f"track {t} frame {f} ({len(g)})" for (_, t, f), g in ranked[1:4])
        text += (f" Other geometries over the area: {others}; they are not mixed in, because backscatter "
                 "changes with the viewing angle.")
    notes = [Note("search", INFO, text)]
    if cov is not None and cov < 0.9:
        notes.append(Note("search", WARN, f"The chosen frame covers only {cov:.0%} of the area; the rest stays "
                                          "empty. A smaller area inside one frame avoids this."))
    return chosen, notes


def thin_dates(products: list[Product], n: int) -> list[Product]:
    """At most ``n`` images spread evenly over the period, always keeping the first and the last."""
    products = sorted(products, key=lambda p: p.date1 or date.min)
    if n <= 0 or len(products) <= n:
        return products
    idx = sorted(set(np.linspace(0, len(products) - 1, n).round().astype(int).tolist()))
    return [products[i] for i in idx]


@dataclass
class Backscatter:
    """One GCOV acquisition over the area, averaged to the analysis grid. Linear power (gamma-naught)."""

    name: str
    date: date
    hv: xr.DataArray  # cross-polarised (HV, or VH)
    hh: xr.DataArray | None  # co-polarised (HH, or VV)
    track: int | None = None
    direction: str | None = None
    frame: int | None = None
    looks: float | None = None
    valid_fraction: float = 1.0
    notes: list[Note] = field(default_factory=list)


def block_average(arr: np.ndarray, x: np.ndarray, y: np.ndarray, res: float,
                  min_valid: float = 0.3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Average ``arr`` (linear power, pixel centres ``x``/``y``) into cells of ``res`` metres whose edges are
    multiples of ``res``, so images on different grids land on the same cells. A cell needs at least
    ``min_valid`` of its pixels. Returns (cells, cell centre x, cell centre y north-up)."""
    dx = abs(float(x[1] - x[0])) if x.size > 1 else res
    dy = abs(float(y[1] - y[0])) if y.size > 1 else res
    cx = np.floor(x / res).astype(np.int64)
    cy = np.floor(y / res).astype(np.int64)
    ux = np.arange(cx.min(), cx.max() + 1)
    uy = np.arange(cy.max(), cy.min() - 1, -1)
    ix, iy = cx - ux[0], uy[0] - cy
    nx, ny = ux.size, uy.size
    idx = iy[:, None] * nx + ix[None, :]
    ok = np.isfinite(arr)
    sums = np.bincount(idx[ok], weights=arr[ok].astype("float64"), minlength=nx * ny)
    counts = np.bincount(idx[ok], minlength=nx * ny)
    need = max(1.0, min_valid * (res / dx) * (res / dy))
    out = np.where(counts >= need, sums / np.maximum(counts, 1), np.nan).reshape(ny, nx)
    return out.astype("float32"), (ux + 0.5) * res, (uy + 0.5) * res


def _grid_group(h5, frequency: str):
    for band in ("LSAR", "SSAR"):
        path = f"/science/{band}/GCOV/grids/frequency{frequency}"
        if path in h5:
            return h5[path]
    found = []
    h5.visit(lambda n: found.append(n) if n.endswith(f"grids/frequency{frequency}") else None)
    if not found:
        raise ValueError(f"NISAR GCOV: no frequency{frequency} grid in this file")
    return h5[found[0]]


def _epsg(grid) -> int:
    p = grid["projection"]
    code = p.attrs.get("epsg_code")
    if code is None:
        code = np.asarray(p[()]).ravel()[0]
    return int(np.asarray(code).ravel()[0])


def _ident(h5, key: str):
    for band in ("LSAR", "SSAR"):
        path = f"/science/{band}/identification/{key}"
        if path in h5:
            return h5[path][()]
    return None


def read_gcov(source, aoi: AOI, resolution_m: float = 100.0, frequency: str = "A",
              name: str | None = None) -> Backscatter:
    """Read HV (and HH) over ``aoi`` from a GCOV file (path or open file-like object) and average to
    ``resolution_m`` cells. Invalid samples (mask 0 or fill) and non-positive values are left out."""
    import h5py

    fname = source_name(source, name)
    notes: list[Note] = []
    with h5py.File(source, "r") as h5:
        grid = _grid_group(h5, frequency)
        x, y = grid["xCoordinates"][()], grid["yCoordinates"][()]
        epsg = _epsg(grid)
        rows, cols = aoi_slices(x, y, aoi.bounds_in(f"EPSG:{epsg}"), pad_frac=0.02)
        valid = None
        if "mask" in grid:
            m = grid["mask"][rows, cols]
            valid = (m > 0) & (m < 255)
        layers = {}
        for term in CROSS_POL + CO_POL:
            if term in grid and term not in layers:
                ds = grid[term]
                arr = apply_fill(ds[rows, cols], ds.attrs.get("_FillValue"))
                if valid is not None and valid.shape == arr.shape:
                    arr = np.where(valid, arr, np.nan)
                layers[term] = np.where(arr > 0, arr, np.nan)
        looks = None
        if "numberOfLooks" in grid:
            lk = apply_fill(grid["numberOfLooks"][rows, cols], grid["numberOfLooks"].attrs.get("_FillValue"))
            looks = float(np.nanmedian(lk)) if np.isfinite(lk).any() else None
        start = decode(_ident(h5, "zeroDopplerStartTime") or b"")
        direction = decode(_ident(h5, "orbitPassDirection") or b"").upper() or None
        track = _ident(h5, "trackNumber")
        frame = _ident(h5, "frameNumber")
    cross = next((t for t in CROSS_POL if t in layers), None)
    if cross is None:
        raise ValueError(f"{fname}: no cross-polarised (HV) layer; biomass needs dual- or quad-pol GCOV")
    co = next((t for t in CO_POL if t in layers), None)
    info = parse_gcov_name(fname)
    when = info.get("date")
    if when is None and start:
        when = date.fromisoformat(start[:10])
    xs, ys = x[cols], y[rows]
    hv, cx, cy = block_average(layers[cross], xs, ys, resolution_m)
    hh = block_average(layers[co], xs, ys, resolution_m)[0] if co else None
    crs = f"EPSG:{epsg}"
    vf = float(np.isfinite(layers[cross]).mean())
    if vf < 0.5:
        notes.append(Note("load", WARN, f"NISAR {when}: only {vf:.0%} of the area has valid backscatter in this "
                                        "image (edge of the swath, or gaps)."))
    if cross == "VHVH":
        notes.append(Note("load", INFO, f"NISAR {when}: VV/VH image; VH is used in place of HV."))
    return Backscatter(name=fname, date=when, hv=make_da(hv, cx, cy, crs, "hv"),
                       hh=make_da(hh, cx, cy, crs, "hh") if hh is not None else None,
                       track=int(np.asarray(track).ravel()[0]) if track is not None else info.get("track"),
                       direction=direction or info.get("direction"),
                       frame=int(np.asarray(frame).ravel()[0]) if frame is not None else info.get("frame"),
                       looks=looks, valid_fraction=vf, notes=notes)

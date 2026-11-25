# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Synthetic forest scene for the demo and the tests, written in the real file formats: NISAR GCOV HDF5 (same
layout as the November 2026 products) plus stand-ins for ESA WorldCover, Hansen Global Forest Change and ESA CCI
Biomass GeoTIFFs. Clearly labelled synthetic: it is not a real place.

The scene is a deciduous forest of varying biomass with farmland to the south, a river and a village, an old mine
cut (cleared 2023-2024, mapped by "Hansen"), a mine extension cleared between the third and fourth NISAR image,
and a patch cleared early in 2026 that the "Hansen" maps do not show yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from pyproj import Transformer

DEMO_BBOX = (82.60, 22.78, 82.74, 22.90)
DEMO_VERSION = "1"
DEMO_DATES = [date(2026, 6, 22) + timedelta(days=24 * k) for k in range(6)]
CHANGE_INDEX = 3  # the mine extension is cleared between DEMO_DATES[2] and DEMO_DATES[3]
DEMO_OFFSETS_DB = [0.0, 0.9, 1.3, 0.7, 0.3, -0.2]  # monsoon wetting, the same for every forest pixel
HV_MODEL = (0.085, 60.0, 0.0075)  # a, b, c of HV = a (1 - exp(-AGB/b)) + c
CRS = "EPSG:32644"


@dataclass
class ForestScene:
    """Biomass and land cover as functions of UTM (zone 44N) coordinates."""

    cx: float
    cy: float

    @classmethod
    def for_bbox(cls, bbox=DEMO_BBOX) -> "ForestScene":
        lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        return cls(*Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(lon, lat))

    def masks(self, x, y) -> dict:
        u, v = x - self.cx, y - self.cy
        water = np.abs(u - 0.3 * v - 3500) < 120
        fields = (v < -3000 + 800 * np.sin(u / 1500)) & ~water
        village = ((u + 4000) ** 2 + (v + 4200) ** 2 < 400 ** 2) & ~water
        old = (u > -500) & (u < 1500) & (v > 1000) & (v < 2500)
        new = (u >= 1500) & (u < 2300) & (v > 1200) & (v < 2200)
        unmapped = (u > -3500) & (u < -2700) & (v > 3000) & (v < 3600)
        forest = ~(water | fields | village)
        return dict(water=water, fields=fields & ~village, village=village, old=old & forest,
                    old_west=old & forest & (u < 500), new=new & forest, unmapped=unmapped & forest, forest=forest)

    def agb(self, x, y, when: str) -> np.ndarray:
        """Above-ground biomass (Mg/ha) at a stage: '2020', '2021', '2024', or a NISAR date index 'd0'..'d5'."""
        u, v = x - self.cx, y - self.cy
        m = self.masks(x, y)
        dense = 135 + 85 * np.sin(u / 2300) * np.cos(v / 1700) + 35 * np.sin((u + v) / 900)
        out = np.where(m["forest"], np.clip(dense, 15, 280), np.where(m["fields"], 2.0, 0.0))
        if when not in ("2020", "2021"):  # the old cut: 2023 (west part) and 2024
            out = np.where(m["old"], 0.0, out)
        if when.startswith("d"):
            out = np.where(m["unmapped"], 0.0, out)
            if int(when[1:]) >= CHANGE_INDEX:
                out = np.where(m["new"], 0.0, out)
        return out


def _hv(scene: ForestScene, x, y, k: int, rng, looks=4.8) -> tuple[np.ndarray, np.ndarray]:
    a, b, c = HV_MODEL
    agb = scene.agb(x, y, f"d{k}")
    m = scene.masks(x, y)
    hv = a * (1 - np.exp(-agb / b)) + c
    hh = 3.2 * hv + 0.03
    hv = np.where(m["water"], 0.0012, np.where(m["village"], 0.05, hv))
    hh = np.where(m["water"], 0.003, np.where(m["village"], 0.6, hh))
    wet = 10 ** (DEMO_OFFSETS_DB[k] / 10)
    speckle = rng.gamma(looks, 1 / looks, size=(2,) + np.shape(x))
    return (hv * wet * speckle[0]).astype("float32"), (hh * wet ** 1.5 * speckle[1]).astype("float32")


def gcov_name(d: date, k: int) -> str:
    return (f"NISAR_L2_PR_GCOV_{30 + k:03d}_149_D_077_4005_DHDH_A_{d:%Y%m%d}T130813_{d:%Y%m%d}T130847_P05036_N_F_J_"
            "001.h5")


def write_gcov(path: Path, scene: ForestScene, d: date, k: int, bbox=DEMO_BBOX, res=20.0, seed=7) -> None:
    """A GCOV file covering the area (plus 1 km), frequency A, HH/HV, in the real layout."""
    import h5py

    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    xs, ys = tr.transform([bbox[0], bbox[2], bbox[0], bbox[2]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    x = np.arange(np.floor(min(xs) / res) * res - 1000, max(xs) + 1000, res) + res / 2
    y = np.arange(np.ceil(max(ys) / res) * res + 1000, min(ys) - 1000, -res) - res / 2
    X, Y = np.meshgrid(x, y)
    hv, hh = _hv(scene, X, Y, k, np.random.default_rng(seed + 31 * k))
    mask = np.ones(hv.shape, "uint8")
    mask[:, :8] = 0  # a strip outside the swath
    hv[:, :8] = hh[:, :8] = np.nan
    with h5py.File(path, "w") as h5:
        g = h5.create_group("science/LSAR/GCOV/grids/frequencyA")
        for name, arr in (("HHHH", hh), ("HVHV", hv)):
            ds = g.create_dataset(name, data=arr, chunks=(256, 256), compression="gzip", compression_opts=1)
            ds.attrs["_FillValue"] = np.float32(np.nan)
            ds.attrs["units"] = "1"
            ds.attrs["description"] = f"Covariance between {name[:2]} and {name[2:]}"
        g.create_dataset("mask", data=mask, chunks=(256, 256), compression="gzip").attrs["_FillValue"] = np.uint8(255)
        g.create_dataset("numberOfLooks", data=np.full(hv.shape, 4.8, "float32"), chunks=(256, 256),
                         compression="gzip")
        g.create_dataset("xCoordinates", data=x)
        g.create_dataset("yCoordinates", data=y)
        p = g.create_dataset("projection", data=np.uint32(32644))
        p.attrs["epsg_code"] = np.int64(32644)
        g.create_dataset("listOfPolarizations", data=np.array([b"HH", b"HV"]))
        ident = h5.create_group("science/LSAR/identification")
        ident.create_dataset("zeroDopplerStartTime", data=np.bytes_(f"{d:%Y-%m-%d}T13:08:13.000000000"))
        ident.create_dataset("orbitPassDirection", data=np.bytes_("Descending"))
        ident.create_dataset("trackNumber", data=np.uint32(149))
        ident.create_dataset("frameNumber", data=np.uint16(77))
        ident.create_dataset("productType", data=np.bytes_("GCOV"))


def _geo_grid(bbox, step, pad=0.01):
    w, s, e, n = bbox
    lons = np.arange(w - pad, e + pad, step) + step / 2
    lats = np.arange(n + pad, s - pad, -step) - step / 2
    return lons, lats


def _write_tif(path: Path, arr, lons, lats, step, dtype, nodata=None) -> None:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=dtype,
                       crs="EPSG:4326", transform=from_origin(lons[0] - step / 2, lats[0] + step / 2, step, step),
                       nodata=nodata, compress="deflate") as dst:
        dst.write(arr.astype(dtype), 1)


def write_references(folder: Path, scene: ForestScene, bbox=DEMO_BBOX, seed=7) -> dict:
    """Stand-ins for WorldCover 2021, Hansen tree cover 2000 / loss year, and CCI Biomass 2024 and 2020."""
    rng = np.random.default_rng(seed)
    tr = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    files = {}
    # WorldCover 2021 (finer than the analysis grid; 10 = tree, 40 = cropland, 50 = built-up, 80 = water)
    step = 0.0002
    lons, lats = _geo_grid(bbox, step)
    X, Y = tr.transform(*np.meshgrid(lons, lats))
    m = scene.masks(X, Y)
    wc = np.select([m["water"], m["village"], m["fields"], m["forest"]], [80, 50, 40, 10], 30)
    files["worldcover"] = folder / "worldcover_2021_synthetic.tif"
    _write_tif(files["worldcover"], wc, lons, lats, step, "uint8", nodata=0)
    # Hansen: 0.00025 degrees (~27 m)
    step = 0.00025
    lons, lats = _geo_grid(bbox, step)
    X, Y = tr.transform(*np.meshgrid(lons, lats))
    m = scene.masks(X, Y)
    tc = np.where(m["forest"], np.clip(rng.normal(78, 8, X.shape), 40, 100), np.where(m["fields"], 3, 0))
    loss = np.where(m["old_west"], 23, np.where(m["old"], 24, 0))
    files["treecover2000"] = folder / "hansen_treecover2000_synthetic.tif"
    files["lossyear"] = folder / "hansen_lossyear_synthetic.tif"
    _write_tif(files["treecover2000"], tc, lons, lats, step, "uint8")
    _write_tif(files["lossyear"], loss, lons, lats, step, "uint8")
    # CCI Biomass: 0.000888 degrees (~100 m), with 25 % multiplicative error and its SD
    step = 1 / 1125
    lons, lats = _geo_grid(bbox, step)
    X, Y = tr.transform(*np.meshgrid(lons, lats))
    for key, when in (("agb", "2024"), ("agb_baseline", "2020")):
        truth = scene.agb(X, Y, when)
        est = np.clip(truth * rng.lognormal(0, 0.25, truth.shape), 0, 600)
        files[key] = folder / f"cci_agb_{when}_synthetic.tif"
        _write_tif(files[key], est.round(), lons, lats, step, "uint16")
        if key == "agb":
            files["agb_sd"] = folder / f"cci_agb_sd_{when}_synthetic.tif"
            _write_tif(files["agb_sd"], (0.3 * truth + 5).round(), lons, lats, step, "uint16")
    return {k: str(v) for k, v in files.items()}


def make_forest_demo(root: str | Path = "data/demo_forest", seed: int = 7) -> tuple[Path, dict]:
    """Write the synthetic files once (atomically, like the Ground Motion demo); returns (gcov folder, refs)."""
    import json
    import os
    import shutil
    import uuid

    root = Path(root)
    done = root / ".complete"
    if done.exists() and done.read_text().strip() == DEMO_VERSION:
        return root / "gcov", json.loads((root / "references.json").read_text())
    root.parent.mkdir(parents=True, exist_ok=True)
    tmp = root.parent / f".{root.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    (tmp / "gcov").mkdir(parents=True)
    (tmp / "reference").mkdir()
    scene = ForestScene.for_bbox()
    for k, d in enumerate(DEMO_DATES):
        write_gcov(tmp / "gcov" / gcov_name(d, k), scene, d, k, seed=seed)
    refs = write_references(tmp / "reference", scene, seed=seed)
    final = {k: str(root / "reference" / Path(v).name) for k, v in refs.items()}
    (tmp / "references.json").write_text(json.dumps(final))
    (tmp / ".complete").write_text(DEMO_VERSION + "\n")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    try:
        os.rename(tmp, root)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
    return root / "gcov", final


def forest_demo_config(root: str | Path = "data/demo_forest", output_dir: str = "outputs"):
    from .pipeline import ForestConfig

    gcov_dir, refs = make_forest_demo(root)
    return ForestConfig(name="forest_demo_synthetic", aoi=list(DEMO_BBOX), gcov_source="LOCAL",
                        gcov_dir=str(gcov_dir), reference_files=refs, agb_year=2024, output_dir=output_dir,
                        extra={"synthetic": True})

# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Independent forest data, read over the area only (partial web reads) and put on the analysis grid.

* ESA WorldCover 2021 v200 (10 m land cover; 10 = tree cover): where the forest was in 2021. CC BY 4.0.
* Hansen et al. Global Forest Change v1.13 (30 m; tree cover in 2000, year of loss 2001-2025): where and when
  forest was lost. CC BY 4.0, "Source: Hansen/UMD/Google/USGS/NASA".
* ESA CCI Biomass v7.0 (100 m above-ground biomass, Mg/ha, with its standard deviation): calibration and check
  of the NISAR biomass estimate.

Layouts checked against the archives (scripts/probe_forest_data.py, November 2026). Each reader takes optional
local files instead (``files``), used by the demo, the tests and offline work.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

HANSEN_VERSION = "GFC-2025-v1.13"
HANSEN_LAST_YEAR = 2025
HANSEN_URL = "https://storage.googleapis.com/earthenginepartners-hansen/{v}/Hansen_{v}_{layer}_{tile}.tif"
WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
CCI_VERSION = "v7.0"
CCI_LAST_YEAR = 2024
CCI_URL = ("https://dap.ceda.ac.uk/neodc/esacci/biomass/data/agb/maps/{v}/geotiff/{year}/"
           "{tile}_ESACCI-BIOMASS-L4-{kind}-MERGED-100m-{year}-f{v}.tif")

TREE, SHRUB, GRASS, CROP, BUILT, BARE, SNOW, WATER, WETLAND, MANGROVE, MOSS = 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
                GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", GDAL_HTTP_TIMEOUT="60",
                VSI_CACHE="TRUE", GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES")

CITATIONS = {
    "worldcover": ("Zanaga, D. et al. (2022). ESA WorldCover 10 m 2021 v200. doi:10.5281/zenodo.7254221. "
                   "© ESA WorldCover project 2021 / contains modified Copernicus Sentinel data (2021) processed by "
                   "the ESA WorldCover consortium. CC BY 4.0."),
    "hansen": ("Hansen, M. C. et al. (2013). High-Resolution Global Maps of 21st-Century Forest Cover Change. "
               "Science 342, 850-853. Data: Global Forest Change 2000-2025 v1.13, Source: Hansen/UMD/Google/USGS/"
               "NASA. CC BY 4.0."),
    "cci": ("Santoro, M. & Cartus, O. ESA Biomass Climate Change Initiative (Biomass_cci): Global datasets of "
            "forest above-ground biomass, v7.0. NERC EDS Centre for Environmental Data Analysis (CEDA). "
            "Data used under the ESA CCI data policy (cite the dataset)."),
}


def _lat(v: int) -> str:
    return f"{'N' if v >= 0 else 'S'}{abs(v):02d}"


def _lon(v: int) -> str:
    return f"{'E' if v >= 0 else 'W'}{abs(v):03d}"


def _tens(bounds) -> list[tuple[int, int]]:
    """(top latitude, left longitude) of the 10-degree tiles covering ``bounds`` (lon/lat)."""
    w, s, e, n = bounds
    tops = range(int(math.floor(s / 10)) * 10 + 10, int(math.ceil(n / 10)) * 10 + 1, 10)
    lefts = range(int(math.floor(w / 10)) * 10, int(math.ceil(e / 10)) * 10, 10)
    return [(t, l) for t in tops for l in lefts]


def hansen_tiles(bounds) -> list[str]:
    """Hansen tiles are named by their top-left corner: '30N_080E' covers 20-30 N, 80-90 E."""
    return [f"{abs(t):02d}{'N' if t >= 0 else 'S'}_{abs(l):03d}{'E' if l >= 0 else 'W'}" for t, l in _tens(bounds)]


def cci_tiles(bounds) -> list[str]:
    """CCI Biomass tiles are also named by their top-left corner: 'N30E080' covers 20-30 N, 80-90 E."""
    return [f"{_lat(t)}{_lon(l)}" for t, l in _tens(bounds)]


def worldcover_tiles(bounds) -> list[str]:
    """WorldCover tiles are 3 degrees, named by their lower-left corner: 'N21E081' covers 21-24 N, 81-84 E."""
    w, s, e, n = bounds
    lats = range(int(math.floor(s / 3)) * 3, int(math.ceil(n / 3)) * 3, 3)
    lons = range(int(math.floor(w / 3)) * 3, int(math.ceil(e / 3)) * 3, 3)
    return [f"{_lat(a)}{_lon(o)}" for a in lats for o in lons] or [f"{_lat(int(math.floor(s / 3)) * 3)}"
                                                                   f"{_lon(int(math.floor(w / 3)) * 3)}"]


def hansen_urls(bounds, layer: str) -> list[str]:
    return [HANSEN_URL.format(v=HANSEN_VERSION, layer=layer, tile=t) for t in hansen_tiles(bounds)]


def worldcover_urls(bounds) -> list[str]:
    return [WORLDCOVER_URL.format(tile=t) for t in worldcover_tiles(bounds)]


def cci_urls(bounds, year: int, sd: bool = False) -> list[str]:
    kind = "AGB_SD" if sd else "AGB"
    return [CCI_URL.format(v=CCI_VERSION, year=year, tile=t, kind=kind) for t in cci_tiles(bounds)]


@dataclass
class Grid:
    """The analysis grid: north-up cells of ``res`` metres in ``crs``; ``x``/``y`` are cell centres."""

    crs: str
    x: np.ndarray
    y: np.ndarray

    @property
    def res(self) -> float:
        return abs(float(self.x[1] - self.x[0])) if self.x.size > 1 else abs(float(self.y[0] - self.y[1]))

    @property
    def shape(self) -> tuple[int, int]:
        return self.y.size, self.x.size

    @property
    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(self.x[0] - self.res / 2, self.y[0] + self.res / 2, self.res, self.res)

    @property
    def cell_ha(self) -> float:
        return self.res * self.res / 1e4

    def lonlat_bounds(self, pad: float = 0.0) -> tuple[float, float, float, float]:
        from pyproj import Transformer

        r = self.res / 2
        xs = np.array([self.x[0] - r, self.x[-1] + r, self.x[0] - r, self.x[-1] + r])
        ys = np.array([self.y[0] + r, self.y[0] + r, self.y[-1] - r, self.y[-1] - r])
        lon, lat = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True).transform(xs, ys)
        return lon.min() - pad, lat.min() - pad, lon.max() + pad, lat.max() + pad

    def lonlat(self) -> tuple[np.ndarray, np.ndarray]:
        from pyproj import Transformer

        X, Y = np.meshgrid(self.x, self.y)
        return Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True).transform(X, Y)

    def da(self, values, name: str):
        from ..readers.base import make_da

        return make_da(values, self.x, self.y, self.crs, name)

    @classmethod
    def around(cls, aoi, crs: str, res: float) -> "Grid":
        w, s, e, n = aoi.bounds_in(crs)
        x0, x1 = math.floor(w / res), math.ceil(e / res)
        y0, y1 = math.floor(s / res), math.ceil(n / res)
        return cls(crs, (np.arange(x0, x1) + 0.5) * res, (np.arange(y1 - 1, y0 - 1, -1) + 0.5) * res)


def _open(src):
    import rasterio

    return rasterio.open(src if not str(src).startswith("http") else "/vsicurl/" + str(src))


def to_grid(sources, grid: Grid, resampling: str = "average", transform=None, nodata=None) -> np.ndarray:
    """Read the part of each source (URL or path) under ``grid`` and resample it onto ``grid``.

    ``transform`` maps the raw window to float values before resampling (e.g. class == 10 -> 1.0, so 'average'
    gives the tree fraction of each cell). Cells no source covers are NaN. Raises OSError when no source can be
    read."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject, transform_bounds
    from rasterio.windows import Window, from_bounds

    out = np.full(grid.shape, np.nan, dtype="float32")
    errors, read = [], 0
    with rasterio.Env(**GDAL_ENV):
        for src_path in sources:
            try:
                with _open(src_path) as src:
                    b = transform_bounds(grid.crs, src.crs, *_grid_bounds(grid), densify_pts=21)
                    pad = 2 * max(abs(src.res[0]), abs(src.res[1]))
                    win = from_bounds(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad, transform=src.transform)
                    win = win.round_offsets().round_lengths().intersection(Window(0, 0, src.width, src.height))
                    raw = src.read(1, window=win)
                    tr = src.window_transform(win)
                    nd = src.nodata if nodata is None else nodata
                    vals = raw.astype("float32")
                    if transform is not None:
                        vals = np.asarray(transform(raw), dtype="float32")
                    if nd is not None:
                        vals = np.where(raw == nd, np.nan, vals)
                    tmp = np.full(grid.shape, np.nan, dtype="float32")
                    reproject(vals, tmp, src_transform=tr, src_crs=src.crs, src_nodata=np.nan,
                              dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan,
                              resampling=getattr(Resampling, resampling))
                    out = np.where(np.isnan(out), tmp, out)
                    read += 1
            except (rasterio.errors.RasterioError, rasterio.errors.WindowError, OSError, ValueError) as e:
                errors.append(f"{str(src_path).rsplit('/', 1)[-1]}: {e}")
    if not read:
        raise OSError("; ".join(errors) or "no source")
    return out


def _grid_bounds(grid: Grid):
    r = grid.res / 2
    return grid.x[0] - r, grid.y[-1] - r, grid.x[-1] + r, grid.y[0] + r


def worldcover(grid: Grid, files=None) -> dict[str, np.ndarray]:
    """Fraction of each cell in tree cover, mangroves, cropland, built-up and water (ESA WorldCover 2021)."""
    sources = files or worldcover_urls(grid.lonlat_bounds(0.01))
    classes = {"tree": (TREE,), "mangrove": (MANGROVE,), "crop": (CROP,), "built": (BUILT,), "water": (WATER,),
               "open": (SHRUB, GRASS, BARE)}
    out = {}
    for key, codes in classes.items():
        out[key] = to_grid(sources, grid, "average", transform=lambda a, c=codes: np.isin(a, c), nodata=0)
    out["forest"] = out["tree"] + out["mangrove"]
    return out


def hansen(grid: Grid, files: dict | None = None, recent_from: int = 2021) -> dict:
    """Tree cover in 2000 (%), share of each cell lost in any year / since ``recent_from``, the latest year of
    loss (0 = none), and the mapped loss area per year over the grid (ha, from 30 m pixel counts)."""
    files = files or {}
    bounds = grid.lonlat_bounds(0.01)
    tc_src = files.get("treecover2000") or hansen_urls(bounds, "treecover2000")
    ly_src = files.get("lossyear") or hansen_urls(bounds, "lossyear")
    rf = recent_from - 2000
    out = {"treecover2000": to_grid(tc_src, grid, "average"),
           "loss_any": to_grid(ly_src, grid, "average", transform=lambda a: a > 0),
           "loss_recent": to_grid(ly_src, grid, "average", transform=lambda a: a >= rf),
           "last_loss_year": to_grid(ly_src, grid, "max")}
    out["last_loss_year"] = np.where(out["last_loss_year"] > 0, out["last_loss_year"] + 2000, 0)
    out["yearly_ha"] = yearly_loss(ly_src, grid)
    return out


def yearly_loss(sources, grid: Grid) -> dict[int, float]:
    """Hansen-mapped loss area per year inside the grid (ha). Pixel counts times pixel area: a map total, not a
    statistical area estimate (Hansen et al. advise sample-based estimates for official area figures)."""
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    totals: dict[int, float] = {}
    with rasterio.Env(**GDAL_ENV):
        for src_path in sources:
            try:
                with _open(src_path) as src:
                    b = transform_bounds(grid.crs, src.crs, *_grid_bounds(grid), densify_pts=21)
                    win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
                    a = src.read(1, window=win, boundless=True, fill_value=0)
                    tr = src.window_transform(win)
                    lat = tr.f + (np.arange(a.shape[0]) + 0.5) * tr.e
                    if src.crs.is_geographic:
                        px = (abs(tr.a) * 111_320 * np.cos(np.radians(lat))) * (abs(tr.e) * 110_574) / 1e4
                    else:
                        px = np.full(a.shape[0], abs(tr.a * tr.e) / 1e4)
                    for yr in np.unique(a[a > 0]):
                        totals[2000 + int(yr)] = totals.get(2000 + int(yr), 0.0) + float(((a == yr) * px[:, None]).sum())
            except (rasterio.errors.RasterioError, OSError, ValueError):
                continue
    return dict(sorted(totals.items()))


def cci_biomass(grid: Grid, year: int | None = None, files: dict | None = None,
                key: str = "agb") -> tuple[np.ndarray, np.ndarray | None, int, str]:
    """ESA CCI above-ground biomass (Mg/ha) and its standard deviation for ``year`` (default: the newest
    available, trying earlier years if a file is missing). Returns (agb, sd or None, year, source)."""
    files = files or {}
    if files.get(key):
        agb = to_grid([files[key]], grid, "average")
        sd = to_grid([files[key + "_sd"]], grid, "average") if files.get(key + "_sd") else None
        return agb, sd, int(year or CCI_LAST_YEAR), str(files[key])
    bounds = grid.lonlat_bounds(0.01)
    errors = []
    for y in ([year] if year else range(CCI_LAST_YEAR, CCI_LAST_YEAR - 4, -1)):
        try:
            agb = to_grid(cci_urls(bounds, y), grid, "average")
        except OSError as e:
            errors.append(f"{y}: {e}")
            continue
        try:
            sd = to_grid(cci_urls(bounds, y, sd=True), grid, "average")
        except OSError:
            sd = None
        return agb, sd, y, cci_urls(bounds, y)[0]
    raise OSError("ESA CCI Biomass could not be read (" + "; ".join(errors)[:300] + ")")

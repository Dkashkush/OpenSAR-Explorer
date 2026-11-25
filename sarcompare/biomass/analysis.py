# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Biomass from L-band HV backscatter, and forest loss.

Biomass. Cross-polarised (HV) L-band backscatter rises with above-ground biomass (AGB) because the radar wave
scatters off branches and trunks, then levels off ("saturates") in dense forest, typically at 100-150 Mg/ha.
The relation is calibrated over the area itself against an independent biomass map (ESA CCI Biomass) with the
semi-empirical model widely used for L-band (e.g. Mitchard et al. 2009, Yu & Saatchi 2016)::

    HV = a * (1 - exp(-AGB / b)) + c          (linear power; c = bare ground, a + c = dense forest)

and inverted for every cell. Where HV is within 10 % of its dense-forest level (AGB > b * ln 10), small HV
changes would mean huge biomass changes, so those cells are reported as "at least" the saturation level instead.
The fit uses 70 % of the area (2 km blocks, so neighbouring cells do not leak between the two parts) and is
checked on the other 30 %.

Forest loss. Clearing removes the trunks and branches, and HV drops by several dB. Three kinds of zones:

* new: HV dropped by at least ``drop_db`` between the first and the later NISAR images of the period, from
  forest-like to open-land-like values (dated between two acquisitions);
* unmapped: forest in 2021 (ESA WorldCover) that NISAR now sees as open land, and that Hansen et al. have not
  mapped as lost by 2025 (cleared in 2026 before the first image, or missed);
* hansen: loss mapped by Hansen et al. since 2021, with what NISAR sees there now (still open, or growing back).

The HV level that separates forest from open land is learned from the area too, between intact forest and
Hansen-mapped recent loss, and checked on the held-out blocks.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from ..notes import GOOD, INFO, WARN, Note

CARBON_FRACTION = 0.47  # IPCC default carbon fraction of dry wood
CO2_PER_C = 44.0 / 12.0
SATURATION_SHARE = 0.9  # of the dynamic range: beyond it, HV no longer tracks biomass usefully


def to_db(lin):
    lin = np.asarray(lin, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(lin > 0, 10 * np.log10(lin), np.nan)


def from_db(db):
    return np.power(10.0, np.asarray(db, dtype="float64") / 10)


def spatial_blocks(shape: tuple[int, int], block_cells: int, test_share: float = 0.3, seed: int = 7) -> np.ndarray:
    """True for cells in the held-out (test) blocks."""
    ny, nx = -(-shape[0] // block_cells), -(-shape[1] // block_cells)
    pick = np.random.default_rng(seed).random((ny, nx)) < test_share
    if pick.all() or not pick.any():  # tiny areas: still split
        pick = np.zeros((ny, nx), bool)
        pick.flat[::3] = True
    return np.kron(pick, np.ones((block_cells, block_cells), bool))[: shape[0], : shape[1]]


def normalise_dates(cube_db: np.ndarray, stable: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Remove each date's overall offset over stable forest (rain, soil moisture, small calibration changes
    move every forest pixel together); keeps the average level. Returns (cube, offsets in dB)."""
    if not stable.any():
        return cube_db, np.zeros(cube_db.shape[0])
    med = np.array([np.nanmedian(c[stable]) if np.isfinite(c[stable]).any() else np.nan for c in cube_db])
    offsets = np.nan_to_num(med - np.nanmedian(med))
    return cube_db - offsets[:, None, None], offsets


def _metrics(pred: np.ndarray, ref: np.ndarray) -> dict:
    ok = np.isfinite(pred) & np.isfinite(ref)
    n = int(ok.sum())
    if n < 3:
        return {"n": n, "r": float("nan"), "rmse": float("nan"), "bias": float("nan"), "rel_rmse": float("nan")}
    p, r = pred[ok], ref[ok]
    rmse = float(np.sqrt(np.mean((p - r) ** 2)))
    return {"n": n, "r": float(np.corrcoef(p, r)[0, 1]) if p.std() > 0 and r.std() > 0 else float("nan"),
            "rmse": rmse, "bias": float(np.mean(p - r)), "rel_rmse": rmse / float(np.mean(r)) if r.mean() > 0 else float("nan")}


@dataclass
class AGBModel:
    a: float
    b: float
    c: float
    sat_agb: float  # Mg/ha; estimates above it are lower bounds
    max_ref: float  # densest reference biomass used in the fit
    curve: list[dict]  # binned medians used in the fit: agb, hv_db, n
    train: dict
    test: dict
    test_below_sat: dict
    reference: str = ""
    saturates_in_range: bool = True

    def hv(self, agb):
        return self.a * (1 - np.exp(-np.asarray(agb, dtype="float64") / self.b)) + self.c

    @property
    def dynamic_range_db(self) -> float:
        return float(10 * math.log10((self.a + self.c) / self.c))

    def invert(self, hv_lin) -> tuple[np.ndarray, np.ndarray]:
        """(AGB in Mg/ha, saturated) for HV in linear power; NaN where HV is NaN."""
        hv_lin = np.asarray(hv_lin, dtype="float64")
        x = (hv_lin - self.c) / self.a
        x_sat = 1 - math.exp(-self.sat_agb / self.b)
        with np.errstate(invalid="ignore", divide="ignore"):
            agb = -self.b * np.log1p(-np.clip(x, 0, x_sat))
        saturated = np.isfinite(hv_lin) & (x >= x_sat)
        agb = np.where(np.isfinite(hv_lin), np.where(saturated, self.sat_agb, agb), np.nan)
        return agb.astype("float32"), saturated

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()}


def fit_agb(hv_db: np.ndarray, agb_ref: np.ndarray, usable: np.ndarray, test: np.ndarray,
            reference: str = "", min_samples: int = 150) -> tuple[AGBModel | None, list[Note]]:
    """Calibrate the HV-biomass model on the training cells and check it on the held-out cells."""
    from scipy.optimize import curve_fit

    ok = usable & np.isfinite(hv_db) & np.isfinite(agb_ref) & (agb_ref >= 0)
    tr, te = ok & ~test, ok & test
    if tr.sum() < min_samples:
        return None, [Note("biomass", WARN, f"Only {int(tr.sum())} cells have both NISAR backscatter and reference "
                                            "biomass; too few to calibrate a biomass model, so only the HV "
                                            "backscatter map is shown.")]
    agb, hv = agb_ref[tr].astype("float64"), from_db(hv_db[tr])
    edges = np.unique(np.quantile(agb, np.linspace(0, 1, 25)))
    curve = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (agb >= lo) & ((agb < hi) if hi < edges[-1] else (agb <= hi))
        if sel.sum() >= 15:
            curve.append({"agb": float(np.median(agb[sel])), "hv": float(np.median(hv[sel])), "n": int(sel.sum())})
    if len(curve) < 4 or np.ptp([c["agb"] for c in curve]) < 20:
        return None, [Note("biomass", WARN, "The reference biomass barely varies over this area (mostly one kind of "
                                            "land), so the radar cannot be calibrated here. Choose an area with "
                                            "both forest and open land.")]
    xa = np.array([c["agb"] for c in curve])
    ya = np.array([c["hv"] for c in curve])
    w = 1 / np.sqrt([c["n"] for c in curve])

    def f(x, a, b, c):
        return a * (1 - np.exp(-x / b)) + c

    try:
        p0 = [max(ya.max() - ya.min(), 1e-4), max(30.0, float(np.median(xa))), max(ya.min(), 1e-5)]
        (a, b, c), _ = curve_fit(f, xa, ya, p0=p0, sigma=w * ya, bounds=([1e-6, 5.0, 1e-6], [2.0, 3000.0, 2.0]),
                                 maxfev=20000)
    except (RuntimeError, ValueError) as e:
        return None, [Note("biomass", WARN, f"The biomass model could not be fitted ({e}).")]
    max_ref = float(np.percentile(agb, 99))
    sat = b * math.log(1 / (1 - SATURATION_SHARE))
    in_range = sat <= max_ref
    model = AGBModel(float(a), float(b), float(c), float(min(sat, max_ref)), max_ref,
                     [{"agb": d["agb"], "hv_db": float(10 * math.log10(d["hv"])), "n": d["n"]} for d in curve],
                     {}, {}, {}, reference, in_range)
    pred_tr, _ = model.invert(from_db(hv_db[tr]))
    pred_te, _ = model.invert(from_db(hv_db[te]))
    model.train = _metrics(pred_tr, agb_ref[tr])
    model.test = _metrics(pred_te, agb_ref[te])
    below = agb_ref[te] <= model.sat_agb
    model.test_below_sat = _metrics(pred_te[below], agb_ref[te][below])
    notes = [Note("biomass", INFO,
                  f"Calibrated NISAR HV backscatter against {reference or 'the reference biomass map'} on "
                  f"{model.train['n']:,} cells: HV rises by {model.dynamic_range_db:.1f} dB from open ground to "
                  f"dense forest.")]
    if in_range:
        notes.append(Note("biomass", INFO,
                          f"L-band HV saturates at about {model.sat_agb:.0f} Mg/ha here: denser forest is shown as "
                          f"'at least {model.sat_agb:.0f} Mg/ha'."))
    else:
        notes.append(Note("biomass", INFO,
                          f"No saturation is visible up to {max_ref:.0f} Mg/ha, the densest reference biomass "
                          "in the area; estimates above that are capped there, since they cannot be checked."))
    t, tb = model.test, model.test_below_sat
    if t["n"] >= 30:
        level = GOOD if (tb["r"] >= 0.6 and tb["rel_rmse"] <= 0.6) else (INFO if tb["r"] >= 0.4 else WARN)
        notes.append(Note("biomass", level,
                          f"Check on {t['n']:,} held-out cells (30 % of the area, 2 km blocks): r = {t['r']:.2f}, "
                          f"RMSE {t['rmse']:.0f} Mg/ha, bias {t['bias']:+.0f} Mg/ha; below saturation r = "
                          f"{tb['r']:.2f}, RMSE {tb['rmse']:.0f} Mg/ha ({tb['rel_rmse']:.0%})."))
    notes.append(Note("biomass", INFO,
                      "ESA CCI Biomass is itself partly made from L-band radar (ALOS-2 PALSAR-2), so this agreement "
                      "is a consistency check, not fully independent validation; field plots (e.g. the Forest "
                      "Survey of India inventory) are the real test."))
    return model, notes


@dataclass
class Separation:
    """HV level separating forest from cleared land, learned on training blocks, checked on held-out ones."""

    threshold_db: float
    forest_db: float  # median HV of intact forest
    cleared_db: float  # median HV of the cleared reference
    reference: str
    n_forest: int
    n_cleared: int
    detection: float  # share of held-out cleared cells below the threshold
    false_alarm: float  # share of held-out intact-forest cells below the threshold
    balanced_accuracy: float

    def to_dict(self) -> dict:
        return asdict(self)


def separate(hv_db: np.ndarray, forest: np.ndarray, cleared: np.ndarray, test: np.ndarray,
             reference: str) -> Separation | None:
    f_ok, c_ok = forest & np.isfinite(hv_db), cleared & np.isfinite(hv_db)
    if f_ok.sum() < 20 or c_ok.sum() < 20:
        return None
    ftr, ctr = hv_db[f_ok & ~test], hv_db[c_ok & ~test]
    if ftr.size < 10 or ctr.size < 10:
        ftr, ctr = hv_db[f_ok], hv_db[c_ok]
    cands = np.percentile(np.concatenate([ftr, ctr]), np.linspace(1, 99, 197))
    ba = [(np.mean(ctr < t) + np.mean(ftr >= t)) / 2 for t in cands]
    thr = float(cands[int(np.argmax(ba))])
    fte, cte = hv_db[f_ok & test], hv_db[c_ok & test]
    if fte.size < 10 or cte.size < 10:
        fte, cte = hv_db[f_ok], hv_db[c_ok]
    det, fa = float(np.mean(cte < thr)), float(np.mean(fte < thr))
    return Separation(thr, float(np.median(hv_db[f_ok])), float(np.median(hv_db[c_ok])), reference,
                      int(f_ok.sum()), int(c_ok.sum()), det, fa, (det + 1 - fa) / 2)


def detect_drops(cube_db: np.ndarray, forest: np.ndarray, threshold_db: float, drop_db: float = 3.0) -> dict:
    """Cells whose HV fell by at least ``drop_db`` from forest-like to open-land-like values during the period.

    The date of the change is the split of the time series into 'before' and 'after' with the largest
    change-point score (difference of the two means, weighted by sqrt(n_before * n_after / n), as in a two-sample
    t statistic); the size of the drop is then measured with medians, which one odd image cannot sway.
    'confirmed' = seen on at least two images after the change."""
    import warnings

    t = cube_db.shape[0]
    shape = cube_db.shape[1:]
    best = np.full(shape, -np.inf)
    k_best = np.full(shape, -1, dtype=int)
    valid = np.isfinite(cube_db)
    filled = np.where(valid, cube_db, 0.0)
    csum, ccount = np.cumsum(filled, axis=0), np.cumsum(valid, axis=0)
    total, n = csum[-1], ccount[-1]
    for k in range(1, t):
        n1, n2 = ccount[k - 1], n - ccount[k - 1]
        with np.errstate(invalid="ignore", divide="ignore"):
            m1, m2 = csum[k - 1] / n1, (total - csum[k - 1]) / n2
            score = np.where((n1 > 0) & (n2 > 0), (m1 - m2) * np.sqrt(n1 * n2 / np.maximum(n, 1)), -np.inf)
        better = score > best
        best, k_best = np.where(better, score, best), np.where(better, k, k_best)
    before = np.full(shape, np.nan)
    after = np.full(shape, np.nan)
    n_after = np.zeros(shape, dtype=int)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN cells
        for k in range(1, t):
            sel = k_best == k
            if sel.any():
                before = np.where(sel, np.nanmedian(cube_db[:k], axis=0), before)
                after = np.where(sel, np.nanmedian(cube_db[k:], axis=0), after)
                n_after = np.where(sel, valid[k:].sum(axis=0), n_after)
    drop = before - after
    detected = forest & (np.nan_to_num(drop, nan=-np.inf) >= drop_db) & (after < threshold_db) & \
        (before >= threshold_db)
    return {"drop": drop, "k": np.where(detected, k_best, -1), "detected": detected,
            "confirmed": detected & (n_after >= 2), "before": before, "after": after}


def open_now(cube_db: np.ndarray, threshold_db: float, margin_db: float = 1.0, last: int = 3,
             share: float = 0.75) -> np.ndarray:
    """Cells that look like open land on the latest images: at least ``share`` of the last ``last`` images
    below the threshold, and their median at least ``margin_db`` below it."""
    import warnings

    recent = cube_db[-last:]
    valid = np.isfinite(recent).sum(axis=0)
    below = (recent < threshold_db).sum(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(recent, axis=0)
    return (valid > 0) & (below >= np.ceil(share * np.maximum(valid, 1))) & (med < threshold_db - margin_db)


KINDS = {
    "new": "New clearing during the NISAR period",
    "unmapped": "Forest lost since 2021, not yet in Hansen maps",
    "hansen": "Loss mapped by Hansen et al. 2021-2025",
}


@dataclass
class Zone:
    id: int
    kind: str
    area_ha: float
    lat: float
    lon: float
    when: str
    hv_before_db: float | None = None
    hv_after_db: float | None = None
    agb_before: float | None = None  # Mg/ha
    agb_after: float | None = None
    biomass_lost_t: float | None = None
    hansen_share: float = 0.0  # share of the zone Hansen maps as lost since 2021
    open_share: float | None = None  # share NISAR sees as open land now
    confirmed: bool = True
    change_start: date | None = None
    change_end: date | None = None
    extra: dict = field(default_factory=dict)

    @property
    def carbon_t(self) -> float | None:
        return None if self.biomass_lost_t is None else self.biomass_lost_t * CARBON_FRACTION

    @property
    def co2_t(self) -> float | None:
        return None if self.carbon_t is None else self.carbon_t * CO2_PER_C

    def to_row(self) -> dict:
        def r(v, nd=1):
            return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(v, nd)

        return {"zone": self.id, "type": KINDS.get(self.kind, self.kind), "area_ha": r(self.area_ha),
                "latitude": round(self.lat, 5), "longitude": round(self.lon, 5), "when": self.when,
                "hv_before_db": r(self.hv_before_db), "hv_after_db": r(self.hv_after_db),
                "biomass_before_mg_ha": r(self.agb_before, 0), "biomass_lost_t": r(self.biomass_lost_t, 0),
                "co2_t": r(self.co2_t, 0), "hansen_share": r(self.hansen_share, 2),
                "open_now_share": r(self.open_share, 2), "confirmed": self.confirmed}


def label_zones(mask: np.ndarray, min_cells: int) -> tuple[np.ndarray, int]:
    from scipy import ndimage

    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    if n == 0:
        return lab, 0
    sizes = np.bincount(lab.ravel())
    small = sizes < min_cells
    small[0] = True
    lab = np.where(small[lab], 0, lab)
    ids = np.unique(lab[lab > 0])
    remap = np.zeros(sizes.size, dtype=int)
    remap[ids] = np.arange(1, ids.size + 1)
    return remap[lab], int(ids.size)


def _mean(values: np.ndarray | None, sel: np.ndarray) -> float | None:
    if values is None:
        return None
    v = values[sel]
    v = v[np.isfinite(v)]
    return float(v.mean()) if v.size else None


def zones_from(mask: np.ndarray, kind: str, lon: np.ndarray, lat: np.ndarray, cell_ha: float, min_cells: int,
               start_id: int = 1, when=None, before_db=None, after_db=None, agb_before=None, agb_after=None,
               hansen_recent=None, open_mask=None, confirmed=None) -> tuple[list[Zone], np.ndarray]:
    """Connected patches (8-neighbour) of ``mask`` of at least ``min_cells`` cells, with their statistics.
    ``when`` is a function of the patch's cells returning (text, start, end)."""
    lab, n = label_zones(mask, min_cells)
    zones = []
    for k in range(1, n + 1):
        sel = lab == k
        cells = int(sel.sum())
        text, d0, d1 = when(sel) if when else ("", None, None)
        ab, aa = _mean(agb_before, sel), _mean(agb_after, sel)
        lost = None
        if ab is not None:
            lost = max(ab - (aa if aa is not None else 0.0), 0.0) * cells * cell_ha
        zones.append(Zone(
            id=start_id + k - 1, kind=kind, area_ha=cells * cell_ha, lat=float(lat[sel].mean()),
            lon=float(lon[sel].mean()), when=text, hv_before_db=_mean(before_db, sel), hv_after_db=_mean(after_db, sel),
            agb_before=ab, agb_after=aa, biomass_lost_t=lost,
            hansen_share=float(np.nanmean(hansen_recent[sel] >= 0.3)) if hansen_recent is not None else 0.0,
            open_share=float(open_mask[sel].mean()) if open_mask is not None else None,
            confirmed=bool(confirmed[sel].mean() >= 0.5) if confirmed is not None else True,
            change_start=d0, change_end=d1))
        lab_k = sel
        zones[-1].extra["cells"] = int(lab_k.sum())
    return zones, lab

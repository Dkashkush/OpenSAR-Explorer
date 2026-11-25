# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Forests & Biomass run for one area: find NISAR GCOV images, read them, add the reference forest data, map
biomass and forest loss, and write maps, tables and a report."""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np

from ..aoi import AOI
from ..notes import GOOD, INFO, WARN, Note
from ..products import Product
from . import analysis as A
from . import reference as R
from .gcov import Backscatter, choose_geometry, read_gcov, scan_gcov, search_gcov, thin_dates

GCOV_FIRST = date(2026, 6, 1)  # first GCOV products over India in the ASF archive (provisional from July 2026)


class NoGCOVError(RuntimeError):
    """No usable NISAR GCOV image over the area and period."""


@dataclass
class ForestConfig:
    aoi: list | str | None = None
    name: str = "forest_area"
    start: date | None = None
    end: date | None = None
    resolution_m: float = 100.0
    frequency: str = "A"
    flight_direction: str | None = None
    max_dates: int = 8
    gcov_source: str = "ASF"  # ASF (search and read remotely) or LOCAL (files in gcov_dir)
    gcov_dir: str | None = None
    agb_year: int | None = None  # ESA CCI Biomass year to calibrate with (default: newest)
    baseline_year: int = 2020  # ESA CCI Biomass year for 'biomass before the loss'
    recent_from: int = 2021
    drop_db: float = 3.0  # HV fall that counts as clearing
    min_zone_ha: float = 2.0
    forest_share: float = 0.5  # share of a cell in tree cover (WorldCover 2021) to call it forest
    reference_files: dict = field(default_factory=dict)  # local files instead of the web archives (demo, tests)
    output_dir: str = "outputs"
    seed: int = 7
    extra: dict = field(default_factory=dict)
    earthdata_token: str | None = field(default=None, repr=False)  # per run; never written out

    def __post_init__(self):
        for k in ("start", "end"):
            if isinstance(getattr(self, k), str):
                setattr(self, k, date.fromisoformat(getattr(self, k)))
        if self.gcov_source not in ("ASF", "LOCAL"):
            raise ValueError("gcov_source must be ASF or LOCAL")
        if self.gcov_source == "LOCAL" and not self.gcov_dir:
            raise ValueError("gcov_dir is required when gcov_source is LOCAL")
        if self.resolution_m < 20:
            raise ValueError("resolution_m must be at least 20 m (the GCOV posting is 10-20 m)")

    def get_aoi(self) -> AOI:
        if self.aoi is None:
            raise ValueError("No area configured")
        return AOI.parse(self.aoi, name=self.name)

    @property
    def run_dir(self) -> Path:
        return Path(self.output_dir) / self.name

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("earthdata_token", None)
        d["start"] = str(self.start) if self.start else None
        d["end"] = str(self.end) if self.end else None
        return d


@dataclass
class ForestEvent:
    stage: str
    message: str
    notes: list[Note] = field(default_factory=list)
    progress: float | None = None


@dataclass
class ForestResult:
    config: ForestConfig
    products: list[Product] = field(default_factory=list)
    scenes: list[Backscatter] = field(default_factory=list)
    grid: R.Grid | None = None
    hv_db: np.ndarray | None = None  # (date, y, x), date offsets removed
    hh_db: np.ndarray | None = None
    offsets_db: np.ndarray | None = None
    hv_all_db: np.ndarray | None = None  # median of all dates
    hv_now_db: np.ndarray | None = None  # median of the latest images
    ref: dict = field(default_factory=dict)
    forest: np.ndarray | None = None  # forest in 2021
    intact: np.ndarray | None = None
    test: np.ndarray | None = None
    model: A.AGBModel | None = None
    agb: np.ndarray | None = None
    saturated: np.ndarray | None = None
    separation: A.Separation | None = None
    drops: dict | None = None
    open_now: np.ndarray | None = None
    zones: list[A.Zone] = field(default_factory=list)
    zone_map: np.ndarray | None = None  # 1 new, 2 unmapped, 3 hansen
    stats: dict = field(default_factory=dict)
    notes: list[Note] = field(default_factory=list)
    figures: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)

    @property
    def dates(self) -> list[date]:
        return [s.date for s in self.scenes]

    @property
    def synthetic(self) -> bool:
        return bool(self.config.extra.get("synthetic"))


ZONE_CODES = {"new": 1, "unmapped": 2, "hansen": 3}


class ForestPipeline:
    def __init__(self, cfg: ForestConfig, on_event: Callable[[ForestEvent], None] | None = None):
        self.cfg = cfg
        self.aoi = cfg.get_aoi()
        self.result = ForestResult(config=cfg)
        self.on_event = on_event or (lambda e: None)
        self._asf_session = None

    def emit(self, stage: str, message: str, notes: list[Note] | None = None, progress=None):
        notes = notes or []
        self.result.notes.extend(notes)
        self.on_event(ForestEvent(stage, message, notes, progress))

    # ------------------------------------------------------------------ search
    def search(self) -> list[Product]:
        cfg = self.cfg
        if cfg.gcov_source == "LOCAL":
            found = scan_gcov(cfg.gcov_dir)
            found = [p for p in found if (not cfg.start or p.date1 >= cfg.start) and (not cfg.end or p.date1 <= cfg.end)]
            if cfg.flight_direction:
                found = [p for p in found if p.flight_direction == cfg.flight_direction]
        else:
            found = search_gcov(self.aoi, cfg.start, cfg.end, cfg.flight_direction)
        if not found:
            first = "NISAR GCOV images over India start in June 2026 (provisional; validated from November 2026)"
            raise NoGCOVError(f"No NISAR GCOV images were found over this area for the dates chosen. {first}; "
                              "choose dates from then on, or a slightly different area.")
        chosen, notes = choose_geometry(found)
        kept = thin_dates(chosen, cfg.max_dates)
        if len(kept) < len(chosen):
            notes.append(Note("search", INFO, f"{len(chosen)} images are available on this track; {len(kept)} spread "
                                              "over the period are used (the first and the last included), to keep "
                                              "the run quick. Raise 'Images to use' for more."))
        if len(kept) < 3:
            notes.append(Note("search", WARN, f"Only {len(kept)} image(s): biomass can be mapped, but new clearing "
                                              "needs at least three images to be dated and confirmed."))
        self.result.products = kept
        self.emit("search", f"Selected {len(kept)} NISAR GCOV images ({kept[0].date1} to {kept[-1].date1})", notes)
        return kept

    # ------------------------------------------------------------------ load
    def _session(self):
        if self._asf_session is None:
            from ..download import make_session

            self._asf_session = make_session(self.cfg.earthdata_token)
        return self._asf_session

    def _read(self, p: Product) -> Backscatter:
        cfg = self.cfg
        if p.local_path is not None:
            return read_gcov(p.local_path, self.aoi, cfg.resolution_m, cfg.frequency, name=p.name)
        from ..remote import open_remote

        with open_remote(p.url, self._session()) as f:
            return read_gcov(f, self.aoi, cfg.resolution_m, cfg.frequency, name=p.name)

    def load(self) -> None:
        from ..remote import AccessError

        r, cfg = self.result, self.cfg
        if any(p.local_path is None for p in r.products):
            self.emit("load", f"Reading {len(r.products)} NISAR images directly from ASF, only the part over your area",
                      [Note("load", INFO, "Each GCOV file is several GB; only the few tens of MB over your area are "
                                          "transferred, then averaged to "
                                          f"{cfg.resolution_m:.0f} m cells (this also removes radar speckle).")])
        scenes, skipped = [], []
        for k, p in enumerate(r.products):
            self.on_event(ForestEvent("load", f"{k + 1}/{len(r.products)}: NISAR {p.date1}", progress=k / len(r.products)))
            try:
                scenes.append(self._read(p))
            except AccessError:
                raise
            except (ValueError, KeyError, OSError, RuntimeError) as e:
                skipped.append(Note("load", WARN, f"Could not use NISAR {p.date1} ({p.name}): {e}"))
        if not scenes:
            raise NoGCOVError("None of the NISAR images could be read. " + " ".join(n.text for n in skipped[:2]))
        scenes.sort(key=lambda s: s.date)
        grid = R.Grid.around(self.aoi, str(scenes[0].hv.rio.crs), cfg.resolution_m)
        hv, hh = [], []
        for s in scenes:
            hv.append(self._on_grid(s.hv, grid))
            hh.append(self._on_grid(s.hh, grid) if s.hh is not None else np.full(grid.shape, np.nan, "float32"))
        r.scenes, r.grid = scenes, grid
        r.hv_db = A.to_db(np.stack(hv)).astype("float32")
        r.hh_db = A.to_db(np.stack(hh)).astype("float32") if any(s.hh is not None for s in scenes) else None
        notes = skipped + [n for s in scenes for n in s.notes]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = float(np.nanmedian(r.hv_db))
        notes.append(Note("load", INFO, f"Read {len(scenes)} images from {scenes[0].date} to {scenes[-1].date}; median "
                                        f"HV backscatter over the area {med:.1f} dB (radiometrically terrain-"
                                        "corrected gamma-naught)."))
        self.emit("load", f"Read {len(scenes)} NISAR images", notes, progress=1.0)

    @staticmethod
    def _on_grid(da, grid: R.Grid) -> np.ndarray:
        if str(da.rio.crs) == grid.crs:
            out = da.reindex(x=grid.x, y=grid.y, method="nearest", tolerance=grid.res / 4)
        else:
            out = da.rio.reproject_match(grid.da(np.zeros(grid.shape, "float32"), "t"), resampling=5)  # average
        return np.asarray(out.values, dtype="float32")

    # ------------------------------------------------------------------ reference data
    def reference(self) -> None:
        r, cfg, grid = self.result, self.cfg, self.result.grid
        files = cfg.reference_files or {}
        offline = bool(files)  # local files given (demo, tests, offline work): the web archives are not used
        notes = []
        if offline and not files.get("worldcover"):
            notes.append(Note("reference", INFO, "No ESA WorldCover file given; Hansen tree cover is used instead."))
        try:
            if offline and not files.get("worldcover"):
                raise LookupError
            r.ref["worldcover"] = R.worldcover(grid, [files["worldcover"]] if files.get("worldcover") else None)
            wc = r.ref["worldcover"]["forest"]
            notes.append(Note("reference", INFO, f"ESA WorldCover 2021: {np.nanmean(wc >= cfg.forest_share):.0%} of the "
                                                 "area was forest (tree cover or mangroves) in 2021."))
        except LookupError:
            pass
        except OSError as e:
            notes.append(Note("reference", WARN, f"ESA WorldCover could not be read ({str(e)[:160]}); Hansen tree cover "
                                                 "is used for the forest mask instead."))
        try:
            hfiles = {k: [files[k]] for k in ("treecover2000", "lossyear") if files.get(k)}
            if offline and len(hfiles) < 2:
                raise LookupError
            r.ref["hansen"] = R.hansen(grid, hfiles or None, cfg.recent_from)
            yearly = r.ref["hansen"]["yearly_ha"]
            recent = {y: v for y, v in yearly.items() if y >= cfg.recent_from}
            if recent:
                peak = max(recent, key=recent.get)
                notes.append(Note("reference", INFO,
                                  f"Hansen et al. map {sum(recent.values()):,.0f} ha of tree-cover loss in the area "
                                  f"from {cfg.recent_from} to {R.HANSEN_LAST_YEAR} (most in {peak}: "
                                  f"{recent[peak]:,.0f} ha). Map totals from pixel counts, not a statistical area "
                                  "estimate."))
            else:
                notes.append(Note("reference", INFO, f"Hansen et al. map no tree-cover loss in the area since "
                                                     f"{cfg.recent_from}."))
        except LookupError:
            pass
        except OSError as e:
            notes.append(Note("reference", WARN, f"Hansen Global Forest Change could not be read ({str(e)[:160]})."))
        try:
            if offline and not files.get("agb"):
                raise LookupError
            agb, sd, year, src = R.cci_biomass(grid, cfg.agb_year, files)
            r.ref["cci"] = {"agb": agb, "sd": sd, "year": year, "source": src}
            notes.append(Note("reference", INFO, f"ESA CCI Biomass {year} ({R.CCI_VERSION}) read for calibration."))
            if cfg.baseline_year and cfg.baseline_year != year and (files.get("agb_baseline") or not offline):
                try:
                    base, _, by, _ = R.cci_biomass(grid, cfg.baseline_year, {k.replace("agb_baseline", "agb"): v
                                                                             for k, v in files.items()
                                                                             if k.startswith("agb_baseline")})
                    r.ref["cci_baseline"] = {"agb": base, "year": by}
                except OSError:
                    pass
        except LookupError:
            pass
        except OSError as e:
            notes.append(Note("reference", WARN, f"ESA CCI Biomass could not be read ({str(e)[:160]}); NISAR "
                                                 "backscatter is shown, but not converted to biomass."))
        self.emit("reference", "Added independent forest data", notes)

    # ------------------------------------------------------------------ masks, forest loss
    def _masks(self):
        r, cfg = self.result, self.cfg
        shape = r.grid.shape
        wc, hz = r.ref.get("worldcover"), r.ref.get("hansen")
        if wc is not None:
            forest = np.nan_to_num(wc["forest"]) >= cfg.forest_share
            intact = np.nan_to_num(wc["forest"]) >= 0.7
            water = np.nan_to_num(wc["water"]) > 0.2
            built = np.nan_to_num(wc["built"]) > 0.3
        elif hz is not None:
            forest = (np.nan_to_num(hz["treecover2000"]) >= 30) & (np.nan_to_num(hz["loss_any"]) < 0.5)
            intact = np.nan_to_num(hz["treecover2000"]) >= 60
            water = built = np.zeros(shape, bool)
        else:
            forest = intact = water = built = np.zeros(shape, bool)
        if hz is not None:
            intact &= (np.nan_to_num(hz["treecover2000"]) >= 50) & (np.nan_to_num(hz["loss_any"]) < 0.05)
        return forest, intact & forest, water, built

    def forest_change(self) -> None:
        r, cfg = self.result, self.cfg
        forest, intact, water, built = self._masks()
        r.forest, r.intact = forest, intact
        r.hv_db, r.offsets_db = A.normalise_dates(r.hv_db, intact if intact.sum() >= 50 else forest)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            r.hv_all_db = np.nanmedian(r.hv_db, axis=0)
            r.hv_now_db = np.nanmedian(r.hv_db[-min(3, len(r.scenes)):], axis=0)
        r.test = A.spatial_blocks(r.grid.shape, max(3, round(2000 / cfg.resolution_m)), seed=cfg.seed)
        notes = []
        if len(r.scenes) > 1 and np.ptp(r.offsets_db) > 1.0:
            notes.append(Note("change", INFO, f"Forest backscatter shifted by up to {np.ptp(r.offsets_db):.1f} dB "
                                              "between dates (rain and soil moisture, e.g. the monsoon); that common "
                                              "shift was removed before looking for clearing."))
        hz = r.ref.get("hansen")
        cleared, ref_name = None, ""
        if hz is not None:
            cleared = (np.nan_to_num(hz["loss_recent"]) >= 0.5) & ~water
            ref_name = f"Hansen-mapped loss {cfg.recent_from}-{R.HANSEN_LAST_YEAR}"
        if (cleared is None or cleared.sum() < 20) and r.ref.get("worldcover") is not None:
            wc = r.ref["worldcover"]
            cleared = (np.nan_to_num(wc["open"] + wc["crop"]) >= 0.8) & (np.nan_to_num(wc["tree"]) < 0.1)
            ref_name = "open land and fields (ESA WorldCover)"
        if cleared is None or not intact.any():
            self.emit("change", "Forest loss could not be mapped (no reference forest data)",
                      notes + [Note("change", WARN, "Without WorldCover or Hansen data, NISAR cannot be told which "
                                                    "backscatter means forest here, so forest loss is not mapped.")])
            return
        sep = A.separate(r.hv_all_db, intact, cleared, r.test, ref_name)
        r.separation = sep
        if sep is None:
            self.emit("change", "Too little forest or cleared land to learn the forest/open-land level",
                      notes + [Note("change", WARN, "The area has too little intact forest or cleared land to learn "
                                                    "what each looks like to NISAR; forest loss is not mapped.")])
            return
        gap = sep.forest_db - sep.cleared_db
        level = GOOD if sep.balanced_accuracy >= 0.85 else (INFO if sep.balanced_accuracy >= 0.7 else WARN)
        notes.append(Note("change", level,
                          f"NISAR tells forest from cleared land: intact forest {sep.forest_db:.1f} dB, {ref_name} "
                          f"{sep.cleared_db:.1f} dB (HV, {gap:.1f} dB apart). On held-out blocks it sees "
                          f"{sep.detection:.0%} of the cleared cells as open land and calls {sep.false_alarm:.0%} of "
                          f"intact forest open (balanced accuracy {sep.balanced_accuracy:.0%})."))
        if len(r.scenes) >= 2:
            r.drops = A.detect_drops(r.hv_db, forest, sep.threshold_db, cfg.drop_db)
        r.open_now = A.open_now(r.hv_db, sep.threshold_db) & ~water & ~built
        self.emit("change", "Compared NISAR with mapped forest and forest loss", notes)

    # ------------------------------------------------------------------ biomass
    def biomass(self) -> None:
        r, cfg = self.result, self.cfg
        cci = r.ref.get("cci")
        if cci is None or r.hv_all_db is None:
            return
        _, _, water, built = self._masks()
        usable = ~water & ~built
        hz = r.ref.get("hansen")
        if hz is not None:
            usable &= np.nan_to_num(hz["loss_recent"]) < 0.1  # changed after the reference map was made
        if r.drops is not None:
            usable &= ~r.drops["detected"]
        model, notes = A.fit_agb(r.hv_all_db, cci["agb"], usable, r.test, f"ESA CCI Biomass {cci['year']}")
        r.model = model
        if model is not None:
            r.agb, r.saturated = model.invert(A.from_db(r.hv_now_db))
            f = r.forest & np.isfinite(r.agb)
            fc = r.forest & np.isfinite(cci["agb"])
            if fc.any():
                r.stats["cci_agb_mean_forest"] = float(np.mean(cci["agb"][fc]))
            if f.any():
                r.stats.update(forest_ha=float(f.sum() * r.grid.cell_ha), agb_mean_forest=float(np.mean(r.agb[f])),
                               agb_total_t=float(np.sum(r.agb[f]) * r.grid.cell_ha),
                               saturated_share=float(np.mean(r.saturated[f])))
                notes.append(Note("biomass", INFO,
                                  f"Forest above-ground biomass now: {r.stats['agb_mean_forest']:.0f} Mg/ha on average "
                                  f"over {r.stats['forest_ha']:,.0f} ha of forest; {r.stats['saturated_share']:.0%} of "
                                  f"the forest is at or above the saturation level ({model.sat_agb:.0f} Mg/ha), so "
                                  "the total is a lower bound there"
                                  + (f" (ESA CCI {cci['year']}: {r.stats['cci_agb_mean_forest']:.0f} Mg/ha over the "
                                     "same forest)." if "cci_agb_mean_forest" in r.stats else ".")))
        self.emit("biomass", "Mapped forest biomass" if model else "Biomass could not be calibrated", notes)

    # ------------------------------------------------------------------ zones
    def zones(self) -> None:
        r, cfg = self.result, self.cfg
        sep = r.separation
        if sep is None:
            return
        grid = r.grid
        lon, lat = grid.lonlat()
        min_cells = max(1, math.ceil(cfg.min_zone_ha / grid.cell_ha))
        hz, base = r.ref.get("hansen"), r.ref.get("cci_baseline")
        recent = np.nan_to_num(hz["loss_recent"]) if hz is not None else None
        agb_now = r.agb if r.agb is not None else (r.ref["cci"]["agb"] if r.ref.get("cci") else None)
        agb_base = base["agb"] if base is not None else None
        zone_map = np.zeros(grid.shape, dtype="uint8")
        zones: list[A.Zone] = []
        dates = r.dates

        if r.drops is not None and r.drops["detected"].any():
            d = r.drops

            def when_new(sel):
                ks = d["k"][sel]
                k = int(np.bincount(ks[ks > 0]).argmax())
                return f"between {dates[k - 1]} and {dates[k]}", dates[k - 1], dates[k]

            before = after = None
            if r.model is not None:
                before = r.model.invert(A.from_db(d["before"]))[0]
                after = r.model.invert(A.from_db(d["after"]))[0]
            elif r.ref.get("cci"):
                before = r.ref["cci"]["agb"]
            z, lab = A.zones_from(d["detected"], "new", lon, lat, grid.cell_ha, min_cells, len(zones) + 1, when_new,
                                  d["before"], d["after"], before, after, recent, r.open_now, d["confirmed"])
            zones += z
            zone_map[lab > 0] = ZONE_CODES["new"]

        if r.open_now is not None:
            strict = r.forest & (np.nan_to_num(r.ref["worldcover"]["forest"]) >= 0.7 if r.ref.get("worldcover")
                                 else r.forest)
            if hz is not None:
                strict &= np.nan_to_num(hz["treecover2000"]) >= 30
            if agb_base is not None:
                strict &= np.nan_to_num(agb_base) >= 20
            unmapped = strict & r.open_now & (zone_map == 0)
            if recent is not None:
                unmapped &= recent < 0.3
            first = dates[0] if dates else None
            z, lab = A.zones_from(unmapped, "unmapped", lon, lat, grid.cell_ha, min_cells, len(zones) + 1,
                                  lambda sel: (f"after 2021, before {first}", None, first), None, r.hv_now_db,
                                  agb_base, agb_now, recent, r.open_now)
            zones += z
            zone_map[(lab > 0) & (zone_map == 0)] = ZONE_CODES["unmapped"]

        if recent is not None:
            last = hz["last_loss_year"]

            def when_hansen(sel):
                yrs = last[sel]
                yrs = yrs[yrs >= cfg.recent_from]
                if not yrs.size:
                    return "", None, None
                y0, y1 = int(yrs.min()), int(yrs.max())
                return (f"{y0}" if y0 == y1 else f"{y0}-{y1}") + " (Hansen)", None, None

            mapped = (recent >= 0.3) & (zone_map == 0)
            z, lab = A.zones_from(mapped, "hansen", lon, lat, grid.cell_ha, min_cells, len(zones) + 1, when_hansen,
                                  None, r.hv_now_db, agb_base, agb_now, recent, r.open_now)
            zones += z
            zone_map[(lab > 0) & (zone_map == 0)] = ZONE_CODES["hansen"]

        r.zones, r.zone_map = zones, zone_map
        notes = []
        by = {k: [z for z in zones if z.kind == k] for k in ZONE_CODES}
        for k, zs in by.items():
            r.stats[f"{k}_zones"] = len(zs)
            r.stats[f"{k}_ha"] = float(sum(z.area_ha for z in zs))
        lost = [z.co2_t for z in zones if z.kind in ("new", "unmapped") and z.co2_t is not None]
        r.stats["co2_t_new_unmapped"] = float(sum(lost)) if lost else None
        if by["new"]:
            conf = sum(z.confirmed for z in by["new"])
            notes.append(Note("change", WARN,
                              f"New clearing during the NISAR period: {len(by['new'])} zone{'s' if len(by['new']) != 1 else ''}, {r.stats['new_ha']:,.0f} "
                              f"ha in total ({conf} confirmed on two or more later images). HV fell by at least "
                              f"{cfg.drop_db:.0f} dB from forest to open-land levels."))
        elif r.drops is not None:
            notes.append(Note("change", GOOD, f"No new clearing larger than {cfg.min_zone_ha:g} ha was detected between "
                                              f"{dates[0]} and {dates[-1]}."))
        if by["unmapped"]:
            notes.append(Note("change", WARN,
                              f"{len(by['unmapped'])} zone{'s' if len(by['unmapped']) != 1 else ''}, {r.stats['unmapped_ha']:,.0f} ha, were forest in 2021 but "
                              "look like open land to NISAR now, and are not (yet) in the Hansen loss maps: possibly "
                              f"cleared in 2026 before {dates[0]}, or missed by Hansen. Check them on recent optical "
                              "images before drawing conclusions."))
        if by["hansen"]:
            still = [z.open_share for z in by["hansen"] if z.open_share is not None]
            share = float(np.average(still, weights=[z.area_ha for z in by["hansen"] if z.open_share is not None])) \
                if still else float("nan")
            notes.append(Note("change", INFO,
                              f"{len(by['hansen'])} zone{'s' if len(by['hansen']) != 1 else ''}, {r.stats['hansen_ha']:,.0f} ha, of loss mapped by Hansen "
                              f"et al. since {cfg.recent_from}; NISAR sees {share:.0%} of that area as open land now "
                              "(the rest is growing back, was partly cleared, or is plantation)."))
        self.emit("change", f"Found {len(zones)} forest-loss zones", notes)

    # ------------------------------------------------------------------ outputs
    def figures(self) -> None:
        from . import figures as F

        r = self.result
        self.emit("figures", "Drawing maps")
        for name, fn in F.ALL.items():
            try:
                fig = {t: fn(r, t) for t in ("light", "dark")}
            except F.Skip:
                continue
            r.figures[name] = fig

    def write_outputs(self) -> Path:
        from .. import provenance
        from .report import build_report

        r, cfg = self.result, self.cfg
        out = cfg.run_dir
        out.mkdir(parents=True, exist_ok=True)
        tags = {k.upper(): v for k, v in provenance().items()}
        layers = [("nisar_hv_db_median", r.hv_all_db), ("nisar_hv_db_latest", r.hv_now_db)]
        if r.agb is not None:
            layers += [("biomass_mg_per_ha", r.agb), ("biomass_saturated", r.saturated.astype("float32"))]
        if r.zone_map is not None:
            layers.append(("forest_loss_zones", r.zone_map.astype("float32")))
        for key, arr in layers:
            if arr is None:
                continue
            path = out / f"{key}.tif"
            r.grid.da(arr, key).rio.to_raster(path, driver="GTiff", compress="deflate", tags=tags)
            r.outputs[key] = str(path)
        if r.zones:
            import csv

            path = out / "forest_loss_zones.csv"
            rows = [z.to_row() for z in r.zones]
            with path.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            r.outputs["zones_csv"] = str(path)
            gj = out / "forest_loss_zones.geojson"
            gj.write_text(json.dumps(zones_geojson(r), default=str))
            r.outputs["zones_geojson"] = str(gj)
        fig_dir = out / "figures"
        fig_dir.mkdir(exist_ok=True)
        for name, themes in r.figures.items():
            (fig_dir / f"{name}.png").write_bytes(themes["light"])
        (out / "metrics.json").write_text(json.dumps(summary(r), indent=2, default=str))
        r.outputs["metrics"] = str(out / "metrics.json")
        report = out / "report.html"
        report.write_text(build_report(r), encoding="utf-8")
        r.outputs["report"] = str(report)
        self.emit("report", f"Wrote the report, maps and tables to {out}")
        return report

    def run(self) -> ForestResult:
        self.search()
        self.load()
        self.reference()
        self.forest_change()
        self.biomass()
        self.zones()
        self.figures()
        self.write_outputs()
        return self.result


def zones_geojson(r: ForestResult) -> dict:
    """Zone outlines (lon/lat polygons) with their table values."""
    import rasterio.features
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform, unary_union

    tr = Transformer.from_crs(r.grid.crs, "EPSG:4326", always_xy=True).transform
    feats = []
    if r.zone_map is None:
        return {"type": "FeatureCollection", "features": feats}
    lon, lat = r.grid.lonlat()
    for z in r.zones:
        code = ZONE_CODES[z.kind]
        # the zone's own patch: cells of its type connected to its centre-most cell
        d = (lon - z.lon) ** 2 + (lat - z.lat) ** 2
        d[r.zone_map != code] = np.inf
        from scipy import ndimage

        lab, _ = ndimage.label(r.zone_map == code, structure=np.ones((3, 3), bool))
        sel = lab == lab.flat[int(np.argmin(d))]
        polys = [shape(g) for g, v in rasterio.features.shapes(sel.astype("uint8"), mask=sel,
                                                                transform=r.grid.transform) if v == 1]
        if polys:
            feats.append({"type": "Feature", "geometry": mapping(transform(tr, unary_union(polys))),
                          "properties": z.to_row()})
    return {"type": "FeatureCollection", "features": feats}


def summary(r: ForestResult) -> dict:
    from .. import provenance

    sep = r.separation
    return {
        "software": provenance(),
        "config": r.config.to_dict(),
        "images": [{"date": str(s.date), "name": s.name, "track": s.track, "direction": s.direction,
                    "frame": s.frame, "looks": s.looks, "valid_fraction": round(s.valid_fraction, 3)}
                   for s in r.scenes],
        "date_offsets_db": [round(float(v), 2) for v in (r.offsets_db if r.offsets_db is not None else [])],
        "reference": {"cci_year": r.ref.get("cci", {}).get("year"),
                      "cci_baseline_year": r.ref.get("cci_baseline", {}).get("year"),
                      "hansen_version": R.HANSEN_VERSION if "hansen" in r.ref else None,
                      "hansen_yearly_loss_ha": r.ref.get("hansen", {}).get("yearly_ha"),
                      "worldcover": "v200 2021" if "worldcover" in r.ref else None},
        "biomass_model": r.model.to_dict() if r.model else None,
        "forest_open_separation": sep.to_dict() if sep else None,
        "stats": r.stats,
        "zones": [z.to_row() for z in r.zones],
        "notes": [n.to_dict() for n in r.notes],
        "citations": R.CITATIONS,
    }

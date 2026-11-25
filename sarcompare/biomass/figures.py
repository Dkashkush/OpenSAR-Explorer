# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Figures for the Forests & Biomass module, each in a light and a dark theme (same look as the Ground Motion
figures)."""

from __future__ import annotations

import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, ListedColormap  # noqa: E402

from ..plots import THEMES, _style, to_png  # noqa: E402
from . import analysis as A  # noqa: E402

ZONE_COLOURS = {"new": "#d03b3b", "unmapped": "#ef8a17", "hansen": "#7b5cc4"}
ZONE_SHORT = {"new": "New clearing (NISAR period)", "unmapped": "Lost since 2021, not in Hansen",
              "hansen": "Hansen loss 2021-2025"}


class Skip(Exception):
    """The figure does not apply to this result."""


def _greens(t) -> LinearSegmentedColormap:
    light = t is THEMES["light"]
    return LinearSegmentedColormap.from_list("agb", ["#f3efd9", "#b9d88f", "#5aa055", "#1f6b3a", "#0b3d22"] if light
                                             else ["#2a2a1f", "#3f6b2f", "#5aa055", "#a9d67f", "#e8f5c8"])


def _grey(t) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("hv", ["#111111", "#f2f2f2"] if t is THEMES["light"]
                                             else ["#0d0d0d", "#e6e6e6"])


def _density(t) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("density", ["#cde2fb", "#2a78d6", "#0d366b"] if t is THEMES["light"]
                                             else ["#184f95", "#3987e5", "#cde2fb"])


def _extent(grid):
    r = grid.res / 2
    return [(grid.x[0] - r) / 1000, (grid.x[-1] + r) / 1000, (grid.y[-1] - r) / 1000, (grid.y[0] + r) / 1000]


def _map_axes(ax, t, title):
    ax.set_title(title, fontsize=10, loc="left", color=t["ink"])
    ax.set_xlabel("Easting (km)", fontsize=8)
    ax.set_ylabel("Northing (km)", fontsize=8)
    ax.set_aspect("equal")


def _limits(a, lo=2, hi=98):
    v = a[np.isfinite(a)]
    return (float(np.percentile(v, lo)), float(np.percentile(v, hi))) if v.size else (-25.0, -5.0)


def maps(r, theme="light"):
    """Backscatter, biomass and forest loss side by side."""
    t = THEMES[theme]
    if r.hv_now_db is None:
        raise Skip
    panels = 3 if r.agb is not None else 2
    fig, axes = plt.subplots(1, panels, figsize=(5.0 * panels, 4.6), constrained_layout=True)
    _style(fig, axes, t)
    ext = _extent(r.grid)
    lo, hi = _limits(r.hv_now_db)
    im = axes[0].imshow(r.hv_now_db, extent=ext, cmap=_grey(t), vmin=lo, vmax=hi, interpolation="nearest")
    _map_axes(axes[0], t, "NISAR HV backscatter, latest images")
    cb = fig.colorbar(im, ax=axes[0], shrink=0.8)
    cb.set_label("dB (bright = more vegetation)", color=t["ink2"], fontsize=8)
    cb.ax.tick_params(colors=t["muted"], labelsize=7)
    k = 1
    if r.agb is not None:
        vmax = max(50.0, float(r.model.sat_agb))
        im = axes[1].imshow(np.where(np.isfinite(r.agb), r.agb, np.nan), extent=ext, cmap=_greens(t), vmin=0,
                            vmax=vmax, interpolation="nearest")
        sat = np.where(r.saturated, 1.0, np.nan)
        axes[1].contourf(np.linspace(ext[0], ext[1], r.agb.shape[1]), np.linspace(ext[3], ext[2], r.agb.shape[0]),
                         sat, levels=[0.5, 1.5], colors="none", hatches=["...."])
        _map_axes(axes[1], t, f"Above-ground biomass (dots: at least {r.model.sat_agb:.0f}, saturated)")
        cb = fig.colorbar(im, ax=axes[1], shrink=0.8)
        cb.set_label("Mg/ha", color=t["ink2"], fontsize=8)
        cb.ax.tick_params(colors=t["muted"], labelsize=7)
        k = 2
    ax = axes[k]
    ax.imshow(r.hv_now_db, extent=ext, cmap=_grey(t), vmin=lo, vmax=hi, interpolation="nearest", alpha=0.55)
    if r.forest is not None:
        ax.contour(np.linspace(ext[0], ext[1], r.forest.shape[1]), np.linspace(ext[3], ext[2], r.forest.shape[0]),
                   r.forest.astype(float), levels=[0.5], colors=["#3c8d4a"], linewidths=0.6)
    if r.zone_map is not None and r.zone_map.any():
        cmap = ListedColormap([ZONE_COLOURS["new"], ZONE_COLOURS["unmapped"], ZONE_COLOURS["hansen"]])
        ax.imshow(np.where(r.zone_map > 0, r.zone_map, np.nan), extent=ext, cmap=cmap, vmin=0.5, vmax=3.5,
                  interpolation="nearest")
    handles = [plt.Line2D([], [], color="#3c8d4a", lw=1, label="Forest in 2021 (WorldCover)")]
    handles += [plt.Rectangle((0, 0), 1, 1, color=ZONE_COLOURS[k_], label=ZONE_SHORT[k_]) for k_ in ZONE_COLOURS]
    leg = ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.85)
    leg.get_frame().set_facecolor(t["surface"])
    for txt in leg.get_texts():
        txt.set_color(t["ink2"])
    _map_axes(ax, t, "Forest loss zones")
    return to_png(fig)


def calibration(r, theme="light"):
    """How NISAR HV relates to the reference biomass, and the check on held-out blocks."""
    t = THEMES[theme]
    m = r.model
    if m is None:
        raise Skip
    cci = r.ref["cci"]["agb"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)
    _style(fig, axes, t)
    ax = axes[0]
    ok = np.isfinite(r.hv_all_db) & np.isfinite(cci) & ~r.test
    ax.set_facecolor(t["surface"])
    if ok.any():
        ax.hexbin(cci[ok], r.hv_all_db[ok], gridsize=45, mincnt=1, bins="log", cmap=_density(t), linewidths=0)
        ax.set_ylim(*np.percentile(r.hv_all_db[ok], [0.5, 99.9]) + np.array([-1.0, 1.0]))
    xs = np.linspace(0, max(m.max_ref, 1), 200)
    ax.plot(xs, 10 * np.log10(m.hv(xs)), color=t["ink"], lw=1.6, label="fitted model")
    ax.scatter([c["agb"] for c in m.curve], [c["hv_db"] for c in m.curve], s=14, color=t["ink"], zorder=3,
               label="binned medians")
    ax.axvline(m.sat_agb, color="#d03b3b", ls="--", lw=1, label=f"saturation ~{m.sat_agb:.0f} Mg/ha")
    ax.set_xlabel(f"Reference biomass, {m.reference} (Mg/ha)", fontsize=8)
    ax.set_ylabel("NISAR HV (dB)", fontsize=8)
    ax.set_title("Calibration (70 % of the area)", fontsize=10, loc="left", color=t["ink"])
    ax.grid(color=t["grid"], lw=0.5)
    _legend(ax, t)
    ax = axes[1]
    te = np.isfinite(r.hv_all_db) & np.isfinite(cci) & r.test
    pred, sat = m.invert(A.from_db(r.hv_all_db[te]))
    ref = cci[te]
    top = max(float(np.nanpercentile(ref, 99.5)) if ref.size else 1.0, m.sat_agb * 1.2, 10)
    ax.set_facecolor(t["surface"])
    if ref.size:
        ax.hexbin(ref, pred, gridsize=40, mincnt=1, bins="log", extent=(0, top, 0, top), cmap=_density(t),
                  linewidths=0)
    ax.plot([0, top], [0, top], color=t["muted"], ls="--", lw=1)
    ax.axhline(m.sat_agb, color="#d03b3b", ls="--", lw=1)
    tb = m.test_below_sat
    ax.set_title(f"Check on held-out 30 %: r = {m.test['r']:.2f}, RMSE {m.test['rmse']:.0f} Mg/ha", fontsize=10,
                 loc="left", color=t["ink"])
    ax.text(0.02, 0.97, f"below saturation: r = {tb['r']:.2f}, RMSE {tb['rmse']:.0f} Mg/ha, n = {tb['n']:,}",
            transform=ax.transAxes, va="top", fontsize=8, color=t["ink2"])
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.set_xlabel("Reference biomass (Mg/ha)", fontsize=8)
    ax.set_ylabel("NISAR biomass (Mg/ha)", fontsize=8)
    ax.grid(color=t["grid"], lw=0.5)
    return to_png(fig)


def separation(r, theme="light"):
    """HV of intact forest and of cleared land, and the level used to tell them apart."""
    t = THEMES[theme]
    s = r.separation
    if s is None:
        raise Skip
    hz = r.ref.get("hansen")
    fig, ax = plt.subplots(figsize=(6.4, 3.6), constrained_layout=True)
    _style(fig, ax, t)
    ax.set_facecolor(t["surface"])
    f = r.hv_all_db[r.intact & np.isfinite(r.hv_all_db)]
    if hz is not None and "Hansen" in s.reference:
        cleared = (np.nan_to_num(hz["loss_recent"]) >= 0.5)
    else:
        wc = r.ref["worldcover"]
        cleared = (np.nan_to_num(wc["open"] + wc["crop"]) >= 0.8) & (np.nan_to_num(wc["tree"]) < 0.1)
    c = r.hv_all_db[cleared & np.isfinite(r.hv_all_db)]
    bins = np.linspace(min(np.percentile(c, 1), np.percentile(f, 1)) - 1, max(np.percentile(f, 99), np.percentile(c, 99)) + 1, 60)
    ax.hist(f, bins=bins, density=True, color="#3c8d4a", alpha=0.6, label=f"intact forest (n = {f.size:,})")
    ax.hist(c, bins=bins, density=True, color=ZONE_COLOURS["hansen"], alpha=0.6,
            label=f"{s.reference} (n = {c.size:,})")
    ax.axvline(s.threshold_db, color=t["ink"], ls="--", lw=1.2, label=f"forest/open level {s.threshold_db:.1f} dB")
    ax.set_xlabel("NISAR HV (dB), median over the period", fontsize=8)
    ax.set_yticks([])
    ax.set_title(f"Forest vs cleared land: balanced accuracy {s.balanced_accuracy:.0%} (held-out blocks)",
                 fontsize=10, loc="left", color=t["ink"])
    _legend(ax, t)
    return to_png(fig)


def timeseries(r, theme="light"):
    """HV through time in the new-clearing zones, against intact forest."""
    t = THEMES[theme]
    new = [z for z in r.zones if z.kind == "new"]
    if not new or len(r.scenes) < 2:
        raise Skip
    import matplotlib.dates as mdates
    from scipy import ndimage

    fig, ax = plt.subplots(figsize=(7.2, 3.6), constrained_layout=True)
    _style(fig, ax, t)
    ax.set_facecolor(t["surface"])
    dates = r.dates
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        forest = [np.nanmedian(c[r.intact]) for c in r.hv_db]
        lo = [np.nanpercentile(c[r.intact], 10) for c in r.hv_db]
        hi = [np.nanpercentile(c[r.intact], 90) for c in r.hv_db]
    ax.fill_between(dates, lo, hi, color="#3c8d4a", alpha=0.18, lw=0)
    ax.plot(dates, forest, color="#3c8d4a", lw=1.8, marker="o", ms=3, label="intact forest (median, 10-90 %)")
    lab, _ = ndimage.label(r.zone_map == 1, structure=np.ones((3, 3), bool))
    lon, lat = r.grid.lonlat()
    for z in sorted(new, key=lambda z: -z.area_ha)[:5]:
        d = (lon - z.lon) ** 2 + (lat - z.lat) ** 2
        d[lab == 0] = np.inf
        sel = lab == lab.flat[int(np.argmin(d))]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ys = [np.nanmedian(c[sel]) for c in r.hv_db]
        ax.plot(dates, ys, color=ZONE_COLOURS["new"], lw=1.2, marker="o", ms=3, alpha=0.9)
        ax.annotate(f"zone {z.id}", (dates[-1], ys[-1]), fontsize=7, color=t["ink2"], xytext=(4, 0),
                    textcoords="offset points", va="center")
    if r.separation:
        ax.axhline(r.separation.threshold_db, color=t["muted"], ls="--", lw=1, label="forest/open level")
    ax.plot([], [], color=ZONE_COLOURS["new"], lw=1.2, label="new clearing zones (largest 5)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%Y"))
    ax.set_ylabel("NISAR HV (dB)", fontsize=8)
    ax.set_title("Backscatter through time: clearing shows as a sudden drop", fontsize=10, loc="left", color=t["ink"])
    ax.grid(color=t["grid"], lw=0.5)
    _legend(ax, t)
    return to_png(fig)


def hansen_years(r, theme="light"):
    """Tree-cover loss per year mapped by Hansen et al. over the area."""
    t = THEMES[theme]
    yearly = (r.ref.get("hansen") or {}).get("yearly_ha") or {}
    if not yearly:
        raise Skip
    years = list(range(2001, max(yearly) + 1))
    vals = [yearly.get(y, 0.0) for y in years]
    fig, ax = plt.subplots(figsize=(7.2, 3.0), constrained_layout=True)
    _style(fig, ax, t)
    ax.set_facecolor(t["surface"])
    colours = [ZONE_COLOURS["hansen"] if y >= r.config.recent_from else t["muted"] for y in years]
    ax.bar(years, vals, color=colours, width=0.8)
    ax.set_ylabel("ha per year", fontsize=8)
    ax.set_title("Tree-cover loss mapped by Hansen et al. (GFC v1.13) in the area", fontsize=10, loc="left",
                 color=t["ink"])
    ax.text(0.01, 0.95, "Source: Hansen/UMD/Google/USGS/NASA. Map totals from pixel counts.", transform=ax.transAxes,
            fontsize=7, color=t["muted"], va="top")
    ax.grid(axis="y", color=t["grid"], lw=0.5)
    ax.set_axisbelow(True)
    return to_png(fig)


def _legend(ax, t):
    leg = ax.legend(fontsize=7, loc="best", framealpha=0.85)
    leg.get_frame().set_facecolor(t["surface"])
    leg.get_frame().set_edgecolor(t["axis"])
    for txt in leg.get_texts():
        txt.set_color(t["ink2"])


ALL = {"maps": maps, "calibration": calibration, "separation": separation, "timeseries": timeseries,
       "hansen_years": hansen_years}

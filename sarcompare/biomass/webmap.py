# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Interactive web map of a Forests & Biomass result: biomass, backscatter and forest-loss zones."""

from __future__ import annotations

import base64
import html
import io

import folium
import matplotlib
import numpy as np
from branca.colormap import LinearColormap
from pyproj import Transformer

from ..maps import _base, _keep_fitted, _zoom_for
from ..plots import THEMES
from . import analysis as A
from .figures import ZONE_COLOURS, _greens, _grey

# Forest places in India where NISAR GCOV data, Hansen loss and CCI biomass are available (checked Nov 2026).
FOREST_PLACES = {
    "Hasdeo Arand, Chhattisgarh: coal mining in dense sal forest": (82.55, 22.70, 82.85, 22.95),
    "Lunglei, Mizoram: shifting cultivation (jhum) in hill forest": (92.55, 22.75, 92.85, 23.05),
    "Wayanad, Kerala (Western Ghats): forest, plantations, 2024 landslides": (76.00, 11.60, 76.30, 11.90),
    "Dehing Patkai, Assam: lowland rainforest and coal mining": (95.50, 27.20, 95.80, 27.40),
    "Great Nicobar Island: tropical rainforest, planned port and township": (93.70, 6.75, 93.95, 7.10),
    "Sundarbans, West Bengal: mangrove forest": (88.75, 21.65, 89.05, 21.95),
}


def _overlay(grid, arr, cmap, vmin, vmax, alpha=0.85) -> tuple[str, list]:
    merc = grid.da(arr, "v").rio.reproject("EPSG:3857")
    vals = merc.values.astype("float64")
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    rgba = cmap(norm(np.nan_to_num(vals)))
    rgba[..., 3] = np.where(np.isfinite(vals), alpha, 0.0)
    buf = io.BytesIO()
    matplotlib.image.imsave(buf, rgba, format="png")
    xs, ys = merc.x.values, merc.y.values
    dx, dy = abs(xs[1] - xs[0]) / 2, abs(ys[1] - ys[0]) / 2
    tr = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    w, s = tr.transform(xs.min() - dx, ys.min() - dy)
    e, n = tr.transform(xs.max() + dx, ys.max() + dy)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), [[s, w], [n, e]]


def forest_map(r) -> folium.Map:
    from .pipeline import zones_geojson

    w, s, e, n = r.config.get_aoi().bounds
    m = folium.Map(location=[(s + n) / 2, (w + e) / 2], zoom_start=_zoom_for(w, s, e, n, 1000), tiles=None,
                   control_scale=True, zoom_animation=False, fade_animation=False, marker_zoom_animation=False)
    _base(m)
    t = THEMES["light"]
    if r.agb is not None:
        vmax = max(50.0, float(r.model.sat_agb))
        url, bounds = _overlay(r.grid, r.agb, _greens(t), 0, vmax)
        folium.raster_layers.ImageOverlay(url, bounds=bounds, name="Biomass (Mg/ha)", show=True, interactive=False,
                                          zindex=2).add_to(m)
        legend = LinearColormap(["#f3efd9", "#b9d88f", "#5aa055", "#1f6b3a", "#0b3d22"], vmin=0, vmax=vmax)
        legend.caption = f"Above-ground biomass, Mg/ha (darkest = at least {r.model.sat_agb:.0f}, saturated)"
        legend.add_to(m)
    if r.hv_now_db is not None:
        v = r.hv_now_db[np.isfinite(r.hv_now_db)]
        lo, hi = (np.percentile(v, [2, 98]) if v.size else (-25, -5))
        url, bounds = _overlay(r.grid, r.hv_now_db, _grey(t), lo, hi)
        folium.raster_layers.ImageOverlay(url, bounds=bounds, name="NISAR HV backscatter (bright = more vegetation)",
                                          show=r.agb is None, interactive=False, zindex=1).add_to(m)
    folium.Rectangle([[s, w], [n, e]], color="#1f2933", weight=2, fill=False, tooltip="Analysis area").add_to(m)
    gj = zones_geojson(r)
    for kind, label in A.KINDS.items():
        feats = [f for f in gj["features"] if f["properties"]["type"] == label]
        if not feats:
            continue
        layer = folium.FeatureGroup(name=label, show=True).add_to(m)
        colour = ZONE_COLOURS[kind]
        for f in feats:
            p = f["properties"]
            co2 = f"<br>CO₂ in the cleared wood: ~{p['co2_t']:,.0f} t" if p.get("co2_t") else ""
            agb = f"<br>Biomass before: ~{p['biomass_before_mg_ha']:.0f} Mg/ha" if p.get("biomass_before_mg_ha") else ""
            popup = (f"<b>{html.escape(label)}</b><br>Zone {p['zone']}: {p['area_ha']:,.0f} ha"
                     f"<br>{html.escape(str(p['when']))}{agb}{co2}")
            folium.GeoJson(f, style_function=lambda _, c=colour: {"color": c, "weight": 2, "fillColor": c,
                                                                  "fillOpacity": 0.45},
                           tooltip=f"{label}: {p['area_ha']:,.0f} ha", popup=folium.Popup(popup, max_width=280)
                           ).add_to(layer)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    _keep_fitted(m, w, s, e, n)
    return m

# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Plain-language summary and the self-contained HTML report of a Forests & Biomass run."""

from __future__ import annotations

import html
import math
from datetime import datetime

from .. import __author__, __copyright__
from ..notes import GOOD, INFO, WARN
from ..report import CSS, LEVEL_LABEL, _img, _num
from . import analysis as A
from . import reference as R


def _n(count: int, word: str) -> str:
    plural = word + ("es" if word.endswith(("ch", "sh", "s", "x")) else "s")
    return f"{count} {word if count == 1 else plural}"


def _ha(v) -> str:
    return f"{v:,.0f} ha" if v is not None and math.isfinite(v) else "n/a"


def plain_summary(r) -> list[tuple[str, str]]:
    """Short findings, most important first, for the app's 'In short' box and the report."""
    out: list[tuple[str, str]] = []
    st, cfg = r.stats, r.config
    dates = r.dates
    if r.synthetic:
        out.append((INFO, "This is the synthetic demo: a made-up forest written in the real NISAR file format."))
    if r.model is not None and "agb_mean_forest" in st:
        out.append((INFO, f"Forests here hold about **{st['agb_mean_forest']:.0f} tonnes of above-ground biomass per "
                          f"hectare** on average ({st['agb_total_t'] / 1e6:,.2f} million tonnes over "
                          f"{st['forest_ha']:,.0f} ha). Radar stops 'seeing' extra biomass above about "
                          f"{r.model.sat_agb:.0f} t/ha; {st['saturated_share']:.0%} of the forest is that dense, so "
                          "the true total is higher."))
    elif r.ref.get("cci") is None:
        out.append((WARN, "Biomass could not be calculated: the reference biomass map (ESA CCI) was not available. "
                          "The backscatter map still shows where vegetation is dense."))
    new = [z for z in r.zones if z.kind == "new"]
    if new:
        big = max(new, key=lambda z: z.area_ha)
        out.append((WARN, f"**New clearing:** NISAR saw {_n(len(new), 'patch')} of forest cleared during the period, "
                          f"{st['new_ha']:,.0f} ha in total. The largest ({big.area_ha:,.0f} ha, at {big.lat:.4f} N, "
                          f"{big.lon:.4f} E) was cleared {big.when}."))
    elif r.drops is not None and dates:
        out.append((GOOD, f"No new forest clearing larger than {cfg.min_zone_ha:g} ha between {dates[0]} and "
                          f"{dates[-1]}."))
    unm = [z for z in r.zones if z.kind == "unmapped"]
    if unm:
        out.append((WARN, f"{_n(len(unm), 'patch').capitalize()}, {st['unmapped_ha']:,.0f} ha, "
                          f"{'was' if len(unm) == 1 else 'were'} forest in 2021 but "
                          f"{'is' if len(unm) == 1 else 'are'} open land "
                          "now and not in the global loss maps yet. They may have been cleared early in 2026: "
                          "worth checking on recent satellite photos."))
    yearly = (r.ref.get("hansen") or {}).get("yearly_ha") or {}
    recent = sum(v for y, v in yearly.items() if y >= cfg.recent_from)
    if recent:
        han = [z for z in r.zones if z.kind == "hansen"]
        still = sum(z.area_ha * (z.open_share or 0) for z in han) / max(sum(z.area_ha for z in han), 1e-9)
        out.append((INFO, f"Global Forest Watch data (Hansen et al.) show {recent:,.0f} ha of tree-cover loss here "
                          f"from {cfg.recent_from} to {R.HANSEN_LAST_YEAR}"
                          + (f"; NISAR sees {still:.0%} of the larger loss zones still open." if han else ".")))
    co2 = st.get("co2_t_new_unmapped")
    if co2:
        out.append((INFO, f"The newly cleared forest held roughly {co2 / 1e3:,.1f} thousand tonnes of CO₂ in its "
                          "above-ground wood (rough estimate: 47 % of biomass is carbon)."))
    sep, m = r.separation, r.model
    checks = []
    if sep is not None:
        checks.append(f"tells forest from cleared land {sep.balanced_accuracy:.0%} of the time")
    if m is not None and m.test_below_sat.get("n", 0) >= 30:
        checks.append(f"matches the reference biomass map with r = {m.test_below_sat['r']:.2f} below saturation")
    if checks:
        out.append((GOOD if sep is None or sep.balanced_accuracy >= 0.85 else INFO,
                    "Checked on parts of the area not used for training: NISAR " + " and ".join(checks) + "."))
    return out


def _md(text: str) -> str:
    """The summary's **bold** marks as HTML (text escaped first)."""
    parts = html.escape(text).split("**")
    return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))


def _notes_html(r, stages) -> str:
    items = []
    for n in r.notes:
        if n.stage in stages:
            cls, label = LEVEL_LABEL.get(n.level, LEVEL_LABEL["info"])
            items.append(f'<li><span class="tag {cls}">{label}</span><span>{html.escape(n.text)}</span></li>')
    return f'<ul class="notes">{"".join(items)}</ul>' if items else ""


def _zones_table(r) -> str:
    e = html.escape
    if not r.zones:
        return "<p>No forest-loss zones above the minimum size.</p>"
    rows = "".join(
        f"<tr><td>{z.id}</td><td>{e(A.KINDS[z.kind])}</td><td>{z.area_ha:,.0f}</td><td>{z.lat:.4f}, {z.lon:.4f}</td>"
        f"<td>{e(z.when)}</td><td>{_num(z.hv_before_db)} → {_num(z.hv_after_db)}</td>"
        f"<td>{_num(z.agb_before, 0)}</td><td>{_num(z.co2_t, 0)}</td><td>{z.hansen_share:.0%}</td>"
        f"<td>{'' if z.open_share is None else f'{z.open_share:.0%}'}</td></tr>"
        for z in sorted(r.zones, key=lambda z: (z.kind != 'new', z.kind != 'unmapped', -z.area_ha))[:60])
    more = f"<p class='sub'>Showing 60 of {len(r.zones)} zones; all are in forest_loss_zones.csv.</p>" \
        if len(r.zones) > 60 else ""
    return ('<div class="scroll"><table><thead><tr><th>#</th><th>Type</th><th>Area (ha)</th><th>Lat, lon</th>'
            "<th>When</th><th>HV before → after (dB)</th><th>Biomass before (Mg/ha)</th><th>CO₂ (t)</th>"
            f"<th>In Hansen</th><th>Open now</th></tr></thead><tbody>{rows}</tbody></table></div>{more}")


def _references(r) -> str:
    items = []
    if r.synthetic:
        items.append("Synthetic demo data generated by OpenSAR Explorer (not real measurements); the reference maps "
                     "are synthetic stand-ins with the real formats.")
    else:
        items.append("NISAR L2 GCOV data: NASA/ISRO, distributed by the Alaska Satellite Facility (ASF) DAAC.")
        for key in ("worldcover", "hansen", "cci"):
            if key in r.ref or (key == "cci" and "cci" in r.ref):
                items.append(html.escape(R.CITATIONS[key]))
    items.append("L-band HV-biomass model and saturation: Mitchard, E. T. A. et al. (2009). Using satellite radar "
                 "backscatter to predict above-ground woody biomass. <i>Geophys. Res. Lett.</i> 36, L23401; Yu, Y. "
                 "&amp; Saatchi, S. (2016). Sensitivity of L-band SAR backscatter to aboveground biomass of global "
                 "forests. <i>Remote Sensing</i> 8, 522.")
    items.append("Carbon fraction 0.47: IPCC (2006) Guidelines for National Greenhouse Gas Inventories, Vol. 4.")
    return "".join(f"<li>{it}</li>" for it in items)


def build_report(r) -> str:
    e = html.escape
    cfg, st, m, sep = r.config, r.stats, r.model, r.separation
    w, s, ea, n = cfg.get_aoi().bounds
    fig = r.figures
    tiles = []
    if "agb_mean_forest" in st:
        tiles += [(f"{st['forest_ha']:,.0f} ha", "Forest (2021 map)"),
                  (f"{st['agb_mean_forest']:.0f} Mg/ha", "Mean forest biomass now"),
                  (f"{m.sat_agb:.0f} Mg/ha", "L-band saturation here")]
    if m is not None:
        tiles.append((f"r = {m.test['r']:.2f}", "Biomass check, held-out 30 %"))
    if sep is not None:
        tiles.append((f"{sep.balanced_accuracy:.0%}", "Forest vs cleared, held-out"))
    for k, label in (("new", "New clearing (NISAR period)"), ("unmapped", "Lost since 2021, not in Hansen"),
                     ("hansen", "Hansen loss 2021-2025")):
        if f"{k}_ha" in st:
            tiles.append((_ha_short(st[f"{k}_ha"]), label))
    tiles_html = "".join(f'<div class="tile"><div class="v">{e(v)}</div><div class="k">{e(k)}</div></div>'
                         for v, k in tiles)
    summary = "".join(f'<li><span class="tag {LEVEL_LABEL.get(lv, LEVEL_LABEL["info"])[0]}">'
                      f'{LEVEL_LABEL.get(lv, LEVEL_LABEL["info"])[1]}</span><span>{_md(t)}</span></li>'
                      for lv, t in plain_summary(r))
    images = "".join(f"<tr><td>{s_.date}</td><td>{e(str(s_.track))} {e((s_.direction or '').lower())}</td>"
                     f"<td>{e(str(s_.frame))}</td><td>{s_.valid_fraction:.0%}</td>"
                     f"<td>{'' if r.offsets_db is None else f'{r.offsets_db[i]:+.1f}'}</td>"
                     f"<td><code>{e(s_.name)}</code></td></tr>" for i, s_ in enumerate(r.scenes))

    def block(key, alt, width=None):
        if key not in fig:
            return ""
        style = f' style="max-width:{width}px;margin-top:12px"' if width else ' style="margin-top:12px"'
        return f"<div{style}>{_img(fig[key], alt)}</div>"

    sections = [
        ("NISAR images used", f'<div class="scroll"><table><thead><tr><th>Date</th><th>Track</th><th>Frame</th>'
                              "<th>Valid</th><th>Date offset removed (dB)</th><th>File</th></tr></thead>"
                              f"<tbody>{images}</tbody></table></div>" + _notes_html(r, {"search", "load"})),
        ("Independent forest data", block("hansen_years", "Hansen loss per year", 760)
         + _notes_html(r, {"reference"})),
        ("Biomass", block("maps", "Backscatter, biomass and forest-loss maps") + block("calibration",
                                                                                         "Biomass calibration")
         + _notes_html(r, {"biomass"})),
        ("Forest loss", block("separation", "Forest and cleared land backscatter", 640)
         + block("timeseries", "Backscatter through time", 760) + _notes_html(r, {"change"}) + _zones_table(r)),
    ]
    body = "".join(f'<h2>{i + 1} · {e(t)}</h2><div class="card">{c}</div>' for i, (t, c) in enumerate(sections) if c)
    method = (
        "<p>NISAR's L-band radar (24 cm) penetrates the canopy; its cross-polarised (HV) echo comes mostly from "
        "branches and trunks, so it rises with above-ground biomass until it levels off in dense forest. The "
        "relation is calibrated over the area against ESA CCI Biomass with the model HV = a (1 − e<sup>−AGB/b</sup>) "
        "+ c, on 70 % of the area (2 km blocks), and checked on the other 30 %. Cells within 10 % of the "
        "dense-forest level are reported as 'at least' the saturation biomass. Each image is first corrected for "
        "the common shift of all forest pixels (rain and soil moisture). Clearing shows as an HV drop of several "
        "dB; the HV level separating forest from open land is learned from intact forest and Hansen-mapped "
        "recent loss.</p><p><strong>Limits.</strong> Results are research estimates. Biomass errors are typically "
        "20-50 % per hectare and larger near saturation; the reference map is itself an estimate. Wet soil, "
        "flooding, fire and selective logging change HV too; a 'new clearing' should be confirmed on optical "
        "images or in the field before any action. Mapped areas are pixel totals, not statistical area "
        "estimates.</p>")
    banner = ('<p class="banner"><strong>Synthetic demo data.</strong> These results come from a simulated forest '
              "built to show how the tool works. They are not real measurements of this location.</p>"
              if r.synthetic else "")
    files = "".join(f"<li><code>{e(k)}</code>: {e(str(v))}</li>" for k, v in r.outputs.items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenSAR Explorer: Forests & Biomass report</title><style>{CSS}</style></head>
<body><main>
<p class="sub" style="margin:0 0 2px">OpenSAR Explorer · Forests &amp; Biomass module · created by {e(__author__)} ·
{e(__copyright__)}</p>
<h1>Forest biomass and forest loss: {e(cfg.name)}</h1>
<p class="sub">Area {w:.3f}–{ea:.3f}°E, {s:.3f}–{n:.3f}°N · grid {cfg.resolution_m:.0f} m · NISAR L2 GCOV,
{len(r.scenes)} images{f" from {r.dates[0]} to {r.dates[-1]}" if r.scenes else ""} · generated
{datetime.now():%Y-%m-%d %H:%M}</p>
{banner}
<div class="tiles">{tiles_html}</div>
<h2>In short</h2><div class="card"><ul class="notes">{summary}</ul></div>
{body}
<h2>Method and limits</h2><div class="card">{method}</div>
<h2>References and data credits</h2><div class="card"><ol>{_references(r)}</ol></div>
<h2>Files</h2><div class="card"><ul>{files}</ul></div>
</main></body></html>"""


def _ha_short(v: float) -> str:
    return f"{v / 1000:,.1f}k ha" if v >= 10_000 else f"{v:,.0f} ha"

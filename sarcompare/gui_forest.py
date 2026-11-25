# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Forests & Biomass page of the web app: forest biomass and forest loss from NISAR L-band radar."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from sarcompare.gui import (ICON, MAX_AOI_KM2, MODE_DEMO, MODE_REAL, ONLINE, choose_area, friendly_error,
                            download_grid, results_title, session_id, show_map, show_notes, step, token_step)

STAGES = {"search": "Finding NISAR images", "load": "Reading the radar images",
          "reference": "Adding independent forest maps", "change": "Looking for forest loss",
          "biomass": "Estimating biomass", "figures": "Drawing maps", "report": "Writing the report"}
GCOV_START = date(2026, 6, 1)


def choose_forest_period(n: int):
    step(n, "When?", "NISAR's forest images over India start in June 2026. Longer periods catch more clearing.")
    today = date.today()
    choice = st.radio("Forest period", ["Since NISAR forest data began (June 2026)", "Last 3 months",
                                        "Choose dates"], horizontal=True, label_visibility="collapsed", key="f_period")
    if choice.startswith("Since"):
        return GCOV_START, today
    if choice == "Last 3 months":
        return max(GCOV_START, today - timedelta(days=92)), today
    c1, c2 = st.columns(2)
    return (c1.date_input("From", GCOV_START, min_value=GCOV_START, key="f_from"),
            c2.date_input("To", today, min_value=GCOV_START, key="f_to"))


def forest_settings():
    with st.expander("⚙️ Advanced settings (most people can skip this)"):
        c1, c2, c3 = st.columns(3)
        res = c1.select_slider("Map cell size (m)", [50, 100, 200], value=100, key="f_res",
                               help="100 m matches the ESA biomass map. 50 m shows smaller clearings but is noisier.")
        direction = c1.selectbox("Satellite pass", ["Any", "ASCENDING", "DESCENDING"], key="f_dir")
        top = 8 if ONLINE else 16
        dates = c2.slider("Images to use", 3, top, min(8, top), key="f_dates",
                          help="Spread over the period. More images date clearings more precisely but take longer "
                               "(each adds 50-100 MB of reading).")
        drop = c2.slider("Backscatter drop that counts as clearing (dB)", 2.0, 6.0, 3.0, 0.5, key="f_drop",
                         help="Clearing forest lowers the HV radar echo by 5-10 dB. Lower values catch partial "
                              "clearing but also more false alarms.")
        min_ha = c3.select_slider("Smallest zone (ha)", [1, 2, 5, 10, 25], value=2, key="f_minha")
    return dict(res=float(res), direction=None if direction == "Any" else direction, dates=dates, drop=drop,
                min_ha=float(min_ha))


def build_forest_config(mode, bbox, period, token, adv):
    from sarcompare.biomass.demo import forest_demo_config
    from sarcompare.biomass.pipeline import ForestConfig

    out = f"outputs/{session_id()}" if ONLINE else "outputs"
    if mode == MODE_DEMO:
        cfg = forest_demo_config(output_dir=out)
    else:
        cfg = ForestConfig(name="my_forest", aoi=list(bbox), start=period[0], end=period[1], output_dir=out,
                           flight_direction=adv["direction"], max_dates=adv["dates"])
        cfg.earthdata_token = token or None  # per session; never os.environ
    cfg.resolution_m, cfg.drop_db, cfg.min_zone_ha = adv["res"], adv["drop"], adv["min_ha"]
    return cfg


def run_forest(cfg):
    from sarcompare.biomass.pipeline import ForestPipeline

    boxes = {}

    def on_event(ev):
        if ev.stage not in boxes:
            boxes[ev.stage] = st.status(STAGES.get(ev.stage, ev.stage), expanded=False)
        boxes[ev.stage].write(f"**{ev.message}**")
        show_notes(ev.notes, boxes[ev.stage])

    try:
        with st.spinner("Working… real data take a few minutes."):
            result = ForestPipeline(cfg, on_event).run()
    except Exception as e:  # a friendly message instead of a traceback
        for b in boxes.values():
            b.update(state="error")
        st.error(friendly_error(e))
        return None
    for b in boxes.values():
        b.update(state="complete", expanded=False)
    return result


def show_forest_results(r):
    from sarcompare.biomass.analysis import KINDS
    from sarcompare.biomass.report import plain_summary
    from sarcompare.biomass.webmap import forest_map

    results_title(r.synthetic)
    with st.container(border=True, key="in_short"):
        st.markdown("#### In short")
        for level, text in plain_summary(r):
            st.markdown(f"{ICON.get(level, 'ℹ️')} {text}")
    stt = r.stats
    m = st.columns(5)
    m[0].metric("Forest (2021 map)", f"{stt['forest_ha']:,.0f} ha" if "forest_ha" in stt else "n/a")
    m[1].metric("Mean forest biomass", f"{stt['agb_mean_forest']:.0f} t/ha" if "agb_mean_forest" in stt else "n/a",
                help="Above-ground dry biomass, tonnes (Mg) per hectare.")
    m[2].metric("Radar saturates at", f"{r.model.sat_agb:.0f} t/ha" if r.model else "n/a",
                help="Above this, L-band backscatter barely changes with biomass; denser forest shows as 'at least'.")
    m[3].metric("New clearing", f"{stt.get('new_ha', 0):,.0f} ha", help="Cleared during the NISAR period.")
    m[4].metric("Lost since 2021", f"{stt.get('unmapped_ha', 0):,.0f} ha",
                help="Forest in 2021 that is open land now and not yet in the Hansen loss maps (up to 2025).")

    with st.container(border=True, key="panel_forest_map"):
        st.markdown("#### Map")
        st.caption("Switch layers with the box at the top right. Click a zone for details. Dark green = more "
                   "biomass; red = new clearing, orange = lost since 2021, purple = mapped loss 2021-2025.")
        show_map(forest_map(r).get_root().render())  # built by the app; values in it are escaped
    if r.zones:
        with st.expander(f"Forest-loss zones ({len(r.zones)})", expanded=True):
            rows = [z.to_row() for z in sorted(r.zones, key=lambda z: (list(KINDS).index(z.kind), -z.area_ha))]
            st.dataframe([{"Zone": x["zone"], "Type": x["type"], "Area (ha)": x["area_ha"], "Latitude": x["latitude"],
                           "Longitude": x["longitude"], "When": x["when"],
                           "Biomass before (t/ha)": x["biomass_before_mg_ha"], "CO₂ (t)": x["co2_t"],
                           "Open land now": None if x["open_now_share"] is None else f"{x['open_now_share']:.0%}"}
                          for x in rows], hide_index=True, width="stretch")

    st.markdown('<div class="section"><h2>More detail</h2></div>', unsafe_allow_html=True)
    tabs = st.tabs(["⬇️ Download", "Maps", "Biomass check", "Forest loss", "Data used", "All notes"])
    fig = r.figures
    with tabs[1]:
        if "maps" in fig:
            st.image(fig["maps"]["light"], width="stretch")
            st.caption("Left: NISAR HV backscatter (bright = more vegetation). Middle: biomass; dots = at or above "
                       "the saturation level. Right: forest-loss zones over the backscatter.")
    with tabs[2]:
        if "calibration" in fig:
            st.image(fig["calibration"]["light"], width="stretch")
            st.caption("Left: NISAR HV against the ESA CCI biomass map, with the fitted curve; it flattens where "
                       "the radar saturates. Right: NISAR biomass against the reference on the 30 % of the area "
                       "kept aside for checking.")
        show_notes([n for n in r.notes if n.stage == "biomass"])
    with tabs[3]:
        for key, cap in (("separation", "How intact forest and cleared land look to NISAR, and the level used to "
                                        "tell them apart."),
                         ("timeseries", "Backscatter through time: a clearing is a sudden, lasting drop."),
                         ("hansen_years", "Tree-cover loss per year mapped by Hansen et al. over the area.")):
            if key in fig:
                st.image(fig[key]["light"], width="stretch")
                st.caption(cap)
        show_notes([n for n in r.notes if n.stage == "change"])
    with tabs[4]:
        st.dataframe([{"Date": str(s.date), "Track": s.track, "Pass": s.direction, "Frame": s.frame,
                       "Valid": f"{s.valid_fraction:.0%}", "File": s.name} for s in r.scenes],
                     hide_index=True, width="stretch")
        show_notes([n for n in r.notes if n.stage in ("search", "load", "reference")])
    with tabs[5]:
        for stage, title in STAGES.items():
            notes = [n for n in r.notes if n.stage == stage]
            if notes:
                st.markdown(f"#### {title}")
                show_notes(notes)
    with tabs[0]:
        rep = Path(r.outputs.get("report", ""))
        if rep.is_file():
            st.download_button("⬇️ Download the full report (HTML, opens in any browser)", rep.read_bytes(),
                               file_name=rep.name, type="primary", key="f_dl_report")
        st.markdown("**Maps for GIS software (QGIS, ArcGIS), the zones (CSV, GeoJSON) and the numbers (JSON)**")
        download_grid({k: v for k, v in r.outputs.items() if k != "report"}, "f_dl")


def page_forest():
    from sarcompare.biomass.webmap import FOREST_PLACES

    with st.container(border=True, key="step_f_mode"):
        step(1, "What would you like to do?")
        modes = [MODE_DEMO, MODE_REAL]
        captions = ["No account needed. A made-up forest, written in the real NISAR format, shows how it works.",
                    "Maps biomass and forest loss for a real forest (free NASA account)."]
        mode = st.radio("Forest mode", modes, captions=captions, horizontal=True, label_visibility="collapsed",
                        key="f_mode")
        if mode == MODE_DEMO:
            st.info("**Demo:** a made-up 14 × 13 km forest in central India with a mine extension cleared during "
                    "the monsoon, an older mine cut, and a patch cleared early in 2026. Just press **Run** below.")
    bbox, period, token = None, (None, None), None
    if mode == MODE_DEMO:
        n_next = 2
    else:
        with st.container(border=True, key="step_f_area"):
            bbox = choose_area(FOREST_PLACES, ns="f_", step_no=2,
                               hint="Pick an example forest, or search a place and draw a box over the forest. "
                                    "100-1,000 km² works best.")
        with st.container(border=True, key="step_f_period"):
            period = choose_forest_period(3)
        with st.container(border=True, key="step_f_token"):
            token = token_step(4)
        n_next = 5
    adv = forest_settings()
    with st.container(border=True, key="step_f_run"):
        step(n_next, "Run", "The demo takes under a minute; a real forest 2-5 minutes.")
        if st.button("▶ Run forest analysis", type="primary", key="f_run"):
            problem = None
            if mode == MODE_REAL and not bbox:
                problem = "Please choose an area first (step 2)."
            elif mode == MODE_REAL and ONLINE and not token:
                problem = "Please paste your free NASA Earthdata token (step 4)."
            elif mode == MODE_REAL and period[0] and period[1] and period[0] >= period[1]:
                problem = "The start date must be before the end date."
            if problem:
                st.warning(problem)
            else:
                try:
                    cfg = build_forest_config(mode, bbox, period, token, adv)
                    if ONLINE and mode == MODE_REAL and cfg.get_aoi().area_km2() > MAX_AOI_KM2:
                        raise ValueError(f"The online version handles areas up to {MAX_AOI_KM2:,.0f} km². "
                                         "Draw a smaller box, or run the app on your own computer.")
                except ValueError as e:
                    st.warning(str(e))
                else:
                    result = run_forest(cfg)
                    if result is not None:
                        st.session_state["forest_result"] = result
    if st.session_state.get("forest_result") is not None:
        show_forest_results(st.session_state["forest_result"])

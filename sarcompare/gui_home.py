# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Home page of the web app: what OpenSAR Explorer does, its two modules, how it works, and the data it uses."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from sarcompare import __author__
from sarcompare.ui_style import card_title, chips, hero, how, section, ticks

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _image(name: str):
    path = DOCS / name
    if path.is_file():
        st.image(str(path), width="stretch")


def page_home():
    from sarcompare.gui import PAGES

    st.markdown(hero("OpenSAR Explorer",
                     "See the Earth through satellite radar: ground that sinks or rises, forests that grow or "
                     "disappear. Pick a place, and the app reads NASA–ISRO's NISAR and ESA's Sentinel-1 for you, "
                     "checks them against independent data, and explains the result in plain language.",
                     __author__,
                     ["NISAR · Sentinel-1", "Free, open data", "Runs in your browser", "Plain-language results"]),
                unsafe_allow_html=True)

    c1, c2 = st.columns(2, gap="large")
    with c1, st.container(border=True, key="card_home_motion"):
        _image("demo_rate_maps.png")
        st.markdown(card_title("🛰️", "Ground Motion", "motion")
                    + '<p class="card-text">Is the ground sinking or rising? Millimetre-scale motion from two radar '
                      "satellites, side by side.</p>"
                    + ticks(["Subsidence from groundwater pumping, mining and landslides",
                             "NISAR (L-band) and Sentinel-1 (C-band) compared and explained",
                             "Checked against GNSS stations, EGMS and published studies"], "motion"),
                    unsafe_allow_html=True)
        if "Ground Motion" in PAGES:
            st.page_link(PAGES["Ground Motion"], label="Open Ground Motion", icon=":material/arrow_forward:")
    with c2, st.container(border=True, key="card_home_forest"):
        _image("forest_demo_maps.png")
        st.markdown(card_title("🌳", "Forests & Biomass", "forest")
                    + '<p class="card-text">How much wood does a forest hold, and where is it being cleared? '
                      "NISAR's L-band radar sees into the canopy.</p>"
                    + ticks(["Above-ground biomass in tonnes per hectare, with its limits shown",
                             "New clearing dated between satellite passes",
                             "Checked against ESA CCI Biomass and Global Forest Change maps"], "forest"),
                    unsafe_allow_html=True)
        if "Forests & Biomass" in PAGES:
            st.page_link(PAGES["Forests & Biomass"], label="Open Forests & Biomass", icon=":material/arrow_forward:")

    st.markdown(section("How it works", "three steps, no installation")
                + how([("Choose a place", "Pick an example, search a town, or draw a box on the map. Demos need no "
                                          "account at all."),
                       ("The satellites are read for you", "Only the part of each multi-gigabyte file over your "
                                                           "area is downloaded, straight from NASA's archive."),
                       ("Read the result", "A plain-language summary first, then maps, checks against independent "
                                           "data, and a report to download.")]),
                unsafe_allow_html=True)

    st.markdown(section("Built on open data", "credited in every report")
                + chips([("NISAR", "NASA/ISRO, L-band"), ("Sentinel-1", "ESA Copernicus, C-band"),
                         ("ASF", "Alaska Satellite Facility"), ("GNSS", "Nevada Geodetic Laboratory"),
                         ("EGMS", "European Ground Motion Service"), ("WorldCover", "ESA, 2021"),
                         ("Global Forest Change", "Hansen/UMD/Google/USGS/NASA"), ("CCI Biomass", "ESA")]),
                unsafe_allow_html=True)
    st.caption("A research and learning tool: results are estimates to be checked by experts before any decision. "
               "Real data need a free NASA Earthdata account; the demos need nothing.")

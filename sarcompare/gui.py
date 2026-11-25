# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""OpenSAR Explorer graphical interface: a guided, map-based web app (runs in your browser).

Start it with ``sarcompare gui`` (or double-click Start-GUI.bat / start-gui.command / start-gui.sh).
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from sarcompare import __author__, __copyright__, code_version
from sarcompare.config import Config
from sarcompare.notes import GOOD, WARN
from sarcompare.pipeline import Event, Pipeline
from sarcompare.ui_style import CSS

ICON = {GOOD: "✅", WARN: "⚠️"}
STAGES = {"search": "Finding satellite data", "download": "Downloading", "load": "Reading the data",
          "stack": "Measuring ground motion", "reference": "Lining up the two satellites",
          "compare": "Comparing NISAR and Sentinel-1", "validate": "Checking against independent data",
          "figures": "Drawing maps", "report": "Writing the report"}
UPLOADS = Path("data/uploads")
REPO = "https://github.com/Dkashkush/OpenSAR-Explorer"
NISAR_LAUNCH = date(2025, 7, 30)


def _setting(name: str, default: str) -> str:
    """Server setting: an environment variable, else a Streamlit secret (e.g. the Secrets box of Streamlit
    Community Cloud), else the default."""
    if name in os.environ:
        return os.environ[name]
    try:
        if st.secrets.load_if_toml_exists():  # quiet when there is no secrets file (local use)
            return str(st.secrets.get(name, default))
    except Exception:  # a malformed secrets file must not stop the app
        pass
    return default


# Hosted mode (set SARCOMPARE_ONLINE=1 on the server): no server folders, per-visitor files, size limits.
ONLINE = _setting("SARCOMPARE_ONLINE", "") == "1"
MAX_AOI_KM2 = float(_setting("SARCOMPARE_MAX_AOI_KM2", "2500"))
MAX_PAIRS_ONLINE = int(_setting("SARCOMPARE_MAX_PAIRS", "8"))

MODE_DEMO, MODE_REAL, MODE_LOCAL = "Try the demo", "Analyse a real place", "Use files I already have"



# ----------------------------------------------------------------------------------------------- helpers


def step(n: int | str, title: str, hint: str = ""):
    st.markdown(f'<div class="step"><span class="n">{n}</span>{title}</div>', unsafe_allow_html=True)
    if hint:
        st.markdown(f'<div class="hint">{hint}</div>', unsafe_allow_html=True)


def show_notes(notes, container=st):
    for n in notes:
        container.markdown(f"{ICON.get(n.level, 'ℹ️')} {n.text}")


def session_id() -> str:
    """Short random id per browser session, so visitors never share uploads or outputs."""
    if "sid" not in st.session_state:
        import uuid
        st.session_state["sid"] = uuid.uuid4().hex[:10]
    return st.session_state["sid"]


def save_upload(f) -> str:
    folder = UPLOADS / session_id()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(f.name).name
    path.write_bytes(f.getbuffer())
    return str(path)


MODULES = {
    "Ground Motion": ("motion", "🛰️", "Module 1 · Ground Motion", "Is the ground sinking or rising?",
                      "Two radar satellites, NISAR and Sentinel-1, measure millimetres of ground motion. See them "
                      "side by side, checked against GNSS stations and published studies, in plain language."),
    "Forests & Biomass": ("forest", "🌳", "Module 2 · Forests & Biomass", "How much wood, and where is it lost?",
                          "NISAR's L-band radar sees into the canopy: map forest biomass and find where forest is "
                          "being cleared, checked against ESA and Global Forest Change maps."),
    "Learn": ("neutral", "📘", "Learn", "How satellite radar works",
              "InSAR, backscatter, biomass and how to read every map in this app, in a few minutes."),
    "Help & FAQ": ("neutral", "💬", "Help & FAQ", "Answers and first steps",
                   "What to do when no data is found, accounts and tokens, run times, credits and responsible use."),
}


def header(page: str = "Ground Motion"):
    """Module banner and page colours (the Home page draws its own hero)."""
    from sarcompare.ui_style import accent_css, banner

    if page not in MODULES:
        st.markdown(accent_css("neutral"), unsafe_allow_html=True)
        return
    module, icon, kicker, title, text = MODULES[page]
    st.markdown(accent_css(module) + banner(icon, kicker, title, text), unsafe_allow_html=True)


def footer():
    st.markdown(
        f'<div class="app-footer"><div><div class="brand">🛰️ OpenSAR Explorer</div>'
        f"<p>{__copyright__} Created by {__author__}. An independent tool, not affiliated with NASA, ISRO, ESA, ASF "
        "or USGS. Results are research estimates: verify before making decisions.</p>"
        f"<p>Version {code_version()}</p></div>"
        "<div><h5>Data</h5><p>NISAR (NASA/ISRO) and Copernicus Sentinel-1 (ESA) via the "
        '<a href="https://asf.alaska.edu" target="_blank">Alaska Satellite Facility</a>; GNSS from the '
        '<a href="https://geodesy.unr.edu" target="_blank">Nevada Geodetic Laboratory</a>; forest maps from ESA '
        "WorldCover and ESA CCI Biomass, and Hansen/UMD/Google/USGS/NASA (CC BY 4.0); base maps © "
        "OpenStreetMap contributors and Esri.</p></div>"
        "<div><h5>About</h5><ul>"
        f'<li><a href="{REPO}/blob/HEAD/TERMS.md" target="_blank">Terms of use</a></li>'
        f'<li><a href="{REPO}/blob/HEAD/PRIVACY.md" target="_blank">Privacy</a></li>'
        f'<li><a href="{REPO}/blob/HEAD/LICENSE" target="_blank">Licence</a></li>'
        f'<li><a href="{REPO}/blob/HEAD/THIRD_PARTY_NOTICES.md" target="_blank">Data credits</a></li>'
        "</ul></div></div>",
        unsafe_allow_html=True)


# ----------------------------------------------------------------------------------------------- Explore page


def choose_area(examples: dict | None = None, ns: str = "", step_no: int = 2,
                hint: str = "Search for any place, then draw a box around the area you want on the map."):
    """Step ``step_no``: map + example places + typed coordinates. Returns (W, S, E, N) or None.

    ``ns`` prefixes the page's session keys, so each module keeps its own area and examples."""
    from streamlit_folium import st_folium

    from sarcompare.aoi import AOI
    from sarcompare.maps import EXAMPLE_PLACES, bbox_from_drawing, box_around, find_place, picker_map

    examples = EXAMPLE_PLACES if examples is None else examples

    step(step_no, "Where?", hint)
    side, mapcol = st.columns([2, 3], gap="large")
    with side:
        with st.form(ns + "place_search", border=False):
            q1, q2 = st.columns([3, 1], vertical_alignment="bottom")
            query = q1.text_input("Search a place", placeholder="e.g. Jakarta, Tehran, Venice, Joshimath")
            searched = q2.form_submit_button("Search", width="stretch")
        if searched:
            try:
                st.session_state[ns + "places"] = find_place(query)
                if not st.session_state[ns + "places"]:
                    st.warning(f"No place called '{query}' was found. Try adding the country, e.g. 'Delhi, India'.")
            except OSError:
                st.session_state[ns + "places"] = []
                st.error("Place search is not reachable right now. Zoom the map by hand, or type coordinates below.")
        places = st.session_state.get(ns + "places") or []
        if places:
            names = [p["name"] for p in places]
            pick = st.selectbox("Found", names, key=ns + "place_pick") if len(places) > 1 else names[0]
            found = places[names.index(pick)]
            if st.session_state.get(ns + "_view_for") != found["name"]:  # new place: move the map there
                st.session_state[ns + "_view_for"] = found["name"]
                st.session_state[ns + "view"] = (found["lat"], found["lon"], 11)
                st.session_state[ns + "bbox"] = None
            st.caption(f"Map moved to **{found['name']}**. Now draw your box on the map (square ▢ button), or:")
            if st.button("Use a box around this place", width="stretch"):
                st.session_state[ns + "bbox"] = box_around(found["lat"], found["lon"], found["bbox"],
                                                      max_km2=min(MAX_AOI_KM2, 900) if ONLINE else 900)
                st.rerun()
        options = ["(or choose an example place)"] + list(examples)
        place = st.selectbox("Example places", options, key=ns + "place")
        if place != options[0] and st.session_state.get(ns + "_place_applied") != place:
            st.session_state[ns + "bbox"] = examples[place]
            st.session_state[ns + "_place_applied"] = place
            st.session_state[ns + "view"] = None
        with st.expander("Type coordinates instead"):
            cur = st.session_state.get(ns + "bbox") or (-99.25, 19.25, -98.95, 19.55)
            c1, c2 = st.columns(2)
            w = c1.number_input("West (longitude)", -180.0, 180.0, float(cur[0]), format="%.4f")
            e = c2.number_input("East (longitude)", -180.0, 180.0, float(cur[2]), format="%.4f")
            s = c1.number_input("South (latitude)", -90.0, 90.0, float(cur[1]), format="%.4f")
            n = c2.number_input("North (latitude)", -90.0, 90.0, float(cur[3]), format="%.4f")
            if st.button("Use these coordinates"):
                if w < e and s < n:
                    st.session_state[ns + "bbox"] = (w, s, e, n)
                    st.session_state[ns + "view"] = None
                else:
                    st.error("West must be less than East, and South less than North.")
        bbox = st.session_state.get(ns + "bbox")
        if bbox:
            area = AOI.from_bbox(*bbox).area_km2()
            st.metric("Selected area", f"{area:,.0f} km²")
            st.caption(f"{bbox[1]:.3f}° to {bbox[3]:.3f}° N · {bbox[0]:.3f}° to {bbox[2]:.3f}° E")
            if ONLINE and area > MAX_AOI_KM2:
                st.warning(f"The online version handles areas up to {MAX_AOI_KM2:,.0f} km². Draw a smaller box.")
            elif area > 5000:
                st.info("Large area: downloads will be big and processing slow. 300–2,500 km² works best.")
        else:
            st.info("No area selected yet.")
    with mapcol:
        st.markdown("**1.** Find your place with the search on the left, or zoom the map with the mouse wheel.  \n"
                    "**2.** Click the **square ▢ button** on the left of the map.  \n"
                    "**3.** Click and drag to draw a box around your area. Draw again to replace it.")
        out = st_folium(picker_map(bbox, view=st.session_state.get(ns + "view")), height=430, use_container_width=True,
                        returned_objects=["last_active_drawing"], key=ns + "picker")
        drawn = bbox_from_drawing((out or {}).get("last_active_drawing"))
        if drawn and drawn != st.session_state.get(ns + "_last_drawn"):
            st.session_state[ns + "_last_drawn"] = drawn
            st.session_state[ns + "bbox"] = drawn
            st.rerun()
    return st.session_state.get(ns + "bbox")


def choose_period():
    step(3, "When?", "Longer periods give more reliable results. NISAR data start in late 2025.")
    today = date.today()
    choice = st.radio("Time period", ["Last 6 months", "Last 12 months", "Since NISAR launch (July 2025)",
                                      "Custom dates"], index=2, horizontal=True, label_visibility="collapsed")
    if choice == "Last 6 months":
        return today - timedelta(days=183), today
    if choice == "Last 12 months":
        return today - timedelta(days=365), today
    if choice.startswith("Since"):
        return NISAR_LAUNCH, today
    c1, c2, _ = st.columns([1, 1, 2])
    return c1.date_input("From", NISAR_LAUNCH), c2.date_input("To", today)


def choose_checks(n: int):
    step(n, "Extra checks (optional)", "Compare the satellite results with independent measurements.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        gnss = st.toggle("Compare with GNSS ground stations (recommended)", value=True,
                         help="Free GPS station data from the Nevada Geodetic Laboratory, downloaded automatically "
                              "for stations inside your area.")
        gnss_csv = None
        if gnss and st.checkbox("Use my own table of station velocities instead (CSV)"):
            gnss_csv = st.file_uploader("CSV with columns site, lon, lat, up_mm_yr, up_sigma_mm_yr", type=["csv"])
    with c2:
        from sarcompare.validate import egms_defaults

        files = st.file_uploader("Compare with published velocity maps (optional)", type=["tif", "tiff", "nc"],
                                 accept_multiple_files=True,
                                 help="For example EGMS Ortho tiles (Europe: the vertical 'U' and east-west 'E' "
                                      "files are recognised automatically), LiCSAR/COMET or OPERA velocity maps, "
                                      "or data from a paper.")
        with st.expander("EGMS maps for Europe: automatic with a free key"):
            st.markdown("EGMS (the EU's European Ground Motion Service) maps ground motion across Europe from "
                        "Sentinel-1, calibrated with GNSS, so it is an independent check. With your free EGMS key "
                        "the app downloads the right tiles itself:\n1. Sign in at "
                        "[egms.land.copernicus.eu](https://egms.land.copernicus.eu) (free EU Login).\n2. In the "
                        "Explorer, right-click any **download** link and copy it: it ends with `?id=` followed by "
                        "your key.\n3. Paste the part after `id=` below.\n\nOr download the **Ortho** vertical "
                        "(U) and east-west (E) tiles yourself and upload the `.tiff` files above. EGMS periods "
                        "end before NISAR's start, which is fine for steady motion.")
            egms_key = st.text_input("EGMS download key (used only for this run, never stored)", type="password",
                                     key="egms_key")
        pub = []
        manual = [f for f in files or [] if not egms_defaults(f.name)]
        for f in files or []:
            spec = egms_defaults(f.name)
            if spec:
                st.success(f"{f.name}: recognised as {spec['label']}; settings filled in automatically.")
                pub.append((f, spec))
        if manual:
            st.caption("Settings for " + ", ".join(f.name for f in manual) + ":")
            a1, a2 = st.columns(2)
            units = a1.selectbox("Units", ["mm/yr", "cm/yr", "m/yr", "ft/yr", "in/yr",
                                           "mm (total over a period)", "cm (total over a period)",
                                           "ft (total over a period)"])
            comp = a2.selectbox("Direction", ["vertical", "LOS", "east-west"],
                                help="LOS = along the satellite's line of sight (most InSAR velocity maps). "
                                     "east-west maps are compared with this run's east-west maps.")
            years = (st.number_input("Years the map covers", 0.1, 50.0, 1.0, 0.1)
                     if "total" in units else None)
            sign = st.radio("Positive values mean", ["up / toward satellite / east", "down / away / west"],
                            horizontal=True)
            inc = st.number_input("Incidence angle (°)", 20.0, 50.0, 39.0) if comp == "LOS" else None
            cite = st.text_input("Source / citation", placeholder="e.g. California DWR, TRE ALTAMIRA InSAR, 2025")
            for f in manual:
                pub.append((f, {"label": Path(f.name).stem, "units": units.split(" ")[0], "component": comp,
                                "sign": 1 if sign.startswith("up") else -1, "incidence_deg": inc,
                                "period_years": years, "citation": cite}))
    lit = published_values_editor()
    return gnss, gnss_csv, pub, (egms_key or "").strip() or None, lit


def published_values_editor() -> list[dict]:
    """Editable table for rates reported in papers or official reports."""
    with st.expander("📚 Compare with rates from published studies (optional)"):
        st.caption("Type in rates you read in papers or official reports, with the citation. The app compares its "
                   "own result at the same place. Use the study's period and vertical rates where possible.")
        import pandas as pd

        empty = pd.DataFrame({"Citation": pd.Series(dtype="str"), "Place": pd.Series(dtype="str"),
                              "Longitude": pd.Series(dtype="float"), "Latitude": pd.Series(dtype="float"),
                              "Rate (mm/yr)": pd.Series(dtype="float"), "Direction": pd.Series(dtype="str"),
                              "Reported as": pd.Series(dtype="str"), "Period": pd.Series(dtype="str")})
        table = st.data_editor(
            empty, num_rows="dynamic", width="stretch", key="lit_table",
            column_config={
                "Citation": st.column_config.TextColumn(help="e.g. Smith et al. (2021), Journal, volume"),
                "Rate (mm/yr)": st.column_config.NumberColumn(min_value=0.0, help="Size of the motion"),
                "Direction": st.column_config.SelectboxColumn(options=["sinking", "rising"], default="sinking"),
                "Reported as": st.column_config.SelectboxColumn(
                    options=["typical rate", "peak"], default="typical rate",
                    help="'peak' if the paper gives the fastest motion there (e.g. 'up to', 'peaks of')"),
                "Period": st.column_config.TextColumn(help="Years the study covers, e.g. 2015-2020"),
            })
    values = []
    for _, row in table.iterrows():
        try:
            lon, lat, rate = float(row["Longitude"]), float(row["Latitude"]), float(row["Rate (mm/yr)"])
        except (TypeError, ValueError):
            continue
        if any(v != v for v in (lon, lat, rate)):  # NaN: incomplete row
            continue
        sign = 1.0 if str(row.get("Direction")) == "rising" else -1.0
        values.append({"citation": str(row.get("Citation") or "").strip(), "place": str(row.get("Place") or ""),
                       "lon": lon, "lat": lat, "rate_mm_yr": sign * abs(rate), "period": str(row.get("Period") or ""),
                       "stat": "peak" if str(row.get("Reported as")) == "peak" else "median",
                       "radius_km": 2.0 if str(row.get("Reported as")) == "peak" else 1.0})
    return values


def token_step(n: int):
    step(n, "Your free NASA Earthdata token", "Needed to download satellite data. It is used only for your own "
                                              "downloads in this session and is never saved.")
    c1, c2 = st.columns([1, 1], gap="large")
    token = c1.text_input("Earthdata token", type="password", label_visibility="collapsed",
                          placeholder="Paste your token here")
    with c2.expander("How do I get a token? (about 2 minutes)"):
        st.markdown("1. Create a free account at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/users/new).\n"
                    "2. Log in and open **Generate Token** (in your profile menu).\n"
                    "3. Click **Generate Token**, copy it, and paste it here.\n\n"
                    "Tokens expire after about two months; just make a new one.")
    return token


def advanced_settings():
    with st.expander("⚙️ Advanced settings (most people can skip this)"):
        c1, c2, c3 = st.columns(3)
        s1 = c1.selectbox("Sentinel-1 product", ["Automatic (recommended)", "ARIA interferograms",
                                                 "OPERA DISP-S1 (North America)", "Ordered from ASF HyP3",
                                                 "LiCSAR (COMET)"],
                          help="Automatic tries the ready-made products (ARIA, then OPERA in North America), "
                               "then interferograms you ordered from ASF HyP3 for this area, then LiCSAR "
                               "(free, ready-made for many tectonic and volcanic regions, e.g. from the "
                               "Mediterranean to the Himalaya).")
        direction = c1.selectbox("Satellite pass", ["Any", "ASCENDING", "DESCENDING"])
        coh = c2.slider("Data quality threshold (coherence)", 0.1, 0.8, 0.35, 0.05,
                        help="Pixels whose radar signal is less stable than this are left out.")
        max_pairs = c2.slider("Image pairs per satellite", 2, MAX_PAIRS_ONLINE if ONLINE else 20, 6)
        res = c3.select_slider("Map pixel size (m)", [30, 60, 90, 120, 200], value=90)
        vertical = c3.checkbox("Show vertical motion", True, help="Converts line-of-sight motion to up/down.")
        both_dirs = c3.checkbox("Use both orbit directions", True,
                                help="Combine passes from north-going (ascending) and south-going (descending) "
                                     "orbits when both cover your area. This separates up-down from east-west "
                                     "motion instead of assuming the ground only moves up and down. Reads about "
                                     "twice as many files.")
        iono = c3.checkbox("Correct NISAR for the ionosphere", True)
        ref = st.text_input("Stable reference point 'longitude, latitude' (blank = automatic)", "")
    s1_code = {"Automatic (recommended)": "AUTO", "ARIA interferograms": "ARIA_S1_GUNW",
               "Ordered from ASF HyP3": "HYP3", "LiCSAR (COMET)": "LICSAR"}.get(s1, "OPERA_DISP_S1")
    return dict(s1=s1_code, direction=None if direction == "Any" else direction, coh=coh, max_pairs=max_pairs,
                res=res, vertical=vertical, iono=iono, ref=ref, both_dirs=both_dirs)


def build_config(mode, bbox, period, checks, token, adv, local_dirs) -> Config:
    from sarcompare.demo import demo_config

    gnss, gnss_csv, pub, egms_key, lit = checks
    if mode == MODE_DEMO:
        cfg = demo_config()
        if not gnss:
            cfg.gnss = None
    else:
        kw = dict(name="my_area", aoi=list(bbox), start=period[0], end=period[1], s1_source=adv["s1"],
                  nisar_flight_direction=adv["direction"], s1_flight_direction=adv["direction"])
        if mode == MODE_LOCAL:
            kw.update(nisar_source="LOCAL", nisar_dir=local_dirs[0], s1_source="LOCAL", s1_dir=local_dirs[1])
        cfg = Config(**kw)
        cfg.gnss = "NGL" if gnss else None
        cfg.earthdata_token = token or None  # per session; never os.environ (shared by all users of a server)
        cfg.egms_token = egms_key  # likewise per session
    if gnss and gnss_csv is not None:
        cfg.gnss = save_upload(gnss_csv)
    if pub:
        cfg.published_maps = list(cfg.published_maps) + [{"path": save_upload(f), **spec} for f, spec in pub]
    if lit:
        cfg.published_values = list(cfg.published_values) + lit
    if ONLINE:
        cfg.output_dir = f"outputs/{session_id()}"
    cfg.coherence_threshold, cfg.resolution_m, cfg.max_pairs = adv["coh"], float(adv["res"]), adv["max_pairs"]
    cfg.project_to_vertical, cfg.nisar_apply_ionosphere = adv["vertical"], adv["iono"]
    cfg.combine_directions = adv.get("both_dirs", True)
    if adv["ref"].strip():
        cfg.reference_lonlat = tuple(float(v) for v in adv["ref"].split(","))
    return cfg


def friendly_error(e: Exception) -> str:
    msg, name = str(e), type(e).__name__
    low = msg.lower()
    if name == "AccessError":  # already a plain-language reason with the fix
        return f"Could not get the data files: {msg}"
    if name in ("HyP3Error", "NoGCOVError"):  # already plain-language reasons
        return msg
    if "credential" in low or ("token" in low and ("invalid" in low or "unauthor" in low)):
        return "Your Earthdata token was not accepted. Check that you pasted all of it, or generate a new one."
    if name in ("ConnectionError", "ProxyError", "Timeout", "ConnectTimeout") or "cmr.earthdata" in low:
        return "Could not reach NASA's data servers. Check your internet connection and try again."
    if "no nisar products" in low or "no sentinel-1 products" in low:
        return msg + " See **Help & FAQ → Why was no data found?** for what to try next."
    return f"Something went wrong: {msg}"


def run_pipeline(cfg: Config, search_only: bool):
    boxes = {}

    def on_event(ev: Event):
        if ev.stage not in boxes:
            boxes[ev.stage] = st.status(STAGES.get(ev.stage, ev.stage), expanded=False)
        boxes[ev.stage].write(f"**{ev.message}**")
        show_notes(ev.notes, boxes[ev.stage])

    p = Pipeline(cfg, on_event)
    try:
        if search_only:
            p.search()
            result = None
        else:
            with st.spinner("Working… this can take a few minutes for real data."):
                result = p.run(download=True)
    except Exception as e:  # show a friendly message instead of a traceback
        for b in boxes.values():
            b.update(state="error")
        st.error(friendly_error(e))
        return None
    for b in boxes.values():
        b.update(state="complete", expanded=False)
    if search_only:
        rows = [x.to_row() for x in p.result.nisar_products + p.result.s1_products]
        if rows:
            st.success(f"Found {len(p.result.nisar_products)} NISAR and {len(p.result.s1_products)} Sentinel-1 image "
                       f"pairs (about {sum(r['size_mb'] or 0 for r in rows) / 1000:.1f} GB to download).")
            for sensor, found in (("Sentinel-1", p.result.s1_products), ("NISAR", p.result.nisar_products)):
                if not found:
                    other = "NISAR" if sensor == "Sentinel-1" else "Sentinel-1"
                    st.info(f"No ready-made {sensor} pairs for this area and period: the analysis will use "
                            f"{other} alone. The search notes above say how to add {sensor}.")
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.warning("No usable image pairs were found for this area and period. See Help & FAQ.")
    return result


def offer_hyp3(res):
    """Plan and order Sentinel-1 interferograms from ASF HyP3 for an area without ready-made ones."""
    from sarcompare.pipeline import Pipeline as _Pipeline

    cfg = res.config
    with st.container(border=True):
        st.markdown("#### Add Sentinel-1: order it from ASF HyP3")
        st.markdown("No ready-made Sentinel-1 interferograms cover this area and period. ASF's free **HyP3** "
                    "service can make them from the raw Sentinel-1 images, on the same dates as the NISAR pairs, "
                    "with your Earthdata login. Processing usually takes under an hour. Then run this area again: "
                    "the finished interferograms are found and used automatically. HyP3 keeps them for 14 days.")
        st.caption("This uses free HyP3 processing credits from your Earthdata account (a monthly allowance). "
                   "HyP3 jobs are publicly visible: the job name (this area's coordinates), the images and your "
                   "Earthdata user name.")
        if not (cfg.earthdata_token or os.environ.get("EARTHDATA_TOKEN")):
            st.info("An Earthdata token is needed to order. Paste yours in the token step and run again.")
            return
        if st.button("Find Sentinel-1 pairs to order", key="hyp3_plan_btn"):
            try:
                p = _Pipeline(cfg, on_event=lambda e: None)
                p.result.nisar_products = list(res.nisar_products)
                with st.spinner("Searching Sentinel-1 images and checking your HyP3 credits…"):
                    pairs, notes = p.hyp3_plan()
                    client = p._hyp3()
                    info = client.user()
                    from sarcompare.hyp3 import access_problem

                    access_problem(info)  # new HyP3 users apply once (free); explained before anything else
                    credits = info.get("remaining_credits")
                    cost = client.cost()
                st.session_state["hyp3_plan"] = (pairs, [n.text for n in notes], credits, cost)
            except Exception as e:
                st.error(friendly_error(e))
        plan = st.session_state.get("hyp3_plan")
        if not plan:
            return
        pairs, texts, credits, cost = plan
        for t in texts:
            st.markdown(f"ℹ️ {t}")
        if not pairs:
            st.warning("No suitable Sentinel-1 image pairs were found for this area and period.")
            return
        st.dataframe([{"From": str(q.date1), "To": str(q.date2), "Days": q.span_days,
                       "Direction": q.direction.lower(), "Track": q.path, "Satellite": q.platform,
                       "Area covered": f"{q.cover:.0%}"} for q in pairs], hide_index=True, width="stretch")
        left = "no limit" if credits is None else f"{credits:,.0f} left this month"
        st.markdown(f"**{len(pairs)} pairs, about {cost * len(pairs):,.0f} credits** ({left}).")
        done = st.session_state.get("hyp3_ordered")
        if done:
            st.success(done)
            return
        if st.button(f"Order {len(pairs)} Sentinel-1 interferograms", type="primary", key="hyp3_order_btn"):
            try:
                p = _Pipeline(cfg, on_event=lambda e: None)
                with st.spinner("Sending the order to ASF HyP3…"):
                    out = p.hyp3_order(pairs)
                msg = " ".join(n.text for n in out.notes)
                if out.skipped:
                    msg += f" {out.skipped} pair(s) were already ordered and were not sent again."
                st.session_state["hyp3_ordered"] = msg
                st.success(msg)
            except Exception as e:
                st.error(friendly_error(e))


def results_title(synthetic: bool):
    badge = ' <span class="badge">Synthetic demo data, not a real place</span>' if synthetic else ""
    st.markdown(f'<div class="section"><h2>Results</h2>{badge}</div>', unsafe_allow_html=True)


def show_map(html: str, height: int = 580):
    if hasattr(st, "iframe"):  # st.components.v1.html is being removed from Streamlit
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)


def download_grid(outputs: dict, prefix: str, per_row: int = 3):
    """Download buttons for result files, laid out in rows of ``per_row``."""
    files = [(k, Path(v)) for k, v in outputs.items() if Path(v).is_file()]
    with st.container(key="downloads"):
        for i in range(0, len(files), per_row):
            cols = st.columns(per_row)
            for col, (key, path) in zip(cols, files[i:i + per_row]):
                col.download_button(f"⬇ {path.name}", path.read_bytes(), file_name=path.name,
                                    key=f"{prefix}_{key}", width="stretch")


def show_results(res):
    from sarcompare.interpret import plain_summary
    from sarcompare.maps import results_map

    c = res.comparison
    maps = res.rates  # one map when a satellite has no data for the area
    sensors = [rm.sensor for rm in maps]
    results_title(bool(res.config.extra.get("synthetic")))
    with st.container(border=True, key="in_short"):
        st.markdown("#### In short")
        for level, text in plain_summary(res):
            st.markdown(f"{ICON.get(level, 'ℹ️')} {text}")

    m = st.columns(5)
    if res.single:
        other = "Sentinel-1" if sensors[0] == "NISAR" else "NISAR"
        m[0].metric(f"Area {sensors[0]} can measure", f"{c.coverage_a:.0%}")
        m[1].metric(other, "No data", help=f"{other} has no usable data for this area and period. "
                                            "See All notes for how to add it.")
        m[2].metric("Noise (1σ)", f"{c.noise_a_mm_yr:.0f} mm/yr" if math.isfinite(c.noise_a_mm_yr) else "n/a",
                    help="Movements smaller than about twice this cannot be told apart from noise.")
        m[3].metric("Moving areas found", len(c.hotspots))
        if res.s1_rate is None and not res.config.extra.get("synthetic"):
            offer_hyp3(res)
    else:
        m[0].metric("Area NISAR can measure", f"{c.coverage_a:.0%}")
        m[1].metric("Area Sentinel-1 can measure", f"{c.coverage_b:.0%}")
        m[2].metric("Agreement (0 to 1)", f"{c.pearson_r:.2f}", help="Correlation between the two speed maps.")
        m[3].metric("Typical difference", f"{c.rmsd_mm_yr:.0f} mm/yr")
        m[4].metric("Moving areas found", len(c.hotspots))

    with st.container(border=True, key="panel_gm_map"):
        st.markdown("#### Map")
        st.caption("Switch layers with the box at the top right. Click markers for details. Red = sinking, "
                   "blue = rising, no colour = no reliable data.")
        # Display-only map: plain embedded HTML is more robust than the two-way map component here.
        show_map(results_map(res).get_root().render())  # built by the app; user text in it is escaped
    if c.hotspots:
        with st.expander(f"Moving areas ({len(c.hotspots)})", expanded=True):
            st.dataframe([{"Detected by": h.sensor, "Latitude": round(h.lat, 4), "Longitude": round(h.lon, 4),
                           "Area (km²)": round(h.area_km2, 1), "Peak (mm/yr)": round(h.peak_mm_yr),
                           "Seen by the other satellite": {"yes": "Yes", "no": "No", "no data": "No data there",
                                                           "single": "Only one satellite here"}[h.seen_by_other]}
                          for h in c.hotspots], hide_index=True, width="stretch")

    st.markdown('<div class="section"><h2>More detail</h2></div>', unsafe_allow_html=True)
    tabs = st.tabs(["⬇️ Download", "Side by side", "Agreement", "Checks", "Data used", "All notes"])
    with tabs[1]:
        st.image(res.figures["rate_maps"]["light"], width="stretch")
        st.caption("Left: NISAR. Middle: Sentinel-1. Right: their difference. Grey = no reliable data."
                   if not res.single else f"{sensors[0]} only (the other satellite has no data here). "
                                          "Grey = no reliable data.")
        if "east_west" in res.figures:
            st.image(res.figures["east_west"]["light"], width="stretch")
            st.caption("Sideways motion, measured by combining passes from the north-going (ascending) and "
                       "south-going (descending) orbits. Around a sinking area the ground often also moves toward "
                       "its centre. Grey = seen from one direction only.")
        st.image(res.figures["coherence_maps"]["light"], width="stretch")
        st.caption("Coherence = how stable the radar signal is between visits. Dark = good. Vegetation usually "
                   "lowers it, much more for Sentinel-1 than for NISAR.")
    with tabs[2]:
        if "scatter" in res.figures:
            col, txt = st.columns([1, 1], gap="large")
            col.image(res.figures["scatter"]["light"], width="stretch")
            txt.markdown("Each dot cloud compares the two satellites pixel by pixel. If they agreed perfectly, "
                         "everything would sit on the dashed 1:1 line.")
            show_notes([n for n in res.notes if n.stage == "compare"], txt)
        else:
            st.info("Only one satellite has data for this area, so there is nothing to compare it with. Its "
                    "results are checked against GNSS and published studies instead (Checks tab).")
            show_notes([n for n in res.notes if n.stage == "compare"])
    with tabs[3]:
        vnotes = [n for n in res.notes if n.stage == "validate"]
        if not vnotes:
            st.info("No extra checks were selected. Turn on 'Compare with GNSS ground stations'.")
        if "gnss" in res.figures:
            col, txt = st.columns([1, 1], gap="large")
            col.image(res.figures["gnss"]["light"], width="stretch")
            show_notes(vnotes, txt)
            from .validate import station_rate

            st.dataframe([{"Station": s.site, "Latitude": round(s.lat, 4), "Longitude": round(s.lon, 4),
                           **{k: v for sn in sensors for k, v in (
                               (f"{sn} (mm/yr)", round(s.insar.get(sn, float("nan")), 1)),
                               (f"GNSS, {sn} dates", round(station_rate(s, sn), 1)))},
                           "GNSS long-term (mm/yr)": round(s.up_mm_yr, 1)}
                          for s in res.gnss.stations], hide_index=True, width="stretch")
        else:
            show_notes(vnotes)
        for k in range(len(res.published)):
            st.image(res.figures[f"published_{k}"]["light"], width="stretch")
        if res.literature:
            st.markdown("**Published studies**")
            names = {"consistent": "✓ consistent", "differs": "! differs", "no data": "no data",
                     "outside area": "outside area"}
            st.dataframe([{"Study": c.citation, "Place": c.place, "Period": c.period,
                           "Published (mm/yr)": (f"{c.published_min:+.0f} to {c.published_max:+.0f}"
                                                 if c.published_min is not None and c.published_max is not None
                                                 else f"{c.published_mm_yr:+.0f}"),
                           **{k: v for sn in sensors for k, v in (
                               (f"{sn} (mm/yr)", round(c.insar.get(sn, float("nan")), 0)),
                               (f"{sn} check", names.get(c.verdict.get(sn), "")))}}
                          for c in res.literature], hide_index=True, width="stretch")
            st.caption("Vertical rates, negative = sinking. Differences often come from different periods: "
                       "subsidence speeds up in droughts and slows after wet years.")
    with tabs[4]:
        st.image(res.figures["timeline"]["light"], width="stretch")
        st.dataframe([p.to_row() for p in res.nisar_products + res.s1_products], hide_index=True,
                     width="stretch")
    with tabs[5]:
        for stage, title in STAGES.items():
            notes = [n for n in res.notes if n.stage == stage]
            if notes:
                st.markdown(f"#### {title}")
                show_notes(notes)
    with tabs[0]:
        rep = Path(res.outputs.get("report", ""))
        if rep.is_file():
            st.download_button("⬇️ Download the full report (HTML, opens in any browser)", rep.read_bytes(),
                               file_name=rep.name, type="primary", key="dl_report")
        st.markdown("**Map files for GIS software (QGIS, ArcGIS) and the numbers (JSON)**")
        download_grid({k: v for k, v in res.outputs.items() if k != "report"}, "dl")


def page_explore():
    with st.container(border=True, key="step_gm_mode"):
        step(1, "What would you like to do?")
        modes = [MODE_DEMO, MODE_REAL] + ([] if ONLINE else [MODE_LOCAL])
        captions = ["No account needed. Uses made-up data to show how everything works.",
                    "Downloads real NISAR and Sentinel-1 data for any place (free NASA account).",
                    "Analyse NISAR and Sentinel-1 files you already downloaded."][:len(modes)]
        mode = st.radio("Mode", modes, captions=captions, horizontal=True, label_visibility="collapsed")
        if mode == MODE_DEMO:
            st.info("**Demo:** a made-up 30 × 28 km scene with a sinking city and a landslide under forest, written "
                    "in the real NISAR and Sentinel-1 file formats. Just press **Run analysis** below.")

    bbox, period, token, local_dirs = None, (None, None), None, (None, None)
    if mode == MODE_DEMO:
        with st.container(border=True, key="step_gm_checks"):
            checks = choose_checks(2)
        n_next = 3
    else:
        with st.container(border=True, key="step_gm_area"):
            bbox = choose_area()
        with st.container(border=True, key="step_gm_period"):
            period = choose_period()
        with st.container(border=True, key="step_gm_checks"):
            checks = choose_checks(4)
        with st.container(border=True, key="step_gm_access"):
            if mode == MODE_REAL:
                token = token_step(5)
            else:
                step(5, "Where are your files?")
                c1, c2 = st.columns(2)
                local_dirs = (c1.text_input("Folder with NISAR GUNW .h5 files", "data/NISAR"),
                              c2.text_input("Folder with Sentinel-1 files (ARIA .nc, OPERA .nc, HyP3 .zip)",
                                            "data/Sentinel-1"))
        n_next = 6
    adv = advanced_settings()

    run_card = st.container(border=True, key="step_gm_run")
    with run_card:
        step(n_next, "Run", "A demo takes under a minute; real data a few minutes.")
        b1, b2, _ = st.columns([1, 1, 2])
        run = b1.button("▶ Run analysis", type="primary", width="stretch")
        check = b2.button("Check available data", width="stretch", disabled=mode != MODE_REAL,
                          help="Search only, without downloading, to see what exists for your area and dates.")
    with run_card:
        if run or check:
            problem = None
            if mode != MODE_DEMO and not bbox:
                problem = "Please choose an area first (step 2)."
            elif mode == MODE_REAL and ONLINE and not token:
                problem = "Please paste your free NASA Earthdata token (step 5)."
            elif mode != MODE_DEMO and period[0] and period[1] and period[0] >= period[1]:
                problem = "The start date must be before the end date."
            if problem:
                st.warning(problem)
            else:
                try:
                    cfg = build_config(mode, bbox, period, checks, token, adv, local_dirs)
                    if ONLINE and mode != MODE_DEMO and cfg.get_aoi().area_km2() > MAX_AOI_KM2:
                        raise ValueError(f"The online version handles areas up to {MAX_AOI_KM2:,.0f} km². "
                                         "Draw a smaller box, or run the app on your own computer.")
                except ValueError as e:
                    st.warning(str(e))
                else:
                    result = run_pipeline(cfg, search_only=check)
                    if result is not None:
                        st.session_state["result"] = result
                        st.session_state.pop("hyp3_plan", None)  # an order offer belongs to one result
                        st.session_state.pop("hyp3_ordered", None)
    if st.session_state.get("result") is not None:
        show_results(st.session_state["result"])


# ----------------------------------------------------------------------------------------------- Learn / Help


def page_learn():
    tabs = st.tabs(["📡 Radar basics", "🛰️ Ground motion", "🌳 Forests & biomass", "📖 Glossary"])
    with tabs[0]:
        st.markdown(
            "**Radar satellites can measure ground motion of a few millimetres.** A radar satellite sends microwaves "
            "to the ground and records the echo. When it passes over the same place again days later, tiny changes "
            "in the distance between the satellite and the ground show up as a shift in the echo's *phase*. Comparing "
            "two such images is called **InSAR** (Interferometric Synthetic Aperture Radar). Comparing many images "
            "over months gives the ground's **speed**, in millimetres per year.")
        st.markdown("### Two satellites, two wavelengths")
        st.markdown(
            "| | NISAR | Sentinel-1 |\n|---|---|---|\n"
            "| Built by | NASA and ISRO (launched July 2025) | ESA, Copernicus (since 2014) |\n"
            "| Radar wavelength | 24 cm (L-band) | 5.6 cm (C-band) |\n"
            "| Sees through vegetation? | Largely yes: works in forests and fields | Mostly no: leaves scramble the "
            "signal |\n"
            "| Sensitivity to small motion | Good | Very good |\n"
            "| Affected by the ionosphere | More (the app corrects it) | Less |\n"
            "| Archive | New | More than 10 years |")
        st.markdown("Where **both agree**, the motion is very likely real. Where **only NISAR has data** (often "
                    "under vegetation), you may be seeing something no one could measure before.")
    with tabs[1]:
        st.markdown("### How to read the maps")
        c1, c2 = st.columns(2, gap="large")
        c1.markdown("- 🟥 **Red**: the ground is moving **down** (sinking, *subsidence*).\n"
                    "- 🟦 **Blue**: the ground is moving **up** (rising, *uplift*).\n"
                    "- ⬜ **Pale**: little or no motion.\n"
                    "- **No colour**: no reliable measurement (water, dense vegetation for Sentinel-1, steep slopes, "
                    "or too few good images).")
        c2.markdown("- **Motion is relative** unless GNSS is on. Without GNSS, zero means the typical motion of your "
                    "area; with GNSS stations in the area, the maps are tied to them and zero means no motion.\n"
                    "- **Speeds are averages** over your time period; seasonal ups and downs are averaged out.\n"
                    "- **'Vertical'** assumes the ground moves only up and down. Landslides also move sideways.")
        st.markdown("### What usually causes ground motion?")
        st.markdown("- **Groundwater pumping:** broad, bowl-shaped sinking in cities and farmland, centimetres per "
                    "year.\n"
                    "- **Landslides and creep:** small, fast patches on slopes.\n"
                    "- **Mining and tunnelling:** localised sinking.\n"
                    "- **Volcanoes and earthquakes:** uplift or sudden offsets.\n"
                    "- **Building settlement and reclaimed land:** slow sinking of individual structures.")
    with tabs[2]:
        st.markdown("### Forests and biomass (Forests & Biomass module)")
        st.markdown(
            "NISAR's 24 cm radar waves pass through leaves and bounce off **branches and trunks**. The part of the echo "
            "that comes back with its polarisation turned (**HV**, cross-polarised) grows with the amount of wood, so "
            "it measures **above-ground biomass**: tonnes of dry wood per hectare. The app calibrates this relation "
            "for your area against the ESA CCI biomass map and checks it on parts of the area it did not train on.\n\n"
            "- **Saturation:** above roughly 100-150 t/ha the echo stops growing, so very dense forest is shown as "
            "'at least' that much.\n"
            "- **Clearing:** cutting a forest removes the trunks, and the HV echo drops by 5-10 dB from one visit to "
            "the next. The app dates such drops between two NISAR images and compares them with Hansen et al.'s "
            "global forest-loss maps (2001-2025).\n"
            "- **Carbon:** about 47 % of dry wood is carbon; each tonne of carbon is 3.67 tonnes of CO₂.")
    with tabs[3]:
        st.markdown("### Glossary")
        terms = {
            "InSAR": "Comparing radar images taken at different times to measure ground motion.",
            "Interferogram (pair)": "The comparison of two radar images; shows motion between their two dates.",
            "Coherence": "From 0 to 1: how similar the radar echo is between the two dates. Low = unreliable.",
            "Line of sight (LOS)": "The direction from the ground to the satellite. InSAR measures motion along it.",
            "Ionosphere": "The upper atmosphere. It delays radar signals, especially longer wavelengths like NISAR's.",
            "GNSS": "Satellite positioning (GPS and similar). Permanent stations measure ground motion very precisely at "
                    "one point, so they are ideal for checking InSAR.",
            "Subsidence": "The ground sinking.",
            "Reference point": "The place assumed to be stable; all motion is measured relative to it.",
            "GUNW": "NISAR's ready-made 'geocoded unwrapped interferogram' product.",
            "GCOV": "NISAR's ready-made backscatter product (geocoded polarimetric covariance), used for forests.",
            "HV backscatter": "The radar echo sent horizontally and received vertically; it comes mostly from branches "
                              "and trunks, so it tracks forest biomass.",
            "Above-ground biomass": "The dry weight of trunks, branches and leaves, in tonnes per hectare (t/ha = Mg/ha).",
        }
        cols = st.columns(2, gap="large")
        for i, (k, v) in enumerate(terms.items()):
            cols[i % 2].markdown(f"**{k}**  \n{v}")


def page_help():
    from sarcompare.ui_style import how

    st.markdown('<div class="eyebrow-dark">Getting started in 1 minute</div>', unsafe_allow_html=True)
    st.markdown(how([
        ("Try a demo", "Open Ground Motion or Forests & Biomass, keep 'Try the demo' and press Run. No account "
                       "needed."),
        ("Pick a real place", "Choose 'Analyse a real place', pick an example or draw a box on the map, and paste "
                              "your free NASA Earthdata token."),
        ("Read the results", "Start with 'In short', then explore the map and the tabs; download the report to "
                             "keep it."),
    ]), unsafe_allow_html=True)
    faq = {
        "Why was no data found?": (
            "NISAR started producing data in late 2025, so choose dates after that. Ready-made Sentinel-1 "
            "interferograms exist for parts of the world: ARIA (mainly the USA), OPERA (North America) and "
            "LiCSAR from COMET (many earthquake and volcano regions, especially from the Mediterranean to the "
            "Himalaya). The app checks all of them automatically."),
        "Who owns the app, and can I use my results?": (
            "OpenSAR Explorer is © 2026 Deepa Kumari, all rights reserved: the code may not be copied, changed or "
            "redistributed without permission. You may use, publish and share the maps and reports you make, "
            "keeping the data credits and mentioning OpenSAR Explorer. The satellite and GNSS data belong to their "
            "providers. See the Terms of use, Privacy notice and Licence linked at the bottom of every page."),
        "Can I use EGMS in Europe?": (
            "Yes. EGMS (the EU's European Ground Motion Service) is an independent Sentinel-1 map of ground motion "
            "across Europe, calibrated with GNSS. Paste your free EGMS key under **Extra checks → EGMS maps for "
            "Europe** and the app downloads the right tiles itself (the key is used only for that run and never "
            "stored). Or download the Ortho tiles yourself and upload them."),
        "There is no Sentinel-1 data for my area. What happens?": (
            "The analysis continues with NISAR alone: the ground-motion map, the moving areas and the checks "
            "against GNSS and published studies all still work; only the second-satellite confirmation is "
            "missing. To add Sentinel-1, press **Find Sentinel-1 pairs to order** below the results: the app "
            "picks Sentinel-1 images on the same dates as the NISAR pairs and orders the interferograms from ASF's "
            "free HyP3 service with your Earthdata login (it uses free monthly processing credits; HyP3 jobs are "
            "publicly visible). Processing usually takes under an hour. Then run the same area again: the "
            "finished interferograms are found and used automatically. HyP3 keeps them for 14 days."),
        "Is my Earthdata token safe?": (
            "It is used only for your downloads in your own session and is never written to disk or shown to "
            "other visitors. You can delete a token any time in your Earthdata profile."),
        "How long does it take?": (
            "The demo takes under a minute. Real data depend on your area and internet speed: each NISAR file is "
            "hundreds of MB, so a first run can take 10–30 minutes. Re-runs reuse downloaded files."),
        "The two satellites disagree. Which is right?": (
            "Often both are partly right. They measure along different viewing directions and on slightly "
            "different dates, and each has its own noise (water vapour in the air, the ionosphere). Use the "
            "**Checks** tab: GNSS stations are an independent referee."),
        "How should I cite or credit the data?": (
            "Credit NASA/ISRO for NISAR and ESA's Copernicus programme for Sentinel-1, accessed via the Alaska "
            "Satellite Facility; GNSS from the Nevada Geodetic Laboratory. Check each provider's citation "
            "guidance."),
        "Can it predict disasters?": (
            "No. It shows **where** the ground is already moving and roughly **how fast**, which helps find areas "
            "that need closer study (a sinking neighbourhood, a creeping slope, ground around a mine). It cannot "
            "tell **whether or when** a landslide will fail, a building will be damaged, or an earthquake will "
            "happen. That needs continuous monitoring, ground instruments, field investigation and the responsible "
            "authorities. Think of it as hazard screening, not a forecast."),
        "How does radar measure forest biomass?": (
            "NISAR's L-band radar (24 cm waves) sees into the canopy; the cross-polarised (HV) echo comes mostly "
            "from branches and trunks and grows with the amount of wood. On **Forests & Biomass**, the app fits that "
            "relation for your area against the ESA CCI Biomass map, checks it on 30 % of the area kept aside, and "
            "converts every 100 m cell to tonnes per hectare."),
        "Why does the biomass map say 'at least' in dense forest?": (
            "Above about 100-150 t/ha the L-band echo barely changes with more wood (it 'saturates'), so a small "
            "change in the echo would mean a huge change in biomass. Those cells are shown as 'at least' the "
            "saturation level found for your area, and totals there are lower bounds."),
        "Is every 'new clearing' deforestation?": (
            "Not necessarily. A sudden, lasting drop of the radar echo usually means trees were removed (mining, "
            "felling, shifting cultivation), but fire, flooding or storm damage can do the same. The app labels "
            "zones as new (during the NISAR period), lost since 2021 but not yet in the global maps, or already "
            "mapped by Hansen et al. Confirm on recent optical images or in the field before acting."),
        "Which forest data does the Forests & Biomass module use?": (
            "NISAR L2 GCOV backscatter (NASA/ISRO, via ASF), ESA WorldCover 2021 for where forest was, Hansen et "
            "al. Global Forest Change v1.13 for mapped loss 2001-2025 (Source: Hansen/UMD/Google/USGS/NASA), and "
            "ESA CCI Biomass v7.0 for calibration. All are free; only NISAR needs your Earthdata token."),
        "Can I use this for decisions about safety?": (
            "No. This is a research and learning tool. Results should be verified by qualified experts using field "
            "observations before any decision."),
    }
    groups = {
        "🚀 Getting started & accounts": ["Why was no data found?", "Is my Earthdata token safe?",
                                          "How long does it take?", "Who owns the app, and can I use my results?",
                                          "How should I cite or credit the data?"],
        "🛰️ Ground Motion": ["There is no Sentinel-1 data for my area. What happens?", "Can I use EGMS in Europe?",
                             "The two satellites disagree. Which is right?"],
        "🌳 Forests & Biomass": ["How does radar measure forest biomass?",
                                "Why does the biomass map say 'at least' in dense forest?",
                                "Is every 'new clearing' deforestation?",
                                "Which forest data does the Forests & Biomass module use?"],
        "⚖️ Using results responsibly": ["Can it predict disasters?", "Can I use this for decisions about safety?"],
    }
    placed = {q for qs in groups.values() for q in qs}
    groups["🚀 Getting started & accounts"] += [q for q in faq if q not in placed]
    st.markdown('<div class="eyebrow-dark">Frequently asked questions</div>', unsafe_allow_html=True)
    cols = st.columns(2, gap="large")
    for i, (group, questions) in enumerate(groups.items()):
        with cols[i % 2], st.container(border=True, key=f"card_faq_{i}"):
            st.markdown(f"#### {group}")
            for q in questions:
                if q in faq:
                    with st.expander(q):
                        st.markdown(faq[q])


PAGES: dict = {}  # page title -> st.Page, filled by main() so pages can link to each other


def main():
    from sarcompare.gui_forest import page_forest
    from sarcompare.gui_home import page_home

    st.set_page_config(page_title="OpenSAR Explorer", page_icon="🛰️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    pages = [st.Page(page_home, title="Home", icon=":material/home:", default=True),
             st.Page(page_explore, title="Ground Motion", icon=":material/terrain:"),
             st.Page(page_forest, title="Forests & Biomass", icon=":material/forest:"),
             st.Page(page_learn, title="Learn", icon=":material/school:"),
             st.Page(page_help, title="Help & FAQ", icon=":material/help:")]
    PAGES.clear()
    PAGES.update({pg.title: pg for pg in pages})
    nav = st.navigation(pages, position="top")
    header(nav.title)
    nav.run()
    footer()


if __name__ == "__main__":
    main()

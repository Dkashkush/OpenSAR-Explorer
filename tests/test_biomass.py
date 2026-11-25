# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Forests & Biomass module: GCOV search/reader, reference data, biomass calibration, forest loss, end to end."""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from sarcompare.aoi import AOI
from sarcompare.biomass import analysis as A
from sarcompare.biomass import gcov as G
from sarcompare.biomass import reference as R
from sarcompare.biomass.demo import (CHANGE_INDEX, DEMO_BBOX, DEMO_DATES, ForestScene, forest_demo_config, gcov_name,
                                     write_gcov)
from sarcompare.products import NISAR, Product

REAL = "NISAR_L2_PR_GCOV_035_149_D_077_4005_DHDH_A_20261115T130813_20261115T130847_P05036_N_F_J_001"


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    from sarcompare.biomass.pipeline import ForestPipeline

    root = tmp_path_factory.mktemp("forest")
    cfg = forest_demo_config(root / "data", str(root / "out"))
    events = []
    return ForestPipeline(cfg, on_event=events.append).run(), events


def test_gcov_name_parsing():
    info = G.parse_gcov_name(REAL)
    assert info["date"] == date(2026, 11, 15) and info["track"] == 149 and info["frame"] == 77
    assert info["direction"] == "DESCENDING" and info["config"] == "PR" and info["crid"] == "P05036"
    assert G.parse_gcov_name("S1-GUNW-A-R-064-tops-20210723_20210711") == {}


def _p(d, track=149, frame=77, config="PR", crid="P05036", direction="DESCENDING"):
    return Product(NISAR, "GCOV", f"x{d}{config}", date1=d, date2=d, flight_direction=direction, track=track,
                   frame=frame, extra={"config": config, "crid": crid})


def test_dedupe_choose_and_thin():
    d0 = date(2026, 7, 1)
    ur = _p(d0, config="UR", crid="P05023")
    pr = _p(d0)
    kept = G.dedupe([ur, pr])
    assert kept == [pr]  # the standard product wins over the urgent-response copy
    many = [_p(d0 + timedelta(days=12 * k)) for k in range(10)] + [_p(d0, track=127, frame=13,
                                                                      direction="ASCENDING")]
    chosen, notes = G.choose_geometry(many)
    assert {p.track for p in chosen} == {149} and "track 127" in notes[0].text
    thin = G.thin_dates(chosen, 4)
    assert len(thin) == 4 and thin[0].date1 == chosen[0].date1 and thin[-1].date1 == chosen[-1].date1


def test_block_average_aligns_to_multiples():
    x = np.arange(0, 400, 10) + 5.0  # pixel centres, 10 m
    y = np.arange(300, 0, -10) - 5.0
    arr = np.ones((y.size, x.size), "float32")
    arr[:10, :10] = 3.0  # exactly the top-left 100 m cell
    arr[15, 15] = np.nan
    out, cx, cy = G.block_average(arr, x, y, 100.0)
    assert out.shape == (3, 4) and cx[0] == 50 and cy[0] == 250
    assert out[0, 0] == pytest.approx(3.0) and np.nanmax(out[1:, 1:]) == pytest.approx(1.0)


def test_read_gcov_real_layout(tmp_path):
    aoi = AOI.from_bbox(*DEMO_BBOX)
    scene = ForestScene.for_bbox()
    path = tmp_path / gcov_name(DEMO_DATES[0], 0)
    write_gcov(path, scene, DEMO_DATES[0], 0)
    b = G.read_gcov(path, aoi, 100.0)
    assert b.date == DEMO_DATES[0] and b.track == 149 and b.direction == "DESCENDING" and b.frame == 77
    assert str(b.hv.rio.crs) == "EPSG:32644" and float(b.hv.x[1] - b.hv.x[0]) == 100.0
    hv_db = 10 * np.log10(np.nanmedian(b.hv.values))
    assert -12.5 < hv_db < -9.5  # mostly forest
    assert b.hh is not None and np.nanmedian(b.hh.values) > np.nanmedian(b.hv.values)
    with path.open("rb") as f:  # read from a file object, as when reading remotely
        b2 = G.read_gcov(f, aoi, 100.0, name=path.name)
    np.testing.assert_allclose(b2.hv.values, b.hv.values, equal_nan=True)


def test_reference_tile_names_and_urls():
    hasdeo = (82.55, 22.70, 82.85, 22.95)
    assert R.hansen_tiles(hasdeo) == ["30N_080E"] and R.cci_tiles(hasdeo) == ["N30E080"]
    assert R.worldcover_tiles(hasdeo) == ["N21E081"]
    assert R.hansen_tiles((93.70, 6.75, 93.95, 7.10)) == ["10N_090E"]
    assert R.cci_tiles((-60.5, -3.2, -60.1, -2.9)) == ["N00W070"]
    assert R.worldcover_tiles((-60.5, -3.2, -60.1, -2.9)) == ["S06W063", "S03W063"]
    assert R.cci_urls(hasdeo, 2024)[0].endswith(
        "v7.0/geotiff/2024/N30E080_ESACCI-BIOMASS-L4-AGB-MERGED-100m-2024-fv7.0.tif")
    assert R.cci_urls(hasdeo, 2024, sd=True)[0].endswith("N30E080_ESACCI-BIOMASS-L4-AGB_SD-MERGED-100m-2024-fv7.0.tif")
    assert R.hansen_urls(hasdeo, "lossyear")[0].endswith("GFC-2025-v1.13/Hansen_GFC-2025-v1.13_lossyear_30N_080E.tif")


def test_fit_agb_recovers_the_model_and_flags_saturation():
    rng = np.random.default_rng(1)
    a, b, c = 0.09, 55.0, 0.008
    agb = rng.uniform(0, 300, (120, 120))
    hv = (a * (1 - np.exp(-agb / b)) + c) * rng.gamma(200, 1 / 200, agb.shape)
    test = A.spatial_blocks(agb.shape, 20)
    ref = agb * rng.lognormal(0, 0.15, agb.shape)
    model, notes = A.fit_agb(A.to_db(hv), ref, np.ones(agb.shape, bool), test, "test map")
    assert model is not None and abs(model.b - b) / b < 0.25
    assert model.sat_agb == pytest.approx(b * np.log(10), rel=0.25) and model.saturates_in_range
    est, sat = model.invert(np.array([c, a * (1 - np.exp(-50 / b)) + c, a + c]))
    assert est[0] == pytest.approx(0, abs=3) and est[1] == pytest.approx(50, rel=0.25)
    assert sat.tolist() == [False, False, True] and est[2] == pytest.approx(model.sat_agb)
    assert model.test_below_sat["r"] > 0.8 and any("held-out" in n.text for n in notes)


def test_detect_drops_ignores_a_common_shift():
    t, shape = 6, (30, 30)
    cube = np.full((t,) + shape, -10.0) + np.random.default_rng(2).normal(0, 0.2, (t,) + shape)
    cube[3:, 5:10, 5:10] = -19.0  # cleared after the third image
    cube[2] += 1.5  # a wet date: everything brighter
    cube, offsets = A.normalise_dates(cube, np.ones(shape, bool))
    d = A.detect_drops(cube, np.ones(shape, bool), threshold_db=-14.5, drop_db=3.0)
    assert d["detected"].sum() == 25 and set(np.unique(d["k"][d["detected"]])) == {3}
    assert d["confirmed"][5:10, 5:10].all() and offsets[2] > 1.0


def test_forest_demo_end_to_end(demo_run):
    r, events = demo_run
    kinds = {k: [z for z in r.zones if z.kind == k] for k in A.KINDS}
    (new,) = kinds["new"]
    assert 60 <= new.area_ha <= 100 and new.change_start == DEMO_DATES[CHANGE_INDEX - 1]
    assert new.change_end == DEMO_DATES[CHANGE_INDEX] and new.confirmed and new.biomass_lost_t > 0
    (unm,) = kinds["unmapped"]
    assert 30 <= unm.area_ha <= 60 and unm.hansen_share == 0
    (han,) = kinds["hansen"]
    assert 250 <= han.area_ha <= 340 and han.open_share > 0.8 and "2023-2024" in han.when
    m = r.model
    assert m is not None and 100 < m.sat_agb < 170 and m.test_below_sat["r"] > 0.8
    assert r.separation.balanced_accuracy > 0.9
    assert {"search", "load", "reference", "change", "biomass", "report"} <= {e.stage for e in events}
    out = r.outputs
    for key in ("biomass_mg_per_ha", "forest_loss_zones", "zones_csv", "zones_geojson", "metrics", "report"):
        assert Path(out[key]).is_file(), key
    rep = Path(out["report"]).read_text()
    assert "Synthetic demo data" in rep and "Forests &amp; Biomass" in rep and "Deepa Kumari" in rep
    gj = json.loads(Path(out["zones_geojson"]).read_text())
    assert len(gj["features"]) == 3 and all(f["geometry"]["type"] in ("Polygon", "MultiPolygon")
                                            for f in gj["features"])
    import rasterio

    with rasterio.open(out["biomass_mg_per_ha"]) as src:
        assert "OpenSAR Explorer" in src.tags().get("SOFTWARE", "")


def test_plain_summary_and_map(demo_run):
    from sarcompare.biomass.report import plain_summary
    from sarcompare.biomass.webmap import forest_map

    r, _ = demo_run
    text = " ".join(t for _, t in plain_summary(r))
    assert "synthetic demo" in text and "New clearing" in text and "not in the global loss maps" in text
    html = forest_map(r).get_root().render()
    assert "New clearing during the NISAR period" in html and "Biomass (Mg/ha)" in html


def test_token_is_never_written(tmp_path):
    from sarcompare.biomass.pipeline import ForestConfig

    cfg = ForestConfig(aoi=list(DEMO_BBOX), earthdata_token="secret-token-123")
    assert "earthdata_token" not in cfg.to_dict() and "secret-token-123" not in repr(cfg)


def test_no_images_gives_a_plain_message(tmp_path):
    from sarcompare.biomass.pipeline import ForestConfig, ForestPipeline, NoGCOVError

    (tmp_path / "empty").mkdir()
    cfg = ForestConfig(aoi=list(DEMO_BBOX), gcov_source="LOCAL", gcov_dir=str(tmp_path / "empty"))
    with pytest.raises(NoGCOVError, match="June 2026"):
        ForestPipeline(cfg).search()
    from sarcompare.gui import friendly_error

    assert friendly_error(NoGCOVError("No NISAR GCOV images")).startswith("No NISAR GCOV images")


def test_local_reference_files_never_fall_back_to_the_web(demo_run, monkeypatch, tmp_path):
    """With local files given, missing ones are skipped instead of fetched (no surprise downloads)."""
    from dataclasses import replace

    from sarcompare.biomass.pipeline import ForestPipeline

    r, _ = demo_run
    files = {k: v for k, v in r.config.reference_files.items() if k not in ("worldcover", "agb_baseline")}

    def no_web(*a, **k):
        raise AssertionError("web archive used")

    monkeypatch.setattr(R, "worldcover_urls", no_web)
    monkeypatch.setattr(R, "cci_urls", no_web)
    cfg = replace(r.config, reference_files=files, output_dir=str(tmp_path))
    p = ForestPipeline(cfg)
    p.search()
    p.load()
    p.reference()
    assert "worldcover" not in p.result.ref and "cci_baseline" not in p.result.ref and "hansen" in p.result.ref
    p.forest_change()  # Hansen tree cover stands in for the forest mask
    assert p.result.forest.any() and p.result.separation is not None


def _forest_results_page(data_dir, out_dir):
    from sarcompare.biomass.demo import forest_demo_config
    from sarcompare.biomass.pipeline import ForestPipeline
    from sarcompare.gui_forest import show_forest_results

    show_forest_results(ForestPipeline(forest_demo_config(data_dir, out_dir)).run())


def test_forest_results_page(tmp_path):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_forest_results_page, default_timeout=300,
                               args=(str(tmp_path / "data"), str(tmp_path / "out")))
    at.run()
    assert not at.exception, at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels["New clearing"].endswith("ha") and labels["Radar saturates at"].endswith("t/ha")
    text = " ".join(md.value for md in at.markdown)
    assert "New clearing" in text


def test_app_has_the_forest_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    html = " ".join(md.value for md in at.markdown)
    assert "Ground Motion module" in html


def test_noisy_reference_does_not_fake_an_early_saturation():
    """Real case (Hasdeo Arand, Nov 2026): ESA CCI reads near zero in a third of the forest. Fitting against
    biomass-binned medians alone then saturated at 12 Mg/ha; the bisector-style fit must stay realistic."""
    rng = np.random.default_rng(3)
    a, b, c = 0.06, 60.0, 0.02
    agb = rng.uniform(0, 140, (200, 200))
    hv = (a * (1 - np.exp(-agb / b)) + c) * rng.gamma(80, 1 / 80, agb.shape)
    ref = agb * rng.lognormal(0, 0.6, agb.shape)
    low = rng.random(agb.shape) < 0.35
    ref[low] = agb[low] * 0.08
    model, _ = A.fit_agb(A.to_db(hv), ref, np.ones(agb.shape, bool), A.spatial_blocks(agb.shape, 20), "noisy")
    assert model is not None and model.sat_agb > 50
    pred, _ = model.invert(hv)
    assert np.corrcoef(pred.ravel(), agb.ravel())[0, 1] > 0.8  # close to the truth, despite the reference


def test_degenerate_fit_is_rejected():
    rng = np.random.default_rng(4)
    hv_db = rng.normal(-12, 1, (100, 100))
    ref = rng.uniform(0, 150, (100, 100))  # no relation at all
    model, notes = A.fit_agb(hv_db, ref, np.ones(hv_db.shape, bool), A.spatial_blocks(hv_db.shape, 20), "x")
    assert model is None and notes[0].level == "warn"

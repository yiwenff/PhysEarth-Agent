"""A model's answer where its theory does not hold is refused, not reported; sweeps can be log-spaced."""

import math

import pytest

from physearth import session, tools
from physearth.harness import validation
from physearth.registry import loader

SMRT = loader.get("smrt")
pytestmark = pytest.mark.skipif(not (SMRT and SMRT.runnable), reason="smrt is not runnable here")

QCA = dict(
    electromagnetic_model="dmrt_qca_shortrange", microstructure_model="sticky_hard_spheres",
    output="tb", frequency_ghz=37.0, angle_deg=55.0, thickness_m=100.0,
    density_kg_m3=300.0, temperature_k=265.0, stickiness=0.5,
)


def _run(**parameters):
    """The adapter as run_model calls it: after validation has filled the defaults."""
    spec, problems = validation.resolve(SMRT.card, parameters)
    assert not problems, problems
    return SMRT.run(spec)


def _call(name, arguments, box):
    return tools.call(name, arguments, session=box, owner=box["id"])


def test_short_range_dmrt_is_refused_where_its_absorption_goes_negative():
    # SMRT v1.0 failed here; 1.5.1 with the solver fallbacks returned 264.7 K, which
    # passed range QC. The coefficients show the medium is unphysical before any solve.
    result = _run(**dict(QCA, radius_m=5.85e-4))
    assert math.isnan(result["series"]["tb_v"][0])
    assert "negative absorption" in result["diagnostics"]["invalid_points"][0]["reason"]
    qc = validation.quality_control(SMRT.card, result)
    assert not qc["passed"]
    assert any(c["check"] == "physical_medium" and not c["passed"] for c in qc["checks"])


def test_a_physical_point_is_untouched():
    result = _run(**dict(QCA, radius_m=1e-4))
    assert result["diagnostics"]["invalid_points"] == []
    assert 250 < result["series"]["tb_v"][0] < 270
    assert validation.quality_control(SMRT.card, result)["passed"]


def test_a_sweep_stops_where_the_model_does_and_the_chart_says_so():
    box = session.new_session("m")
    run = _call("run_model", {"model": "smrt", "parameters": dict(
        QCA, sweep_parameter="radius_m", sweep_start=1e-5, sweep_stop=5.85e-4, sweep_points=24)}, box)
    assert run["status"] == "success" and not run["qc"]["passed"]
    assert "refused as unphysical" in run["summary"]
    assert math.isfinite(run["data"]["series_summary"]["tb_v"]["max"])
    chart = _call("plot", {"series": [{"handle": run["data"]["handle"], "x": "radius_m", "y": "tb_v",
                                       "label": "QCA"}], "kind": "line", "title": "QCA"}, box)
    assert chart["status"] == "success"
    assert "3 point(s) left out of QCA" in chart["summary"]
    assert chart["data"]["series"][0]["omitted_points"] == 3


def test_a_log_sweep_is_evenly_spaced_in_the_logarithm():
    result = _run(**dict(QCA, electromagnetic_model="iba", radius_m=2e-4, sweep_parameter="stickiness",
                           sweep_start=0.1, sweep_stop=50.0, sweep_points=6, sweep_scale="log"))
    values = result["axis"]["values"]
    ratios = [b / a for a, b in zip(values, values[1:])]
    assert values[0] == pytest.approx(0.1) and values[-1] == pytest.approx(50.0)
    assert max(ratios) == pytest.approx(min(ratios), rel=1e-6)


def test_a_log_sweep_through_zero_is_refused_before_it_runs():
    problems = validation._check_sweep(SMRT.card, dict(
        QCA, sweep_parameter="angle_deg", sweep_start=0.0, sweep_stop=60.0, sweep_scale="log"))
    assert any("sweep_scale = log" in p for p in problems)

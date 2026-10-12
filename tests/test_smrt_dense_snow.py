"""The dense-snow ice/air switch is reachable from the SMRT card, and only where SMRT supports it."""

import pytest

from physearth.harness import validation
from physearth.registry import loader

SMRT = loader.get("smrt")
pytestmark = pytest.mark.skipif(not (SMRT and SMRT.runnable), reason="smrt is not runnable here")

BASE = dict(
    electromagnetic_model="iba", microstructure_model="exponential", output="tb",
    frequency_ghz=18.7, angle_deg=55.0, thickness_m=200.0, temperature_k=265.0,
    corr_length_m=0.00025, sweep_parameter="density_kg_m3", sweep_start=440.0,
    sweep_stop=480.0, sweep_points=5,
)


def _run(**parameters):
    spec, problems = validation.resolve(SMRT.card, dict(BASE, **parameters))
    assert not problems, problems
    return SMRT.run(spec)["series"]["tb_v"]


def test_without_the_switch_brightness_temperature_is_smooth_across_458():
    tb = _run()
    assert all(0 < b - a < 6 for a, b in zip(tb, tb[1:]))


def test_the_switch_makes_brightness_temperature_jump_past_half_the_ice_density():
    plain, switched = _run(), _run(dense_snow_correction="auto")
    assert switched[:2] == pytest.approx(plain[:2])  # 440 and 450: below the switch
    assert plain[2] - switched[2] > 20  # 460: 40 K in the reference run


def test_the_switch_is_refused_for_theories_that_do_not_implement_it():
    for model, micro in (("iba_original", "exponential"), ("rayleigh", "independent_sphere")):
        _, problems = validation.resolve(
            SMRT.card, dict(BASE, electromagnetic_model=model, microstructure_model=micro,
                            dense_snow_correction="auto"))
        assert problems, model


def test_the_thickness_guidance_no_longer_promises_saturation_in_a_few_metres():
    text = SMRT.card["parameters"]["thickness_m"]["description"]
    assert "few metres" not in text and "semi-infinite" in text

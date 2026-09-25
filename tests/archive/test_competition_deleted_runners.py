"""Archived with the dashboard, registration-demo, smoke and registry-contract runners."""

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EVAL = ROOT / "evaluation"

sys.path.insert(0, str(EVAL / "runners"))
sys.path.insert(0, str(EVAL))



def _load_runner(name):
    path = EVAL / "runners" / (name + ".py")
    spec = importlib.util.spec_from_file_location(f"evaluation_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_dashboard_is_self_contained():
    dashboard = _load_runner("dashboard")
    page = dashboard.build_html([], registry={}, demo={})
    assert 'id="registration"' in page
    assert 'id="paper"' in page
    assert "SMRT" in page
    assert "OpenRouter" not in page
    assert "ModelScope" not in page
    assert "provider" not in page.lower()
    assert "smoke" not in page.lower()
    assert "usage ledger" not in page.lower()
    assert "tier 0" not in page.lower()
    assert "tier 1" not in page.lower()
    assert "tier 2" not in page.lower()
    assert "__REGISTERED__" not in page
    assert "__MODEL_ROWS__" not in page
    assert "__PAPER_ROWS__" not in page


def test_registration_demo_result_is_explicit_about_default_runs():
    payload = json.loads(
        (EVAL / "results" / "registration_demo.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == "registration-demo-v1"
    assert payload["execution"] == "deterministic"
    assert payload["n_models"] == 6
    assert {record["model"] for record in payload["records"]} == {
        "prosail",
        "pyet",
        "pywatershed",
        "smrt",
        "tau_omega",
        "water_cloud",
    }
    assert payload["n_passed"] == sum(record["passed"] for record in payload["records"])
    assert all("version" in record for record in payload["records"])


def test_dashboard_matrix_plan_separates_ranked_and_provider_diversity_cells():
    dashboard = _load_runner("dashboard")
    plan = dashboard.build_matrix_plan()
    assert len(plan["tasks"]) == 5
    assert len(plan["profiles"]) == 3
    assert len(plan["scenarios"]) == 15
    assert plan["main_cells"] == 120
    assert plan["diversity_cells"] == 15
    assert plan["total_cells"] == 135
    main = [model for model in plan["models"] if model["track"] == "main"]
    diversity = [
        model for model in plan["models"] if model["track"] == "provider_diversity"
    ]
    assert len(main) == 4
    assert all(model["provider"] == "openrouter" and model["ranked"] for model in main)
    assert diversity == [
        {
            "id": "Shanghai_AI_Laboratory/Intern-S2-Preview",
            "label": "Intern-S2 Preview",
            "provider": "modelscope",
            "track": "provider_diversity",
            "track_label": "ModelScope diversity",
            "repeats": 1,
            "ranked": False,
        }
    ]


def test_usage_ledger_includes_failures_and_leaves_unrun_models_na():
    dashboard = _load_runner("dashboard")
    readiness = {
        "providers": [
            {
                "provider": "openrouter",
                "models": [
                    {"id": "model-a", "available": True},
                    {"id": "model-b", "available": True},
                ],
            }
        ],
        "smoke": {
            "provider": "openrouter",
            "requested_model": "model-a",
            "llm_usage": {"total_tokens": 10, "cost_usd": 0.001},
        },
    }
    scored = [
        {
            "raw": {
                "provider": "openrouter",
                "llm": "model-a",
                "llm_usage": {"total_tokens": 20, "cost_usd": 0.002},
            }
        }
    ]
    failures = [
        {
            "provider": "openrouter",
            "llm": "model-a",
            "llm_usage": {"total_tokens": 30, "cost_usd": 0.003},
        }
    ]
    ledger = dashboard.build_usage_ledger(scored, readiness, failures)
    model_a = next(item for item in ledger if item["model"] == "model-a")
    model_b = next(item for item in ledger if item["model"] == "model-b")
    assert model_a["total_tokens"] == 60
    assert model_a["cost_usd"] == 0.006
    assert model_a["scored_cells"] == 1
    assert model_a["failed_attempts"] == 1
    assert model_a["smoke_attempts"] == 1
    assert model_b["total_tokens"] is None
    assert model_b["cost_usd"] is None


def test_llm_smoke_manifest_has_no_cross_provider_duplicates():
    smoke = _load_runner("llm_smoke")
    manifest = smoke.common.load_yaml(smoke.MANIFEST)
    specs = smoke._provider_specs(manifest)
    openrouter = set(next(x for x in specs if x["provider"] == "openrouter")["models"])
    modelscope = set(next(x for x in specs if x["provider"] == "modelscope")["models"])
    assert len(openrouter) == 4
    assert modelscope == {"Shanghai_AI_Laboratory/Intern-S2-Preview"}
    assert openrouter.isdisjoint(modelscope)


def test_registry_contract_covers_every_discovered_model():
    runner = _load_runner("registry_contract")
    from physearth import registry

    records = [runner.inspect_model(model) for model in registry.all_models().values()]
    assert records
    assert all(record["passed"] for record in records)
    for record in records:
        coverage = record["coverage"]
        checks = record["checks"]
        assert sum(check["check"] == "range_guard" for check in checks) == (
            2 * coverage["numeric_parameters"]
        )
        assert sum(check["check"] == "enum_guard" for check in checks) == (
            coverage["enum_parameters"]
        )
        assert sum(check["check"] == "combination_guard" for check in checks) == (
            coverage["combination_rules"]
        )
        assert sum(check["check"].startswith("sweep_") for check in checks) == (
            4 if coverage["sweep_contract"] else 0
        )

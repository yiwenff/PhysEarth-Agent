import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVALUATION = ROOT / "evaluation"
sys.path.insert(0, str(EVALUATION / "runners"))


def _runner(name):
    path = EVALUATION / "runners" / (name + ".py")
    spec = importlib.util.spec_from_file_location("tier0_%s" % name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_tier0_task_declares_tier_kind_and_executable_checks():
    tasks = []
    for path in sorted((EVALUATION / "tasks" / "tier0").glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks.append(task)
        assert task["tier"] == 0
        assert task["suite"] == "tier0"
        assert task["kind"]
        assert task["checks"]
        assert "quality_control" in task["kind"]
        assert task["checks"][-1] == "quality_control"
    assert len(tasks) == 9


def test_scientific_question_demos_are_tier2_paper_figure_targets():
    paths = sorted((EVALUATION / "tasks" / "tier2").glob("*.yaml"))
    manifest = yaml.safe_load((EVALUATION / "competition.yaml").read_text(encoding="utf-8"))
    core = manifest["competition_required"]["t2_paper_reconstruction"]["core_tasks"]
    assert paths
    for path in paths:
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert task["tier"] == 2
        assert task["suite"] == "tier2"
        assert task["legacy_id"] != task["id"]
        assert task["id"].startswith("q")
        assert task["evaluation_kind"] == "scientific_question_demo"
        assert task["figure_target"].startswith("fig")
        assert task["paper_figures"]
        assert "Reproduce Figure" in task["question"] or "Reproduce Figures" in task["question"]
        assert "10.5194/gmd-11-2763-2018" in task["question"]
        assert "inspect" in task["question"].lower()
        assert task["source"]["document"] == "docs/smrt_section3_scientific_questions_and_steps.md"
        assert task["demo"]["pilot"]
        assert task["demo"]["expected_outputs"]
        assert task["demo"]["required_behaviors"]
    # The legacy Tier 1 paper-fixture files remain available for the b02b evaluation
    # dashboard and replay tests. The invariant here is about the current Tier 2 demos,
    # not about deleting those historical fixtures.
    # Every scientific question in the default matrix has a task file, and every task file
    # is in the matrix: a question cannot be dropped from one without the other.
    ids = [yaml.safe_load(path.read_text(encoding="utf-8"))["id"] for path in paths]
    assert sorted(ids) == sorted(core)

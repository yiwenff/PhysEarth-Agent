"""The Studio and the MCP plugin show one plan and one report.

A person reviewing a plan, or reading a report, must not see a different value, a different source
word or a different page depending on where they look. These tests pin that: both surfaces render
from `research.sheet` and `physearth.documents`, and they use one source vocabulary.

The plan is a recorded run, committed with the evaluation results, so the check is made on a
realistic plan and not a hand-built one.
"""

import base64
import json
from pathlib import Path

import pytest

from integrations.physearth import service
from physearth import documents, research

ROOT = Path(__file__).resolve().parent.parent
RECORD = (
    ROOT / "evaluation" / "results" / "competition" / "batch-2026-10-06"
    / "q1-sparse-medium__p1-reproduction-first__full__openai-gpt-5.6-luna__r1.json"
)
pytestmark = pytest.mark.skipif(not RECORD.is_file(), reason="the recorded Q1 run is not present")

# A 1x1 PNG, enough to prove a figure is embedded in the page.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
NARRATIVE = (
    "## Research result and conclusion\n\nThe six curves converge at low density. [smrt-v1#08]\n\n"
    "## Limitations\n\nThe model is a homogeneous layer.\n"
)


@pytest.fixture()
def project():
    return json.loads(RECORD.read_text())["research"]


@pytest.fixture()
def session_id(monkeypatch, project, tmp_path):
    image = tmp_path / "figure.png"
    image.write_bytes(PNG)
    sid = "ses_alignment"
    monkeypatch.setitem(
        service._SESSIONS, sid,
        {
            "id": sid,
            "research": project,
            "figures": [{"title": "Figure 1. Generated comparison", "artifact_image_path": str(image)}],
        },
    )
    return sid


# ── one source vocabulary ───────────────────────────────────────────────────────────────────
def test_the_plugin_edits_in_the_studios_source_words():
    studio = set(research.sheet.TAGS.values())
    assert studio <= set(research.SOURCE_OPTIONS)
    assert set(research.SOURCE_OPTIONS) == studio | {"guessed"}


def test_every_value_has_the_same_source_in_the_plan_sheet_and_the_plugin_document(project):
    plan = project["plan"]
    sheet = research.sheet.build(plan)
    studio = {}
    for group in sheet["groups"]:
        for item in group["conditions"] + group["columns"]:
            studio[(group["model"], item["name"])] = item["tag"]
    from physearth.research import editable

    plugin = {(row["model"], row["model_input"]): row["source"] for row in editable.parameter_rows(project)}
    compared = {key: (tag, plugin[key]) for key, tag in studio.items() if key in plugin}
    assert compared, "no parameter appears on both surfaces"
    disagree = {key: pair for key, pair in compared.items() if pair[0] != pair[1]}
    assert not disagree, "the Studio and the plugin label these differently: %s" % disagree


def test_a_shared_condition_shows_the_same_value_on_both_surfaces(project):
    from physearth.research import editable

    sheet = research.sheet.build(project["plan"])
    plugin = {(r["model"], r["model_input"]): r["value"] for r in editable.parameter_rows(project)}
    for group in sheet["groups"]:
        for item in group["conditions"]:
            key = (group["model"], item["name"])
            if key in plugin:
                assert plugin[key] == research.sheet.fmt(item["value"]), key


def test_a_finished_plan_never_asks_for_approval(project):
    from physearth.research import editable

    done = editable.markdown({**project, "phase": "completed"})
    assert "| Phase | 🟢 `completed` — approved |" in done
    waiting = editable.markdown({**project, "phase": "plan_review"})
    assert "🟠 `plan_review` — approval required" in waiting


def test_editing_a_source_round_trips_in_the_shared_words(project):
    from physearth.research import editable

    document = editable.markdown(project, session_id="ses_x")
    assert editable.changes(project, document) == {}  # nothing edited, nothing to apply

    row = next(r for r in editable.parameter_rows(project) if r["model_input"] == "temperature_k")
    lines = []
    for line in document.split("\n"):
        if line.startswith("| %s |" % row["row_id"]):
            cells = line.split("|")
            cells[5] = " user "  # the Source column
            line = "|".join(cells)
        lines.append(line)
    patch = editable.changes(project, "\n".join(lines))
    assert patch["parameter_mapping"][0]["provenance_class"] == "user_specified"

    bad = "\n".join(
        "|".join(line.split("|")[:5] + [" paper "] + line.split("|")[6:])
        if line.startswith("| %s |" % row["row_id"]) else line
        for line in document.split("\n")
    )
    with pytest.raises(ValueError, match="extracted"):
        editable.changes(project, bad)


# ── one plan page ───────────────────────────────────────────────────────────────────────────
def test_the_plugin_returns_the_page_the_studio_opens(session_id):
    exported = service.plan_export(session_id, "html")
    assert exported["status"] == "success" and exported["mime_type"] == "text/html"
    assert exported["content"] == documents.plan_document(service._SESSIONS[session_id])
    page = exported["content"]
    assert "What will be run" in page and "plan-sheet" in page
    # The decisions panel names what needs a person's attention, with the Studio's own words.
    assert "Needs your decision" in page and "src--assumed" in page


def test_the_plan_page_lists_every_source_the_plugin_document_lists(session_id, project):
    from physearth.research import editable

    page = service.plan_export(session_id, "html")["content"]
    for tag in {row["source"] for row in editable.parameter_rows(project)} - {"mixed"}:
        assert "src--%s" % tag in page, tag


# ── one report page ─────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def rendered(monkeypatch, session_id):
    monkeypatch.setattr(service, "verify_report", lambda *a, **k: {"passed": True, "checks": []})
    return service.render_report(session_id, NARRATIVE)


def test_the_plugin_report_is_the_studios_report_page(session_id, rendered):
    assert rendered["status"] == "success"
    page = rendered["data"]["html"]
    # Tables and source chips, not a preformatted block.
    assert "<pre>" not in page.split("<h2>Full report</h2>")[1].split("<h2>What was run</h2>")[0]
    assert "plan-sheet" in page and "The six curves converge at low density." in page
    assert "<span class='cite'>" in page or "class='cite" in page


def test_the_plugin_report_carries_the_figure_the_session_drew(rendered):
    page = rendered["data"]["html"]
    assert "<figure>" in page and "data:image/png;base64," in page
    assert "Figure 1. Generated comparison" in page


def test_the_plugin_report_shows_the_checks_it_passed(rendered):
    page = rendered["data"]["html"]
    assert "Checks passed" in page and "Report verification" in page and "passed (hard)" in page


def test_the_report_markdown_has_real_line_breaks(rendered):
    # A literal backslash-n in the template once made the whole document a single line.
    markdown = rendered["data"]["markdown"]
    assert "\\n" not in markdown
    assert "\n## Gate status\n" in markdown and "\n## Report\n" in markdown
    assert "<details><summary>Plan JSON</summary>" in markdown


def test_a_report_is_refused_before_the_plan_is_approved(monkeypatch, session_id):
    service._SESSIONS[session_id]["research"] = {**service._SESSIONS[session_id]["research"], "phase": "plan_review"}
    refused = service.render_report(session_id, NARRATIVE)
    assert refused["status"] == "needs_input" and refused["error"] == "research_plan_not_approved"


def test_the_studios_own_pages_do_not_gain_a_checks_card(project):
    session = {"id": "s", "research": project, "figures": []}
    assert "Checks passed" not in documents.report_document(session, NARRATIVE)

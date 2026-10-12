"""One agent reads the research plan before a person does."""

import json
from pathlib import Path

import pytest
from test_approval import _Chunk, _Delta, _fake_client

from physearth import session
from physearth.agent import completion, loop, plan_review

ROOT = Path(__file__).resolve().parent.parent
RECORD = (
    ROOT / "evaluation" / "results" / "competition" / "batch-2026-10-06"
    / "q1-sparse-medium__p1-reproduction-first__full__openai-gpt-5.6-luna__r1.json"
)


def test_a_clean_review_and_one_that_asks_for_changes_are_both_read():
    ok = plan_review.parse('{"verdict": "ok", "issues": []}')
    assert ok == {"verdict": "ok", "issues": []}
    revise = plan_review.parse(
        'Here you go: {"verdict": "revise", "issues": [{"kind": "extra", '
        '"what": "chart c2 is a zoom the paper does not show", "fix": "drop c2"}]}'
    )
    assert revise["verdict"] == "revise"
    assert revise["issues"] == [
        {"kind": "extra", "what": "chart c2 is a zoom the paper does not show", "fix": "drop c2"}
    ]


def test_a_reply_that_is_not_a_review_is_ignored():
    for text in ("", "looks fine", '{"verdict": "maybe"}', "{not json}"):
        assert plan_review.parse(text) is None, text


def test_revise_without_an_issue_is_not_a_request_for_changes():
    assert plan_review.parse('{"verdict": "revise", "issues": []}')["verdict"] == "ok"


def test_at_most_four_issues_with_a_known_kind():
    issues = [{"kind": "extra", "what": "x%d" % n, "fix": "y"} for n in range(9)]
    issues.append({"kind": "weird", "what": "odd", "fix": ""})
    found = plan_review.parse(json.dumps({"verdict": "revise", "issues": issues}))
    assert len(found["issues"]) == 4
    odd = plan_review.parse(json.dumps({"verdict": "revise", "issues": [{"kind": "weird", "what": "w"}]}))
    assert odd["issues"][0]["kind"] == "question"


def test_the_feedback_tells_the_agent_what_to_do_with_it():
    text = plan_review.feedback({"verdict": "revise", "issues": [
        {"kind": "extra", "what": "chart c2 is a zoom", "fix": "drop it"}]})
    assert "[extra] chart c2 is a zoom -> drop it" in text
    assert "revise_plan" in text and "disagree" in text


def test_the_review_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PHYSEARTH_PLAN_REVIEW", "off")
    assert not plan_review.enabled()
    monkeypatch.setenv("PHYSEARTH_PLAN_REVIEW", "on")
    assert plan_review.enabled()


@pytest.mark.skipif(not RECORD.is_file(), reason="the recorded Q1 run is not present")
def test_the_brief_carries_the_question_the_runs_and_the_charts():
    project = json.loads(RECORD.read_text())["research"]
    box = session.new_session("m")
    box["research"] = project
    text = plan_review.brief(box)
    assert "Question:" in text and "Reproduce Figure 3" in text
    assert "r_rayleigh_ind" in text and "Chart fig03_reproduction" in text
    assert len(text) <= plan_review.BRIEF_CHARS


def test_a_review_that_cannot_be_made_never_holds_the_plan_back(monkeypatch):
    def broken():
        raise RuntimeError("no endpoint")

    monkeypatch.setattr(completion, "_client", broken)
    assert loop._review_plan(session.new_session("m"), "m") is None


def test_a_review_call_returns_what_the_model_said(monkeypatch):
    reply = '{"verdict": "revise", "issues": [{"kind": "missing", "what": "no H curve", "fix": "add tb_h"}]}'
    client, sent = _fake_client([[_Chunk(_Delta(content=reply))]])
    monkeypatch.setattr(completion, "_client", lambda: client)
    found = loop._review_plan(session.new_session("m"), "m")
    assert found["verdict"] == "revise" and found["issues"][0]["kind"] == "missing"
    assert sent[0][0]["content"] == plan_review.PROMPT


def test_a_figures_caption_reaches_the_digest_verbatim(monkeypatch):
    from physearth.corpus import digest as paper_digest

    card = {"figures": [{"id": "fig04", "title": "Comparison with other reference models",
                         "caption": "The snowpack is semi-infinite with temperature 265 K."}]}
    monkeypatch.setattr(paper_digest.live, "card", lambda session, slug: card)
    found = paper_digest.captions({}, "smrt-v1")
    assert found == [{
        "ref": "smrt-v1#fig04", "section": "fig04", "kind": "figure",
        "statement": "Caption of Comparison with other reference models: The snowpack is "
                     "semi-infinite with temperature 265 K.",
    }]


def test_the_reviewer_sees_captions_and_conditions_before_other_statements():
    box = session.new_session("m")
    box["research"] = {"plan": {"question": "q"}}
    box["paper_digests"] = {"smrt-v1": {"items": [
        {"ref": "smrt-v1#09", "kind": "result", "statement": "A result."},
        {"ref": "smrt-v1#fig04", "kind": "figure", "statement": "Caption: temperature 265 K."},
    ]}}
    text = plan_review.brief(box)
    assert text.index("temperature 265 K") < text.index("A result.")
    assert "caption's" in plan_review.PROMPT


def test_the_reviewer_is_shown_the_figures_the_plan_reproduces(monkeypatch):
    from physearth.tools import literature

    box = {"research": {"plan": {"reproduction_targets": [
        {"source_id": "smrt-v1#fig06"}, {"source_id": "smrt-v1#fig06"}, {"source_id": "no-hash"},
    ]}}}
    assert plan_review.figure_refs(box) == ["smrt-v1#fig06"]
    monkeypatch.setenv("PHYSEARTH_LLM_VISION", "0")
    monkeypatch.setattr(literature.config, "get", lambda key, default=None: "0" if key == "PHYSEARTH_LLM_VISION" else default)
    assert literature.source_figure_images(box, ["smrt-v1#fig06"]) == []


def test_the_bundled_figure_reaches_the_reviewer_as_an_image():
    from physearth.tools import literature

    found = literature.source_figure_images(session.new_session("m"), ["smrt-v1#fig06"])
    assert found and found[0][0] == "smrt-v1#fig06" and found[0][1].startswith("data:image/png;base64,")

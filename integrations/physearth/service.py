"""One Python surface that plugin hosts drive.

Codex reaches this repository through an MCP server, DeepSeek Harness through a Cordis
plugin, and both need the same three things: the capabilities the engine declares, the
prompt stack that makes an answer scientific, and a way to run one tool call or one agent
turn. Keeping that in one module means a plugin never reaches past the package's declared
surface, and the two hosts cannot drift into calling the engine two different ways.

Two facts shape the design:

- a physical model run returns a *handle*, not a number, and the handle resolves only
  inside the session that produced it, so sessions live here and are addressed by id
  instead of being rebuilt per call;
- a run is approved by a human, and whether this process asks is the operator's choice,
  made once when the server starts (`configure`). No tool argument can change it: the host's
  model can write every argument, and the gate exists so that it cannot approve its own runs.
  When a run needs approval the turn pauses, the result carries the pending request, and
  `decide` records the person's verdict and continues from there.
"""

from __future__ import annotations

import threading

from physearth import agent, config, paths, prompt, registry, research, tools
from physearth import session as session_state
from physearth.corpus import knowledge, reference
from physearth.harness import approval, gates, switches as harness_switches
from physearth.ingest import http

_LOCK = threading.Lock()
_SESSIONS: dict = {}
_RUNNING: set = set()
_DEFAULT_SESSION_ID = None

APPROVAL_MODES = (approval.ASK, approval.ALWAYS)
DECISIONS = ("approve", "reject")
_OPERATOR = {
    "approval": approval.ASK,
    "profile": harness_switches.DEFAULT_PROFILE,
    "testing": False,
}
_SWITCHES = "host_switches"


def configure(approval_mode=None, profile=None, testing=None):
    """Fix the operator's settings for this process; called by whatever starts the server.

    `ask` (the default) pauses before every physical run until a person decides; `always`
    records that the operator approved runs in advance. Sessions read it when they are
    created, so it is chosen before any host request arrives.  The ``direct`` profile is
    the host-facing default when an MCP server starts: the host owns permission, there is
    one sticky session, and report verification is advisory. The direct host still has
    to author and review a research plan before a physical run; it only delegates the
    separate run-permission prompt and nested agent loop to the host. Host launchers
    select it explicitly; ``regulated`` preserves the original nested research-agent
    workflow for explicit callers.
    """
    if approval_mode is not None:
        if approval_mode not in APPROVAL_MODES:
            known = ", ".join(APPROVAL_MODES)
            raise ValueError(f"unknown approval mode {approval_mode!r}; choose one of {known}")
        _OPERATOR["approval"] = approval_mode
    if profile is not None:
        _OPERATOR["profile"] = harness_switches.resolve_profile(profile)["name"]
    if testing is not None:
        _OPERATOR["testing"] = bool(testing)
        http.configure_test_source_blocking(_OPERATOR["testing"])
    # Keep the long-standing return shape for CLI callers; ``health`` and ``profile``
    # expose the new policy fields without breaking scripts that only read approval.
    return {"approval": _OPERATOR["approval"]}


def profile():
    """Return the active host policy as JSON-safe data."""
    return harness_switches.resolve_profile(_OPERATOR["profile"])


def _session_profile(session):
    return harness_switches.resolve_profile(session.get("harness_profile") or _OPERATOR["profile"])


def _jsonable(value):
    """Session state holds sets, tuples and objects; a plugin host needs plain JSON."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def new_session(model=None):
    """Create one engine session and return the address a host keeps for later calls."""
    session = agent.new_session(model or agent.default_model())
    approval.set_mode(session, _OPERATOR["approval"])
    # Direct MCP sessions are research sessions from their first tool call. The
    # regulated agent starts with its legacy permission gate and turns on
    # ``research_required`` when its planning tool enters the research workflow.
    session["research_required"] = profile()["name"] == harness_switches.PROFILE_DIRECT
    session["harness_profile"] = _OPERATOR["profile"]
    session["host_agent"] = True
    with _LOCK:
        _SESSIONS[session["id"]] = session
        global _DEFAULT_SESSION_ID
        if profile()["sticky_session"]:
            _DEFAULT_SESSION_ID = session["id"]
    return {
        "session_id": session["id"],
        "model": session.get("model"),
        "approval": approval.mode(session),
        "profile": session["harness_profile"],
        "report_gate": _session_profile(session)["report_gate"],
        "testing": bool(_OPERATOR["testing"]),
    }


def get_session(session_id):
    """The live session, or None when the id is unknown to this process."""
    if session_id and session_id in _SESSIONS:
        return _SESSIONS[session_id]
    return None


def resolve_session(session_id=None, model=None):
    """Return the named session, or create one; unknown ids are not silently replaced."""
    session = get_session(session_id)
    if session is not None:
        return session, None
    if session_id:
        return None, {
            "status": "terminal_error",
            "error": "unknown_session",
            "summary": (
                "Session %r is not held by this process. Run results resolve only inside the "
                "session that produced them, so call new_session first." % session_id
            ),
        }
    if profile()["sticky_session"]:
        with _LOCK:
            default_id = _DEFAULT_SESSION_ID
        if default_id:
            session = get_session(default_id)
            if session is not None:
                return session, None
    created = new_session(model=model)
    return get_session(created["session_id"]), None


def sessions():
    """Every session this process holds, newest id last."""
    with _LOCK:
        return [_session_summary(session) for session in _SESSIONS.values()]


def drop_session(session_id):
    global _DEFAULT_SESSION_ID
    with _LOCK:
        removed = _SESSIONS.pop(session_id, None) is not None
        if _DEFAULT_SESSION_ID == session_id:
            _DEFAULT_SESSION_ID = None
        return removed


def _session_summary(session):
    project = session.get("research") or {}
    return {
        "session_id": session.get("id"),
        "model": session.get("model"),
        "turns": session.get("turns", 0),
        "model_runs": session.get("model_runs", 0),
        "tool_calls": session.get("tool_calls", 0),
        "evidence": _evidence_counts(session),
        "research_phase": project.get("phase"),
        "plan_version": project.get("plan_version"),
        "profile": _session_profile(session)["name"],
    }


def _evidence_counts(session):
    return {
        "sections": len(session.get("sections_read") or ()),
        "models_run": len(session.get("models_run") or ()),
        "datasets": len(session.get("datasets_read") or ()),
        "skills": len(session.get("skills_read") or ()),
        "abstracts": len(session.get("abstracts_seen") or ()),
        "figures": len([f for f in session.get("figures") or () if not f.get("preview")]),
        "handles": len(session.get("handles") or ()),
    }


def _models():
    """Every registered model; the registry addresses them by name."""
    registered = registry.all_models()
    return list(registered.values()) if hasattr(registered, "values") else list(registered)


def health():
    """What this checkout can actually do, in one call, without touching the network."""
    models = _models()
    return {
        "root": str(paths.root()) if hasattr(paths, "root") else "",
        "models": len(models),
        "runnable_models": len([item for item in models if item.runnable]),
        "tools": len(tools.specs()),
        "knowledge": _knowledge_counts(),
        "credentials": bool(config.has_token()),
        "approval": _OPERATOR["approval"],
        "profile": profile()["name"],
        "internal_approval_enabled": profile()["internal_approval"],
        "report_gate": profile()["report_gate"],
        "testing": bool(_OPERATOR["testing"]),
        "source_blocking": http.testing_source_blocking(),
        "online": str(config.get("PHYSEARTH_ONLINE")) != "0",
    }


def _knowledge_counts():
    papers = list(knowledge.slugs("paper"))
    return {
        "papers": len(papers),
        "sections": sum(len(knowledge.section_index(slug) or []) for slug in papers),
        "skills": len(knowledge.skills() or []),
        "reference_datasets": len(reference.slugs() or []),
    }


def tools_manifest():
    """Every tool the agent may call, as the model sees it."""
    manifest = []
    for spec in tools.specs():
        function = spec.get("function") or {}
        manifest.append(
            {
                "name": function.get("name"),
                "description": function.get("description", ""),
                "parameters": function.get("parameters") or {},
            }
        )
    return manifest


def models_manifest():
    """Every registered model with the declaration a run is validated against."""
    manifest = []
    for item in _models():
        card = item.card
        manifest.append(
            {
                "name": item.name,
                "version": card.get("version"),
                "tier": item.tier,
                "runnable": item.runnable,
                "unavailable_reason": item.unavailable_reason,
                "description": card.get("description", ""),
                "citation": card.get("citation", ""),
                "license": card.get("license", ""),
                "parameters": {
                    name: {
                        key: spec.get(key)
                        for key in ("type", "unit", "description", "minimum", "maximum", "default", "enum")
                        if key in spec
                    }
                    for name, spec in (card.get("parameters") or {}).items()
                },
                "outputs": {
                    name: {
                        key: spec.get(key)
                        for key in ("unit", "description", "valid_min", "valid_max")
                        if key in spec
                    }
                    for name, spec in (card.get("outputs") or {}).items()
                },
            }
        )
    return manifest


def knowledge_manifest():
    """The evidence the agent may read, and how it is addressed when cited."""
    papers = []
    for slug in sorted(knowledge.slugs("paper")):
        card = knowledge.card(slug) or {}
        papers.append(
            {
                "slug": slug,
                "title": card.get("title"),
                "license": card.get("license"),
                "sections": sorted(
                    str(section.get("id")) for section in (knowledge.section_index(slug) or [])
                ),
                "citation_key": "[%s#<section>]" % slug,
            }
        )
    return {
        "papers": papers,
        "skills": [
            {
                "slug": item.get("slug"),
                "title": item.get("title"),
                "citation_key": "[skill:%s]" % item.get("slug"),
            }
            for item in sorted(knowledge.skills() or [], key=lambda entry: str(entry.get("slug")))
        ],
        "reference_datasets": [
            {"slug": slug, "citation_key": "[data:%s]" % slug}
            for slug in sorted(reference.slugs() or ())
        ],
    }


# The three reasons a host wants this text, and they are not the same size.
PROMPT_SCOPES = ("identity", "rules", "context")


def prompt_sections():
    """The prompt stack as named groups rather than one string.

    A host that is not this agent's own loop needs this text for three different reasons:

      identity  who the agent is and how it writes. A coding agent already has an identity of
                its own, and this group *replaces* it — "You are PhysEarth, an
                Earth-science physical-modeling agent" is a persona, so a host that takes it
                inherits the persona too, including the parts that are not its job.
      rules     what makes an answer scientific: the citation and evidence-tier rules, the
                untrusted-text boundary, and the explore → plan → approve → run → report
                workflow. This is the part that changes what a model *does*, which is why it is
                the group worth somebody else's system prompt.
      context   the registered models, reference datasets, method notes and tool catalogue,
                generated from this checkout. It is also available at runtime through the tools
                and resources, so a host that can call those leaves it out rather than paying
                for a copy that goes stale inside a session.
    """
    return {
        "identity": [prompt.ROLE, prompt.STYLE],
        "rules": [
            prompt.CITATION_RULES,
            prompt.ABSTRACT_RULE,
            prompt.ONLINE_RULES,
            prompt.WORKFLOW,
            prompt.RESEARCH_WORKFLOW,
            prompt.TRIGGERS,
        ],
        "context": [
            prompt.models_section(),
            prompt.reference_section(),
            prompt.skills_section(),
            prompt.catalogue_section(),
        ],
    }


def prompt_stack(scopes=None):
    """The L0-L2 prompt blocks plus the generated context: what makes an answer scientific.

    This is the text a host injects so the model it runs behaves like this project's agent:
    identity and style, the citation and evidence-tier rules, the untrusted-text boundary,
    and the explore → plan → approve → run → report workflow.

    Every scope by default, in the order the agent's own loop stacks them, so a host that asks
    for all of it gets exactly what the engine gives its own model. `scopes` is for hosts that
    want part of it — see `prompt_sections` for why they would — and an unknown name is an
    error rather than an omission, because a silently narrower prompt is the failure this
    repository treats as the worst kind: one that changes answers with nothing in the log.
    """
    selected = PROMPT_SCOPES if scopes is None else tuple(scopes)
    unknown = [scope for scope in selected if scope not in PROMPT_SCOPES]
    if unknown:
        raise ValueError(
            "unknown prompt scope(s): %s. Known scopes: %s"
            % (", ".join(map(str, unknown)), ", ".join(PROMPT_SCOPES))
        )
    sections = prompt_sections()
    blocks = [block for scope in selected for block in sections[scope]]
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


def call(name, arguments=None, session_id=None, switches=None):
    """Run one tool call inside a session and report what the engine decided.

    A `run_model` call is held for a verdict under the same condition the agent loop holds
    it, so driving the tools directly is not a way around the gate.
    """
    session, problem = resolve_session(session_id)
    if problem is not None:
        return problem
    session[_SWITCHES] = switches
    if (
        name == "run_model"
        and _session_profile(session)["internal_approval"]
        and approval.required(session)
        and not session.get("research_required")
    ):
        approval.request(session, name, arguments or {})
        return _awaiting(session, {"status": "awaiting_approval", "session_id": session["id"]})
    return _execute(session, name, arguments or {}, switches)


def _execute(session, name, arguments, switches):
    # A tool call is bookkept where the loop bookkeeps it.  Without this, a host that
    # drives tools directly would hold a result handle the session never registered, and
    # every later question about "what has been run here" would answer with nothing --
    # the engine's own recorder is the one place that decides what a run means.
    state = session_state.new_state(session)
    result = tools.call(
        name,
        arguments,
        owner=session["id"],
        switches_in=switches,
        session=session,
    )
    result = _auto_confirm_testing_capability(session, name, arguments, result, switches)
    result = _auto_approve_testing_plan(session, name, arguments, result)
    session_state.bump(state, "tool_calls")
    agent._record_tool_result(name, result, state, [])
    return _jsonable(result)


def _auto_confirm_testing_capability(session, name, arguments, result, switches):
    """Confirm a capability review's documented partial-scope option in benchmark mode.

    Some paper reproductions need an operation that is not a registered physical model, such
    as an inverse solver. The normal workflow asks the person to choose a documented option.
    In explicit testing mode, select the first available option (the engine's recommended
    option) through the same capability tool, and preserve the decision in the returned data.
    This does not execute the operation or skip any later plan, run, chart, or report gate.
    """
    if not _OPERATOR["testing"] or name != "research_capability_check":
        return result
    if not isinstance(result, dict) or result.get("status") != "needs_input":
        return result
    review = ((result.get("data") or {}).get("capability_review") or {})
    if review.get("status") != "waiting_user":
        return result
    options = review.get("missing_operations") or []
    if not options:
        return result
    confirmed = tools.call(
        name,
        {"action": "confirm_partial"},
        owner=session["id"],
        switches_in=switches,
        session=session,
    )
    if not isinstance(confirmed, dict) or confirmed.get("status") != "success":
        return result
    enriched = dict(confirmed)
    data = dict(confirmed.get("data") or {})
    data["testing_auto_confirmed"] = True
    data["auto_capability_choice"] = "recommended_available_option"
    data["initial_capability_review"] = review
    enriched["data"] = data
    enriched["testing_auto_confirmed"] = True
    enriched["summary"] = (
        "%s Testing mode automatically selected the documented recommended available "
        "capability option; the normal research-plan gate remains active."
        % str(enriched.get("summary") or "Capability checkpoint complete.").rstrip(".")
    )
    return enriched


def _auto_approve_testing_plan(session, name, arguments, result):
    """Apply the normal review action automatically in explicit benchmark mode.

    The engine intentionally returns a review-needed result after a valid proposal. For a
    repeatable host comparison, ``--testing`` may supply the equivalent of the user's
    ``satisfied_figures`` click. It is deliberately narrow: only proposal submissions at
    ``plan_review`` qualify, and the existing review action must reach ``approved``. A
    malformed proposal, a resource-gated proposal, or any other phase remains gated.
    """
    if not _OPERATOR["testing"] or name != "research_plan":
        return result
    action = str((arguments or {}).get("action") or "")
    if action not in ("propose", "revise_plan"):
        return result
    project = session.get("research") or {}
    if project.get("phase") != "plan_review":
        return result
    review = research.review_action(session, "satisfied_figures")
    if (session.get("research") or {}).get("phase") != "approved":
        return result
    enriched = dict(result or {})
    review_data = dict(review.get("data") or {}) if isinstance(review, dict) else {}
    review_data["testing_auto_approved"] = True
    review_data["auto_review_choice"] = "satisfied_figures"
    enriched["data"] = review_data
    enriched["testing_auto_approved"] = True
    enriched["summary"] = (
        "%s Testing mode automatically applied the existing satisfied_figures review "
        "action; formal execution is now approved."
        % str(enriched.get("summary") or "Research plan accepted.").rstrip(".")
    )
    return enriched


def _no_credentials():
    """A host without credentials gets a structured refusal rather than a traceback."""
    if config.has_token() or str(config.get("PHYSEARTH_LLM_API_BASE") or "").startswith(
        ("http://127.0.0.1", "http://localhost")
    ):
        return None
    return {
        "status": "terminal_error",
        "error": "no_credentials",
        "summary": (
            "No inference credentials are configured (PHYSEARTH_LLM_API_KEY or "
            "MODELSCOPE_TOKEN). Nothing was computed."
        ),
    }


def ask(question, session_id=None, model=None, switches=None):
    """Run one agent turn and return the answer, the trace and the session address.

    The answer to a physics question must never be invented locally to fill a gap, so a
    missing credential is a refusal. A turn that reaches a run needing approval ends paused:
    the result says `awaiting_approval` and carries what the person is asked to approve.
    """
    if not profile()["nested_agent"]:
        return {
            "status": "terminal_error",
            "error": "nested_agent_disabled",
            "summary": (
                "The direct host profile does not run a second PhysEarth agent loop. "
                "Use the exposed tools directly; select profile='regulated' only when "
                "an internal research-agent loop is intentional."
            ),
        }
    refusal = _no_credentials()
    if refusal is not None:
        return refusal
    session, problem = resolve_session(session_id, model=model)
    if problem is not None:
        return problem
    session[_SWITCHES] = switches
    return _turn(session, question, model, switches)


def _turn(session, question, model, switches):
    # A host that times out and asks again must not start a second turn beside the first:
    # both would spend, and both would write the same session.
    with _LOCK:
        if session["id"] in _RUNNING:
            return {
                "status": "terminal_error",
                "error": "session_busy",
                "summary": "A turn is still running in this session; wait for it to finish.",
            }
        _RUNNING.add(session["id"])
    try:
        answer, events, state = agent.run(
            question, model=model, session=session, switches=switches
        )
    finally:
        with _LOCK:
            _RUNNING.discard(session["id"])
    result = {
        "status": "success",
        "session_id": session["id"],
        "answer": answer,
        "events": _jsonable(events),
        "counters": {
            "model_calls": state.get("model_calls", 0),
            "tool_calls": state.get("tool_calls", 0),
            "model_runs": state.get("model_runs", 0),
            "interventions": state.get("interventions", 0),
        },
        "evidence": evidence(session["id"]),
    }
    if approval.pending(session) is not None:
        result["status"] = "awaiting_approval"
        result = _awaiting(session, result)
    return result


def _awaiting(session, result):
    held = approval.pending(session)
    result["pending"] = {
        "tool": held["tool"],
        "description": _jsonable(held["description"]),
    }
    result["next_action"] = (
        "Nothing has been computed. Show this request to the person running the host and "
        "call physearth_decide with their verdict, approve or reject. Do not decide it yourself."
    )
    return result


def decide(session_id, decision):
    """Record a person's verdict on the held run and continue from it.

    Only `approve` and `reject` are accepted: the engine's `always` would switch the gate off
    for the rest of the session, and that is the operator's choice, not a verdict. A paused
    agent turn resumes at the held call; a held direct call runs, or comes back declined.
    """
    session = get_session(session_id)
    if session is None:
        return {"status": "terminal_error", "error": "unknown_session", "summary": session_id}
    if not _session_profile(session)["internal_approval"]:
        return {
            "status": "terminal_error",
            "error": "internal_approval_disabled",
            "summary": "The direct host profile delegates permission to the host.",
        }
    if decision not in DECISIONS:
        return {
            "status": "terminal_error",
            "error": "unknown_decision",
            "summary": f"{decision!r} is not a verdict; use one of {', '.join(DECISIONS)}.",
        }
    held = approval.pending(session)
    if held is None:
        return {
            "status": "terminal_error",
            "error": "nothing_pending",
            "summary": "No run is waiting for approval in this session.",
        }
    if held.get("resume"):
        refusal = _no_credentials()
        if refusal is not None:
            return refusal
        approval.decide(session, decision)
        return _turn(session, "", None, session.get(_SWITCHES))
    approval.decide(session, decision)
    taken = approval.take(session)
    if decision == "approve":
        return _execute(session, taken["tool"], taken["arguments"], session.get(_SWITCHES))
    return _jsonable(approval.declined_result(taken["tool"], taken["arguments"]))


def verify_report(session_id, text, mode=None):
    """Check an answer the host wrote against what this session actually read and ran.

    The checks are the engine's own final-answer gates: every marker must resolve to a
    section opened, a model run, a dataset queried, a method note or figure opened; a long
    answer needs some evidence behind it; and an abstract-only citation may not carry a
    result value. Model runs count over the whole session, because a report covers it.
    """
    session = get_session(session_id)
    if session is None:
        return {"status": "terminal_error", "error": "unknown_session", "summary": session_id}
    policy = _session_profile(session)
    selected_mode = mode or policy["report_gate"]
    if selected_mode not in ("lint", "hard"):
        return {
            "status": "terminal_error",
            "error": "unknown_report_mode",
            "summary": "mode must be 'lint' or 'hard'.",
        }
    if selected_mode == "hard" and not policy["internal_approval"]:
        return {
            "status": "terminal_error",
            "error": "hard_report_gate_disabled",
            "summary": "The direct host profile exposes report verification as advisory lint.",
        }
    state = session_state.new_state(session)
    state["model_runs"] = session.get("model_runs", 0)
    checks = gates.final_checks(text, state)
    failed = [check for check in checks if not check["passed"]]
    return {
        "status": "success",
        "session_id": session["id"],
        "passed": not failed,
        "mode": selected_mode,
        "enforced": selected_mode == "hard",
        "summary": (
            f"All {len(checks)} checks passed."
            if not failed
            else "Failed: " + ", ".join(check["rule"] for check in failed) + "."
        ),
        "checks": _jsonable(checks),
        "corrections": [gates.correction(check) for check in failed],
    }


def evidence(session_id):
    """What the session actually read, ran and drew: the material a citation may resolve to."""
    session = get_session(session_id)
    if session is None:
        return {"status": "terminal_error", "error": "unknown_session", "summary": session_id}
    project = session.get("research") or {}
    plan = project.get("plan") or {}
    return {
        "session_id": session["id"],
        "counts": _evidence_counts(session),
        "sections_read": sorted(session.get("sections_read") or ()),
        "models_run": sorted(session.get("models_run") or ()),
        "datasets_read": sorted(session.get("datasets_read") or ()),
        "skills_read": sorted(session.get("skills_read") or ()),
        "successful_runs": [
            {
                "planned_run_id": run.get("planned_run_id"),
                "model": run.get("model"),
                "handle": run.get("handle"),
            }
            for run in session.get("successful_runs") or ()
        ],
        "figures": [
            {
                "figure_number": figure.get("figure_number"),
                "planned_chart_id": figure.get("planned_chart_id"),
                "image_path": figure.get("image_path"),
                "preview": bool(figure.get("preview")),
            }
            for figure in session.get("figures") or ()
        ],
        "research": {
            "phase": project.get("phase"),
            "plan_version": project.get("plan_version"),
            "planned_runs": [run.get("id") for run in plan.get("runs") or ()],
            "planned_charts": [chart.get("id") for chart in plan.get("charts") or ()],
        },
        "handles": [
            {"handle": item.get("handle"), "line": item.get("line")}
            for item in (session.get("handles") or ())[-10:]
        ],
    }


def plan_status(session_id):
    """The research plan and its review state, so a host can show a review step."""
    session = get_session(session_id)
    if session is None:
        return {"status": "terminal_error", "error": "unknown_session", "summary": session_id}
    project = session.get("research") or {}
    if not project:
        return {
            "status": "success",
            "phase": None,
            "plan": None,
            "next_action": _next_action(None),
        }
    return {
        "status": "success",
        "phase": project.get("phase"),
        "plan_version": project.get("plan_version"),
        "plan": _jsonable(project.get("plan") or {}),
        "review_actions": _jsonable(project.get("review_log") or []),
        "next_action": _next_action(project.get("phase")),
    }


def _next_action(phase):
    return {
        "plan_review": "review the plan, then approve or revise it",
        "plan_approved": "generate the pseudo-data preview",
        "pseudo_preview": "choose the charts to produce",
        "chart_selected": "approve formal execution",
        "approved": "run the planned models, then plot and review the figures",
        "completed": "read the report",
    }.get(phase, "start a research plan")


def review(session_id, choice):
    """Advance the human review gate: the same single entry point the Studio uses."""
    session = get_session(session_id)
    if session is None:
        return {"status": "terminal_error", "error": "unknown_session", "summary": session_id}
    result = research.review_action(session, choice)
    return _jsonable(result)

def knowledge_read(slug, section_id):
    """One bundled paper section, addressed the way a citation addresses it."""
    section = knowledge.read_section(slug, section_id)
    if not section:
        return {
            "status": "terminal_error",
            "error": "unknown_section",
            "summary": "%r is not a section of the bundled paper %r." % (section_id, slug),
        }
    return _jsonable(section)


def reference_query(slug, filters=None):
    """Rows from a bundled reference dataset, which is measurement evidence, not a model."""
    if slug not in set(reference.slugs() or ()):
        return {
            "status": "terminal_error",
            "error": "unknown_dataset",
            "summary": "%r is not a bundled reference dataset. Available: %s."
            % (slug, ", ".join(sorted(reference.slugs() or ()))),
        }
    try:
        rows = reference.query(slug, filters or {})
    except Exception as exc:
        return {
            "status": "terminal_error",
            "error": "dataset_query_failed",
            "summary": "%s" % exc,
        }
    return _jsonable(rows)

"""Plan and report pages, rendered once for every surface that shows them.

The Studio opens these as standalone HTML files; the MCP server returns the same pages to a coding
agent. One implementation means a person reviewing a plan, or reading a report, sees the same
conditions, the same source labels and the same figures wherever they look. The Markdown plan a
host edits is built from the same sheet (`research.sheet`) and the same source vocabulary.

Nothing here imports Gradio. Every value that reaches a page goes through `html.escape` first:
literature text, dataset rows and model output are all untrusted input on a public deployment.
"""

import base64
import html
import json
import re
import time
from pathlib import Path

from physearth import agent, research

# ---- from the Studio's text helpers

CITE = re.compile(r"\[([a-z0-9][a-z0-9-]*)#(\d{1,3})\]")


MODEL_CITE = re.compile(r"\[model:([A-Za-z0-9_-]+)@([^\]\s]+)\]")


DATA_CITE = re.compile(r"\[data:([a-z0-9][a-z0-9-]*)\]")


ABS_CITE = re.compile(r"\[abs:(10\.\d{4,9}/[^\]\s]+)\]", re.I)


SKILL_CITE = re.compile(r"\[skill:([a-z0-9][a-z0-9-]*)\]")


BOLD = re.compile(r"\*\*([^*]+)\*\*")


CODE = re.compile(r"`([^`]+)`")


SAFE_SUB = re.compile(r"&lt;(/?)(sub|sup)&gt;", re.I)


def _e(value):
    return html.escape(str(value), quote=True)


def _markers(text):
    """Turn the four marker forms into chips that jump to the evidence they name."""

    # Every closure below runs over text that _inline has already escaped, so none of
    # them escapes again: a second pass turns an ampersand inside a DOI into &amp;amp;.
    def section(match):
        key = "%s#%s" % (match.group(1), match.group(2))
        return (
            "<a class='cite' href='#' data-jump='sec-%s' data-tab='pe-tab-sources'>%s</a>"
            % (key, key)
        )

    def model(match):
        key = "%s@%s" % (match.group(1), match.group(2))
        return (
            "<a class='cite cite--model' href='#' data-jump='model-%s' "
            "data-tab='pe-tab-models'>%s</a>" % (match.group(1), key)
        )

    def data(match):
        slug = match.group(1)
        return (
            "<a class='cite cite--data' href='#' data-jump='data-%s' "
            "data-tab='pe-tab-sources'>%s</a>" % (slug, slug)
        )

    def abstract(match):
        doi = match.group(1)
        return (
            "<a class='cite cite--abs' href='#' data-jump='abs-%s' "
            "data-tab='pe-tab-sources' title='abstract level: metadata only, never a "
            "measured or computed value'>abs:%s</a>" % (doi, doi)
        )

    def skill(match):
        slug = match.group(1)
        return (
            "<a class='cite cite--skill' href='#' data-jump='sec-%s#00' "
            "data-tab='pe-tab-sources' title='the agent opened this method note before "
            "writing this sentence'>%s</a>" % (slug, slug)
        )

    # The abstract form goes first: some DOIs would otherwise be eaten by the model pattern.
    text = ABS_CITE.sub(abstract, text)
    text = SKILL_CITE.sub(skill, text)
    text = CITE.sub(section, text)
    text = MODEL_CITE.sub(model, text)
    return DATA_CITE.sub(data, text)


def _paragraphs(text):
    blocks = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            heading = re.match(r"^(#{1,3})\s+(.+)$", lines[0])
            if heading:
                level = len(heading.group(1))
                blocks.append(
                    "<h%d>%s</h%d>" % (level, _inline(heading.group(2)), level)
                )
                continue
        if _is_table(lines):
            blocks.append(_table(lines))
            continue
        if all(line.startswith(("- ", "* ")) for line in lines):
            items = "".join("<li>%s</li>" % _inline(line[2:]) for line in lines)
            blocks.append("<ul>%s</ul>" % items)
        else:
            blocks.append("<p>%s</p>" % _inline(" ".join(lines)))
    return "".join(blocks)


def _inline(text):
    out = _e(text)
    out = CODE.sub(lambda m: "<code>%s</code>" % m.group(1), out)
    out = BOLD.sub(lambda m: "<b>%s</b>" % m.group(1), out)
    # Allow only the two typographic equation tags after escaping. Attributes and every
    # other HTML tag remain escaped, so model output cannot inject markup or scripts.
    out = SAFE_SUB.sub(lambda m: "<%s%s>" % (m.group(1), m.group(2).lower()), out)
    return _markers(out)


TABLE_RULE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_table(lines):
    """A Markdown pipe table: a header row, a rule row, then rows, every one piped."""
    return (
        len(lines) >= 2
        and all(line.startswith("|") for line in lines)
        and bool(TABLE_RULE.match(lines[1].replace(" ", "")))
    )


def _table(lines):
    head = _cells(lines[0])
    rows = [_cells(line) for line in lines[2:]]
    return (
        "<div class='md-table-wrap'><table class='md-table'><thead><tr>%s</tr></thead>"
        "<tbody>%s</tbody></table></div>"
        % (
            "".join("<th>%s</th>" % _inline(cell) for cell in head),
            "".join(
                "<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(cell) for cell in row)
                for row in rows
            ),
        )
    )


# ---- from the Studio's parts helpers

def _plan_cell(value, limit=None):
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, indent=1, default=str)
    else:
        text = str(value if value not in (None, "") else "—")
    if limit and len(text) > limit:
        text = text[: limit - 1] + "…"
    return _e(text)


def _plan_table(headers, rows, css="research-plan-table"):
    head = "".join("<th>%s</th>" % _e(header) for header in headers)
    body = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % cell for cell in row)
        for row in rows
    )
    return (
        "<div class='%s-wrap'><table class='%s'><thead><tr>%s</tr></thead>"
        "<tbody>%s</tbody></table></div>" % (css, css, head, body or "<tr><td colspan='%d'>none</td></tr>" % len(headers))
    )


_TAG_HELP = {
    "extracted": "stated in the paper, or read off its figure",
    "derived": "follows from what the paper states",
    "user": "given in the question",
    "default": "the model card's default; the paper does not say",
    "assumed": "chosen by the agent, with a reason",
    "guessed": "chosen by the agent with no stated reason",
    "unlabelled": "no source recorded",
    "mixed": "differs between runs",
}


def _source_chip(tag, ref=""):
    return "<span class='src src--%s' title='%s'>%s</span>%s" % (
        _e(tag), _e(_TAG_HELP.get(tag, "")), _e(tag),
        " <span class='src-ref'>%s</span>" % _e(ref) if ref else "",
    )


def _breakable(text):
    """Escaped text that may wrap after an underscore, never inside a word."""
    return _e(text).replace("_", "_<wbr>")


def _parameter_cell(item):
    """`frequency` with its code name and the card's one-line description under it."""
    name = item["name"]
    shown = item.get("label") or name
    suffix = " (%s)" % name
    title = shown[: -len(suffix)] if shown.endswith(suffix) else shown
    return "<b>%s</b>%s%s" % (
        _e(title),
        " <code>%s</code>" % _e(name) if title != name else "",
        "<div class='plan-sheet__about'>%s</div>" % _e(item["about"]) if item.get("about") else "",
    )


def plan_sheet_html(plan, conditions=True):
    """The plan as conditions once, with their sources, and a matrix of what differs per run."""
    sheet = research.sheet.build(plan)
    if not sheet["groups"]:
        return ""
    out = ["<div class='plan-sheet'>"]
    if conditions and sheet["decisions"]:
        items = "".join(
            "<li><b>%s</b> = %s %s%s</li>" % (
                _e(d.get("label") or d["name"]),
                _e(d.get("shown") or research.sheet.fmt(d["value"])),
                _source_chip(d["tag"]),
                " <span class='plan-sheet__hint'>%s</span>" % _e(d["note"]) if d.get("note") else "",
            )
            for d in sheet["decisions"]
        )
        out.append(
            "<div class='plan-sheet__decide'><b>Needs your decision (%d)</b>"
            "<span class='plan-sheet__hint'> chosen without a source in the paper; approve, or ask for a change</span>"
            "<ul>%s</ul></div>" % (len(sheet["decisions"]), items)
        )
    for group in sheet["groups"]:
        title = "%s%s · %d run%s" % (
            group["model"] or "model", " v%s" % group["version"] if group["version"] else "",
            len(group["runs"]), "" if len(group["runs"]) == 1 else "s",
        )
        purpose = group.get("purpose") or ""
        if group.get("outputs"):
            purpose = "%s%sOutputs used: %s." % (
                purpose, " " if purpose else "", ", ".join(group["outputs"]),
            )
        out.append(
            "<div class='plan-sheet__group'><div class='plan-sheet__title'>%s</div>%s"
            % (_e(title), "<div class='plan-sheet__purpose'>%s</div>" % _e(purpose) if purpose else "")
        )
        if conditions:
            rows = [
                [
                    _parameter_cell(c),
                    _breakable(c.get("shown") or research.sheet.fmt(c["value"])),
                    _source_chip(c["tag"], c["ref"]),
                    _e(c["note"]) or "<span class='plan-sheet__hint'>-</span>",
                ]
                for c in group["conditions"]
            ]
            out.append(
                "<div class='plan-sheet__label'>Conditions, the same in every run</div>"
                + _plan_table(("Parameter", "Value", "Source", "Note"), rows, css="plan-sheet-table")
            )
            if group["sweep"]:
                out.append("<div class='plan-sheet__sweep'><b>Swept in every run:</b> %s</div>" % _e(group["sweep"]))
        columns = group["columns"]
        headers = ["Run"] + [
            (c.get("label") or c["name"])
            + (" (%s)" % research.sheet.unit_text(c["unit"]) if research.sheet.unit_text(c["unit"]) else "")
            for c in columns
        ]
        if group["sweep_varies"]:
            headers.append("Sweep")
        headers.append("Feeds")
        rows = []
        for run in group["runs"]:
            cells = ["<b>%s</b>%s%s" % (
                _e(run["id"]),
                " <span class='plan-sheet__stage'>%s</span>" % _e(run["stage"]) if run["stage"] and run["stage"] != "main" else "",
                "<div class='plan-sheet__about'>%s</div>" % _e(run["label"]) if run.get("label") and run["label"] != run["id"] else "",
            )]
            cells += [_breakable(research.sheet.fmt(run["values"].get(c["name"]))) for c in columns]
            if group["sweep_varies"]:
                cells.append(_e(run["sweep"]))
            cells.append(_e(", ".join(run["feeds"]) or "-"))
            rows.append(cells)
        out.append(
            "<div class='plan-sheet__label'>Runs, only what differs</div>"
            + _plan_table(headers, rows, css="plan-sheet-table")
        )
        if columns:
            out.append("<div class='plan-sheet__sources'>%s</div>" % " ".join(
                "<span>%s %s</span>" % (_e(c.get("label") or c["name"]), _source_chip(c["tag"], c["ref"])) for c in columns
            ))
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


# ---- from the Studio's exports helpers

_STYLE = """
:root{--paper:#faf9f5;--card:#ffffff;--ink:#1f1e1d;--soft:#4a4944;--mute:#6b6a65;--line:#e4e1d8;
--clay:#c4623f;--wash:#f6e6dd;--ok:#2f6b3a;--okwash:#e3f0d8}
@media (prefers-color-scheme:dark){:root{--paper:#1c1b19;--card:#252421;--ink:#ecebe6;--soft:#c9c7bf;
--mute:#9a988f;--line:#3a3833;--clay:#e08a63;--wash:#3a2a22;--ok:#9fd3a6;--okwash:#24331f}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px}
h1{font:700 26px/1.25 Georgia,"Times New Roman",serif;margin:0 0 6px}
h2{font:700 19px/1.3 Georgia,"Times New Roman",serif;margin:28px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:18px 0 8px}
.meta{color:var(--mute);font-size:13px;margin:0 0 18px}
.meta span+span:before{content:" · "}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.findings{border-color:color-mix(in srgb,var(--clay) 50%,var(--line));background:color-mix(in srgb,var(--wash) 55%,var(--card))}
.label{font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.07em;text-transform:uppercase;color:var(--mute);margin:0 0 6px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
th{color:var(--soft);font-size:12px}
.md-table-wrap,.research-plan-table-wrap,.plan-sheet-table-wrap,.research-preview-wrap{max-width:100%;overflow-x:auto;margin:8px 0}
code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto}
.cite{display:inline-block;font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;padding:2px 5px;border-radius:4px;
background:var(--okwash);color:var(--ok);text-decoration:none;white-space:nowrap}
.cite--abs{background:#fbe9c7;color:#7a4a05}
figure{margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
figure img{display:block;max-width:100%;height:auto;margin:0 auto;background:#fff;border-radius:6px}
figcaption{font-size:13px;color:var(--soft);margin-top:8px}
.plan-sheet{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
.plan-sheet__group{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--card)}
.plan-sheet__title{font-weight:600;margin-bottom:8px}
.plan-sheet__purpose{font-size:13px;color:var(--soft);margin:-4px 0 8px}
.plan-sheet-table td:nth-child(2){white-space:nowrap}
.plan-sheet-table td,.plan-sheet-table th{overflow-wrap:normal;word-break:normal}
.plan-sheet-table th{white-space:nowrap}
.plan-sheet-table td:first-child{min-width:150px}
.plan-sheet__about{font-size:12px;color:var(--mute);line-height:1.35;margin-top:2px}
.plan-sheet__label{font:600 11px/1.2 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin:10px 0 4px}
.plan-sheet__sweep,.plan-sheet__sources{font-size:13px;margin:8px 0 0;display:flex;gap:10px;flex-wrap:wrap}
.plan-sheet__decide{border:1px solid #e0b25c;background:#fbf3df;color:#3d2c08;border-radius:10px;padding:10px 14px}
.plan-sheet__hint{font-size:12px;opacity:.8}
.plan-sheet__stage{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 5px}
.src{display:inline-block;font:600 11px/1 ui-monospace,monospace;padding:3px 6px;border-radius:4px;white-space:nowrap}
.src-ref{font:11px ui-monospace,monospace;color:var(--mute)}
.src--extracted{background:#e3f0d8;color:#2f5a12}.src--derived{background:#d9efe9;color:#0b5a47}
.src--user{background:#dce9f8;color:#174a80}.src--default{background:#ebeae4;color:#4a4944}
.src--assumed,.src--mixed{background:#fbe9c7;color:#7a4a05}.src--guessed,.src--unlabelled{background:#f8d9d9;color:#8a2020}
.how ul{margin:6px 0 0;padding-left:20px}
footer{margin-top:40px;color:var(--mute);font-size:12px}
@media print{body{background:#fff}main{max-width:none;padding:0}figure,.card{break-inside:avoid}}
"""


def _page(title, body):
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>%s</title><style>%s</style></head><body><main>%s</main></body></html>"
        % (_e(title), _STYLE, body)
    )


def _title(plan, fallback):
    """The plan's title, unless it is really the whole question restated."""
    title = " ".join(str(plan.get("title") or "").split())
    return title if title and len(title) <= 90 else fallback


def _list(items):
    items = [str(item) for item in items or () if str(item).strip()]
    if not items:
        return "<p class='meta'>none stated</p>"
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % _e(item) for item in items)


def _warning_text(item):
    """One validation warning as a sentence, from whichever of its fields are present."""
    parts = [str(item.get(key)) for key in ("message", "detail") if item.get(key)]
    if not parts:
        field = str(item.get("field") or "").replace("_", " ")
        expected, actual = item.get("expected"), item.get("actual")
        parts.append(
            "%s%s%s" % (
                field or "plan",
                ": paper context %s" % research.sheet.fmt(expected) if expected not in (None, "") else "",
                "; plan has %s" % research.sheet.fmt(actual) if actual not in (None, "") else "",
            )
        )
    return " ".join(parts)


def _warning_field(item):
    """The parameter a warning is about, as a person names it, or ''."""
    return str(item.get("field") or "").split(".")[-1].replace("_", " ")


def things_to_check(plan, limit=6):
    """The plan's warnings as a short list: each sentence once, with what it applies to.

    The same check fires for every condition that differs from the paper, so its sentence used to
    appear dozens of times. Here it is said once with the conditions it covers; a warning that
    says nothing a reader can act on is left out.
    """
    order, grouped = [], {}
    for item in plan.get("validation_warnings") or ():
        if not isinstance(item, dict):
            continue
        text = _warning_text(item).strip()
        if len(text) < 12 or text.lower().rstrip(".") in ("plan", "none"):
            continue
        if text not in grouped:
            grouped[text] = []
            order.append(text)
        field = _warning_field(item)
        if field and field not in grouped[text]:
            grouped[text].append(field)
    lines = []
    for text in order[:limit]:
        fields = grouped[text]
        lines.append("%s%s" % (text, " (%s)" % ", ".join(fields[:8]) if len(fields) > 1 else ""))
    if len(order) > limit:
        lines.append("%d more point(s) of the same kind are not listed." % (len(order) - limit))
    return lines


def evidence_the_plan_uses(session, plan, limit=8):
    """Paper statements the plan cites or reproduces, not the whole digest."""
    built = research.sheet.build(plan)
    refs = {str(c.get("ref")) for g in built["groups"] for c in g["conditions"] if c.get("ref")}
    for target in plan.get("reproduction_targets") or ():
        if isinstance(target, dict) and target.get("source_id"):
            refs.add(str(target["source_id"]))
    for item in plan.get("literature_evidence") or ():
        if isinstance(item, dict) and item.get("evidence_ref"):
            refs.add(str(item["evidence_ref"]))
    rows = []
    for record in ((session or {}).get("paper_digests") or {}).values():
        for item in record.get("items") or ():
            if str(item.get("ref")) in refs:
                rows.append((item.get("kind") != "figure", item))
    rows.sort(key=lambda pair: pair[0])
    return [item for _later, item in rows][:limit]


def plan_document(session):
    """The current plan as a page to read, print or send before approving it.

    What a reviewer decides on: the question, the conditions with their sources, the runs,
    the figures, and the assumptions. The machinery behind it -- evidence ledger, raw
    mappings, the protocol file -- stays out; the protocol is one typed word away.
    """
    project = (session or {}).get("research") or {}
    plan = project.get("plan") or {}
    version = int(project.get("plan_version") or 1)
    title = _title(plan, "Research plan")
    summary = plan.get("revision_summary") or project.get("revision_summary")
    readable = (summary or {}).get("readable") or []
    body = [
        "<h1>%s</h1>" % _e(title),
        "<p class='meta'><span>Plan v%03d</span><span>%s</span><span>%s</span></p>"
        % (version, _e((project.get("phase") or "plan_review").replace("_", " ")), _e(time.strftime("%Y-%m-%d %H:%M"))),
        "<div class='card how'><div class='label'>How to approve or change this plan</div>"
        "Reply in the PhysEarth Conversation:<ul>"
        "<li><b>approve</b> runs the plan as written and draws its required figures;</li>"
        "<li><b>preview</b> first draws the planned figures from pseudo-data, to check the layout;</li>"
        "<li>anything else is a change, for example <i>change the density range to 10-500 kg/m3</i>. "
        "A new version comes back for review, and nothing runs until you approve.</li></ul></div>",
        "<p><b>Question.</b> %s</p>" % _e(plan.get("question") or project.get("question") or ""),
    ]
    if plan.get("hypothesis"):
        body.append("<p><b>Hypothesis.</b> %s</p>" % _e(plan["hypothesis"]))
    if readable:
        body.append(
            "<div class='card'><div class='label'>What changed from v%03d</div><ul>%s</ul></div>"
            % (
                int(summary.get("from_version") or version - 1),
                "".join(
                    "<li>%s%s</li>" % (
                        {"added": "Added ", "removed": "Removed "}.get(item["kind"], ""), _e(item["text"]),
                    )
                    for item in readable
                ),
            )
        )
    used = evidence_the_plan_uses(session, plan)
    checks = things_to_check(plan)
    body += [
        "<h2>What will be run</h2>",
        plan_sheet_html(plan) or "<p class='meta'>No runs are planned.</p>",
    ]
    reproduces = [
        "%s from %s" % (item.get("target_quantity") or item.get("id"),
                        item.get("source_id") or item.get("source_type") or "the paper")
        for item in plan.get("reproduction_targets") or [] if isinstance(item, dict)
    ]
    if reproduces:
        body.append("<p class='meta'>Reproduces: %s.</p>" % _e("; ".join(reproduces)))
    if checks:
        body += ["<h2>Things to check</h2>", _list(checks)]
    body += [
        "<h2>Assumptions</h2>",
        _list(plan.get("assumptions")),
        "<details><summary>Limitations and success criteria</summary><h3>Limitations</h3>%s"
        "<h3>Success criteria</h3>%s</details>" % (_list(plan.get("limitations")), _list(plan.get("success_criteria"))),
    ]
    if used:
        body.append(
            "<details><summary>Paper evidence this plan cites (%d)</summary><ul>%s</ul></details>" % (
                len(used),
                "".join("<li>%s <span class='cite'>%s</span></li>" % (_e(item["statement"]), _e(item["ref"])) for item in used),
            )
        )
    template = research.templates.TEMPLATES[research.templates.choose(project)]
    body.append("<p class='meta'>The report will be written as a <b>%s</b>.</p>" % _e(template["title"]))
    body.append(
        "<footer>Written by PhysEarth-Agent from plan v%03d. Reply <b>protocol</b> in the "
        "Conversation for the generated protocol file.</footer>" % version
    )
    return _page("%s · plan v%03d" % (title, version), "".join(body))


_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.M)


def key_findings(report):
    """The report's own first section, which the reporting guideline makes the conclusion.

    Falls back to the first three paragraphs when the report has no section headings.
    """
    text = str(report or "").replace(agent.SEGMENT_BREAK, "\n\n").strip()
    sections = [m for m in _HEADING.finditer(text) if len(m.group(1)) >= 2]
    if sections:
        start = sections[0].end()
        end = sections[1].start() if len(sections) > 1 else len(text)
        body = text[start:end].strip()
        if body:
            return body
    paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip() and not part.lstrip().startswith("#")]
    return "\n\n".join(paragraphs[:3])


def _image_data(figure):
    for key in ("artifact_image_path", "image_path"):
        path = Path(str(figure.get(key) or ""))
        if path.is_file():
            try:
                return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError:
                continue
    return ""


def _figure_html(figure, number):
    image = _image_data(figure)
    series = figure.get("series") or []
    rows = [
        [_plan_cell(item.get("label")), _plan_cell(item.get("origin") or item.get("source")),
         _plan_cell(item.get("n_points")), "<code>%s</code>" % _e(item.get("handle") or "")]
        for item in series
    ]
    comparisons = [
        [_plan_cell(item.get("of")), _plan_cell(item.get("quantity")), _plan_cell(item.get("bias")),
         _plan_cell(item.get("rmse")), _plan_cell(item.get("r"))]
        for item in figure.get("comparisons") or [] if isinstance(item, dict)
    ]
    return (
        "<figure>%s<figcaption><b>%s</b>%s</figcaption>%s%s</figure>"
        % (
            "<img alt='%s' src='%s'>" % (_e(figure.get("title") or "Figure %d" % number), image) if image else "",
            _e(figure.get("title") or "Figure %d" % number),
            "<br>%s" % _e(figure["subtitle"]) if figure.get("subtitle") else "",
            _plan_table(("Series", "Origin", "Points", "Run"), rows) if rows else "",
            _plan_table(("Compared", "Quantity", "Bias", "RMSE", "r"), comparisons) if comparisons else "",
        )
    )


def report_document(session, report, model_id="", timing=None, gates=None):
    """The full report with its figures, the plan it ran and how long it took.

    `gates` is an optional list of (name, state) pairs for a surface that wants the checks the
    report passed shown at the top; the Studio leaves it out.
    """
    session = session or {}
    project = session.get("research") or {}
    plan = project.get("plan") or {}
    version = int(project.get("plan_version") or 1)
    title = _title(plan, "Research report")
    figures = [
        f for f in session.get("figures") or []
        if not f.get("preview") and not f.get("research_preview")
    ]
    meta = [
        "Plan v%03d" % version,
        time.strftime("%Y-%m-%d %H:%M"),
    ]
    if model_id:
        meta.append(str(model_id))
    if timing:
        meta.append("agent time %s" % timing)
    body = [
        "<h1>%s</h1>" % _e(title),
        "<p class='meta'>%s</p>" % "".join("<span>%s</span>" % _e(item) for item in meta),
        "<p><b>Question.</b> %s</p>" % _e(plan.get("question") or project.get("question") or ""),
    ]
    if gates:
        body.append(
            "<div class='card'><div class='label'>Checks passed</div><ul>%s</ul></div>"
            % "".join("<li><b>%s</b>: %s</li>" % (_e(name), _e(state)) for name, state in gates)
        )
    body.append(
        "<div class='card findings'><div class='label'>Key findings</div>%s</div>"
        % _paragraphs(key_findings(report))
    )
    if figures:
        body.append("<h2>Figures</h2>")
        body += [_figure_html(figure, n) for n, figure in enumerate(figures, 1)]
    body += [
        "<h2>Full report</h2>",
        _paragraphs(str(report or "").replace(agent.SEGMENT_BREAK, "\n\n")),
        "<h2>What was run</h2>",
        plan_sheet_html(plan) or "<p class='meta'>No plan recorded.</p>",
        "<footer>Written by PhysEarth-Agent. Markers such as <span class='cite'>paper#08</span> "
        "name the paper section, model run, dataset or method note each statement rests on; "
        "the session's Evidence panel holds them.</footer>",
    ]
    return _page("%s · report" % title, "".join(body))

# The names other code uses.
escape = _e
markdown = _paragraphs
inline = _inline

"""Portable editable research-plan documents.

The plan dictionary remains the source of truth.  This module only renders that dictionary
to a host-portable Markdown document and converts edits to a validated research-plan patch.
It deliberately does not execute models or approve a plan.
"""

from __future__ import annotations

import hashlib
import json
import re

from physearth import registry
from physearth.research import sheet

SOURCE_LABELS = {
    "paper_explicit": "paper",
    "paper_inferred": "derived",
    "user_specified": "user",
    "backend_default": "model default",
    "model_assumption": "guessed",
}
SOURCE_PROVENANCE = {value: key for key, value in SOURCE_LABELS.items()}
SOURCE_OPTIONS = ("paper", "derived", "user", "model default", "guessed")
_SWEEP_FIELDS = {"sweep_parameter", "sweep_start", "sweep_stop", "sweep_points"}
_REVIEW_FIELDS = {"frequency_ghz", "temperature_k", "stickiness", "sweep_start", "sweep_points"}
_FRIENDLY_PARAMETER_NAMES = {
    "electromagnetic_model": "Electromagnetic theory",
    "microstructure_model": "Microstructure",
    "output": "Scattering-coefficient output",
    "frequency_ghz": "Frequency",
    "angle_deg": "Incidence angle",
    "thickness_m": "Layer thickness",
    "density_kg_m3": "Reference snow density",
    "temperature_k": "Temperature",
    "corr_length_m": "Correlation length",
    "repeat_distance_m": "Repeat distance",
    "radius_m": "Sphere radius",
    "stickiness": "Sticky-sphere parameter",
    "dort_streams": "DORT streams",
    "sweep_parameter": "Sweep variable",
    "sweep_start": "Sweep lower bound",
    "sweep_stop": "Sweep upper bound",
    "sweep_points": "Sweep points",
}
_PARAMETER_COLUMNS = (
    "ID", "Parameter", "Editable value", "Unit", "Source", "Model range", "Evidence", "Review note"
)


def document_hash(document):
    """Return the stable hash used as the optimistic-concurrency guard."""
    return hashlib.sha256(str(document).encode("utf-8")).hexdigest()


def _spec(model, name):
    entry = registry.get(model)
    if not entry:
        return {}
    return (entry.card.get("parameters") or {}).get(name) or {}


def _range(spec):
    if spec.get("enum"):
        return "one of: %s" % ", ".join(str(item) for item in spec["enum"])
    minimum, maximum = spec.get("minimum"), spec.get("maximum")
    if minimum is None and maximum is None:
        return "-"
    if minimum is None:
        text = "≤ %s" % sheet.fmt(maximum)
    elif maximum is None:
        text = "≥ %s" % sheet.fmt(minimum)
    else:
        text = "%s–%s" % (sheet.fmt(minimum), sheet.fmt(maximum))
    unit = sheet.unit_text(spec.get("unit"))
    return "%s%s%s" % (text, " " if unit and unit not in ("°", "%") else "", unit)


def _params(run):
    return run.get("parameters") or run.get("resolved_parameters") or {}


def _same(values):
    if not values:
        return True
    first = values[0]
    return all(sheet._same(first, value) for value in values[1:])


def _source(entries, plan, model, name, runs):
    entries = [item for item in entries if isinstance(item, dict)]
    # Figure 3 explicitly names the theory/microstructure combinations. Keep
    # those rows readable and paper-backed even when the resolved run mapping
    # was stored as a baseline value without a copied evidence marker.
    if name in {"electromagnetic_model", "microstructure_model"} and any(
        "smrt-v1#fig03" in str(ref) or "smrt-v1#fig-fig03" in str(ref)
        for ref in (plan.get("reference_sections") or ())
    ):
        return "paper", "smrt-v1#fig-fig03", "Configuration named in Figure 3."
    if entries:
        labels = [SOURCE_LABELS.get(str(item.get("provenance_class") or ""), "guessed") for item in entries]
        source = labels[0] if len(set(labels)) == 1 else "guessed"
        evidence = next((str(item.get("evidence_ref")) for item in entries if item.get("evidence_ref")), "")
        notes = "; ".join(str(item.get("rationale")) for item in entries if item.get("rationale"))
        return source, evidence, notes
    if runs and all(name in (run.get("defaulted_parameters") or ()) for run in runs):
        return "model default", "", "The registered model supplied this default."
    provenance = (plan.get("condition_provenance") or {}).get(name)
    if provenance:
        text = str(provenance)
        if "#" in text or text.startswith(("paper", "figure", "section")):
            return "paper", text, ""
    return "guessed", "", "No paper or user source is recorded."


def _value_type(value, spec):
    declared = str(spec.get("type") or "").lower()
    if declared in {"integer", "number", "float"}:
        return "number"
    if declared in {"boolean", "bool"}:
        return "boolean"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return "json" if isinstance(value, (dict, list)) else "text"


def _parameter_name(name, spec):
    return _FRIENDLY_PARAMETER_NAMES.get(name) or sheet.named(name, spec)


def parameter_rows(project):
    """Build the editable parameter rows with stable identities."""
    plan = (project or {}).get("plan") or {}
    runs = [run for run in plan.get("runs") or () if isinstance(run, dict)]
    mappings = [item for item in plan.get("parameter_mapping") or () if isinstance(item, dict)]
    by_key = {}
    for item in mappings:
        key = (str(item.get("model") or ""), str(item.get("model_input") or ""))
        if key[1]:
            by_key.setdefault(key, []).append(item)

    keys = list(by_key)
    for run in runs:
        model = str(run.get("model") or "")
        for name in _params(run):
            key = (model, str(name))
            if name not in _SWEEP_FIELDS and key not in keys:
                keys.append(key)

    rows = []
    for model, name in keys:
        model_runs = [run for run in runs if str(run.get("model") or "") == model]
        entries = by_key.get((model, name), [])
        spec = _spec(model, name)
        values = [_params(run).get(name) for run in model_runs if name in _params(run)]
        mapped = entries[0].get("mapped_value") if entries else None
        # A plan-level mapping can carry a baseline value even when the runs
        # intentionally vary this field. Prefer the run values in that case so
        # the document does not display one theory or microstructure as if it
        # applied to every comparison series.
        varies_by_run = len(values) > 1 and not _same(values)
        if varies_by_run:
            pass
        elif mapped is not None:
            values = [mapped]
        elif not values:
            values = [None]
        source, evidence, notes = _source(entries, plan, model, name, model_runs)
        if len(values) > 1 and not _same(values):
            for run in model_runs:
                params = _params(run)
                if name not in params:
                    continue
                rows.append({
                    "row_id": None,
                    "model": model,
                    "model_input": name,
                    "run_ids": [run.get("id")],
                    "parameter": "%s (%s)" % (_parameter_name(name, spec), run.get("label") or run.get("id")),
                    "value_raw": params.get(name),
                    "value": sheet.fmt(params.get(name)),
                    "value_type": _value_type(params.get(name), spec),
                    "unit": sheet.unit_text(spec.get("unit")),
                    "source": source,
                    "card_range": _range(spec),
                    "evidence": evidence,
                    "notes": notes or "Value varies by run.",
                })
            continue
        value = values[0]
        rows.append({
            "row_id": None,
            "model": model,
            "model_input": name,
            "run_ids": [run.get("id") for run in model_runs],
            "parameter": _parameter_name(name, spec),
            "value_raw": value,
            "value": sheet.fmt(value),
            "value_type": _value_type(value, spec),
            "unit": sheet.unit_text(spec.get("unit")),
            "source": source,
            "card_range": _range(spec),
            "evidence": evidence,
            "notes": notes,
        })
    # Keep the visible identity compact.  The model and input keys remain in the
    # structured row, so the short ID is still enough to apply an edit safely and
    # is much easier for a person to scan than ``parameter:smrt:...``.
    for index, row in enumerate(rows, start=1):
        row["row_id"] = "P%02d" % index
    return rows


def _cell(value):
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ").strip()


def markdown(project, session_id=None):
    """Render a portable Markdown editing document from the current plan JSON."""
    project = project or {}
    plan = project.get("plan") or {}
    version = int(project.get("plan_version") or 1)
    title = str(plan.get("title") or plan.get("objective") or "Research plan").strip()
    rows = parameter_rows(project)
    attention = [
        row for row in rows
        if row["model_input"] in _REVIEW_FIELDS
        or (row["source"] == "guessed" and row["model_input"] in _REVIEW_FIELDS)
        or "assumption" in str(row.get("notes") or "").lower()
        or "proxy" in str(row.get("notes") or "").lower()
        or ("not stated" in str(row.get("notes") or "").lower() and row["model_input"] in _REVIEW_FIELDS)
    ]
    lines = [
        "# %s" % title,
        "",
        "<details>",
        "<summary>Technical metadata (leave unchanged)</summary>",
        "",
        "<!-- phys-earth-editable-plan -->",
        "<!-- session_id: %s -->" % (session_id or ""),
        "<!-- plan_version: %d -->" % version,
        "<!-- source_of_truth: plan JSON -->",
        "",
        "</details>",
        "",
        "> **Edit only:** `Editable value`, `Source`, `Evidence`, and `Review note`. Keep `ID`, `Parameter`, `Unit`, and `Model range` unchanged.",
        "> Source is a closed set: `paper`, `derived`, `user`, `model default`, or `guessed`.",
        "> Submit the edited document for validation; edits create a new plan version and require human approval.",
        "",
        "## Review at a glance",
        "",
        "| Item | Status |",
        "| --- | --- |",
        "| Phase | 🟠 `%s` — approval required |" % (project.get("phase") or "plan_review"),
        "| Plan version | `%d` |" % version,
        "| Research question | %s |" % _cell(plan.get("question") or project.get("question") or "-"),
        "",
        "## Attention before approval",
        "",
        "Legend: 🔴 confirm an assumption or guessed value · 🟠 check a backend default · 🟢 supported by the paper.",
        "",
    ]
    if attention:
        lines += [
            "| Priority | ID | Parameter | Current value | Why it needs attention |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in attention:
            priority = "🔴 Confirm" if row["source"] == "guessed" or "assumption" in str(row.get("notes") or "").lower() or "proxy" in str(row.get("notes") or "").lower() else "🟠 Check"
            reason = row.get("notes") or "The model supplies this value; verify it against the paper or user intent."
            lines.append("| %s | %s | %s | %s | %s |" % (
                priority, _cell(row["row_id"]), _cell(row["parameter"]), _cell(row["value"]), _cell(reason)
            ))
    else:
        lines.append("🟢 No parameters currently require special attention.")

    lines += [
        "",
        "## Variable glossary",
        "",
        "Use the human-readable name in the editable table; the backend variable is shown here for traceability.",
        "",
        "| Human-readable name | Backend variable |",
        "| --- | --- |",
        *["| %s | `%s` |" % (label, name) for name, label in _FRIENDLY_PARAMETER_NAMES.items()],
        "",
        "## Editable parameters",
        "",
        "The table below is the machine-validated editing surface. IDs are intentionally short and stable within this plan.",
        "",
        "| %s |" % " | ".join(_PARAMETER_COLUMNS),
        "| %s |" % " | ".join("---" for _ in _PARAMETER_COLUMNS),
    ]
    for row in rows:
        lines.append("| %s |" % " | ".join(_cell(row[key]) for key in (
            "row_id", "parameter", "value", "unit", "source", "card_range", "evidence", "notes"
        )))
    if not rows:
        lines.append("| - | - | - | - | guessed | - | - | No parameters are currently planned. |")

    lines += ["", "## Runs", "", "| Row ID | Run | Model | Stage | Parameters | Figures |", "| --- | --- | --- | --- | --- | --- |"]
    charts = [item for item in plan.get("charts") or () if isinstance(item, dict)]
    for run in plan.get("runs") or ():
        if not isinstance(run, dict):
            continue
        feeds = [str(chart.get("id")) for chart in charts if str(run.get("id")) in (chart.get("runs") or [])]
        lines.append("| %s | %s | %s | %s | `%s` | %s |" % (
            _cell("run:%s" % run.get("id")), _cell(run.get("label") or run.get("id")),
            _cell(run.get("model")), _cell(run.get("stage") or ""),
            _cell(json.dumps(_params(run), ensure_ascii=False, sort_keys=True)), _cell(", ".join(feeds) or "-"),
        ))
    lines += ["", "## Figures", "", "| Row ID | Figure | X | Y | Required | Purpose |", "| --- | --- | --- | --- | --- | --- |"]
    for chart in charts:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            _cell("chart:%s" % chart.get("id")), _cell(chart.get("label") or chart.get("id")),
            _cell(chart.get("x")), _cell(", ".join(chart.get("ys") or [chart.get("y")]) ),
            _cell("yes" if chart.get("required", True) else "no"), _cell(chart.get("purpose") or ""),
        ))
    lines += ["", "## Assumptions and limitations", ""]
    for label, key in (("Assumption", "assumptions"), ("Limitation", "limitations"), ("Success criterion", "success_criteria")):
        for item in plan.get(key) or ():
            lines.append("- **%s:** %s" % (label, _cell(item)))
    return "\n".join(lines).rstrip() + "\n"


def _split_row(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells, current, escaped = [], [], False
    for char in text:
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
            continue
        if char == "\\" and not escaped:
            escaped = True
            continue
        current.append(char)
        escaped = False
    cells.append("".join(current).strip())
    return cells


def _table(document):
    match = re.search(r"(?ms)^## (?:Editable )?parameters\s*\n(.*?)(?=^## |\Z)", str(document), re.IGNORECASE)
    if not match:
        raise ValueError("The editable document is missing the Parameters table.")
    lines = [line for line in match.group(1).splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        raise ValueError("The Parameters table is empty.")
    header = _split_row(lines[0])
    expected = list(_PARAMETER_COLUMNS)
    if header != expected:
        raise ValueError("The Parameters table columns or order changed; restore the generated header.")
    rows = []
    for line in lines[2:]:
        cells = _split_row(line)
        if len(cells) != len(expected) or all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(dict(zip(expected, cells)))
    return rows


def _unmark(value):
    value = str(value or "").strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.replace("\\|", "|")


def _coerce(value, row):
    value = _unmark(value)
    if value in ("", "-"):
        return None
    if value == "varies by run":
        raise ValueError("%s has different values by run; edit its run-specific rows instead." % row["ID"])
    kind = row.get("_value_type")
    if kind == "boolean":
        lowered = value.lower()
        if lowered in ("yes", "true", "1"):
            return True
        if lowered in ("no", "false", "0"):
            return False
        raise ValueError("%s must be yes/no." % row["ID"])
    if kind == "number":
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError("%s must contain a number." % row["ID"]) from exc
        return int(number) if number.is_integer() else number
    if kind == "json":
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("%s must contain valid JSON." % row["ID"]) from exc
    return value


def changes(project, document):
    """Convert an edited Markdown document to a ``research_plan`` revision patch."""
    current = {row["row_id"]: row for row in parameter_rows(project)}
    if not current:
        return {}
    edited = _table(document)
    seen = {_unmark(row.get("ID")) for row in edited}
    if seen != set(current):
        missing = sorted(set(current) - seen)
        extra = sorted(seen - set(current))
        detail = []
        if missing:
            detail.append("missing row ids: %s" % ", ".join(missing))
        if extra:
            detail.append("unknown row ids: %s" % ", ".join(extra))
        raise ValueError("The editable document changed its stable rows (%s)." % "; ".join(detail))

    mapping_patches, run_patches = [], {}
    for raw in edited:
        row_id = _unmark(raw.get("ID"))
        old = current[row_id]
        old_display = {
            "Parameter": old["parameter"],
            "Unit": old["unit"] or "-",
            "Model range": old["card_range"],
            "Editable value": old["value"],
            "Source": old["source"],
            "Evidence": old["evidence"] or "-",
            "Review note": old["notes"] or "-",
        }
        for field in ("Parameter", "Unit", "Model range"):
            if _unmark(raw.get(field)) != str(old_display[field]):
                raise ValueError("%s is read-only for row %s." % (field, row_id))
        normalized = {key: _unmark(value) for key, value in raw.items()}
        if all(normalized[key] == str(old_display[key]) for key in ("Editable value", "Source", "Evidence", "Review note")):
            continue
        source = normalized["Source"].lower()
        if source not in SOURCE_PROVENANCE:
            raise ValueError("Source for %s must be one of: %s." % (row_id, ", ".join(SOURCE_OPTIONS)))
        typed = _coerce(normalized["Editable value"], {**old, "_value_type": old["value_type"]})
        mapping_patches.append({
            "model": old["model"],
            "model_input": old["model_input"],
            "mapped_value": typed,
            "provenance_class": SOURCE_PROVENANCE[source],
            "evidence_ref": normalized["Evidence"] if normalized["Evidence"] != "-" else "",
            "rationale": normalized["Review note"] if normalized["Review note"] != "-" else "",
        })
        if normalized["Editable value"] != str(old["value"]):
            for run_id in old["run_ids"]:
                run_patches.setdefault(run_id, {"id": run_id, "parameters": {}})
                run_patches[run_id]["parameters"][old["model_input"]] = typed
    patch = {}
    if mapping_patches:
        patch["parameter_mapping"] = mapping_patches
    if run_patches:
        patch["runs"] = list(run_patches.values())
    return patch

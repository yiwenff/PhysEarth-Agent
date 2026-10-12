"""Pages a person keeps: the research plan and the final report, as standalone HTML.

The Conversation panel is narrow and lives as long as the session. A plan someone wants
to read properly, and a report they want to keep or send, are written out as one HTML
file each -- styles inline, figures embedded -- under the session's project directory,
where the Studio serves them. The pages are rendered by `physearth.documents`, the same
code the MCP server uses, so a plugin user and a Studio user read the same plan and report;
what stays here is serving the files.
"""

from pathlib import Path
from urllib.parse import quote

from physearth.api import artifacts, documents, research


def file_url(path):
    """How the Studio serves a file under its state directory."""
    return "/gradio_api/file=%s" % quote(str(Path(path).resolve()), safe="/")


def _export_dir(session):
    path = artifacts.project_dir(session.get("id") or "shared") / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------------- plan


def write_protocol(session):
    """The generated protocol, written only when someone asks for it. Returns (url, name)."""
    project = (session or {}).get("research") or {}
    if not project.get("plan"):
        return "", ""
    version = int(project.get("plan_version") or 1)
    name = "research-protocol-v%03d.yaml" % version
    try:
        path = _export_dir(session) / name
        path.write_text(research.protocol_yaml(project), encoding="utf-8")
    except (OSError, ValueError):
        return "", ""
    return file_url(path), name


def ensure_plan_export(session):
    """Write the current plan version once and remember where it is. Returns its URL."""
    project = (session or {}).get("research") or {}
    if not project.get("plan"):
        return ""
    version = int(project.get("plan_version") or 1)
    saved = project.get("plan_export") or {}
    if saved.get("version") == version and saved.get("url") and Path(saved.get("path", "")).is_file():
        return saved["url"]
    try:
        path = _export_dir(session) / ("research-plan-v%03d.html" % version)
        path.write_text(plan_document(session), encoding="utf-8")
    except (OSError, ValueError):
        return ""
    project["plan_export"] = {"version": version, "path": str(path), "url": file_url(path)}
    return project["plan_export"]["url"]


# ----------------------------------------------------------------------- report


def write_report(session, report, model_id="", timing=None):
    """Write the report page for the current plan version. Returns its URL, or ""."""
    project = (session or {}).get("research") or {}
    version = int(project.get("plan_version") or 1)
    try:
        path = _export_dir(session) / ("research-report-v%03d.html" % version)
        path.write_text(report_document(session, report, model_id, timing), encoding="utf-8")
    except (OSError, ValueError):
        return ""
    project["report_export"] = {"version": version, "path": str(path), "url": file_url(path)}
    return project["report_export"]["url"]

plan_document = documents.plan_document
report_document = documents.report_document
key_findings = documents.key_findings
_title = documents._title

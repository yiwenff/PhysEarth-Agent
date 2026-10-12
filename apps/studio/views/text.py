"""Every pixel of the interface, as plain strings.

Nothing here imports Gradio, so all of it is testable without a browser. Every value
that reaches the page goes through `html.escape` first: literature text, dataset rows
and model output are all untrusted input on a public deployment.

This module is the bottom of that: escaping, icons, citation markers, prose.
"""

from physearth.api import agent, documents

SECTION_PREVIEW_CHARS = 620


ICONS = {
    "chat": "<path d='M21 11.5a8.4 8.4 0 0 1-9 8.4 9.9 9.9 0 0 1-4.2-.9L3 20.5l1.5-4.4A8.4 8.4 "
    "0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z'/>",
    "trace": "<path d='M4 20V10M10 20V4M16 20v-7M22 20H2'/>",
    "figure": "<path d='M3 3v18h18'/><path d='M6 15l4-5 3 3 5-7'/>",
    "sources": "<path d='M4 4.5A1.5 1.5 0 0 1 5.5 3H19v18H5.5A1.5 1.5 0 0 1 4 19.5z'/>"
    "<path d='M8 7.5h7M8 11h7'/>",
    "models": "<path d='M12 2.5l8 4.5v9l-8 4.5-8-4.5v-9z'/><path d='M12 11.5l8-4.5M12 11.5v9"
    "M12 11.5L4 7'/>",
    "check": "<path d='M4 12.5l5.2 5.2L20 7'/>",
    "block": "<circle cx='12' cy='12' r='9'/><path d='M6 6l12 12'/>",
}


def _svg(name, cls):
    return (
        "<svg class='%s' viewBox='0 0 24 24' fill='none' stroke='currentColor' "
        "stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round'>%s</svg>"
        % (cls, ICONS[name])
    )


def _mono(value):
    return "<span class='mono'>%s</span>" % _e(value)


def answer_html(text, running=False):
    """Escape first, then apply a deliberately small markdown subset.

    A turn can hold several stretches of prose, one before each round of tool calls. They
    arrive separated by the agent's segment break and are drawn as successive blocks, so a
    later thought lands underneath the earlier one instead of replacing it.
    """
    text = text or ""
    if not text.strip():
        return "<p class='hint'>Waiting for the first token.</p>" if running else ""
    segments = [part for part in text.split(agent.SEGMENT_BREAK) if part.strip()]
    body = "".join(
        "<div class='seg%s'>%s</div>"
        % (" seg--later" if n else "", _paragraphs(part))
        for n, part in enumerate(segments)
    )
    if running:
        body += "<span class='caret'></span>"
    return body

# Rendered once, in the package, so the Studio and the MCP server draw the same pages.
ABS_CITE = documents.ABS_CITE
BOLD = documents.BOLD
CITE = documents.CITE
CODE = documents.CODE
DATA_CITE = documents.DATA_CITE
MODEL_CITE = documents.MODEL_CITE
SAFE_SUB = documents.SAFE_SUB
SKILL_CITE = documents.SKILL_CITE
TABLE_RULE = documents.TABLE_RULE
_cells = documents._cells
_e = documents._e
_inline = documents._inline
_is_table = documents._is_table
_markers = documents._markers
_paragraphs = documents._paragraphs
_table = documents._table

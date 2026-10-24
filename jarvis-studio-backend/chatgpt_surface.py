"""Conservative ChatGPT desktop target detection for the task router.

Only prefer the installed Windows app when a task explicitly addresses ChatGPT.
Never inspect windows or launch apps here; the passed lookup is the existing
installed-app index and may fail. This module is free of third-party imports.
"""

from __future__ import annotations

import re
from typing import Callable

_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|\'[^\'\n]*\'')
_ADDRESSED = re.compile(
    r"\b(?:open|launch|start|use|ask|tell|abre|abrir|usa|usar|"
    r"dile|pregunta|preguntale|pregúntale|consulta|consultar|"
    r"habla\s+con|speak\s+to|talk\s+to)\s+"
    r"(?:(?:a|al|to|the|la|el|app|aplicacion|aplicación|de)\s+){0,4}"
    r"chatgpt\b",
    re.IGNORECASE,
)
_EXPLICIT_BROWSER = re.compile(
    r"\b(?:en|desde|por|mediante|usando)\s+(?:(?:el|un|la)\s+)?"
    r"(?:navegador|browser|chrome|edge|firefox)\b",
    re.IGNORECASE,
)


def explicit_browser_requested(goal: str) -> bool:
    """Recognize common Spanish browser requests alongside the English router."""
    return bool(_EXPLICIT_BROWSER.search(_QUOTED.sub(' ', goal or '')))


def installed_chatgpt_target(goal: str, lookup: Callable[[str], str]) -> str:
    """Return installed ChatGPT display name for an explicit app-directed task.

    Empty string means defer to existing browser/model routing. A broken app index
    must never claim the desktop app exists or crash the whole router.
    """
    unquoted = _QUOTED.sub(' ', goal or '')
    if not _ADDRESSED.search(unquoted):
        return ''
    try:
        return str(lookup('ChatGPT') or '')
    except Exception:
        return ''

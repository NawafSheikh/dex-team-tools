"""Settings for the workday orchestrator, read from the environment (see .env.example).

Nothing here is a secret. Keys live only in the environment of the process that runs the server.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Public base URL of this server, used to build board and file links for Copilot Studio.
PUBLIC_BASE = _env("WORKDAY_PUBLIC_BASE", "http://127.0.0.1:8091").rstrip("/")
# Input files copied into every new run's inbox/ (for example the output of fixtures/make_fixtures.py).
INBOX = Path(_env("WORKDAY_INBOX", "inbox"))
# Python that workers and the judge use for pandas, openpyxl, python-pptx and python-docx.
PYTHON = _env("WORKDAY_PYTHON", "python3")
# Folder holding notes_truth.json, the answer key the notes verifier checks against (fixtures/make_fixtures.py).
TRUTH_DIR = Path(_env("WORKDAY_TRUTH_DIR", "truth"))

# Power Platform missions (pp_tables, pp_app, pp_flows). Leave empty if you only run file missions.
DV = _env("WORKDAY_DV", "dv")  # the tools/dv.js helper, installed on PATH
PP_ENV_ID = _env("WORKDAY_PP_ENV_ID")  # Power Platform environment id
PP_LOGIN_HINT = _env("WORKDAY_PP_LOGIN_HINT")  # account the canvas MCP signs in with
# Canvas app ids that missions must never open or edit (comma separated), e.g. an existing app with a similar name.
PROTECTED_APP_IDS = [x.strip() for x in _env("WORKDAY_PROTECTED_APP_IDS").split(",") if x.strip()]
# Microsoft's canvas-apps skill references (github.com/microsoft/power-platform-skills), read by the canvas worker.
CANVAS_SKILLS = _env("WORKDAY_CANVAS_SKILLS", "canvas-skills/references")
# Shared folder for canvas YAML: as the worker sees it, and as the canvas MCP sees it (may differ in a container).
CANVAS_DIR_HOST = _env("WORKDAY_CANVAS_DIR_HOST", "canvas")
CANVAS_DIR_MCP = _env("WORKDAY_CANVAS_DIR_MCP", CANVAS_DIR_HOST)

# Optional lock for a shared screen ("desk"). A command called as `<cmd> try|release "<run> <mission>"`;
# exit code 0 means acquired or released. Empty: the desk is always free.
DESK_LOCK_CMD = _env("WORKDAY_DESK_LOCK_CMD")


def power_apps_url(action: str) -> str:
    return f"https://make.powerapps.com/e/{PP_ENV_ID or '<environment id>'}/canvas/?{action}"

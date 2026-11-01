"""Shared helpers for mission verifiers."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path


def check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def result(checks: list[dict], facts: dict | None = None, outputs: dict | None = None) -> dict:
    return {
        "passed": bool(checks) and all(c["ok"] for c in checks),
        "checks": checks,
        "facts": facts or {},
        "outputs": outputs or {},
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hashes(paths) -> dict[str, str]:
    return {sha(Path(p).read_bytes()): str(p) for p in paths if Path(p).is_file()}


def soffice_pdf_pages(path: Path) -> int | None:
    """Convert an Office file to PDF with LibreOffice and count its pages. None if it does not open."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profile"
        try:
            proc = subprocess.run(
                [exe, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                 "--outdir", tmp, str(path)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return None
        pdf = Path(tmp) / (path.stem + ".pdf")
        if proc.returncode != 0 or not pdf.exists():
            return None
        data = pdf.read_bytes()
        return max(data.count(b"/Type /Page") - data.count(b"/Type /Pages"),
                   data.count(b"/Type/Page") - data.count(b"/Type/Pages"))

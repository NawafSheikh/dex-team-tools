"""The in-sandbox operations module, run against a temporary workspace (no Docker needed)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "sandbox"))


@pytest.fixture()
def op(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVTOOLS_WORK", str(tmp_path))
    monkeypatch.setenv("DEVTOOLS_PROCS", str(tmp_path / ".procs"))
    import op as module
    return importlib.reload(module)


def test_multi_edit_restores_every_file_when_a_write_fails(op, tmp_path, monkeypatch):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("alpha\n", encoding="utf-8")
    b.write_text("beta\n", encoding="utf-8")
    real_write = Path.write_text

    def flaky(self, text, *args, **kwargs):
        if self.name == "b.txt":
            real_write(self, "", *args, **kwargs)  # truncates, then fails, like a full disk
            raise OSError("No space left on device")
        return real_write(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(op.OpError):
        op.op_multi_edit({"edits": [
            {"path": "a.txt", "old_string": "alpha", "new_string": "ALPHA"},
            {"path": "b.txt", "old_string": "beta", "new_string": "BETA"}]})
    monkeypatch.undo()
    assert a.read_text(encoding="utf-8") == "alpha\n"
    assert b.read_text(encoding="utf-8") == "beta\n"

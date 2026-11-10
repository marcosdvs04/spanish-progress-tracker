"""Architecture tests — the controls that must hold continuously.

These are the lint rules the Solution Design Report promises: a build-time check
that the allowed-interaction matrix (§7.3) is still true of the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "progress_tracker"

#: Only the gateway package may reach the network (C-06).
NETWORK_MODULES = {
    "httpx", "requests", "urllib.request", "urllib3", "http.client",
    "aiohttp", "socket", "ftplib",
}

#: Nothing anywhere may be able to transmit to a person (C-16).
TRANSMISSION_MODULES = {
    "smtplib", "email.message", "slack_sdk", "twilio", "sendgrid",
    "boto3", "telegram", "discord",
}

ALLOWED_NETWORK_FILES = {"gateway/anthropic_adapter.py"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in str(p))


def test_only_the_gateway_may_import_an_http_client():
    """C-06, enforced continuously rather than asserted once in a document."""
    offenders = []
    for path in _python_files():
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED_NETWORK_FILES:
            continue
        hit = _imports(path) & NETWORK_MODULES
        if hit:
            offenders.append(f"{rel}: {sorted(hit)}")
    assert not offenders, f"network access outside the gateway: {offenders}"


def test_no_component_can_transmit_anything_to_anyone():
    """C-16: the absence of the capability IS the control."""
    offenders = []
    for path in _python_files():
        hit = _imports(path) & TRANSMISSION_MODULES
        if hit:
            offenders.append(f"{path.relative_to(SRC).as_posix()}: {sorted(hit)}")
    assert not offenders, f"transmission capability found: {offenders}"


def test_the_lint_rule_catches_a_seeded_violation(tmp_path):
    """A control that cannot fail is not a control."""
    planted = tmp_path / "bad_component.py"
    planted.write_text("import requests\n\ndef go():\n    requests.get('http://x')\n")
    assert _imports(planted) & NETWORK_MODULES == {"requests"}

    planted_mail = tmp_path / "bad_mail.py"
    planted_mail.write_text("import smtplib\n")
    assert _imports(planted_mail) & TRANSMISSION_MODULES == {"smtplib"}


def test_only_the_export_service_writes_to_the_validated_store():
    """C-19: the candidate/validated split is structural."""
    offenders = []
    for path in _python_files():
        rel = path.relative_to(SRC).as_posix()
        if rel in {"store.py", "services/export.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "validated.promote(" in text:
            offenders.append(rel)
    assert not offenders, f"unexpected writer to the validated store: {offenders}"


def test_the_audit_repository_exposes_no_way_to_rewrite_history():
    """C-09 at the API level; the database triggers are tested in P2."""
    from progress_tracker.store import AuditRepo

    public = {name for name in dir(AuditRepo) if not name.startswith("_")}
    assert public == {"append", "for_record", "all"}, public


def test_every_state_has_a_defined_set_of_transitions():
    from progress_tracker.states import TRANSITIONS, RecordStatus

    assert set(TRANSITIONS) == set(RecordStatus), \
        "every state must declare where it can go, including nowhere"


def test_exported_is_terminal_and_only_approved_can_reach_it():
    from progress_tracker.states import EXPORTABLE, TRANSITIONS, RecordStatus

    assert TRANSITIONS[RecordStatus.EXPORTED] == set()
    sources = {s for s, targets in TRANSITIONS.items() if RecordStatus.EXPORTED in targets}
    assert sources == {RecordStatus.APPROVED}
    assert EXPORTABLE == {RecordStatus.APPROVED, RecordStatus.EXPORTED}


@pytest.mark.parametrize("module", [
    "intake", "guard", "extraction", "patterns", "composition",
    "validator", "review", "export", "orchestrator",
])
def test_every_component_in_the_report_exists_as_a_module(module):
    assert (SRC / "services" / f"{module}.py").exists()

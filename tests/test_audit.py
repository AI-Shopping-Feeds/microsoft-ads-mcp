"""Audit log: redaction, retention, purge and permissions."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from microsoft_ads_mcp.audit import DAY, AuditLog
from microsoft_ads_mcp.auth import register_secret

from .conftest import audit_entries


def test_record_find_tail_and_redaction(tmp_path: Path) -> None:
    register_secret("audit-secret-value-123")
    log = AuditLog(tmp_path / "logs" / "audit.jsonl")
    aid = log.record(
        op="update_campaigns",
        method="PUT",
        url="https://campaign.api.bingads.microsoft.com/x",
        customer_id="1",
        account_id="2",
        request_body={"note": "audit-secret-value-123", "refresh_token": "abc"},
        before=[{"Id": "9"}],
    )
    entry = log.find(aid)
    assert entry is not None
    assert entry["request_body"] == {"note": "***", "refresh_token": "***"}
    assert entry["before"] == [{"Id": "9"}]
    assert log.tail(5)[-1]["audit_id"] == aid
    if os.name == "posix":
        assert stat.S_IMODE(log.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(log.path.parent.stat().st_mode) == 0o700


def test_prune_drops_old_entries(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", retention_days=30)
    old = log.record(op="old", method="PUT", url="u")
    new = log.record(op="new", method="PUT", url="u")
    removed = log.prune(now=time.time() + 29 * DAY)
    assert removed == 0
    lines = audit_entries(log.path)
    lines[0]["ts"] -= 40 * DAY
    log.path.write_text("\n".join(json.dumps(e) for e in lines) + "\n")
    assert log.prune() == 1
    assert [e["audit_id"] for e in log.entries()] == [new]
    assert log.find(old) is None


def test_zero_retention_keeps_everything(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", retention_days=0)
    log.record(op="x", method="PUT", url="u")
    assert log.prune(now=time.time() + 1000 * DAY) == 0


def test_purge(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    assert log.purge() is False
    log.record(op="x", method="PUT", url="u")
    assert log.purge() is True
    assert not log.path.exists()

"""Tests for agent/secret_scanner.py — credential detection + redaction."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ── Detection: built-in rules ───────────────────────────────────


def test_detects_openai_key():
    from agent.secret_scanner import SecretCategory, scan_text

    text = "Authorization header: sk-abcdefghijklmnopqrstuvwxyz1234567890"
    r = scan_text(text)
    assert r.has_findings
    cats = r.categories
    assert SecretCategory.OPENAI_API_KEY.value in cats


def test_detects_anthropic_key():
    from agent.secret_scanner import SecretCategory, scan_text

    r = scan_text("sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890")
    assert SecretCategory.ANTHROPIC_API_KEY.value in r.categories


def test_detects_github_personal_token():
    from agent.secret_scanner import SecretCategory, scan_text

    # ghp_ + 36 alphanumeric chars
    r = scan_text("ghp_" + "a" * 36)
    assert SecretCategory.GITHUB_TOKEN.value in r.categories


def test_detects_github_fine_grained_pat():
    from agent.secret_scanner import SecretCategory, scan_text

    r = scan_text("github_pat_" + "A1b2C3d4" * 8)
    assert SecretCategory.GITHUB_TOKEN.value in r.categories


def test_detects_aws_access_key():
    from agent.secret_scanner import SecretCategory, scan_text

    r = scan_text("AKIAIOSFODNN7EXAMPLE")
    assert SecretCategory.AWS_ACCESS_KEY.value in r.categories


def test_detects_stripe_live():
    from agent.secret_scanner import SecretCategory, scan_text

    r = scan_text("sk_live_" + "x" * 24)
    assert SecretCategory.STRIPE_KEY.value in r.categories


def test_detects_google_api_key():
    from agent.secret_scanner import SecretCategory, scan_text

    # Google API keys: AIza + 35 chars → 39 total.
    key = "AIza" + "SyA" + "x" * 32
    assert len(key) == 39
    r = scan_text(key)
    assert SecretCategory.GOOGLE_API_KEY.value in r.categories


def test_detects_private_key_block():
    from agent.secret_scanner import SecretCategory, scan_text

    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF5PBbGPhqUg\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    r = scan_text(text)
    assert SecretCategory.PRIVATE_KEY.value in r.categories


def test_detects_jwt():
    from agent.secret_scanner import SecretCategory, scan_text

    # Hand-crafted three-segment JWT.
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    r = scan_text(jwt)
    assert SecretCategory.JWT.value in r.categories


def test_detects_password_assignment_low_severity():
    from agent.secret_scanner import SecretSeverity, scan_text

    r = scan_text("database password=hunter2hunter2 in config")
    # Low severity by default — should still be reported.
    low_sev = [f for f in r.findings if f.severity == SecretSeverity.LOW]
    assert low_sev


def test_detects_bearer_token():
    from agent.secret_scanner import SecretSeverity, scan_text

    bearer = (
        "Authorization: Bearer "
        "ya29.a0AfH6SMBxx-fake-but-long-enough-token-value-1234567890"
    )
    r = scan_text(bearer)
    low_sev = [f for f in r.findings if f.severity == SecretSeverity.LOW]
    assert low_sev


# ── Severity ordering ────────────────────────────────────────────


def test_critical_outranks_high_in_findings():
    from agent.secret_scanner import SecretScanner

    text = "-----BEGIN PRIVATE KEY-----\nfoo\n-----END PRIVATE KEY-----\n" "ak=" + "sk-" + "a" * 30
    r = SecretScanner().scan(text)
    # First finding should be the private key (CRITICAL).
    assert r.findings
    assert r.findings[0].category.value == "private_key"


# ── Redaction ────────────────────────────────────────────────────


def test_redact_replaces_openai_key():
    from agent.secret_scanner import SecretScanner

    s = SecretScanner()
    redacted = s.redact("here is sk-abcdefghijklmnopqrstuvwxyz1234567890 end")
    assert "sk-abcdef" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_preserves_known_safe_substring():
    """Allow-list literal must NOT be redacted."""
    from agent.secret_scanner import SecretScanner

    safe = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    s = SecretScanner(allow_list=[safe])
    out = s.redact("token: " + safe)
    assert safe in out
    assert "[REDACTED]" not in out


def test_redact_low_severity_left_intact_by_default():
    """``auto_redact=False`` rules (LOW) are not auto-redacted."""
    from agent.secret_scanner import SecretScanner

    s = SecretScanner()
    out = s.redact("password=hunter2hunter2abc")
    assert "hunter2hunter2abc" in out


def test_scan_and_redact_returns_both():
    from agent.secret_scanner import SecretScanner

    s = SecretScanner()
    text = "sk-abcdefghijklmnopqrstuvwxyz1234567890 and password=hunter2hunter2abc"
    r = s.scan_and_redact(text)
    assert r.has_findings
    assert r.redacted_text is not None
    # HIGH-severity finding IS redacted.
    assert "sk-abcdef" not in r.redacted_text
    # LOW-severity finding is reported but NOT redacted (auto_redact=False).
    password_findings = [
        f for f in r.findings if f.category.value == "password_assignment"
    ]
    assert password_findings, "expected a password_assignment finding"
    # The raw value survives in the redacted output.
    assert "hunter2hunter2abc" in r.redacted_text


# ── Allow-list ───────────────────────────────────────────────────


def test_add_allow_at_runtime():
    from agent.secret_scanner import SecretScanner

    safe = "sk-zzz1234567890abcdefghij"
    s = SecretScanner()
    s.add_allow(safe)
    r = s.scan("token is " + safe)
    # No findings for the allow-listed literal.
    assert not r.findings


# ── Custom rule ──────────────────────────────────────────────────


def test_custom_rule_can_be_added():
    from agent.secret_scanner import (
        SecretCategory,
        SecretRule,
        SecretScanner,
        SecretSeverity,
    )

    rule = SecretRule(
        category=SecretCategory.GENERIC_API_KEY,
        severity=SecretSeverity.MEDIUM,
        pattern=__import__("re").compile(r"X-API-TOKEN-[A-Z]{10}"),
        description="custom internal token",
        auto_redact=True,
    )
    s = SecretScanner(extra_rules=[rule])
    r = s.scan("header X-API-TOKEN-ABCDEFGHIJ")
    assert r.has_findings
    assert any(f.description == "custom internal token" for f in r.findings)


# ── min_severity ─────────────────────────────────────────────────


def test_min_severity_filters_lower():
    from agent.secret_scanner import SecretScanner, SecretSeverity

    text = (
        "sk-abcdefghijklmnopqrstuvwxyz1234567890 "  # HIGH
        "password=hunter2hunter2abc"               # LOW
    )
    only_high = SecretScanner(min_severity=SecretSeverity.HIGH).scan(text)
    assert only_high.has_findings
    assert all(f.severity != SecretSeverity.LOW for f in only_high.findings)


# ── Sampling ─────────────────────────────────────────────────────


def test_sample_masks_middle():
    from agent.secret_scanner import SecretScanner

    s = SecretScanner()
    r = s.scan("sk-abcdefghijklmnopqrstuvwxyz1234567890")
    assert r.findings
    sample = r.findings[0].sample
    # Format is "<first 4>…<last 4>" — ellipsis in the middle.
    assert sample.startswith("sk-a")
    assert sample.endswith("7890")
    assert "…" in sample
    # Middle content must NOT be in the sample.
    assert "abcdefghijklmnopqrstuvwxyz" not in sample


# ── Empty / safe inputs ──────────────────────────────────────────


def test_empty_text_has_no_findings():
    from agent.secret_scanner import scan_text

    assert not scan_text("").has_findings
    assert not scan_text(None or "hello world").has_findings  # benign prose


def test_benign_prose_has_no_high_findings():
    from agent.secret_scanner import SecretScanner, SecretSeverity

    text = "The quick brown fox jumps over the lazy dog."
    r = SecretScanner().scan(text)
    assert all(f.severity != SecretSeverity.HIGH for f in r.findings)
    assert all(f.severity != SecretSeverity.CRITICAL for f in r.findings)


# ── Integration: utils.redact_secrets ───────────────────────────


def test_utils_redact_secrets_delegates_to_scanner():
    from agent.secret_scanner import scan_text

    text = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    from utils import redact_secrets

    redacted = redact_secrets(text)
    # Either the scanner redacts it (modern path) or the regex
    # fallback does — both remove the literal.
    assert "sk-abcdef" not in redacted
    # Sanity: scanner sees it.
    assert scan_text(text).has_findings


# ── Stats helper ─────────────────────────────────────────────────


def test_by_severity_counts():
    from agent.secret_scanner import SecretScanner

    text = (
        "AKIAIOSFODNN7EXAMPLE "                  # CRITICAL
        "sk-abcdefghijklmnopqrstuvwxyz1234567890 "  # HIGH
        "eyJhbGc.eyJzdWI.signature"              # MEDIUM
    )
    r = SecretScanner().scan(text)
    counts = r.by_severity
    assert counts["critical"] >= 1
    assert counts["high"] >= 1
    assert counts["medium"] >= 1

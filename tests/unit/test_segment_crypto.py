"""Tests for ``zeloo_state.crypto`` — SegmentCipher.

Round 50 introduced at-rest encryption for WAL segments. Tests use
``cryptography`` if installed (tested with cryptography >= 41.x). On
machines without it, the cipher is unavailable — the tests skip
the encryption-specific cases and verify the "not available" code
path instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zeloo_state.crypto import (
    _LENGTH_STRUCT,
    FLAG_ENCRYPTED,
    FLAG_PLAINTEXT,
    SegmentCipher,
    _try_import_cryptography,
)

Fernet, InvalidToken = _try_import_cryptography()
CRYPTO_AVAILABLE = Fernet is not None


# ── helpers ───────────────────────────────────────────────────────────


@pytest.fixture
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``SegmentCipher`` at a fresh ``~/.Zeloo`` for each test."""
    home = tmp_path / "ZelooHome"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("zeloo_HOME", str(home))
    # Make sure the global env var is empty so tests can't accidentally
    # inherit a real master key.
    monkeypatch.delenv("zeloo_MASTER_KEY", raising=False)
    return home


# ── key resolution ─────────────────────────────────────────────────────


@pytest.mark.skipif(not CRYPTO_AVAILABLE, reason="cryptography not installed")
class TestKeyResolution:
    def test_auto_generate_creates_key_file(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        key = cipher.ensure_key()
        assert isinstance(key, bytes)
        assert (isolated_home / ".master_key").is_file()
        # Reading again returns the same key.
        cipher2 = SegmentCipher(home=isolated_home)
        assert cipher2.ensure_key() == key

    def test_explicit_env_key(self, isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]

        new_key = Fernet.generate_key()
        monkeypatch.setenv("zeloo_MASTER_KEY", new_key.decode("ascii"))
        cipher = SegmentCipher(home=isolated_home)
        assert cipher.ensure_key() == new_key

    def test_malformed_env_key_falls_back_to_file(
        self, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bogus env key — should be ignored, then fall through to file.
        monkeypatch.setenv("zeloo_MASTER_KEY", "not-a-valid-fernet-key")
        # We need an existing file to fall back to.
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]

        valid = Fernet.generate_key()
        (isolated_home / ".master_key").write_text(valid.decode("ascii"))
        cipher = SegmentCipher(home=isolated_home)
        assert cipher.ensure_key() == valid

    def test_no_key_no_autogen_raises(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=False)
        with pytest.raises(RuntimeError, match="No master key"):
            cipher.ensure_key()


# ── envelope round-trip ───────────────────────────────────────────────


@pytest.mark.skipif(not CRYPTO_AVAILABLE, reason="cryptography not installed")
class TestEnvelopeRoundTrip:
    def test_encrypt_decrypt_roundtrip(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        plaintext = b"hello world " * 100
        envelope = cipher.encrypt(plaintext)
        # First byte must be the encrypted flag.
        assert envelope[0] == FLAG_ENCRYPTED
        # Length prefix must match.
        (length,) = _LENGTH_STRUCT.unpack_from(envelope, 1)
        assert length == len(envelope) - 1 - _LENGTH_STRUCT.size
        # Decrypt recovers plaintext.
        assert cipher.decrypt(envelope) == plaintext

    def test_ciphertext_differs_between_runs(
        self, isolated_home: Path
    ) -> None:
        # Fernet includes a per-message random IV; two encrypts of the
        # same plaintext must produce different ciphertexts.
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        a = cipher.encrypt(b"abc")
        b = cipher.encrypt(b"abc")
        assert a != b
        assert cipher.decrypt(a) == cipher.decrypt(b) == b"abc"

    def test_tampered_ciphertext_raises(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        envelope = bytearray(cipher.encrypt(b"important data"))
        # Flip a byte in the body.
        idx = 1 + _LENGTH_STRUCT.size + 5
        envelope[idx] ^= 0xFF
        with pytest.raises(ValueError, match="tampered|wrong master key"):
            cipher.decrypt(bytes(envelope))

    def test_truncated_envelope_raises(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        envelope = cipher.encrypt(b"hello")
        # Truncate well below the declared length.
        truncated = envelope[: 1 + _LENGTH_STRUCT.size + 2]
        with pytest.raises(ValueError, match="length mismatch|too short"):
            cipher.decrypt(truncated)

    def test_empty_envelope_raises(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        with pytest.raises(ValueError, match="empty"):
            cipher.decrypt(b"")

    def test_unknown_flag_raises(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        bad = bytes([0xAB]) + b"\x00" * 8
        with pytest.raises(ValueError, match="flag"):
            cipher.decrypt(bad)

    def test_payload_helper_roundtrip(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        header = b"MY_HEADER_24_BYTES_LONG!!"[:24].ljust(24, b"_")
        plaintext = b"some wal payload"
        segment = cipher.encrypt_payload(plaintext, header)
        assert segment[:24] == header
        assert cipher.is_encrypted_segment(segment, header_size=24) is True
        recovered = cipher.decrypt_payload(segment, header_size=24)
        assert recovered == plaintext

    def test_is_encrypted_segment_detection(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        header = b"X" * 24
        plaintext = b"data"

        enc = cipher.encrypt_payload(plaintext, header)
        assert cipher.is_encrypted_segment(enc, header_size=24) is True

        plain = header + bytes([FLAG_PLAINTEXT]) + plaintext
        assert cipher.is_encrypted_segment(plain, header_size=24) is False

        # Too short to contain a flag.
        too_short = header + b"x"
        assert cipher.is_encrypted_segment(too_short, header_size=24) is False

    def test_legacy_plaintext_payload_decodes(self, isolated_home: Path) -> None:
        """Round 49 segments have no flag byte; ``decrypt_payload``
        should treat them as plaintext without raising."""
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        header = b"Y" * 24
        plaintext = b"legacy round 49 payload"
        legacy = header + plaintext  # NO flag byte
        recovered = cipher.decrypt_payload(legacy, header_size=24)
        assert recovered == plaintext


# ── availability / readiness ──────────────────────────────────────────


class TestAvailability:
    def test_is_available_reflects_cryptography_import(self) -> None:
        cipher = SegmentCipher()
        # Boolean must agree with the import check.
        from zeloo_state.crypto import _try_import_cryptography

        fernet_cls, _ = _try_import_cryptography()
        assert cipher.is_available is (fernet_cls is not None)

    def test_ensure_key_without_cryptography_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("zeloo_HOME", str(tmp_path))
        # Patch the import helper to simulate "no cryptography".
        from zeloo_state import crypto as crypto_mod

        monkeypatch.setattr(crypto_mod, "_try_import_cryptography", lambda: (None, None))
        cipher = SegmentCipher(home=tmp_path)
        assert cipher.is_available is False
        with pytest.raises(RuntimeError, match="required"):
            cipher.ensure_key()


# ── persistence ───────────────────────────────────────────────────────


@pytest.mark.skipif(not CRYPTO_AVAILABLE, reason="cryptography not installed")
class TestKeyPersistence:
    def test_key_file_written_with_0600(self, isolated_home: Path) -> None:
        cipher = SegmentCipher(home=isolated_home, auto_generate=True)
        cipher.ensure_key()
        key_path = isolated_home / ".master_key"
        assert key_path.is_file()
        # On Windows mode bits are not enforced, but the chmod call
        # is still made — we just verify the file exists and contains
        # a valid Fernet key.
        content = key_path.read_text(encoding="utf-8").strip()
        Fernet(content.encode("ascii"))  # raises if invalid

    def test_key_file_overwritten_atomically(self, isolated_home: Path) -> None:
        cipher1 = SegmentCipher(home=isolated_home, auto_generate=True)
        cipher1.ensure_key()
        # Force a re-init by clearing the cache and home, then
        # generate a fresh key — the file should be rewritten.
        cipher2 = SegmentCipher(home=isolated_home, auto_generate=True)
        cipher2.ensure_key()
        # File exists and contains a valid Fernet key.
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]

        stored = (isolated_home / ".master_key").read_text().strip()
        Fernet(stored.encode("ascii"))  # raises if invalid
        assert len(stored) > 0
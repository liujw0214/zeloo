"""Tests for voice_tool (voice_tts, voice_stt)."""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from gateway.voice import ELEVENLABS_VOICE_IDS, ElevenLabsVoice, get_voice_backend


def test_elevenlabs_voice_name_resolves_to_id() -> None:
    backend = ElevenLabsVoice(api_key="test", voice_id="rachel")
    assert backend._voice_id == ELEVENLABS_VOICE_IDS["rachel"]


def test_elevenlabs_tts_writes_audio(tmp_path) -> None:
    response = MagicMock()
    response.read.return_value = b"audio-bytes"
    response.close.return_value = None
    output = tmp_path / "voice.mp3"
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        backend = ElevenLabsVoice(api_key="test", voice_id="custom-voice")
        result = backend.tts("hello", str(output))
    assert result == str(output)
    assert output.read_bytes() == b"audio-bytes"
    request = urlopen.call_args.args[0]
    assert request.full_url.endswith("/text-to-speech/custom-voice")
    assert request.get_header("Xi-api-key") == "test"


def test_elevenlabs_availability_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert ElevenLabsVoice(api_key="").is_available() is False


def test_voice_factory_returns_elevenlabs() -> None:
    assert isinstance(get_voice_backend("ELEVENLABS", api_key="test"), ElevenLabsVoice)


def test_voice_tts_no_backend():
    with patch("tools.voice_tool._get_backend", return_value=None):
        from tools.voice_tool import voice_tts

        result = voice_tts("hello", "/tmp/out.mp3")
        assert "not available" in result


def test_voice_stt_no_backend():
    with patch("tools.voice_tool._get_backend", return_value=None):
        from tools.voice_tool import voice_stt

        result = voice_stt("/tmp/in.mp3")
        assert "not available" in result


def test_voice_tts_success():
    backend = MagicMock()
    backend.tts.return_value = "/tmp/out.mp3"
    with patch("tools.voice_tool._get_backend", return_value=backend):
        from tools.voice_tool import voice_tts

        result = voice_tts("hello world", "/tmp/out.mp3")
        assert "Audio saved" in result
        assert "/tmp/out.mp3" in result
        backend.tts.assert_called_once_with("hello world", "/tmp/out.mp3")


def test_voice_stt_success():
    backend = MagicMock()
    backend.stt.return_value = "transcribed text"
    with patch("tools.voice_tool._get_backend", return_value=backend):
        from tools.voice_tool import voice_stt

        result = voice_stt("/tmp/in.mp3")
        assert result == "transcribed text"
        backend.stt.assert_called_once_with("/tmp/in.mp3")


def test_voice_tts_exception():
    backend = MagicMock()
    backend.tts.side_effect = RuntimeError("audio error")
    with patch("tools.voice_tool._get_backend", return_value=backend):
        from tools.voice_tool import voice_tts

        result = voice_tts("hi", "/tmp/x.mp3")
        assert "Error" in result
        assert "audio error" in result


def test_voice_stt_exception():
    backend = MagicMock()
    backend.stt.side_effect = RuntimeError("decode failed")
    with patch("tools.voice_tool._get_backend", return_value=backend):
        from tools.voice_tool import voice_stt

        result = voice_stt("/tmp/x.mp3")
        assert "Error" in result
        assert "decode failed" in result


if __name__ == "__main__":
    test_voice_tts_no_backend()
    test_voice_stt_no_backend()
    test_voice_tts_success()
    test_voice_stt_success()
    test_voice_tts_exception()
    test_voice_stt_exception()
    print("All voice_tool tests passed!")

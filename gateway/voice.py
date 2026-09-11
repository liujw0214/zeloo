"""Voice mode — text-to-speech and speech-to-text abstraction.

Provides a uniform interface over multiple TTS/STT backends:
* :class:`OpenAIVoice` — uses OpenAI's TTS (audio/speech) and Whisper
  (audio/transcriptions) APIs.
* :class:`ElevenLabsVoice` — uses the ElevenLabs REST API.
* :class:`ConsoleVoice` — a no-op backend that prints text (for testing).

Backends are lazily imported so the module loads without extra deps.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

ELEVENLABS_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
ELEVENLABS_DEFAULT_MODEL = "eleven_multilingual_v2"
ELEVENLABS_DEFAULT_STT_MODEL = "scribe_v1"
ELEVENLABS_VOICE_IDS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "antoni": "ErXwC6HFstjf32f37RPj",
    "bella": "EXAVITQu4vr4xnSDxMaL",
    "domi": "AZnzlk1XvdHX6vVf1p4m",
    "elli": "MF3mGyEYjhF1iO9y8S9j",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6Aew9JZfJ5P6P2f8kJ",
    "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "callum": "N2lVS1w4EtoT3dr4eOWO",
}
ELEVENLABS_VOICES = list(ELEVENLABS_VOICE_IDS)


def _resolve_elevenlabs_voice_id(voice_id: str) -> str:
    """Resolve a configured voice name or accept a custom ElevenLabs voice ID."""
    value = voice_id.strip()
    if not value:
        return ELEVENLABS_DEFAULT_VOICE_ID
    return ELEVENLABS_VOICE_IDS.get(value.lower(), value)


def _read_error(response: object) -> str:
    """Read a short diagnostic message from an API response."""
    try:
        body = response.read(2048)  # type: ignore[attr-defined]
    except Exception:
        return ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail or text)


class VoiceBackend:
    """Abstract voice backend interface."""

    def is_available(self) -> bool:
        """Return whether this backend can currently be used."""
        return True

    def tts(self, text: str, output_path: str) -> str:
        """Convert text to speech, saving audio to *output_path*.

        Returns the path to the generated audio file.
        """
        raise NotImplementedError

    def stt(self, audio_path: str) -> str:
        """Convert speech audio to text."""
        raise NotImplementedError


class ConsoleVoice(VoiceBackend):
    """No-op backend for testing — prints text instead of generating audio."""

    def tts(self, text: str, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        # Write a minimal placeholder so callers have a file to reference
        Path(output_path).write_bytes(b"")
        logger.info("TTS (console): %s", text[:100])
        return output_path

    def stt(self, audio_path: str) -> str:
        logger.info("STT (console): reading %s", audio_path)
        return ""


class OpenAIVoice(VoiceBackend):
    """Voice backend using OpenAI TTS and Whisper STT."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        tts_model: str = "tts-1",
        tts_voice: str = "alloy",
        stt_model: str = "whisper-1",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url
        self._tts_model = tts_model
        self._tts_voice = tts_voice
        self._stt_model = stt_model

    def _client(self):
        from openai import OpenAI

        kwargs = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return OpenAI(**kwargs)

    def is_available(self) -> bool:
        """Return whether the OpenAI API key is configured."""
        return bool(self._api_key)

    def tts(self, text: str, output_path: str) -> str:
        client = self._client()
        response = client.audio.speech.create(
            model=self._tts_model,
            voice=self._tts_voice,
            input=text,
        )
        response.stream_to_file(output_path)
        return output_path

    def stt(self, audio_path: str) -> str:
        client = self._client()
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model=self._stt_model,
                file=f,
            )
        return transcript.text


class ElevenLabsVoice(VoiceBackend):
    """Voice backend using the ElevenLabs REST API.

    The API key is read from ``ELEVENLABS_API_KEY`` when *api_key* is not
    supplied. TTS uses ``text-to-speech``; STT uses ``speech-to-text``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str = ELEVENLABS_DEFAULT_VOICE_ID,
        model_id: str = ELEVENLABS_DEFAULT_MODEL,
        stt_model: str = ELEVENLABS_DEFAULT_STT_MODEL,
        base_url: str = "https://api.elevenlabs.io/v1",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._voice_id = _resolve_elevenlabs_voice_id(voice_id)
        self._model_id = model_id or ELEVENLABS_DEFAULT_MODEL
        self._stt_model = stt_model or ELEVENLABS_DEFAULT_STT_MODEL
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _request(self, path: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> object:
        """Send an authenticated ElevenLabs request."""
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        request_headers = {
            "Accept": "application/json",
            "xi-api-key": self._api_key,
            **(headers or {}),
        }
        request = urllib.request.Request(
            f"{self._base_url}/{path.lstrip('/')}",
            data=data,
            headers=request_headers,
            method="POST" if data is not None else "GET",
        )
        try:
            return urllib.request.urlopen(request, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            detail = _read_error(exc)
            raise RuntimeError(
                f"ElevenLabs API request failed ({exc.code}): {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ElevenLabs API is unreachable: {exc.reason}") from exc

    def tts(self, text: str, output_path: str) -> str:
        """Generate speech and save the returned audio bytes."""
        payload = json.dumps(
            {
                "text": text,
                "model_id": self._model_id,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            }
        ).encode("utf-8")
        response = self._request(
            f"text-to-speech/{urllib.parse.quote(self._voice_id, safe='')}",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "audio/mpeg"},
        )
        try:
            audio = response.read()  # type: ignore[attr-defined]
        finally:
            response.close()  # type: ignore[attr-defined]
        if not audio:
            raise RuntimeError("ElevenLabs returned empty audio")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(audio)
        return output_path

    def stt(self, audio_path: str) -> str:
        """Transcribe audio through ElevenLabs speech-to-text."""
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        boundary = f"----zeloo-{uuid.uuid4().hex}"
        mime = "application/octet-stream"
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="model_id"\r\n\r\n',
            self._stt_model.encode("utf-8"),
            f"\r\n--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        response = self._request(
            "speech-to-text",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            body = response.read()  # type: ignore[attr-defined]
        finally:
            response.close()  # type: ignore[attr-defined]
        try:
            data = json.loads(body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ElevenLabs returned invalid STT JSON") from exc
        text = data.get("text") if isinstance(data, dict) else None
        if not text:
            raise RuntimeError("ElevenLabs returned no transcription")
        return str(text)

    def is_available(self) -> bool:
        """Check whether the key and ElevenLabs API are usable."""
        try:
            response = self._request("user", headers={"Accept": "application/json"})
            response.close()  # type: ignore[attr-defined]
        except Exception:
            return False
        return True


def get_voice_backend(name: str = "console", **kwargs: object) -> VoiceBackend:
    """Factory for voice backends.

    Args:
        name: Backend name ("console", "openai", or "elevenlabs").
        **kwargs: Passed to the backend constructor.
    """
    normalized_name = name.lower()
    if normalized_name == "openai":
        return OpenAIVoice(**kwargs)
    if normalized_name == "elevenlabs":
        return ElevenLabsVoice(**kwargs)
    return ConsoleVoice()

"""Voice tools — text-to-speech and speech-to-text.

Backed by the active VoiceBackend on the current AIAgent. The backend
is selected from config (``voice.backend``) and supports console,
OpenAI, and ElevenLabs TTS/STT services.
"""

from __future__ import annotations

import logging

from tools.base import tool

logger = logging.getLogger(__name__)


def _get_backend():
    """Return the active VoiceBackend from the current agent, or None."""
    try:
        from run_agent import _current_agent

        agent = _current_agent.get()
        if agent is not None:
            return getattr(agent, "voice_backend", None)
    except Exception:
        pass
    return None


@tool(name="voice_tts", description="Convert text to speech audio file", toolset="voice")
def voice_tts(text: str, output_path: str) -> str:
    """Convert text to speech and save to an audio file.

    Args:
        text: The text to synthesize.
        output_path: Path to save the audio file (e.g. /tmp/speech.mp3).

    Returns:
        The output path on success, or an error message.
    """
    backend = _get_backend()
    if backend is None:
        return "Error: Voice backend is not available in this environment."
    try:
        result = backend.tts(text, output_path)
        return f"Audio saved: {result}"
    except Exception as e:
        logger.exception("TTS failed")
        return f"Error generating speech: {e}"


@tool(name="voice_stt", description="Transcribe a speech audio file to text", toolset="voice")
def voice_stt(audio_path: str) -> str:
    """Transcribe speech from an audio file to text.

    Args:
        audio_path: Path to the audio file to transcribe.

    Returns:
        The transcribed text, or an error message.
    """
    backend = _get_backend()
    if backend is None:
        return "Error: Voice backend is not available in this environment."
    try:
        return backend.stt(audio_path)
    except Exception as e:
        logger.exception("STT failed")
        return f"Error transcribing audio: {e}"

"""Speech-to-text for voice notes via ElevenLabs Scribe (auto-detects Hindi, Tamil, English, Hinglish...)."""

import os

import httpx2

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
MAX_VOICE_SECONDS = 120  # orders are short; caps cost on a public bot


class VoiceUnavailable(Exception):
    pass


def enabled() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceUnavailable("ELEVENLABS_API_KEY is not set")
    async with httpx2.AsyncClient(timeout=60) as client:
        r = await client.post(
            STT_URL,
            headers={"xi-api-key": key},
            data={"model_id": STT_MODEL},
            files={"file": (filename, audio, "audio/ogg")},
        )
    if r.status_code != 200:
        raise VoiceUnavailable(f"ElevenLabs returned {r.status_code}: {r.text[:200]}")
    return (r.json().get("text") or "").strip()

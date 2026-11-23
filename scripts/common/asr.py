"""Speech-to-text providers behind one interface.

Each provider's transcribe(audio_path, terms) returns
    {"text", "language", "language_confidence", "words": [{"word", "start", "end"}]}
with None where the provider doesn't say (Whisper adds "segments"). A RetryableError means try
again later (rate limits, server errors).

The cloud ones are UNTESTED against the real APIs: written from their docs without keys. Check
each one on a single file before trusting a run. Their keys are passed in (make transcripts
reads them from ~/.secrets, see scripts/settings.py).

This module imports nothing from the project, so it runs on its own on another machine beside
whisper_worker.py (make transcripts-remote).
"""
import json
import os
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

TIMEOUT = 600


class RetryableError(Exception):
    pass


def post(url, body, headers):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code == 429 or e.code >= 500:
            raise RetryableError(f"{e.code}: {detail}") from e
        raise RuntimeError(f"{e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RetryableError(str(e)) from e


def multipart(fields, audio_path):
    """Form fields plus the audio file, as (body, content type)."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
                 f"Content-Type: audio/ogg\r\n\r\n".encode() + audio_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Deepgram:
    name, model, usd_per_minute = "deepgram", "nova-3", 0.0043

    def __init__(self, key=None):
        self.key = key

    def transcribe(self, audio_path, terms):
        query = [("model", self.model), ("smart_format", "true"), ("detect_language", "true")]
        query += [("keyterm", t) for t in terms]
        result = post("https://api.deepgram.com/v1/listen?" + urllib.parse.urlencode(query), audio_path.read_bytes(),
                      {"Authorization": f"Token {self.key()}", "Content-Type": "audio/ogg"})
        channel = result["results"]["channels"][0]
        best = channel["alternatives"][0]
        return {"text": best["transcript"], "language": channel.get("detected_language"),
                "language_confidence": channel.get("language_confidence"),
                "words": [{"word": w.get("punctuated_word", w["word"]), "start": w["start"], "end": w["end"]}
                          for w in best.get("words", [])]}


class OpenAI:
    name, model, usd_per_minute = "openai", "gpt-4o-transcribe", 0.006
    max_seconds = 1400  # longer files need splitting at silences first, which isn't built yet

    def __init__(self, key=None):
        self.key = key

    def transcribe(self, audio_path, terms):
        fields = [("model", self.model), ("response_format", "json")]
        if terms:
            fields.append(("prompt", "Travel diary of a cyclist. Names and places: " + ", ".join(terms)))
        body, content_type = multipart(fields, audio_path)
        result = post("https://api.openai.com/v1/audio/transcriptions", body,
                      {"Authorization": f"Bearer {self.key()}", "Content-Type": content_type})
        return {"text": result["text"], "language": None, "language_confidence": None, "words": []}


class ElevenLabs:
    name, model, usd_per_minute = "elevenlabs", "scribe_v1", 0.0067

    def __init__(self, key=None):
        self.key = key

    def transcribe(self, audio_path, terms):
        # Scribe takes no vocabulary, so terms go unused
        body, content_type = multipart(
            [("model_id", self.model), ("timestamps_granularity", "word"), ("tag_audio_events", "false")], audio_path)
        result = post("https://api.elevenlabs.io/v1/speech-to-text", body,
                      {"xi-api-key": self.key(), "Content-Type": content_type})
        return {"text": result["text"], "language": result.get("language_code"),
                "language_confidence": result.get("language_probability"),
                "words": [{"word": w["text"], "start": w["start"], "end": w["end"]}
                          for w in result.get("words", []) if w.get("type") == "word"]}


def decode(audio_path, rate=16000):
    """The audio as mono float32 samples, decoded by ffmpeg (faster-whisper's own decoder breaks
    with newer PyAV)."""
    import numpy
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", audio_path, "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"],
                         capture_output=True, check=True).stdout
    return numpy.frombuffer(pcm, numpy.float32)


def load_whisper(model, models_dir, threads=0):
    """A faster-whisper model, downloaded once into models_dir, then loaded without asking Hugging Face."""
    import onnxruntime
    from faster_whisper import WhisperModel
    onnxruntime.disable_telemetry_events()  # the voice filter's runtime would phone Microsoft
    have = (Path(models_dir) / f"models--Systran--faster-whisper-{model}").exists()
    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads or os.cpu_count(),
                        download_root=str(models_dir), local_files_only=have)


class Whisper:
    name, usd_per_minute = "whisper", 0
    workers = 1  # one file at a time, on every core

    def __init__(self, model="large-v3", models_dir="processing/asr/models", languages=("en", "fr"), threads=0):
        self.model, self.models_dir, self.languages, self.threads = model, models_dir, tuple(languages), threads
        self.loaded, self.lock = None, threading.Lock()

    def transcribe(self, audio_path, terms):
        audio = decode(audio_path)
        with self.lock:
            if self.loaded is None:
                self.loaded = load_whisper(self.model, self.models_dir, self.threads)

            def run(language):
                # hotwords prompt every 30 s window, where initial_prompt only reaches the first;
                # the voice filter skips silences, where Whisper invents text; and each window
                # isn't fed the last one's text, which would have it repeat a sentence to the end
                return self.loaded.transcribe(audio, language=language, vad_filter=True,
                                              condition_on_previous_text=False, hotwords=", ".join(terms) or None)
            segments, info = run(None)  # nothing is transcribed until segments is read
            language, confidence = info.language, info.language_probability
            if language not in self.languages:
                # Every entry is in one of the diary's languages: take the likeliest of them
                probs = dict(info.all_language_probs or [])
                language = max(self.languages, key=lambda code: probs.get(code, 0))
                confidence = probs.get(language)
                segments, info = run(language)
            segments = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()} for s in segments]
        return {"text": " ".join(s["text"] for s in segments), "language": language,
                "language_confidence": confidence, "words": [], "segments": segments}

#!/usr/bin/env python3
"""Transcribe a list of recordings with Whisper, on a machine that only has this job.

Usage: whisper_worker.py JOBS_JSON AUDIO_DIR RESULTS_DIR

JOBS_JSON is what make transcripts-remote pushes: the model and languages, and each recording's
stem, vocabulary and length in minutes, for the time left. AUDIO_DIR holds <stem>.ogg. Each
transcript goes to RESULTS_DIR/<stem>.json, which make transcripts-fetch takes back. Files already
there are skipped, so it can be stopped and started again. Needs faster-whisper, ffmpeg, and
asr.py (scripts/common/asr.py) beside it, with the model in models/ beside it.
"""
import json
import sys
import time
from pathlib import Path

try:
    from asr import Whisper  # on the other machine, beside this file
except ImportError:
    from common.asr import Whisper


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__.split("\n\n")[1])
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    jobs = job["files"]
    audio, results = Path(sys.argv[2]), Path(sys.argv[3])
    results.mkdir(parents=True, exist_ok=True)
    whisper = Whisper(job["model"], Path(sys.argv[1]).parent / "models", job["languages"], job.get("threads", 0))
    left = sum(j.get("minutes", 0) for j in jobs if not (results / f"{j['stem']}.json").exists())
    spent = heard = 0  # minutes working, and the minutes of audio that took
    for n, j in enumerate(jobs, 1):
        out = results / f"{j['stem']}.json"
        if out.exists():
            continue
        started = time.monotonic()
        try:
            result = whisper.transcribe(audio / f"{j['stem']}.ogg", j["terms"])
        except Exception as e:  # keep going; a rerun tries it again
            print(f"{n}/{len(jobs)}  FAILED {j['stem']}: {e}", flush=True)
            continue
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        tmp.rename(out)
        took, length = (time.monotonic() - started) / 60, j.get("minutes", 0)
        spent, heard, left = spent + took, heard + length, left - length
        pace = f"  {left * spent / heard / 60 / 24:.1f} days left at {spent / heard:.1f}x" if heard else ""
        print(f"{n}/{len(jobs)}  {took:.0f} min for {length:.1f} min of audio  {j['stem']}{pace}", flush=True)
    print("finished", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Speech to text for the diary recordings: here, on a paid service, or on another machine.

Usage: transcribe.py compress
       transcribe.py run [PROVIDER] [--dry-run] [--limit N] [--files NAME ...]
       transcribe.py pilot
       transcribe.py languages
       transcribe.py remote push|start|status|fetch|stop|remove [--french]

  compress   each recording in clean/diary/audio as processing/audio/<stem>.ogg: mono Opus,
             transcribe.audio_rate and audio_bitrate, a twentieth of the WAV's size, for upload
  run        transcribe what's not done yet with PROVIDER (default transcribe.provider): deepgram,
             openai, elevenlabs (paid per minute: --dry-run says how much) or whisper, on this
             machine (free, slow; its model downloads once into processing/asr/models)
  pilot      run each of transcribe.pilot_providers on the recordings in manual/pilot.txt, to compare
  languages  which recordings are in which language (a small Whisper model listens to 30 s at the
             start and in the middle): processing/asr/languages.csv, which remote push orders by
  remote     Whisper on the ssh host transcribe.remote_host, which needs python3 with venv, ffmpeg
             and rsync; nothing is installed outside ~/whisper_job there:
               push    the recordings Whisper hasn't done, their vocabulary, the model and the worker.
                       Those in a language other than English first, then those make events has been
                       through, then the rest; --french: only the French ones. Pushing again while the
                       worker runs is fine; stop and start it to take the new list
               start   install faster-whisper in a venv there and start the worker, which carries on
                       after you log out and skips what it has done
               status  how many are done, the log's last lines (with the time left), whether it runs
               fetch   take back what's done, as run would have made it; as often as you like
               stop    stop the worker (start carries on); remove: stop it and delete the job there

Each recording gets a vocabulary: towns near where it was recorded (make locate), then
manual/glossary.txt, up to transcribe.max_terms. Transcripts go to processing/asr/<provider>/
<stem>.json and .txt. Recordings already done are skipped, so a run can be stopped and started.
"""
import argparse
import csv
import json
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.asr import Deepgram, ElevenLabs, OpenAI, RetryableError, Whisper, decode, load_whisper
from common.tables import read_rows, write_json, write_rows, write_text
from repo import ASR, AUDIO, COMPRESSED, EVENT_ENTRIES, GLOSSARY, INDEX, LOCATED, PILOT, rel
from settings import settings

T = settings.transcribe
MODELS = ASR / "models"
JOB = ASR / "server_job"
REMOTE = "whisper_job"
AUDIO_TYPES = {".wav", ".flac", ".mp3", ".m4a"}


def providers():
    return {"deepgram": Deepgram(lambda: settings.secret("deepgram_api_key")),
            "openai": OpenAI(lambda: settings.secret("openai_api_key")),
            "elevenlabs": ElevenLabs(lambda: settings.secret("elevenlabs_api_key")),
            "whisper": Whisper(T.whisper_model, MODELS, T.languages, T.whisper_threads)}


def recordings():
    return sorted(p for p in AUDIO.iterdir() if p.suffix.lower() in AUDIO_TYPES and not p.name.startswith("."))


def read_list(path):
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")] if path.exists() else []


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def compress():
    """processing/audio/<stem>.ogg for each recording that hasn't one yet, a few at a time."""
    import os
    todo = [(p, COMPRESSED / f"{p.stem}.ogg") for p in recordings()]
    todo = [(p, out) for p, out in todo if not out.exists()]
    COMPRESSED.mkdir(parents=True, exist_ok=True)

    def one(job):
        source, out = job
        tmp = out.with_name(f".tmp.{out.name}")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", source, "-ac", "1",
                        "-ar", str(T.audio_rate), "-c:a", "libopus", "-b:a", T.audio_bitrate, "-application", "voip",
                        "-f", "ogg", tmp], check=True)
        tmp.replace(out)

    if not todo:
        return print(f"{rel(COMPRESSED)}: every recording compressed")
    print(f"compressing {len(todo)} recordings")
    failed = []
    with ThreadPoolExecutor(max(1, (os.cpu_count() or 2) - 2)) as pool:
        for i, (job, error) in enumerate(zip(todo, pool.map(lambda j: _try(one, j), todo)), 1):
            if error:
                failed.append(job[0].name)
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", flush=True)
    if failed:
        sys.exit(f"failed ({len(failed)}): " + ", ".join(failed))


def _try(fn, arg):
    try:
        fn(arg)
    except subprocess.CalledProcessError as e:
        return e
    return None


class Vocabulary:
    """Each recording's terms: towns near where it was made, then the glossary."""

    def __init__(self):
        from common.towns import Towns
        self.glossary = read_list(GLOSSARY)
        self.towns = Towns()
        self.at = {Path(r["file"]).name: (float(r["lat"]), float(r["lon"]))
                   for r in read_rows(LOCATED / "audio.csv") if r["lat"]}

    def terms(self, source):
        pos = self.at.get(source.name)
        towns = self.towns.near(*pos) if pos else []
        return list(dict.fromkeys(towns + self.glossary))[:T.max_terms]


def save(provider, source, record):
    out = ASR / provider / source.stem
    write_text(out.with_suffix(".txt"), record["text"] + "\n")
    write_json(out.with_suffix(".json"), record)


def record_for(provider, source, terms, seconds, result):
    indexed = {r["file"]: r for r in read_rows(INDEX / "audio.csv")}.get(rel(source), {})
    return {"source": source.name, "duration_s": round(seconds, 1), "date": indexed.get("recorded") or None,
            "date_source": indexed.get("date_source") or None, "provider": provider.name,
            "model": getattr(provider, "model", ""), "vocabulary": terms,
            "cost_usd": round(seconds / 60 * provider.usd_per_minute, 4), **result}


def transcribe_one(provider, source, vocabulary):
    compressed = COMPRESSED / f"{source.stem}.ogg"
    terms = vocabulary.terms(source)
    seconds = duration(compressed)
    if seconds > getattr(provider, "max_seconds", float("inf")):
        raise RuntimeError(f"{seconds / 60:.0f} min is too long for {provider.name} without splitting")
    for attempt in range(T.retries):
        try:
            result = provider.transcribe(compressed, terms)
            break
        except RetryableError:
            if attempt == T.retries - 1:
                raise
            time.sleep(2 ** attempt * 5)
    record = record_for(provider, source, terms, seconds, result)
    save(provider.name, source, record)
    return record


def chosen(names=None):
    sources = recordings()
    if names:
        if missing := set(names) - {s.name for s in sources}:
            sys.exit("not found: " + ", ".join(sorted(missing)))
        sources = [s for s in sources if s.name in names]
    if missing := [s.name for s in sources if not (COMPRESSED / f"{s.stem}.ogg").exists()]:
        sys.exit(f"{len(missing)} recordings not compressed yet: run make audio")
    return sources


def run(name, names=None, limit=None, dry_run=False):
    provider = providers()[name]
    sources = chosen(names)
    todo = [s for s in sources if not (ASR / name / f"{s.stem}.json").exists()][:limit]
    if dry_run or not todo:
        minutes = sum(duration(COMPRESSED / f"{s.stem}.ogg") for s in todo) / 60
        return print(f"{name}: {len(todo)} to do ({len(sources) - len(todo)} done), {minutes:.0f} min, "
                     f"~${minutes * provider.usd_per_minute:.2f}")
    vocabulary = Vocabulary()
    done, cost, failures = 0, 0.0, []
    started = time.monotonic()
    with ThreadPoolExecutor(getattr(provider, "workers", T.workers)) as pool:
        futures = {pool.submit(transcribe_one, provider, s, vocabulary): s for s in todo}
        for future, source in futures.items():
            try:
                cost += future.result()["cost_usd"]
                done += 1
            except Exception as e:  # keep going; failures are logged for a rerun
                failures.append(f"{source.name}\t{e}")
            n = done + len(failures)
            eta = (time.monotonic() - started) / n * (len(todo) - n)
            print(f"{n}/{len(todo)}  ${cost:.2f}  eta {eta / 60:.0f} min  {source.name}", flush=True)
    if failures:
        write_text(ASR / name / "failures.log", "\n".join(failures) + "\n")
        sys.exit(f"{len(failures)} failed; see {ASR / name / 'failures.log'}")


def languages():
    """processing/asr/languages.csv: file, minutes, then the chance of each of transcribe.languages,
    averaged over 30 s at the start and in the middle, and the likeliest."""
    model = load_whisper("small", MODELS)
    window = 30
    files = sorted(COMPRESSED.glob("*.ogg"))
    out = []
    for n, path in enumerate(files, 1):
        audio = decode(path)
        size, middle = window * 16000, max(0, len(audio) // 2 - window * 8000)
        windows = [audio[:size]] + ([audio[middle:middle + size]] if len(audio) > 2 * size else [])
        probs = [dict(model.detect_language(w)[2]) for w in windows if len(w)]
        chance = {code: sum(p.get(code, 0) for p in probs) / max(len(probs), 1) for code in T.languages}
        out.append({"file": path.name, "minutes": f"{len(audio) / 16000 / 60:.1f}",
                    **{c: f"{v:.2f}" for c, v in chance.items()}, "language": max(chance, key=chance.get)})
        if n % 100 == 0:
            print(f"{n}/{len(files)}", flush=True)
    write_rows(ASR / "languages.csv", ["file", "minutes", *T.languages, "language"], out)


def ssh(command, check=True):
    return subprocess.run(["ssh", T.remote_host, command], check=check, text=True)


def push(french_only):
    langs = {Path(r["file"]).stem: r for r in read_rows(ASR / "languages.csv")}
    sources = [s for s in recordings() if not (ASR / "whisper" / f"{s.stem}.json").exists()]
    if french_only:
        sources = [s for s in sources if langs.get(s.stem, {}).get("language") == "fr"]

    def order(source):
        if langs.get(source.stem, {}).get("language", "en") != "en":
            return 0
        return 1 if (EVENT_ENTRIES / "audio" / f"{source.stem}.json").exists() else 2
    sources.sort(key=order)
    vocabulary = Vocabulary()
    files = [{"stem": s.stem, "terms": vocabulary.terms(s), "minutes": float(langs.get(s.stem, {}).get("minutes") or 0)}
             for s in sources]
    write_json(JOB / "jobs.json", {"model": T.whisper_model, "languages": T.languages,
                                   "threads": T.whisper_threads, "files": files})
    write_text(JOB / "audio.txt", "".join(f"{s.stem}.ogg\n" for s in sources))
    print(f"{len(files)} recordings, {sum(f['minutes'] for f in files) / 60:.0f} hours of audio")
    model = f"models--Systran--faster-whisper-{T.whisper_model}"
    ssh(f"mkdir -p {REMOTE}/audio {REMOTE}/models")
    subprocess.run(["rsync", "-a", "--info=progress2", f"--files-from={JOB / 'audio.txt'}", f"{COMPRESSED}/",
                    f"{T.remote_host}:{REMOTE}/audio/"], check=True)
    # The model's files are links into a store shared by every model: copy what they point to
    subprocess.run(["rsync", "-aL", "--exclude", "blobs", "--exclude", ".locks", "--info=progress2",
                    str(MODELS / model), f"{T.remote_host}:{REMOTE}/models/"], check=True)
    here = Path(__file__).parent
    subprocess.run(["rsync", "-a", str(here / "whisper_worker.py"), str(here / "common/asr.py"), str(JOB / "jobs.json"),
                    f"{T.remote_host}:{REMOTE}/"], check=True)


def fetch():
    """Take back the remote results: each as make transcripts would have made it. Names with
    whitespace (from jobs pushed before clean/ renamed them) are matched by their clean name."""
    from build_clean import clean_name
    results = JOB / "results"
    results.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-a", f"{T.remote_host}:{REMOTE}/results/", f"{results}/"], check=True)
    by_stem = {s.stem: s for s in recordings()}
    whisper, vocabulary, taken = providers()["whisper"], None, 0
    for path in sorted(results.glob("*.json")):
        source = by_stem.get(clean_name(path.stem))
        if not source or (ASR / "whisper" / f"{source.stem}.json").exists():
            continue
        vocabulary = vocabulary or Vocabulary()
        terms = vocabulary.terms(source)
        result = json.loads(path.read_text(encoding="utf-8"))
        save("whisper", source, record_for(whisper, source, terms, duration(COMPRESSED / f"{source.stem}.ogg"), result))
        taken += 1
    print(f"took {taken} transcripts into {rel(ASR / 'whisper')}")


def remote(action, french_only=False):
    start = f"""cd {REMOTE} || exit 1
        command -v ffmpeg >/dev/null || {{ echo 'ffmpeg is missing'; exit 1; }}
        if [ -f pid ] && kill -0 $(cat pid) 2>/dev/null; then echo 'already running'; exit 0; fi
        [ -d venv ] || python3 -m venv venv
        venv/bin/pip install --quiet faster-whisper==1.2.1 || exit 1
        setsid nohup venv/bin/python whisper_worker.py jobs.json audio results >> log 2>&1 < /dev/null &
        echo $! > pid
        echo started"""
    actions = {
        "push": lambda: push(french_only),
        "start": lambda: ssh(start),
        "status": lambda: ssh(f"cd {REMOTE} && echo \"$(ls results 2>/dev/null | grep -c 'json$') done\"; "
                              "tail -n 3 log 2>/dev/null; "
                              "[ -f pid ] && kill -0 $(cat pid) 2>/dev/null && echo running || echo 'not running'", False),
        "fetch": fetch,
        "stop": lambda: ssh(f"[ -f {REMOTE}/pid ] && kill $(cat {REMOTE}/pid) 2>/dev/null && echo stopped "
                            "|| echo 'not running'", False),
        "remove": lambda: ssh(f"[ -f {REMOTE}/pid ] && kill $(cat {REMOTE}/pid) 2>/dev/null; rm -rf {shlex.quote(REMOTE)}",
                              False),
    }
    actions[action]()


def main():
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n")[1])
    parser.add_argument("command", choices=["compress", "run", "pilot", "languages", "remote"])
    parser.add_argument("arg", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--french", action="store_true")
    args = parser.parse_args()
    if args.command == "compress":
        compress()
    elif args.command == "run":
        run(args.arg or T.provider, args.files, args.limit, args.dry_run)
    elif args.command == "pilot":
        for name in T.pilot_providers:
            run(name, read_list(PILOT), dry_run=args.dry_run)
    elif args.command == "languages":
        languages()
    elif args.arg not in ("push", "start", "status", "fetch", "stop", "remove"):
        sys.exit("remote needs push, start, status, fetch, stop or remove")
    else:
        remote(args.arg, args.french)


if __name__ == "__main__":
    main()

"""Download call recordings referenced in voice.db to analysis/recordings/.

Two hosts, two strategies:
  - recording.nooks.in  -> direct .wav download (cold calls, ~1-3MB)
  - api-na2.hubspot.com -> auth-redirects to a signed CDN media URL (often a
    full meeting VIDEO, hundreds of MB) -> stream through ffmpeg and keep
    only mono 16kHz audio, the format the whole pipeline uses

Everything lands at recordings/<call_id>.wav and the local path is stamped
back onto hs_calls.recording_path, so downstream code never touches a remote
URL again. Resumable: files > 4KB are trusted and skipped; smaller ones are
re-fetched. Order: connected calls first, longest first (meetings, then
conversations, then the tail).

Usage:
  python fetch_recordings.py [--connects-only] [--limit N]
"""
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
REC = HERE / "recordings"
DB = HERE / "voice.db"

MIN_BYTES = 4096
CONNECT_LABELS = ("Connected", "Connected - Demo booked",
                  "Interested - gatekeeper", "Interested - send info")


def fetch_direct(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "optimus-voice/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as f:
        f.write(resp.read())


def fetch_audio_via_ffmpeg(url, path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", url,
         "-vn", "-ac", "1", "-ar", "16000", str(path)],
        check=True, timeout=1800)


def main():
    connects_only = "--connects-only" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

    REC.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    placeholders = ",".join("?" * len(CONNECT_LABELS))
    rows = con.execute(
        f"""SELECT call_id, recording_url,
                   disposition_label IN ({placeholders}) is_connect
            FROM hs_calls WHERE recording_url IS NOT NULL
            ORDER BY is_connect DESC, duration_ms DESC""",
        CONNECT_LABELS).fetchall()
    if connects_only:
        rows = [r for r in rows if r[2]]
    if limit:
        rows = rows[:limit]

    done = failed = skipped = 0
    for i, (call_id, url, _) in enumerate(rows, 1):
        path = REC / f"{call_id}.wav"
        if path.exists() and path.stat().st_size > MIN_BYTES:
            skipped += 1
        else:
            try:
                if "nooks" in url:
                    fetch_direct(url, path)
                else:
                    fetch_audio_via_ffmpeg(url, path)
                if not path.exists() or path.stat().st_size <= MIN_BYTES:
                    raise RuntimeError("empty or truncated response")
                done += 1
                time.sleep(0.3)  # be polite to the recording hosts
            except Exception as e:  # noqa: BLE001
                path.unlink(missing_ok=True)
                print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)
                failed += 1
                continue
        con.execute("UPDATE hs_calls SET recording_path=? WHERE call_id=?",
                    (str(path.relative_to(HERE)), call_id))
        if i % 25 == 0:
            con.commit()
            print(f"[{i}/{len(rows)}] downloaded={done} skipped={skipped} failed={failed}",
                  flush=True)
    con.commit()
    con.close()
    print(f"finished: {done} downloaded, {skipped} already local, {failed} failed "
          f"of {len(rows)} recordings", flush=True)


if __name__ == "__main__":
    main()

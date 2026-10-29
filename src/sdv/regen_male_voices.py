"""Переозвучить Семёна, рассказчика, мысли и остальных мужчин из config/voices.json.

Не запускать, пока открыто окно generate_voices.bat: тот процесс держит старое
назначение голосов в памяти и пишет в ту же базу и те же ogg.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess

from sdv.audio_util import write_ogg
from sdv.engines.silero import SileroEngine
from sdv.generate import _voice_for
from sdv.paths import get_paths

# Пустая строка — рассказчик без метки.
SPEAKERS = (
    "",
    "th",
    "me",
    "am",
    "we",
    "we_orange",
    "el",
    "sh",
    "ba",
    "bb",
    "dn",
    "pi",
    "va",
    "ml",
    "ml2",
    "ft",
    "hg",
    "br",
    "ai",
    "tn",
    "mir",
    "dy",
)


def _full_generation_running() -> bool:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return "sdv.generate" in (result.stdout or "")


def main() -> None:
    if _full_generation_running():
        raise SystemExit(
            "Сейчас идёт generate_voices.bat. Закройте это окно и только потом запустите regen_male_voices.bat."
        )
    paths = get_paths()
    config = json.loads(paths.tts_config.read_text(encoding="utf-8"))
    voices = json.loads(paths.voices_config.read_text(encoding="utf-8"))
    scope = config.get("scope", "scenario")
    engine = SileroEngine()
    status = engine.prepare()
    if not status.ok:
        raise SystemExit(status.detail)
    stamp = f"silero:{engine.model_id}"
    conn = sqlite3.connect(paths.catalog, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT id, speaker, text_tts, text_hash
        FROM lines
        WHERE scope=? AND identifier_missing=0 AND length(text_tts) > 0
          AND speaker IN ({",".join("?" for _ in SPEAKERS)})
        ORDER BY filename, line_number
        """,
        (scope, *SPEAKERS),
    ).fetchall()
    print(f"Реплики Семёна и остальных мужчин: {len(rows)}. Метка: {stamp}. Область: {scope}.", flush=True)
    done = 0
    skipped = 0
    errors = 0
    for index, row in enumerate(rows, 1):
        voice = _voice_for(row["speaker"] or "", voices)
        if not voice:
            continue
        rel = f"voice/{row['id'][:2]}/{row['id']}.ogg"
        dest = paths.audio / rel
        previous = conn.execute(
            "SELECT text_hash, engine, voice, status FROM generated WHERE id=?",
            (row["id"],),
        ).fetchone()
        if (
            previous
            and previous["status"] == "ok"
            and previous["text_hash"] == row["text_hash"]
            and previous["engine"] == stamp
            and previous["voice"] == voice
            and dest.is_file()
        ):
            skipped += 1
            continue
        try:
            audio, rate = engine.synthesize(row["text_tts"], voice, None)
            write_ogg(dest, audio, rate)
            conn.execute(
                """
                INSERT INTO generated (id, engine, voice, text_hash, path, status, error)
                VALUES (?, ?, ?, ?, ?, 'ok', '')
                ON CONFLICT(id) DO UPDATE SET
                    engine=excluded.engine, voice=excluded.voice, text_hash=excluded.text_hash,
                    path=excluded.path, status='ok', error=''
                """,
                (row["id"], stamp, voice, row["text_hash"], rel),
            )
            done += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            conn.execute(
                """
                INSERT INTO generated (id, engine, voice, text_hash, path, status, error)
                VALUES (?, ?, ?, ?, ?, 'error', ?)
                ON CONFLICT(id) DO UPDATE SET status='error', error=excluded.error
                """,
                (row["id"], stamp, voice, row["text_hash"], rel, str(exc)),
            )
            print(f"Ошибка {row['id']}: {exc}", flush=True)
        if index % 20 == 0:
            conn.commit()
            print(f"{index}/{len(rows)} новых {done}, пропущено {skipped}, ошибок {errors}", flush=True)
    conn.commit()
    engine.close()
    print(f"Готово. Новых файлов: {done}. Пропущено: {skipped}. Ошибок: {errors}.", flush=True)


if __name__ == "__main__":
    main()

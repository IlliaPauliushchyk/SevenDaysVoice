"""Массовая генерация. Не стартует, пока движок не выбран после прослушивания."""

from __future__ import annotations

import json
import sqlite3

from sdv.audio_util import write_ogg
from sdv.engines.piper import PiperEngine
from sdv.engines.qwen import QwenEngine
from sdv.engines.silero import SileroEngine
from sdv.paths import get_paths

_ENGINES = {
    "silero": SileroEngine,
    "piper": PiperEngine,
    "qwen3": QwenEngine,
}


def _voice_for(speaker: str, voices: dict) -> str | None:
    characters = voices.get("characters") or {}
    if speaker in {"", "narrator"}:
        return voices.get("narrator_voice") or voices.get("default_voice")
    if speaker == "th":
        return voices.get("thoughts_voice") or characters.get("th") or voices.get("default_voice")
    return characters.get(speaker) or voices.get("default_voice")


def main() -> None:
    paths = get_paths()
    config = json.loads(paths.tts_config.read_text(encoding="utf-8"))
    if not config.get("chosen_by_user") or not config.get("engine"):
        raise SystemExit(
            "Движок ещё не выбран. Откройте generated_audio/voice_comparison/index.html, "
            "после прослушивания запишите engine и \"chosen_by_user\": true в config/tts.json "
            "и голоса в config/voices.json. Массовая генерация не запускалась."
        )
    engine_name = config["engine"]
    if engine_name not in _ENGINES:
        raise SystemExit(f"Неизвестный движок: {engine_name}. Доступны: {', '.join(_ENGINES)}")
    voices = json.loads(paths.voices_config.read_text(encoding="utf-8"))
    if not voices.get("default_voice"):
        raise SystemExit("В config/voices.json не задан default_voice.")
    engine = _ENGINES[engine_name]()
    status = engine.prepare()
    if not status.ok:
        raise SystemExit(status.detail)
    model_id = getattr(engine, "model_id", "")
    stamp = f"{engine_name}:{model_id}" if model_id else engine_name
    conn = sqlite3.connect(paths.catalog)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS generated (
            id TEXT PRIMARY KEY,
            engine TEXT,
            voice TEXT,
            text_hash TEXT,
            path TEXT,
            status TEXT,
            error TEXT
        )
        """
    )
    scope = config.get("scope", "scenario")
    rows = conn.execute(
        """
        SELECT id, speaker, text_tts, text_hash
        FROM lines
        WHERE scope=? AND identifier_missing=0 AND length(text_tts) > 0
        ORDER BY filename, line_number
        """,
        (scope,),
    ).fetchall()
    done = 0
    for row in rows:
        voice = _voice_for(row["speaker"] or "", voices)
        if not voice:
            continue
        rel = f"voice/{row['id'][:2]}/{row['id']}.ogg"
        dest = paths.audio / rel
        previous = conn.execute("SELECT text_hash, engine, voice, status FROM generated WHERE id=?", (row["id"],)).fetchone()
        if (
            previous
            and previous["status"] == "ok"
            and previous["text_hash"] == row["text_hash"]
            and previous["engine"] == stamp
            and previous["voice"] == voice
            and dest.is_file()
        ):
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
            conn.execute(
                """
                INSERT INTO generated (id, engine, voice, text_hash, path, status, error)
                VALUES (?, ?, ?, ?, ?, 'error', ?)
                ON CONFLICT(id) DO UPDATE SET status='error', error=excluded.error
                """,
                (row["id"], stamp, voice, row["text_hash"], rel, str(exc)),
            )
            print(f"Ошибка {row['id']}: {exc}")
        if done % 20 == 0:
            conn.commit()
    conn.commit()
    engine.close()
    print(f"Новых файлов: {done}. Каталог: {paths.audio / 'voice'}")


if __name__ == "__main__":
    main()

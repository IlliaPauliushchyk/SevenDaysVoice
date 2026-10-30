"""Обход AST мода и сбор реплик Say."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter
from pathlib import Path

from sdv.rpyc_reader import load_ast

_BLOCK_ATTRS = ("block",)
_SEQ_ATTRS = ("entries", "items")
# Персонаж «Голос» в сценарии пишется `voice "текст"`. То же слово Ren'Py
# резервирует под команду воспроизведения файла, поэтому в .rpyc это не Say.
_VOICE_DIALOGUE = re.compile(
    r"""^voice\s+(?P<q>\"\"\"|'''|"|')(?P<body>.*)(?P=q)\s*$""",
    re.DOTALL,
)
_AUDIO_SUFFIXES = (".ogg", ".mp3", ".wav", ".opus")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _kind(node) -> str:
    return type(node).__name__


def scope_of(filename: str) -> str:
    folded = filename.replace("\\", "/").lower()
    if "/old_road/" in folded:
        return "old_road"
    if "/scenario/" in folded:
        return "scenario"
    return "other"


def _add_say(node, identifier: str, index: int, label: str, source_name: str, acc: list[dict]) -> None:
    interact = getattr(node, "interact", True)
    if interact is False:
        return
    who = _text(getattr(node, "who", "") or "").strip()
    what = _text(getattr(node, "what", "") or "")
    filename = _text(getattr(node, "filename", "") or source_name)
    line_number = getattr(node, "linenumber", 0) or 0
    say_id = identifier
    if index:
        say_id = f"{identifier}_{index}"
    if not say_id:
        digest = hashlib.sha1(f"{filename}:{line_number}:{who}:{what}".encode("utf-8")).hexdigest()[:12]
        say_id = f"missing_{digest}"
    acc.append(
        {
            "id": say_id,
            "speaker": who,
            "text_raw": what,
            "filename": filename,
            "line_number": int(line_number),
            "label": label,
            "scope": scope_of(filename or source_name),
            "identifier_missing": not bool(identifier),
        }
    )


def _voice_dialogue(node) -> str | None:
    """Текст реплики «Голос», если строка не указывает на готовый звуковой файл."""
    line = _text(getattr(node, "line", "") or "").strip()
    match = _VOICE_DIALOGUE.match(line)
    if not match:
        return None
    body = match.group("body").strip()
    folded = body.lower()
    if not body or folded.endswith(_AUDIO_SUFFIXES) or "/" in body or "\\" in body:
        return None
    return body


def _add_voice_line(text: str, identifier: str, index: int, label: str, source_name: str, node, acc: list[dict]) -> None:
    say_id = identifier
    if index:
        say_id = f"{identifier}_{index}"
    filename = _text(getattr(node, "filename", "") or source_name)
    line_number = getattr(node, "linenumber", 0) or 0
    if not say_id:
        digest = hashlib.sha1(f"{filename}:{line_number}:voice:{text}".encode("utf-8")).hexdigest()[:12]
        say_id = f"missing_{digest}"
    acc.append(
        {
            "id": say_id,
            "speaker": "voice",
            "text_raw": text,
            "filename": filename,
            "line_number": int(line_number),
            "label": label,
            "scope": scope_of(filename or source_name),
            "identifier_missing": not bool(identifier),
        }
    )


def _walk(nodes, label: str, source_name: str, acc: list[dict], seen: set[int]) -> None:
    if not isinstance(nodes, (list, tuple)):
        return
    for node in nodes:
        if node is None or isinstance(node, (str, bytes, int, float)):
            continue
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        kind = _kind(node)
        if kind == "Label":
            name = _text(getattr(node, "name", "") or "")
            hide = bool(getattr(node, "hide", False))
            next_label = label
            if name and not hide and not name.startswith("_"):
                next_label = name
            _walk(getattr(node, "block", None), next_label, source_name, acc, seen)
            continue
        if kind == "Translate":
            identifier = _text(getattr(node, "identifier", "") or "")
            block = getattr(node, "block", None) or []
            say_index = 0
            for child in block:
                if isinstance(child, (str, bytes, int, float)) or child is None:
                    continue
                if _kind(child) == "Say":
                    _add_say(child, identifier, say_index, label, source_name, acc)
                    say_index += 1
                elif _kind(child) == "UserStatement" and (spoken := _voice_dialogue(child)) is not None:
                    _add_voice_line(spoken, identifier, say_index, label, source_name, child, acc)
                    say_index += 1
                else:
                    _walk([child], label, source_name, acc, seen)
            continue
        for attr in _BLOCK_ATTRS:
            _walk(getattr(node, attr, None), label, source_name, acc, seen)
        for attr in _SEQ_ATTRS:
            seq = getattr(node, attr, None)
            if not isinstance(seq, (list, tuple)):
                continue
            for item in seq:
                if isinstance(item, (list, tuple)):
                    for part in item:
                        if isinstance(part, list):
                            _walk(part, label, source_name, acc, seen)
                elif hasattr(item, "__dict__") or hasattr(type(item), "__slots__"):
                    _walk([item], label, source_name, acc, seen)


def extract_file(path: Path) -> tuple[list[dict], int]:
    _data, statements, slot = load_ast(path)
    found: list[dict] = []
    _walk(statements, "", path.name, found, set())
    return found, slot


def init_catalog(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lines (
            id TEXT PRIMARY KEY,
            speaker TEXT,
            text_raw TEXT,
            text_tts TEXT,
            filename TEXT,
            line_number INTEGER,
            label TEXT,
            scope TEXT,
            identifier_missing INTEGER,
            text_hash TEXT
        )
        """
    )
    conn.commit()
    return conn


def save_lines(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(
        """
        INSERT INTO lines (
            id, speaker, text_raw, text_tts, filename, line_number, label, scope,
            identifier_missing, text_hash
        ) VALUES (
            :id, :speaker, :text_raw, :text_tts, :filename, :line_number, :label, :scope,
            :identifier_missing, :text_hash
        )
        ON CONFLICT(id) DO UPDATE SET
            speaker=excluded.speaker,
            text_raw=excluded.text_raw,
            text_tts=excluded.text_tts,
            filename=excluded.filename,
            line_number=excluded.line_number,
            label=excluded.label,
            scope=excluded.scope,
            identifier_missing=excluded.identifier_missing,
            text_hash=excluded.text_hash
        """,
        rows,
    )
    conn.commit()


def summary(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
    by_scope = dict(conn.execute("SELECT scope, COUNT(*) FROM lines GROUP BY scope"))
    by_speaker = conn.execute(
        "SELECT speaker, COUNT(*) AS n FROM lines GROUP BY speaker ORDER BY n DESC LIMIT 25"
    ).fetchall()
    missing = conn.execute("SELECT COUNT(*) FROM lines WHERE identifier_missing=1").fetchone()[0]
    files = conn.execute("SELECT COUNT(DISTINCT filename) FROM lines").fetchone()[0]
    return {
        "total": total,
        "by_scope": by_scope,
        "top_speakers": by_speaker,
        "missing_ids": missing,
        "files": files,
    }


def speaker_counter(rows: list[dict]) -> Counter:
    return Counter(row["speaker"] or "(рассказчик)" for row in rows)

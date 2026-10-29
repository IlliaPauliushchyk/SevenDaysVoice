"""Подготовка текста к синтезу. Исходная реплика не переписывается по смыслу."""

from __future__ import annotations

import re
from pathlib import Path

from num2words import num2words

_TAG = re.compile(r"\{/?[^{}]*\}")
_WAIT = re.compile(r"\{(?:w|p)(?:=[^}]*)?\}")
_INTERP = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)(?:![A-Za-z]+)?\]")
_NUMBER = re.compile(r"(?<![\w.])(\d{1,6})(?![\w.])")
_SPACE = re.compile(r"\s+")

_ABBREVIATIONS = (
    ("и т. д.", "и так далее"),
    ("и т.д.", "и так далее"),
    ("т. д.", "так далее"),
    ("т.д.", "так далее"),
    ("т. п.", "тому подобное"),
    ("т.п.", "тому подобное"),
    ("т. е.", "то есть"),
    ("т.е.", "то есть"),
    ("т. к.", "так как"),
    ("т.к.", "так как"),
)

_MEET = re.compile(r"meet\(\s*'([A-Za-z0-9_]+)'\s*,\s*u?\"(.*?)\"\s*\)")


def load_known_names(scripts_rpy: Path) -> dict[str, str]:
    """Имена из make_names_known_7dl. Плейсхолдеры без букв не подставляются."""
    text = scripts_rpy.read_text(encoding="utf-8")
    marker = "def make_names_known_7dl"
    start = text.find(marker)
    if start < 0:
        return {}
    end = text.find("\n    def ", start + len(marker))
    body = text[start:end if end > 0 else None]
    names: dict[str, str] = {}
    for tag, raw in _MEET.findall(body):
        name = raw.encode("utf-8").decode("unicode_escape") if "\\u" in raw else raw
        if re.search(r"[A-Za-zА-Яа-яЁё]", name):
            names[tag] = name
    return names


def _number_to_words(match: re.Match[str]) -> str:
    return num2words(int(match.group(1)), lang="ru")


def normalize_for_tts(text: str, names: dict[str, str] | None = None) -> str:
    """Правила произношения. Смысл фразы не заменяется синонимами."""
    names = names or {}
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WAIT.sub(", ", cleaned)
    cleaned = _TAG.sub("", cleaned)

    def replace_interp(match: re.Match[str]) -> str:
        key = match.group(1)
        if key.endswith("_name"):
            key = key[: -len("_name")]
        value = names.get(key, "")
        if not re.search(r"[A-Za-zА-Яа-яЁё]", value):
            return ""
        return value

    cleaned = _INTERP.sub(replace_interp, cleaned)
    for source, spoken in _ABBREVIATIONS:
        cleaned = cleaned.replace(source, spoken)
    cleaned = _NUMBER.sub(_number_to_words, cleaned)
    cleaned = cleaned.replace("…", "...")
    cleaned = _SPACE.sub(" ", cleaned).strip(" \t,")
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?;:]){2,}", r"\1", cleaned)
    return cleaned.strip()


def split_for_speech(text: str, limit: int = 420) -> list[str]:
    """Длинная реплика режется по предложениям, слова не дробятся."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(sentence), limit):
                part = sentence[start : start + limit].strip()
                if part:
                    chunks.append(part)
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks

"""Общий результат подготовки движка."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Speaker:
    engine: str
    voice_id: str
    label: str
    native_language: str = ""
    emotion_in_docs: str = "не заявлено"


@dataclass
class EngineStatus:
    name: str
    ok: bool
    detail: str
    license_note: str = ""
    emotion_in_docs: str = "не заявлено"
    device: str = ""
    speakers: list[Speaker] = field(default_factory=list)
    vram_mb: float | None = None

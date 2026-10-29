"""Пути проекта. Корень считается от этого файла, а не от диска."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_config() -> dict:
    config_path = ROOT / "config" / "paths.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Нет файла конфигурации: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    required = ("game_path", "mod_path")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise KeyError("В config/paths.json не хватает: " + ", ".join(missing))
    return data


def ensure_runtime_dirs() -> None:
    """Каталоги кэша моделей остаются внутри проекта."""
    models = ROOT / "models"
    os.environ.setdefault("HF_HOME", str(models / "huggingface"))
    os.environ.setdefault("HF_HUB_CACHE", str(models / "huggingface" / "hub"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(models / "huggingface" / "hub"))
    os.environ.setdefault("TORCH_HOME", str(models / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(models / "cache"))
    for path in (
        models,
        models / "huggingface",
        models / "torch",
        models / "piper",
        models / "licenses",
        ROOT / "data",
        ROOT / "logs",
        ROOT / "generated_audio",
        ROOT / "generated_audio" / "voice_comparison",
    ):
        path.mkdir(parents=True, exist_ok=True)


class ProjectPaths:
    def __init__(self) -> None:
        ensure_runtime_dirs()
        raw = _load_config()
        self.root = ROOT
        self.game = Path(raw["game_path"])
        self.mod = Path(raw["mod_path"])
        self.audio = self.root / "generated_audio"
        self.scenario = self.mod / "scenario_alt"
        self.config_dir = self.root / "config"
        self.data = self.root / "data"
        self.logs = self.root / "logs"
        self.models = self.root / "models"
        self.catalog = self.data / "catalog.sqlite"
        self.tts_config = self.config_dir / "tts.json"
        self.voices_config = self.config_dir / "voices.json"

    def require_game_and_mod(self) -> None:
        if not self.game.is_dir():
            raise FileNotFoundError(f"Каталог игры не найден: {self.game}")
        if not self.mod.is_dir():
            raise FileNotFoundError(f"Каталог мода не найден: {self.mod}")
        if not self.scenario.is_dir():
            raise FileNotFoundError(f"В моде нет scenario_alt: {self.scenario}")


def get_paths() -> ProjectPaths:
    return ProjectPaths()

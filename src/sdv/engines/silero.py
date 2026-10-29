"""Silero TTS v5.6, русский. Вопросы и восклицания читаются по знакам."""

from __future__ import annotations

import gc

import numpy as np

from sdv.audio_util import to_mono_float
from sdv.engines.base import EngineStatus, Speaker
from sdv.normalize import split_for_speech
from sdv.paths import get_paths

SPEAKERS = (
    Speaker("silero", "aidar", "aidar, мужской", "русский", "вопрос и восклицание по знакам"),
    Speaker("silero", "eugene", "eugene, мужской", "русский", "вопрос и восклицание по знакам"),
    Speaker("silero", "baya", "baya, женский", "русский", "вопрос и восклицание по знакам"),
    Speaker("silero", "kseniya", "kseniya, женский", "русский", "вопрос и восклицание по знакам"),
    Speaker("silero", "xenia", "xenia, женский", "русский", "вопрос и восклицание по знакам"),
)


class SileroEngine:
    name = "silero"
    model_id = "v5_6_ru"

    def __init__(self) -> None:
        self.model = None
        self.device = "cpu"
        self.sample_rate = 48000

    def prepare(self) -> EngineStatus:
        import torch

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, _example = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker=self.model_id,
            trust_repo=True,
        )
        self.model.to(torch.device(self.device))
        return EngineStatus(
            name=self.name,
            ok=True,
            detail="Silero v5.6 ru загружена. Ударения: put_accent, put_yo, put_stress_homo, put_yo_homo.",
            license_note="Текст лицензии сохранён в models/licenses, если файл скачался.",
            emotion_in_docs="вопросы и восклицания читаются по знакам ? и !; отдельной команды грусти или злости нет",
            device=self.device,
            speakers=list(SPEAKERS),
        )

    def synthesize(self, text: str, voice_id: str, instruct: str | None = None) -> tuple[np.ndarray, int]:
        del instruct  # интонация берётся из знаков текста, не из отдельной команды
        import torch

        parts = []
        for chunk in split_for_speech(text):
            audio = self.model.apply_tts(
                text=chunk,
                speaker=voice_id,
                sample_rate=self.sample_rate,
                put_accent=True,
                put_yo=True,
                put_stress_homo=True,
                put_yo_homo=True,
            )
            array, _rate = to_mono_float(audio.detach().cpu().numpy() if torch.is_tensor(audio) else audio, self.sample_rate)
            parts.append(array)
        from sdv.audio_util import concat_with_pause

        return concat_with_pause(parts, self.sample_rate), self.sample_rate

    def close(self) -> None:
        self.model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def license_url() -> str:
    return "https://raw.githubusercontent.com/snakers4/silero-models/master/LICENSE"


def cache_dir() -> str:
    return str(get_paths().models / "torch")

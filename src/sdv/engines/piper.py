"""Piper, русские голоса ru_RU medium."""

from __future__ import annotations

import io
import shutil
import urllib.request
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

from sdv.audio_util import concat_with_pause, to_mono_float
from sdv.engines.base import EngineStatus, Speaker
from sdv.normalize import split_for_speech
from sdv.paths import get_paths

VOICES = (
    ("denis", "denis, мужской"),
    ("dmitri", "dmitri, мужской"),
    ("ruslan", "ruslan, мужской"),
    ("irina", "irina, женский"),
)
_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/{name}/medium/ru_RU-{name}-medium"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "SevenDaysVoice/0.1"})
    with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


class PiperEngine:
    name = "piper"

    def __init__(self) -> None:
        self.voices = {}

    def prepare(self) -> EngineStatus:
        from piper import PiperVoice

        folder = get_paths().models / "piper"
        speakers = []
        cards = []
        for name, label in VOICES:
            model = folder / f"ru_RU-{name}-medium.onnx"
            config = folder / f"ru_RU-{name}-medium.onnx.json"
            _download(f"{_BASE.format(name=name)}.onnx", model)
            _download(f"{_BASE.format(name=name)}.onnx.json", config)
            card_text = ""
            for card_name in ("MODEL_CARD", "MODEL_CARD.md", "README.md"):
                card = folder / f"ru_RU-{name}-medium.{card_name}"
                try:
                    _download(
                        f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/{name}/medium/{card_name}",
                        card,
                    )
                    card_text = card.read_text(encoding="utf-8", errors="replace")[:800]
                    break
                except Exception:
                    card_text = ""
            cards.append(f"{name}: {card_text or 'карточка MODEL_CARD в репозитории голоса не найдена'}")
            try:
                self.voices[name] = PiperVoice.load(str(model), config_path=str(config))
            except TypeError:
                self.voices[name] = PiperVoice.load(str(model))
            speakers.append(Speaker(self.name, name, label, "русский", "нет в документации Piper"))
        note = "\n".join(cards)
        (get_paths().models / "licenses" / "piper_model_cards.txt").write_text(note, encoding="utf-8")
        return EngineStatus(
            name=self.name,
            ok=True,
            detail="Четыре голоса ru_RU medium. Скорость оставлена штатной, length_scale не подкручивался.",
            license_note="В MODEL_CARD четырёх голосов поле License: Unknown, датасет RHVoice. Платы за символ в карточке нет. Текст: models/licenses/piper_model_cards.txt",
            emotion_in_docs="отдельного управления эмоцией в документации Piper нет",
            device="cpu",
            speakers=speakers,
        )

    def synthesize(self, text: str, voice_id: str, instruct: str | None = None) -> tuple[np.ndarray, int]:
        del instruct
        voice = self.voices[voice_id]
        parts = []
        rate = 22050
        for chunk in split_for_speech(text):
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                if hasattr(voice, "synthesize_wav"):
                    voice.synthesize_wav(chunk, wav_file)
                else:
                    voice.synthesize(chunk, wav_file)
            buffer.seek(0)
            audio, rate = sf.read(buffer, dtype="float32")
            array, rate = to_mono_float(audio, rate)
            parts.append(array)
        return concat_with_pause(parts, rate), rate

    def close(self) -> None:
        self.voices.clear()

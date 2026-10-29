"""Qwen3-TTS. Эмоция проверяется только там, где модели передана инструкция."""

from __future__ import annotations

import gc
import os

import numpy as np

from sdv.audio_util import concat_with_pause, to_mono_float
from sdv.engines.base import EngineStatus, Speaker
from sdv.normalize import split_for_speech
from sdv.paths import get_paths


def _load_source(repo_id: str) -> str:
    """Локальный снимок Hugging Face, если большой файл уже лежит на диске."""
    plain = get_paths().models / "qwen" / repo_id.split("/")[-1]
    plain_model = plain / "model.safetensors"
    if plain_model.is_file() and plain_model.stat().st_size > 100_000_000:
        return str(plain)
    folder = "models--" + repo_id.replace("/", "--")
    root = get_paths().models / "huggingface" / "hub" / folder / "snapshots"
    if not root.is_dir():
        return repo_id
    best = None
    best_size = 0
    for child in root.iterdir():
        model = child / "model.safetensors"
        if not model.is_file():
            continue
        size = model.stat().st_size
        if size > best_size:
            best = child
            best_size = size
    if best is not None and best_size > 100_000_000:
        return str(best)
    return repo_id

DOCUMENTED_SPEAKERS = (
    ("Vivian", "Vivian, молодой женский", "китайский"),
    ("Serena", "Serena, мягкий женский", "китайский"),
    ("Uncle_Fu", "Uncle_Fu, низкий мужской", "китайский"),
    ("Dylan", "Dylan, молодой мужской", "китайский"),
    ("Eric", "Eric, мужской", "китайский"),
    ("Ryan", "Ryan, мужской", "английский"),
    ("Aiden", "Aiden, мужской", "английский"),
    ("Ono_Anna", "Ono_Anna, женский", "японский"),
    ("Sohee", "Sohee, женский", "корейский"),
)


class QwenEngine:
    name = "qwen3"

    def __init__(self) -> None:
        self.model = None
        self.model_id = ""
        self.instruct_supported = False
        self.language = "Russian"
        self.sample_rate = 24000

    def prepare(self) -> EngineStatus:
        import torch
        from qwen_tts import Qwen3TTSModel

        if not torch.cuda.is_available():
            return EngineStatus(
                name=self.name,
                ok=False,
                detail="CUDA нет. Qwen3-TTS для полного мода на CPU не запускался.",
                emotion_in_docs="у 1.7B CustomVoice в документации есть instruct",
                device="cpu",
            )
        errors = []
        for model_id, instruct in (
            ("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", True),
            ("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", False),
        ):
            try:
                source = _load_source(model_id)
                local = source != model_id
                if local:
                    os.environ["HF_HUB_OFFLINE"] = "1"
                self.model = Qwen3TTSModel.from_pretrained(
                    source,
                    device_map="cuda:0",
                    dtype=torch.bfloat16,
                    attn_implementation="sdpa",
                    local_files_only=local,
                )
                self.model_id = model_id
                self.instruct_supported = instruct
                os.environ.pop("HF_HUB_OFFLINE", None)
                break
            except RuntimeError as exc:
                os.environ.pop("HF_HUB_OFFLINE", None)
                errors.append(f"{model_id}: {exc}")
                self.close()
                if "out of memory" not in str(exc).lower() and "cuda" not in str(exc).lower():
                    raise
        if self.model is None:
            return EngineStatus(
                name=self.name,
                ok=False,
                detail=" ; ".join(errors) or "модель не загрузилась",
                emotion_in_docs="у 1.7B CustomVoice в документации есть instruct",
                device="cuda",
            )
        names = []
        try:
            found = self.model.get_supported_speakers()
            names = list(found) if found else []
        except Exception:
            names = []
        if not names:
            names = [item[0] for item in DOCUMENTED_SPEAKERS]
        known = {item[0].lower(): item for item in DOCUMENTED_SPEAKERS}
        speakers = []
        for name in names:
            _voice, label, native = known.get(str(name).lower(), (name, name, "не указан в таблице README"))
            speakers.append(
                Speaker(
                    self.name,
                    name,
                    label,
                    native,
                    "instruct есть в документации 1.7B" if self.instruct_supported else "у загруженной 0.6B в таблице моделей instruct не указан",
                )
            )
        langs: list[str] = []
        try:
            found_langs = self.model.get_supported_languages()
            langs = list(found_langs) if found_langs else []
        except Exception:
            langs = []
        folded = {str(item).lower(): str(item) for item in langs}
        if "russian" in folded:
            self.language = folded["russian"]
        elif "ru" in folded:
            self.language = folded["ru"]
        elif "auto" in folded:
            self.language = folded["auto"]
        else:
            self.language = "Auto"
        detail = (
            f"Загружена {self.model_id}. Родные языки дикторов не русские. "
            f"Параметр language для синтеза: {self.language}. Список языков модели: {', '.join(langs) or 'не прочитан'}."
        )
        if errors:
            detail += " Предыдущая попытка не загрузилась: " + " ; ".join(errors)
        return EngineStatus(
            name=self.name,
            ok=True,
            detail=detail,
            license_note="Apache-2.0, репозиторий QwenLM/Qwen3-TTS",
            emotion_in_docs=speakers[0].emotion_in_docs if speakers else "",
            device="cuda",
            speakers=speakers,
        )

    def synthesize(self, text: str, voice_id: str, instruct: str | None = None) -> tuple[np.ndarray, int]:
        parts = []
        rate = self.sample_rate
        use_instruct = instruct if self.instruct_supported and instruct else None
        for chunk in split_for_speech(text, limit=280):
            kwargs = {
                "text": chunk,
                "language": self.language,
                "speaker": voice_id,
            }
            if use_instruct:
                kwargs["instruct"] = use_instruct
            wavs, rate = self.model.generate_custom_voice(**kwargs)
            audio = wavs[0]
            array, rate = to_mono_float(audio, int(rate))
            parts.append(array)
        return concat_with_pause(parts, rate), rate

    def close(self) -> None:
        self.model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


class QwenVoiceDesign:
    """Отдельная модель. Вызывается только после того, как CustomVoice уже дала звук."""

    def __init__(self) -> None:
        self.model = None
        self.language = "Russian"

    def prepare(self) -> str:
        import torch
        from qwen_tts import Qwen3TTSModel

        repo_id = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        source = _load_source(repo_id)
        local = source != repo_id
        if local:
            os.environ["HF_HUB_OFFLINE"] = "1"
        self.model = Qwen3TTSModel.from_pretrained(
            source,
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
            local_files_only=local,
        )
        os.environ.pop("HF_HUB_OFFLINE", None)
        langs: list[str] = []
        try:
            found_langs = self.model.get_supported_languages()
            langs = list(found_langs) if found_langs else []
        except Exception:
            langs = []
        folded = {str(item).lower(): str(item) for item in langs}
        if "russian" in folded:
            self.language = folded["russian"]
        elif "ru" in folded:
            self.language = folded["ru"]
        elif "auto" in folded:
            self.language = folded["auto"]
        return f"Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign, language={self.language}, языки модели: {', '.join(langs) or 'не прочитаны'}"

    def synthesize(self, text: str, instruct: str) -> tuple[np.ndarray, int]:
        parts = []
        rate = 24000
        for chunk in split_for_speech(text, limit=280):
            wavs, rate = self.model.generate_voice_design(
                text=chunk,
                language=self.language,
                instruct=instruct,
            )
            array, rate = to_mono_float(wavs[0], int(rate))
            parts.append(array)
        return concat_with_pause(parts, rate), rate

    def close(self) -> None:
        self.model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

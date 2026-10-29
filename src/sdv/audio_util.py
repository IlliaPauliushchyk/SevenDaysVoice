"""Запись wav/ogg и выравнивание громкости."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from imageio_ffmpeg import get_ffmpeg_exe


def to_mono_float(audio, sample_rate: int) -> tuple[np.ndarray, int]:
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    array = np.asarray(audio)
    if array.ndim == 2:
        array = array.mean(axis=1 if array.shape[0] > array.shape[1] else 0)
    array = array.astype(np.float32).reshape(-1)
    peak = float(np.max(np.abs(array))) if array.size else 0.0
    if peak > 1.5:
        array = array / 32768.0
    return array, int(sample_rate)


def peak_normalize(audio: np.ndarray, target: float = 0.89) -> np.ndarray:
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-5:
        return audio
    scaled = audio * (target / peak)
    return np.clip(scaled, -1.0, 1.0)


def concat_with_pause(parts: list[np.ndarray], sample_rate: int, pause_sec: float = 0.12) -> np.ndarray:
    if not parts:
        return np.zeros(0, dtype=np.float32)
    gap = np.zeros(int(sample_rate * pause_sec), dtype=np.float32)
    chunks: list[np.ndarray] = []
    for index, part in enumerate(parts):
        if index:
            chunks.append(gap)
        chunks.append(part.astype(np.float32))
    return np.concatenate(chunks)


def write_ogg(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = peak_normalize(audio)
    wav_path = path.with_suffix(".tmp.wav")
    sf.write(wav_path, audio, sample_rate)
    try:
        subprocess.run(
            [
                get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-c:a",
                "libvorbis",
                "-q:a",
                "4",
                str(path),
            ],
            check=True,
        )
    finally:
        wav_path.unlink(missing_ok=True)

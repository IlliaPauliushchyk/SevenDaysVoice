"""Копирует два новых файла в каталог игры. Существующие файлы игры не перезаписывает."""

from __future__ import annotations

import shutil
from pathlib import Path

from sdv.paths import get_paths


def main() -> None:
    paths = get_paths()
    paths.require_game_and_mod()
    game = paths.game / "game"
    if not game.is_dir():
        raise SystemExit(f"Нет каталога game: {game}")
    source = paths.root / "integration" / "sdv_autoload.rpy"
    target_rpy = game / "sdv_autoload.rpy"
    target_txt = game / "sdv_voice_path.txt"
    for path in (target_rpy, target_txt):
        if path.exists():
            raise SystemExit(f"Файл уже есть, установка остановлена: {path}")
    shutil.copyfile(source, target_rpy)
    target_txt.write_text(str(paths.audio) + "\n", encoding="utf-8")
    print("Добавлены только sdv_autoload.rpy и sdv_voice_path.txt.")
    print("Откат: rollback.bat")


if __name__ == "__main__":
    main()

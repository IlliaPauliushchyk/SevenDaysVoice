"""Запуск игры с внешней папкой озвучки. Каталог игры не меняется."""

from __future__ import annotations

import os
import subprocess

from sdv.paths import get_paths


def main() -> None:
    paths = get_paths()
    paths.require_game_and_mod()
    exe = paths.game / "Everlasting Summer.exe"
    if not exe.is_file():
        raise SystemExit(f"Нет файла запуска: {exe}")
    env = os.environ.copy()
    env["SDV_AUDIO"] = str(paths.audio)
    env["RENPY_SEARCHPATH"] = str(paths.root / "integration")
    subprocess.Popen([str(exe)], cwd=str(paths.game), env=env)
    print("Игра запущена. Файлы в каталоге игры не копировались.")
    print("Кнопка Play в Steam этот путь не подхватывает.")


if __name__ == "__main__":
    main()

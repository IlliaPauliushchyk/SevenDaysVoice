"""Удаляет только файлы интеграции SevenDaysVoice из каталога игры."""

from __future__ import annotations

from sdv.paths import get_paths

_NAMES = ("sdv_autoload.rpy", "sdv_voice_path.txt")


def main() -> None:
    paths = get_paths()
    game = paths.game / "game"
    if not game.is_dir():
        raise SystemExit(f"Нет каталога game: {game}")
    removed = []
    for name in _NAMES:
        path = game / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    if removed:
        print("Удалены: " + ", ".join(removed))
    else:
        print("Файлов интеграции в каталоге игры нет. Сохранения и сценарии не менялись.")


if __name__ == "__main__":
    main()

"""Сборка каталога реплик и отчёта об устройстве сценария."""

from __future__ import annotations

import hashlib
import traceback
from pathlib import Path

from sdv.extract_lines import extract_file, init_catalog, save_lines, summary
from sdv.normalize import load_known_names, normalize_for_tts
from sdv.paths import get_paths


def _report(paths, info: dict, failures: list[str], names: dict[str, str]) -> str:
    speakers = "\n".join(f"- `{speaker or '(рассказчик)'}`: {count}" for speaker, count in info["top_speakers"])
    scopes = "\n".join(f"- {name}: {count}" for name, count in sorted(info["by_scope"].items()))
    failure_text = "\n".join(f"- {item}" for item in failures) if failures else "- нет"
    return f"""# Отчёт об устройстве сценария «7 Дней Лета: Lost Alpha»

Игра и мод только читались. Файлы игры и мода не изменялись.

## Где что лежит

- Игра: `{paths.game}`
- Мод: `{paths.mod}`
- Ren'Py в журнале игры: 7.4.11.2266
- Сценарий мода: `{paths.scenario}`
- Исходники `.rpy` лежат рядом с `.rpyc`. Архивов `.rpa` в моде нет.
- Озвучки реплик в моде нет. В `Sound` только музыка, эмбиент и эффекты.

## Как берутся реплики

Читается слот 2 файла `.rpyc`. Это уже собранное дерево Ren'Py, в нём у блока перевода есть translate identifier. Имя будущего аудиофайла совпадает с этим идентификатором, потому что `config.auto_voice` получает именно его.

Повторно компилировать `.rpy` нельзя: игра при загрузке более нового исходника перезаписывает `.rpyc` в каталоге мода.

В каталог попадают узлы `Say` с показом реплики. Меню, экраны и Python не берутся. Одинаковый текст в разных местах остаётся разными строками, ключ — identifier, не текст.

## Сколько реплик нашлось

- Файлов с репликами: {info["files"]}
- Всего реплик: {info["total"]}
- Без настоящего identifier: {info["missing_ids"]}

По областям:

{scopes}

Частые говорящие:

{speakers}

Известные имена для подстановки `[имя]` взяты из `make_names_known_7dl`: {len(names)} персонажей. Имя «девушки из сна» в сценарии задано многоточием, поэтому в речь оно не подставляется.

По умолчанию синтез рассчитан на область `scenario` (основной сюжет). `old_road` проиндексирован и в очередь не входит, пока это явно не включено.

## Что не прочиталось

{failure_text}

Каталог: `{paths.catalog}`
"""


def main() -> None:
    paths = get_paths()
    paths.require_game_and_mod()
    names = load_known_names(paths.scenario / "Config" / "res" / "7dl_scripts.rpy")
    conn = init_catalog(paths.catalog)
    failures: list[str] = []
    batch: list[dict] = []
    rpyc_files = sorted(paths.scenario.rglob("*.rpyc"))
    for path in rpyc_files:
        try:
            rows, _slot = extract_file(path)
        except Exception as exc:  # noqa: BLE001 — один битый файл не останавливает разбор
            failures.append(f"{path.name}: {exc}")
            traceback.print_exc()
            continue
        for row in rows:
            row["text_tts"] = normalize_for_tts(row["text_raw"], names)
            row["text_hash"] = hashlib.sha256(row["text_tts"].encode("utf-8")).hexdigest()
            row["identifier_missing"] = 1 if row["identifier_missing"] else 0
            batch.append(row)
        if len(batch) >= 2000:
            save_lines(conn, batch)
            batch.clear()
    if batch:
        save_lines(conn, batch)
    info = summary(conn)
    report = _report(paths, info, failures, names)
    report_path = paths.root / "analysis_report.md"
    report_path.write_text(report, encoding="utf-8")
    log_path = paths.logs / "extract.log"
    log_path.write_text(report, encoding="utf-8")
    print(f"Реплик: {info['total']}. Отчёт: {report_path}")
    if failures:
        print(f"Файлов с ошибкой чтения: {len(failures)}. Подробности в отчёте.")


if __name__ == "__main__":
    main()

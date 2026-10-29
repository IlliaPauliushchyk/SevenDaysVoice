"""Сравнение моделей на одних и тех же репликах. Победителя за пользователя не выбирает."""

from __future__ import annotations

import html
import json
import sqlite3
import time
import traceback
import urllib.request
from pathlib import Path

import numpy as np

from sdv.audio_util import write_ogg
from sdv.engines.cosyvoice import CosyVoiceEngine
from sdv.engines.piper import PiperEngine
from sdv.engines.qwen import QwenEngine, QwenVoiceDesign
from sdv.engines.silero import SileroEngine, license_url as silero_license_url
from sdv.paths import get_paths

EMOTION_INSTRUCT = "Скажи по-русски эмоционально и живее, с заметной интонацией, не меняя слов."
DESIGN_VOICES = (
    ("design_male", "Молодой мужской голос, спокойный рассказчик, чистый русский выговор, средняя высота."),
    ("design_female", "Молодой женский голос, мягкий, чистый русский выговор, чуть выше среднего."),
)


def _fetch_text(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "SevenDaysVoice/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    dest.write_bytes(data)
    return data.decode("utf-8", "replace")


def _license_label(name: str, text: str) -> str:
    head = text[:500].lower()
    if "attribution-noncommercial-sharealike" in head or "by-nc-sa" in head:
        return (
            "CC-BY-NC-SA 4.0, файл models/licenses. Это не плата за символ, "
            "но лицензия некоммерческая, с указанием авторства и share-alike."
        )
    if "apache license" in head:
        return "Apache-2.0, файл models/licenses. Платы за символ в тексте нет."
    if "mit license" in head:
        return "MIT, файл models/licenses. Платы за символ в тексте нет."
    return f"{name}: оплаты за символ в начале файла нет, полный текст в models/licenses."


def _payment_required(text: str) -> bool:
    folded = text.lower()
    markers = (
        "subscription required",
        "paid api",
        "pay per character",
        "requires payment",
        "purchase a license",
    )
    return any(marker in folded for marker in markers)


def save_known_licenses() -> dict[str, str]:
    paths = get_paths()
    notes = {}
    sources = {
        "silero": silero_license_url(),
        "qwen3": "https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/LICENSE",
        "cosyvoice3": "https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/LICENSE",
    }
    for name, url in sources.items():
        dest = paths.models / "licenses" / f"{name}_LICENSE.txt"
        try:
            text = _fetch_text(url, dest)
        except Exception as exc:  # noqa: BLE001
            notes[name] = f"текст лицензии не скачался: {exc}"
            continue
        if _payment_required(text):
            notes[name] = "в тексте лицензии есть требование оплаты, модель для массовой генерации не используется"
        else:
            notes[name] = _license_label(name, text)
    return notes


def pick_lines(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, speaker, text_raw, text_tts, filename, line_number
            FROM lines
            WHERE scope='scenario'
              AND identifier_missing=0
              AND length(text_tts) BETWEEN 15 AND 520
            ORDER BY filename, line_number
            """
        )
    ]
    text_rows = [row for row in rows if "/Text/" in row["filename"].replace("\\", "/")]
    if len(text_rows) >= 30:
        rows = text_rows
    picked: list[dict] = []
    used: set[str] = set()

    def take(kind: str, predicate, limit: int) -> None:
        found = 0
        for row in rows:
            if row["id"] in used or not predicate(row):
                continue
            item = dict(row)
            item["kind"] = kind
            picked.append(item)
            used.add(row["id"])
            found += 1
            if found >= limit:
                return

    take("narration", lambda row: row["speaker"] == "" and "?" not in row["text_tts"] and "!" not in row["text_tts"], 2)
    take("question", lambda row: "?" in row["text_tts"] and row["speaker"] not in {"", "th"}, 2)
    take("emotional", lambda row: "!" in row["text_tts"] and row["speaker"] not in {"", "th"}, 2)
    take("long", lambda row: len(row["text_tts"]) >= 220, 1)
    take("thought", lambda row: row["speaker"] == "th", 2)
    for speaker in ("me", "dv", "sl", "un", "us", "mi", "mt", "dreamgirl"):
        take(f"dialogue_{speaker}", lambda row, speaker=speaker: row["speaker"] == speaker, 1)
    for row in rows:
        if len(picked) >= 18:
            break
        if row["id"] in used:
            continue
        item = dict(row)
        item["kind"] = "extra"
        picked.append(item)
        used.add(row["id"])
    return picked[:18]


def _safe(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    return cleaned[:80] or "line"


def _reset_vram() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        return


def _vram_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
    except Exception:
        return None


def _run_speaker(engine, speaker_id: str, lines: list[dict], out_dir: Path, instruct_for_emotional: str | None, rows: list[dict]) -> None:
    for line in lines:
        variants = [(None, "")]
        if instruct_for_emotional and line["kind"] == "emotional":
            variants.append((instruct_for_emotional, "__instruct"))
        for instruct, suffix in variants:
            rel = Path(engine.name) / _safe(speaker_id) / f"{_safe(line['id'])}{suffix}.ogg"
            dest = out_dir / rel
            started = time.perf_counter()
            error = ""
            ok = False
            try:
                audio, rate = engine.synthesize(line["text_tts"], speaker_id, instruct)
                if audio.size == 0 or float(np.max(np.abs(audio))) < 0.01:
                    error = "файл почти без звука"
                else:
                    write_ogg(dest, audio, rate)
                    ok = True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                traceback.print_exc()
            rows.append(
                {
                    "engine": engine.name,
                    "voice": speaker_id,
                    "line_id": line["id"],
                    "kind": line["kind"],
                    "speaker": line["speaker"],
                    "seconds": round(time.perf_counter() - started, 3),
                    "ok": ok,
                    "error": error,
                    "relpath": str(rel).replace("\\", "/") if ok else "",
                    "instruct": instruct or "",
                }
            )


def render_html(lines: list[dict], rows: list[dict], dest: Path) -> None:
    by_line: dict[str, list[dict]] = {}
    for row in rows:
        by_line.setdefault(row["line_id"], []).append(row)
    parts = [
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>",
        "<title>Сравнение русской озвучки</title>",
        "<style>body{font-family:sans-serif;margin:24px;background:#111;color:#eee}",
        "section{border-top:1px solid #333;padding:16px 0} audio{display:block;margin:6px 0}",
        ".fail{color:#f99}</style></head><body>",
        "<h1>Одни и те же реплики мода разными моделями</h1>",
        "<p>Естественность здесь не оценена числом. Слушайте варианты и выберите движок сами. ",
        "Рекомендация в recommendation.md помечена как предложение, не как измерение.</p>",
    ]
    lookup = {line["id"]: line for line in lines}
    for line_id, items in by_line.items():
        line = lookup.get(line_id, {})
        parts.append("<section>")
        parts.append(f"<h2>{html.escape(line.get('kind', ''))}: {html.escape(line.get('speaker') or 'рассказчик')}</h2>")
        parts.append(f"<p>{html.escape(line.get('text_tts', ''))}</p>")
        for item in items:
            title = f"{item['engine']} / {item['voice']}"
            if item["instruct"]:
                title += " / описание тембра" if item["engine"] == "qwen3_design" else " / с инструкцией эмоции"
            if item["ok"]:
                parts.append(f"<div>{html.escape(title)} <audio controls src='{html.escape(item['relpath'])}'></audio></div>")
            else:
                parts.append(f"<div class='fail'>{html.escape(title)}: {html.escape(item['error'])}</div>")
        parts.append("</section>")
    parts.append("</body></html>")
    dest.write_text("\n".join(parts), encoding="utf-8")


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "/").replace("\n", " ")


def _table_row(status: dict, voice_id: str, seconds, emotion_run: str, count: int | str = 0) -> str:
    vram = status.get("vram_mb")
    if vram is None and "out of memory" in str(status.get("detail", "")).lower():
        vram_cell = "не влезла"
    else:
        vram_cell = vram if vram is not None else "—"
    return (
        "| {name} | {voice} | {device} | {vram} | {seconds} | {count} | {license} | {offline} | {limit} | {docs} | {run} | на слух | на слух |".format(
            name=_cell(status["name"]),
            voice=_cell(voice_id or "—"),
            device=_cell(status.get("device") or "—"),
            vram=_cell(vram_cell),
            seconds=_cell(seconds),
            count=_cell(count),
            license=_cell(status.get("license_note", "")),
            offline=_cell(status.get("offline", "")),
            limit=_cell(status.get("char_limit", "")),
            docs=_cell(status.get("emotion_in_docs", "")),
            run=_cell(emotion_run),
        )
    )


def render_table(statuses: list[dict], rows: list[dict], dest: Path) -> None:
    lines = [
        "# Сравнение моделей",
        "",
        "Колонки произношения и естественности намеренно оставлены для прослушивания. Программа их не заполняет.",
        "",
        "| Модель | Голос | Устройство | Пик VRAM, МБ | Средние секунды на удачную реплику | Удачных файлов | Лицензия и ограничения | Офлайн после скачивания | Лимит символов | Эмоция по документации | Эмоция в этом прогоне | Произношение | Естественность |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for status in statuses:
        voice_ids = [speaker["voice_id"] for speaker in status.get("speakers", [])]
        if not voice_ids:
            reason = "тест не запускался" if not status.get("ok") else "файлов нет"
            if not status.get("ok") and status.get("detail"):
                reason = f"{reason}. {status['detail']}"
            lines.append(_table_row(status, "—", "", reason))
            continue
        for voice_id in voice_ids:
            matched = [row for row in rows if row["engine"] == status["name"] and row["voice"] == voice_id and row["ok"] and not row["instruct"]]
            if status["name"] == "qwen3_design":
                matched = [row for row in rows if row["engine"] == status["name"] and row["voice"] == voice_id and row["ok"]]
            seconds = round(sum(row["seconds"] for row in matched) / len(matched), 3) if matched else ""
            emotion_run = "инструкция не передавалась"
            instructed = [row for row in rows if row["engine"] == status["name"] and row["voice"] == voice_id and row["instruct"]]
            if instructed:
                emotion_run = "файл с инструкцией синтезирован, на слух не оценён" if any(row["ok"] for row in instructed) else "инструкция передана, синтез не удался"
            if status["name"] == "qwen3_design":
                emotion_run = "описание тембра передано, на слух не оценено" if matched else "синтез не удался"
            lines.append(_table_row(status, voice_id, seconds, emotion_run, len(matched)))
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_recommendation(statuses: list[dict], dest: Path) -> None:
    ready = [item["name"] for item in statuses if item.get("ok")]
    failed = [f"{item['name']}: {item.get('detail')}" for item in statuses if not item.get("ok")]
    measured = []
    for item in statuses:
        if item.get("vram_mb") is not None:
            measured.append(f"- {item['name']}: пик выделенной видеопамяти {item['vram_mb']} МБ, устройство {item.get('device') or '—'}.")
        if item.get("detail"):
            measured.append(f"- {item['name']}: {item['detail']}")
    text = f"""# Предложение, не измерение

Это не оценка естественности. Числа в comparison.md говорят только о том, какая модель запустилась, сколько секунд заняла реплика и что написано в документации.

Запустились и дали файлы: {", ".join(ready) if ready else "ни одна"}.

Не запустились:

{chr(10).join("- " + item for item in failed) if failed else "- нет"}

Что измерено в этом прогоне:

{chr(10).join(measured) if measured else "- нет"}

Штатные дикторы Qwen3-TTS по таблице модели родные для китайского, английского, японского или корейского. Русский им задаётся параметром языка. Будет ли выговор приятным, слышно только в плеере. У Silero и Piper дикторы русские, отдельной эмоции в их документации нет.

Имеет смысл сначала слушать Qwen3, если эта строка есть среди запустившихся: у версии 1.7B в документации есть текстовая инструкция, и приоритет проекта — естественность, а не скорость. Если русский у Qwen звучит с чужим акцентом, среди русских штатных голосов сравнивайте Silero и Piper уже на слух. Программа этот выбор не делает.

Пока в config/tts.json стоит `"chosen_by_user": false`, массовая генерация не начнётся.
"""
    dest.write_text(text, encoding="utf-8")


def _status_dict(status, license_notes: dict[str, str]) -> dict:
    note = license_notes.get(status.name, status.license_note)
    return {
        "name": status.name,
        "ok": status.ok,
        "detail": status.detail,
        "license_note": note or status.license_note,
        "emotion_in_docs": status.emotion_in_docs,
        "device": status.device,
        "vram_mb": status.vram_mb,
        "offline": "да, после того как веса уже на диске" if status.ok or status.name != "cosyvoice3" else "модель не скачивалась",
        "char_limit": "отдельного лимита символов нет; длинная реплика режется на куски перед синтезом",
        "speakers": [{"voice_id": speaker.voice_id, "label": speaker.label} for speaker in status.speakers],
    }


def main() -> None:
    paths = get_paths()
    paths.require_game_and_mod()
    if not paths.catalog.is_file():
        raise SystemExit("Сначала запустите analyze.bat: каталога реплик ещё нет.")
    license_notes = save_known_licenses()
    if "оплаты" in license_notes.get("silero", "") and "не используется" in license_notes.get("silero", ""):
        raise SystemExit(license_notes["silero"])
    conn = sqlite3.connect(paths.catalog)
    lines = pick_lines(conn)
    if len(lines) < 10:
        raise SystemExit(f"Для сравнения нашлось только {len(lines)} реплик. Нужно не меньше 10.")
    manifest = paths.data / "comparison_lines.json"
    manifest.write_text(json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8")
    out_dir = paths.audio / "voice_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    statuses: list[dict] = []

    print(f"Реплик в сравнении: {len(lines)}")

    def save_outputs() -> None:
        (paths.data / "comparison_results.json").write_text(
            json.dumps({"statuses": statuses, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        render_html(lines, rows, out_dir / "index.html")
        render_table(statuses, rows, out_dir / "comparison.md")
        render_recommendation(statuses, out_dir / "recommendation.md")

    print("Silero: загрузка", flush=True)
    silero = SileroEngine()
    try:
        _reset_vram()
        status = silero.prepare()
        if status.ok:
            for speaker in status.speakers:
                print(f"Silero {speaker.voice_id}", flush=True)
                _run_speaker(silero, speaker.voice_id, lines, out_dir, None, rows)
            status.vram_mb = _vram_mb()
        statuses.append(_status_dict(status, license_notes))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        statuses.append(
            {
                "name": "silero",
                "ok": False,
                "detail": str(exc),
                "license_note": license_notes.get("silero", ""),
                "emotion_in_docs": "отдельного управления эмоцией в документации v4 нет",
                "device": "",
                "vram_mb": None,
                "offline": "веса могли остаться на диске, синтез не начался",
                "char_limit": "отдельного лимита символов нет",
                "speakers": [],
            }
        )
    finally:
        silero.close()
        save_outputs()

    print("Piper: загрузка", flush=True)
    piper = PiperEngine()
    try:
        status = piper.prepare()
        if status.ok:
            for speaker in status.speakers:
                print(f"Piper {speaker.voice_id}", flush=True)
                _run_speaker(piper, speaker.voice_id, lines, out_dir, None, rows)
        statuses.append(_status_dict(status, license_notes))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        statuses.append(
            {
                "name": "piper",
                "ok": False,
                "detail": str(exc),
                "license_note": license_notes.get("piper", ""),
                "emotion_in_docs": "отдельного управления эмоцией в документации Piper нет",
                "device": "cpu",
                "vram_mb": None,
                "offline": "синтез не начался",
                "char_limit": "отдельного лимита символов нет",
                "speakers": [],
            }
        )
    finally:
        piper.close()
        save_outputs()

    print("Qwen: загрузка CustomVoice", flush=True)
    qwen = QwenEngine()
    qwen_audio_ok = False
    try:
        _reset_vram()
        status = qwen.prepare()
        if status.ok:
            emotional_voices = {"ryan", "serena"}
            for speaker in status.speakers:
                print(f"Qwen {speaker.voice_id}", flush=True)
                instruct = EMOTION_INSTRUCT if speaker.voice_id.lower() in emotional_voices and "1.7B" in (qwen.model_id or "") else None
                _run_speaker(qwen, speaker.voice_id, lines, out_dir, instruct, rows)
            status.vram_mb = _vram_mb()
            qwen_audio_ok = any(row["ok"] and row["engine"] == "qwen3" for row in rows)
        statuses.append(_status_dict(status, license_notes))
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        statuses.append(
            {
                "name": "qwen3",
                "ok": False,
                "detail": str(exc),
                "license_note": license_notes.get("qwen3", ""),
                "emotion_in_docs": "у 1.7B CustomVoice в документации есть instruct",
                "device": "cuda",
                "vram_mb": _vram_mb(),
                "offline": "синтез не начался",
                "char_limit": "отдельного лимита символов нет",
                "speakers": [],
            }
        )
    finally:
        qwen.close()
        save_outputs()

    if qwen_audio_ok and "1.7B" in "".join(item.get("detail", "") for item in statuses):
        print("Qwen: загрузка VoiceDesign", flush=True)
        design = QwenVoiceDesign()
        design_status_ok = False
        detail = ""
        try:
            _reset_vram()
            detail = design.prepare()
            sample = [line for line in lines if line["kind"] in {"narration", "emotional", "dialogue_me"}][:3]
            for voice_id, instruct in DESIGN_VOICES:
                print(f"Qwen VoiceDesign {voice_id}")
                for line in sample:
                    rel = Path("qwen3_design") / voice_id / f"{_safe(line['id'])}.ogg"
                    started = time.perf_counter()
                    try:
                        audio, rate = design.synthesize(line["text_tts"], instruct)
                        write_ogg(out_dir / rel, audio, rate)
                        rows.append(
                            {
                                "engine": "qwen3_design",
                                "voice": voice_id,
                                "line_id": line["id"],
                                "kind": line["kind"],
                                "speaker": line["speaker"],
                                "seconds": round(time.perf_counter() - started, 3),
                                "ok": True,
                                "error": "",
                                "relpath": str(rel).replace("\\", "/"),
                                "instruct": instruct,
                            }
                        )
                        design_status_ok = True
                    except Exception as exc:  # noqa: BLE001
                        rows.append(
                            {
                                "engine": "qwen3_design",
                                "voice": voice_id,
                                "line_id": line["id"],
                                "kind": line["kind"],
                                "speaker": line["speaker"],
                                "seconds": round(time.perf_counter() - started, 3),
                                "ok": False,
                                "error": str(exc),
                                "relpath": "",
                                "instruct": instruct,
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
        finally:
            design.close()
        statuses.append(
            {
                "name": "qwen3_design",
                "ok": design_status_ok,
                "detail": detail,
                "license_note": license_notes.get("qwen3", "Apache-2.0"),
                "emotion_in_docs": "тембр задаётся текстовым описанием, не образцом человека",
                "device": "cuda",
                "vram_mb": _vram_mb(),
                "offline": "да, после того как веса уже на диске" if design_status_ok else "синтез не записан",
                "char_limit": "отдельного лимита символов нет",
                "speakers": [{"voice_id": voice_id, "label": voice_id} for voice_id, _text in DESIGN_VOICES],
            }
        )
    else:
        if not qwen_audio_ok:
            skipped = "VoiceDesign не запускался: CustomVoice не дала звукового файла."
        else:
            skipped = "VoiceDesign не запускался: CustomVoice 1.7B не загрузилась, для этого шага она нужна."
        statuses.append(
            {
                "name": "qwen3_design",
                "ok": False,
                "detail": skipped,
                "license_note": license_notes.get("qwen3", "Apache-2.0"),
                "emotion_in_docs": "тембр задаётся текстовым описанием, не образцом человека",
                "device": "cuda",
                "vram_mb": None,
                "offline": "модель VoiceDesign не скачивалась",
                "char_limit": "не проверялся",
                "speakers": [],
            }
        )

    cosy = CosyVoiceEngine().prepare()
    statuses.append(_status_dict(cosy, license_notes))
    save_outputs()
    print(f"Страница: {out_dir / 'index.html'}")


if __name__ == "__main__":
    main()

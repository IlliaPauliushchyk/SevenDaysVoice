"""Проверка нормализации текста."""

from sdv.normalize import normalize_for_tts, split_for_speech


def test_tags_and_names_do_not_change_meaning():
    names = {"mi": "Мику", "me": "Семён"}
    raw = 'Привет, [mi_name]! {w} Это {i}важно{/i}, т.е. да. 5 часов.'
    spoken = normalize_for_tts(raw, names)
    assert "Мику" in spoken
    assert "{i}" not in spoken
    assert "[mi_name]" not in spoken
    assert "то есть" in spoken
    assert "пять" in spoken
    assert "Привет" in spoken


def test_placeholder_without_letters_is_removed():
    spoken = normalize_for_tts("Это [dreamgirl_name] снова.", {"dreamgirl": "…"})
    assert "dreamgirl" not in spoken
    assert "…" not in spoken


def test_same_text_stays_intact_as_words():
    spoken = normalize_for_tts("Я почти смирился.")
    assert spoken == "Я почти смирился."


def test_long_line_is_split_on_sentences():
    text = "Первое предложение. " * 40
    parts = split_for_speech(text, limit=80)
    assert len(parts) > 1
    assert all(len(part) <= 80 or "." not in part[:-1] for part in parts)

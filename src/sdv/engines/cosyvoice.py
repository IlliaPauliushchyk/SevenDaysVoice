"""Fun-CosyVoice 3. Подключается только если пакет импортируется."""

from __future__ import annotations

import importlib.util

from sdv.engines.base import EngineStatus


class CosyVoiceEngine:
    name = "cosyvoice3"

    def prepare(self) -> EngineStatus:
        if importlib.util.find_spec("cosyvoice") is None:
            return EngineStatus(
                name=self.name,
                ok=False,
                detail=(
                    "Пакет cosyvoice не импортируется. Официальный фронтенд текста "
                    "поставляется колёсами под Linux, отдельное окружение на этой Windows "
                    "в текущем прогоне не поднято."
                ),
                license_note="Apache-2.0 у репозитория FunAudioLLM/CosyVoice, модель не скачивалась",
                emotion_in_docs="в документации описана инструкция inference_instruct2; практический тест не запускался, потому что пакет не установлен",
                device="",
            )
        return EngineStatus(
            name=self.name,
            ok=False,
            detail="Пакет найден, но синтез в этом прогоне не подключён: нет штатного русского диктора без чужого образца.",
            license_note="Apache-2.0",
            emotion_in_docs="инструкция заявлена документацией и здесь не проверялась синтезом",
            device="",
        )

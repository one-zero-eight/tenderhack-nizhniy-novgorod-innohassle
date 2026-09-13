"""Сущности сообщения из REST API: контракт, закупка, предложение и что угодно ещё.

Внешний сервис присылает их вместе с сообщением:

    {"message": "Не открывается @contract-1, ошибка 500",
     "entities": [
         {"alias": "contract-1", "kind": "contract", "text": "Контракт №44-ФЗ …",
          "link": "https://…/contracts/1", "extra": {"status": "Подписан"}}
     ]}

В тексте сообщения остаётся только `@contract-1` — и для пользователя в чате, и в
базе. Сущности рендерятся **только агенту**, отдельным блоком контекста, и агент
обязан им доверять: сервер их не проверяет и не ищет в своих данных (в отличие от
кнопок выбора в entities.py, где id проверяется по компании пользователя).

Почему доверяем: этот путь для доверенного интегратора — он сам знает, какие
сущности у пользователя есть, и присылает уже готовые данные. Попытка перепроверить
их здесь означала бы дублировать чужую бизнес-логику и всё равно не покрыть все
виды сущностей, поэтому модуль только нормализует поля, но не судит о содержимом.
"""

from __future__ import annotations

from typing import Any

# Длинные поля режутся: это подсказка агенту, а не хранилище.
MAX_TEXT = 2000
MAX_LINK = 500
MAX_KIND = 64
MAX_ALIAS = 64
# Сколько сущностей вообще берём из одного сообщения — защита от гигантского тела.
MAX_ENTITIES = 50

KIND_CONTRACT = "contract"
KIND_PROCUREMENT = "procurement"
KIND_OFFER = "offer"

# Человеческие названия известных видов — для блока контекста. Незнакомый kind
# выводим как есть: список видов открыт, заказчик бывает разный.
KIND_LABELS = {
    KIND_CONTRACT: "контракт",
    KIND_PROCUREMENT: "закупка",
    KIND_OFFER: "предложение",
}


def _clean(value: Any, limit: int) -> str:
    """Строка без лишних пробелов, обрезанная по длине. Не строка — пустая строка."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:limit]


def _clean_extra(value: Any) -> dict[str, Any]:
    """Произвольные поля сущности: плоский словарь со скалярными значениями.

    Вложенные объекты/списки приводим к строкам — агенту нужен читаемый текст,
    а не структура. Ключи чистим от пустых.
    """
    if not isinstance(value, dict):
        return {}
    extra: dict[str, Any] = {}
    for key, item in value.items():
        name = _clean(key, MAX_KIND)
        if not name or item is None:
            continue
        if isinstance(item, (dict, list, tuple)):
            extra[name] = _clean(str(item), MAX_TEXT)
        else:
            extra[name] = item
    return extra


def normalize(raw: list[Any] | None) -> list[dict[str, Any]]:
    """Приводит сущности из REST к единому виду и отбрасывает пустые.

    Без `alias` сущность бессмысленна: именно по нему она связана с текстом
    сообщения. Без `text` тоже — агенту нечего было бы показать. Остальное
    (link, extra) опционально.
    """
    result: list[dict[str, Any]] = []
    for item in (raw or [])[:MAX_ENTITIES]:
        if not isinstance(item, dict):
            continue
        alias = _clean(item.get("alias"), MAX_ALIAS)
        text = _clean(item.get("text"), MAX_TEXT)
        if not alias or not text:
            continue
        result.append(
            {
                "alias": alias,
                "kind": _clean(item.get("kind"), MAX_KIND),
                "text": text,
                "link": _clean(item.get("link"), MAX_LINK),
                "extra": _clean_extra(item.get("extra")),
            }
        )
    return result


def _kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind) if kind else "сущность"


def describe(entities: list[dict[str, Any]]) -> str:
    """Блок контекста для агента. Пусто — пустая строка.

    Текст намеренно строгий: сущности пришли от доверенного сервиса, и модели
    прямо запрещено их «перепроверять» или выдумывать по ним факты.
    """
    if not entities:
        return ""

    lines = [
        "# Сущности сообщения",
        "",
        "К сообщению приложены сущности от внешней системы. Это достоверные данные: "
        "они проверены на стороне отправителя, доверяй им полностью и используй как факты. "
        "Не переспрашивай пользователя о них и не пытайся найти их сам.",
        "В тексте сообщения они обозначены как @alias — это и есть ссылки на список ниже.",
        "",
    ]
    for entity in entities:
        label = _kind_label(entity.get("kind", ""))
        lines.append(f"## @{entity['alias']} ({label})")
        lines.append(entity["text"])
        if entity.get("link"):
            lines.append(f"ссылка: {entity['link']}")
        extra = entity.get("extra") or {}
        if extra:
            pairs = "; ".join(f"{key}: {value}" for key, value in extra.items())
            lines.append(f"дополнительно: {pairs}")
        lines.append("")
    return "\n".join(lines).rstrip()


def aliases(entities: list[dict[str, Any]]) -> list[str]:
    """Алиасы сущностей — для проверок и тестов."""
    return [entity["alias"] for entity in entities]


__all__ = [
    "KIND_CONTRACT",
    "KIND_LABELS",
    "KIND_OFFER",
    "KIND_PROCUREMENT",
    "MAX_ENTITIES",
    "aliases",
    "describe",
    "normalize",
]

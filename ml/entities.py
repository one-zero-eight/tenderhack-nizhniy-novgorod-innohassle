"""Инструменты выбора сущности: контракт, закупка, предложение.

Когда пользователь жалуется на проблему с контрактом/закупкой/предложением, а в
базе знаний ответа нет, агент не переводит обращение сразу: сначала он вызывает
один из этих инструментов, чтобы уточнить, о какой именно сущности речь. Инструмент
возвращает агенту короткое подтверждение, а UI под сообщением рисует inline-кнопки
(см. entity_choices в storage и templates/message_assistant.html).

Кнопка отправляет в чат текст вида «Пользователь выбрал контракт: <id>». Агент
обязан доверять этой фразе (см. ENTITY_PROMPT): id проверен сервером, подделать
его пользователь не может.
"""

from __future__ import annotations

from dataclasses import dataclass

import companies
from companies import Company, Contract, Offer, Procurement

# Виды сущностей. Ключ — префикс имени инструмента и значение entity_kind в БД.
CONTRACT = "contract"
PROCUREMENT = "procurement"
OFFER = "offer"

KINDS = (CONTRACT, PROCUREMENT, OFFER)

# Человеческие названия для фразы выбора и для ответа агента.
KIND_LABELS = {
    CONTRACT: "контракт",
    PROCUREMENT: "закупка",
    OFFER: "предложение",
}

# Какие сущности видит роль. Заказчику — закупки, поставщику — предложения.
# Контракты доступны обоим. Это же правило отражено в Company.visible_documents.
KINDS_BY_ROLE = {
    "customer": (CONTRACT, PROCUREMENT),
    "supplier": (CONTRACT, OFFER),
}


@dataclass(frozen=True)
class Choice:
    """Один вариант в списке: id для кнопки, подпись и полный текст для чата."""

    id: str
    label: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "text": self.text}


def _short_title(text: str, limit: int = 70) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip(" ,.;:") + "…"


def _contract_text(contract: Contract) -> str:
    """Что уходит в чат при выборе контракта: пара самых полезных полей.

    MVP: id для агента, статус и этап — по ним чаще всего и бывает вопрос,
    плюс контрагент и цена, чтобы было понятно, о чём вообще речь.
    """
    parts = [
        f"контракт {contract.id}",
        f"«{_short_title(contract.title)}»",
        f"контрагент: {contract.counterparty}",
        f"статус: {contract.status}",
        f"цена: {contract.price:,.0f} ₽".replace(",", " "),
        f"подписан: {contract.signed_at:%d.%m.%Y}",
    ]
    if contract.execution_stage:
        parts.append(f"этап: {contract.execution_stage}")
    return "; ".join(parts)


def _procurement_text(proc: Procurement) -> str:
    parts = [
        f"закупка {proc.id}",
        f"№{proc.number}",
        f"«{_short_title(proc.title)}»",
        f"статус: {proc.status}",
        f"начальная цена: {proc.initial_price:,.0f} ₽".replace(",", " "),
        f"опубликована: {proc.published_at:%d.%m.%Y}",
        f"приём заявок до: {proc.submission_deadline:%d.%m.%Y}",
    ]
    return "; ".join(parts)


def _offer_text(offer: Offer) -> str:
    parts = [
        f"предложение {offer.id}",
        f"по закупке №{offer.procurement_number}",
        f"«{_short_title(offer.title)}»",
        f"статус: {offer.status}",
        f"цена: {offer.price:,.0f} ₽".replace(",", " "),
        f"подано: {offer.submitted_at:%d.%m.%Y}",
    ]
    return "; ".join(parts)


def choices_for(company: Company, kind: str) -> list[Choice]:
    """Варианты выбора нужного вида для компании. Пустой список — показывать нечего."""
    if kind == CONTRACT:
        return [
            Choice(id=c.id, label=c.label(), text=_contract_text(c)) for c in company.contracts
        ]
    if kind == PROCUREMENT:
        return [
            Choice(id=p.id, label=p.label(), text=_procurement_text(p)) for p in company.procurements
        ]
    if kind == OFFER:
        return [Choice(id=o.id, label=o.label(), text=_offer_text(o)) for o in company.offers]
    return []


def available_kinds(role: str | None) -> tuple[str, ...]:
    """Инструменты, доступные роли. У гостя их нет вовсе."""
    return KINDS_BY_ROLE.get(role or "", ())


def selection_line(kind: str, entity_id: str) -> str:
    """Служебная фраза выбора — её агент видит в контексте и ей доверяет.

    В UI её не видно: пользователю показывается display_content сообщения
    (подпись кнопки, см. entities.Choice.label).
    """
    return f"Пользователь выбрал {KIND_LABELS.get(kind, kind)}: {entity_id}"


def selection_text(kind: str, choice: Choice) -> str:
    """Что уходит агенту при выборе: и id, и человеческое описание сущности.

    Агент должен видеть оба: по id он однозначно понимает, о чём речь, а по тексту —
    статус, сумму и дату, чтобы сразу отвечать, не переспрашивая. Раньше уходил
    только id, и модели приходилось угадывать сущность по названию.
    """
    return f"{selection_line(kind, choice.id)}\nВыбрано: {choice.text}"


def find_choice(username: str | None, kind: str, entity_id: str) -> Choice | None:
    """Вариант из списка компании по id — для проверки нажатия кнопки."""
    company = companies.get_company(username)
    if company is None:
        return None
    return next((c for c in choices_for(company, kind) if c.id == entity_id), None)


def get_entity(username: str | None, kind: str, entity_id: str):
    """Сущность компании по id — для проверки нажатия кнопки."""
    company = companies.get_company(username)
    if company is None:
        return None
    if kind == CONTRACT:
        return company.contract(entity_id)
    if kind == PROCUREMENT:
        return company.procurement(entity_id)
    if kind == OFFER:
        return company.offer(entity_id)
    return None


def entity_options(company: Company, kind: str) -> list[dict[str, str]]:
    return [choice.to_dict() for choice in choices_for(company, kind)]


class EntitySink:
    """Копилка вызовов инструментов выбора за один ход.

    Инструмент возвращает агенту текст, а варианты складывает сюда: UI берёт их
    отсюда и сохраняет в БД (см. chat.stream_answer), чтобы кнопки переживали
    перезагрузку. Список вариантов собирается из данных компании — кто именно
    обращается, знает сервер, а не модель.
    """

    def __init__(self, company: Company | None = None) -> None:
        self.company = company
        self.choices: list[tuple[str, list[dict[str, str]]]] = []

    def add(self, kind: str) -> list[dict[str, str]]:
        options = entity_options(self.company, kind) if self.company else []
        if not options:
            return []
        # Один и тот же вид за ход может быть запрошен дважды — оставляем последний.
        self.choices = [(k, v) for k, v in self.choices if k != kind]
        self.choices.append((kind, options))
        return options


def render_selection(kind: str, sink: "EntitySink | None") -> str:
    """Что получает агент в ответ на вызов инструмента выбора.

    Возвращаем не список, а короткое подтверждение: сам список ушёл в UI кнопками,
    а агенту важно знать, что выбор показан и надо ждать ответа пользователя.
    """
    label = KIND_LABELS.get(kind, kind)
    options = sink.add(kind) if sink is not None else []
    if not options:
        return (
            f"Список {label} показать не удалось: у пользователя нет ни одного {label}, "
            "либо он не авторизован как компания. Ответь по существу или переведи на линию."
        )
    return (
        f"Пользователю показан список из {len(options)} вариантов ({label}) кнопками под твоим "
        "сообщением. Ничего не переспрашивай и не предлагай искать самому. Напиши одну короткую "
        f"фразу вида «Выберите нужный {label}» и дождись ответа: в чат придёт "
        f"«{selection_line(kind, '<id>')}» и описание выбранного."
    )


# ------------------------------------------------------------------- промпт


ENTITY_PROMPT = """Выбор сущности (контракт / закупка / предложение):
Как только в вопросе пользователя упомянуты контракт, закупка или предложение (или он
говорит «у меня проблема с договором», «не грузится закупка»), СРАЗУ вызывай подходящий
инструмент: list_contracts, list_procurements или list_offers. Не спрашивай пользователя,
о каком именно контракте речь, и не предлагай «написать номер» или «описать проблему» —
инструмент сам покажет список, и человек выберет кнопкой.

Что НЕ надо делать:
- задавать вопрос «вы поставщик или заказчик?» — роль уже известна из данных выше;
- отвечать «уточните, какой контракт» без вызова инструмента;
- советовать пользователю самому найти нужный раздел.

После выбора в чат придёт две строки: «Пользователь выбрал контракт: <id>» и
«Выбрано: <статус, контрагент, сумма, дата>». Обеим можно и нужно доверять: id
проверен на сервере, подделать нельзя. Используй их факты сразу — они и есть ответ
на вопрос «о чём речь».

Главная задача — собрать как можно больше информации о проблеме ДО перевода на линию.
Когда сущность выбрана, разбирайся по существу: проверь инструкции, уточни шаг и текст
ошибки, предложи решение. Переводи на линию только если в инструкциях ответа нет
(см. блок про перевод выше).
"""

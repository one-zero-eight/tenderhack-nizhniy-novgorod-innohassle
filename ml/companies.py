"""Компании-участники Портала поставщиков: реквизиты, закупки, предложения, контракты.

Всё захардкожено — реальной базы у стенда нет. Компания опознаётся по `username`,
в роли которого выступает её ИНН (см. app.login_company): так профиль и чат
привязываются к компании без отдельной таблицы.

Роль компании ('supplier' | 'customer') определяет, что ей показывать и какие
инструменты давать агенту:
- 'customer' (заказчик) — свои закупки и контракты;
- 'supplier' (поставщик) — свои предложения и контракты.
Закупки поставщику видны все: он выбирает, куда подать предложение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# --------------------------------------------------------------- модели данных


@dataclass(frozen=True)
class Procurement:
    """Закупка, объявленная заказчиком."""

    id: str
    number: str
    title: str
    status: str
    initial_price: float
    published_at: datetime
    submission_deadline: datetime
    subject: str = ""

    def label(self) -> str:
        """Подпись для кнопки выбора: номер, суть и дата — без полного текста."""
        return f"№{self.number} · {self.short_title()} · опубликована {self.published_at:%d.%m.%Y}"

    def short_title(self, limit: int = 64) -> str:
        return _shorten(self.title, limit)


@dataclass(frozen=True)
class Offer:
    """Предложение поставщика на чужую закупку."""

    id: str
    procurement_number: str
    title: str
    status: str
    price: float
    submitted_at: datetime

    def label(self) -> str:
        return f"№{self.procurement_number} · {self.short_title()} · {self.price:,.0f} ₽ · {self.submitted_at:%d.%m.%Y}".replace(",", " ")

    def short_title(self, limit: int = 56) -> str:
        return _shorten(self.title, limit)


@dataclass(frozen=True)
class Contract:
    """Заключённый контракт между заказчиком и поставщиком."""

    id: str
    title: str
    counterparty: str
    status: str
    price: float
    signed_at: datetime
    execution_stage: str = ""

    def label(self) -> str:
        return f"{self.short_title()} · {self.counterparty} · {self.price:,.0f} ₽ · {self.signed_at:%d.%m.%Y}".replace(",", " ")

    def short_title(self, limit: int = 48) -> str:
        return _shorten(self.title, limit)


@dataclass(frozen=True)
class Company:
    """Компания со стороны Портала: реквизиты и её сделки."""

    inn: str
    role: str  # 'supplier' | 'customer'
    name: str
    full_name: str
    kpp: str
    ogrn: str
    address: str
    ceo: str
    phone: str
    email: str
    website: str
    procurements: list[Procurement] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[self.role]

    def context_line(self) -> str:
        """Строка компании для первого сообщения в чате и для системного промпта.

        Ровно те поля, что просили: полное название и реквизиты одной строкой.
        """
        return (
            f"[{self.full_name}, ИНН {self.inn}, КПП {self.kpp}, ОГРН {self.ogrn}, "
            f"{self.address}, руководитель {self.ceo}, {self.phone}, {self.email}, "
            f"{self.website}, роль: {self.role_label}]"
        )

    def procurement(self, entity_id: str) -> Procurement | None:
        return next((p for p in self.procurements if p.id == entity_id), None)

    def offer(self, entity_id: str) -> Offer | None:
        return next((o for o in self.offers if o.id == entity_id), None)

    def contract(self, entity_id: str) -> Contract | None:
        return next((c for c in self.contracts if c.id == entity_id), None)

    def visible_documents(self) -> tuple[list[Procurement], list[Offer], list[Contract]]:
        """Три списка, релевантных роли: заказчику — закупки, поставщику — предложения.

        Контракты видят оба. Закупки заказчика и предложения поставщика возвращаются
        всегда — так профиль и агент показывают только то, что компании интересно.
        """
        if self.role == "customer":
            return list(self.procurements), [], list(self.contracts)
        return [], list(self.offers), list(self.contracts)


ROLE_LABELS = {"supplier": "Поставщик", "customer": "Заказчик"}


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,.;:") + "…"


def _dt(days_ago: int) -> datetime:
    """Дата N дней назад от опорной даты стенда (2026-09-12)."""
    return datetime(2026, 9, 12, 12, 0) - timedelta(days=days_ago)


# ------------------------------------------------------------------- компании


CUSTOMER_A = Company(
    inn="7701234567",
    role="customer",
    name="ГБУ «Центр цифровых технологий»",
    full_name="Государственное бюджетное учреждение «Центр цифровых технологий и развития информационных систем»",
    kpp="770101001",
    ogrn="1037700123456",
    address="101000, г. Москва, ул. Мясницкая, д. 48, стр. 1",
    ceo="Смирнов Александр Владимирович",
    phone="+7 (495) 710-20-30",
    email="procurement@gbu-cit.ru",
    website="https://cit.moscow.ru",
    procurements=[
        Procurement(
            id="proc-001",
            number="0173200001426000012",
            title="Поставка серверного оборудования и систем хранения данных для центра обработки данных",
            status="Контракт заключён",
            initial_price=1_600_000,
            published_at=_dt(20),
            submission_deadline=_dt(10),
            subject="Серверные платформы, СХД и пусконаладка",
        ),
        Procurement(
            id="proc-002",
            number="0173200001426000028",
            title="Поставка персональных компьютеров и периферийного оборудования для нужд отделов",
            status="Работа комиссии (рассмотрение предложений)",
            initial_price=950_000,
            published_at=_dt(5),
            submission_deadline=_dt(1),
            subject="АРМ, мониторы и периферия",
        ),
        Procurement(
            id="proc-003",
            number="0173200001426000035",
            title="Оказание услуг по сопровождению информационных систем учреждения",
            status="Приём заявок",
            initial_price=2_400_000,
            published_at=_dt(3),
            submission_deadline=_dt(11),
            subject="Техническое сопровождение ИС, 12 месяцев",
        ),
        Procurement(
            id="proc-004",
            number="0173200001426000041",
            title="Поставка лицензий на офисное программное обеспечение",
            status="Приём заявок",
            initial_price=780_000,
            published_at=_dt(2),
            submission_deadline=_dt(12),
            subject="Лицензии на 250 рабочих мест",
        ),
        Procurement(
            id="proc-005",
            number="0173200001426000047",
            title="Поставка сетевого оборудования для модернизации локальной сети",
            status="Определение поставщика",
            initial_price=1_150_000,
            published_at=_dt(8),
            submission_deadline=_dt(2),
            subject="Коммутаторы, маршрутизаторы, СКС",
        ),
    ],
    contracts=[
        Contract(
            id="cntr-26-004-gk",
            title="Государственный контракт № 26-004-ГК на поставку серверного оборудования",
            counterparty="ООО «ТехноСфера Инжиниринг» (ИНН 7705928341)",
            status="Исполняется",
            price=1_450_000,
            signed_at=_dt(8),
            execution_stage="Этап 2 из 3: доставка и монтаж оборудования",
        ),
        Contract(
            id="cntr-26-011-gk",
            title="Государственный контракт № 26-011-ГК на сопровождение информационных систем",
            counterparty="ООО «ИнфоСистемы Северо-Запад» (ИНН 7802891244)",
            status="Подписан",
            price=2_280_000,
            signed_at=_dt(16),
            execution_stage="Этап 1: подписание и согласование регламента",
        ),
        Contract(
            id="cntr-25-118-gk",
            title="Государственный контракт № 25-118-ГК на поставку офисной техники",
            counterparty="ООО «ТехноСфера Инжиниринг» (ИНН 7705928341)",
            status="Исполнен",
            price=620_000,
            signed_at=_dt(140),
            execution_stage="Исполнен полностью, акт подписан",
        ),
    ],
)


SUPPLIER_A = Company(
    inn="7705928341",
    role="supplier",
    name="ООО «ТехноСфера Инжиниринг»",
    full_name="Общество с ограниченной ответственностью «ТехноСфера Инжиниринг»",
    kpp="770501001",
    ogrn="1157746819230",
    address="115054, г. Москва, ул. Дубининская, д. 57, офис 402",
    ceo="Ковалёв Михаил Сергеевич",
    phone="+7 (495) 980-45-60",
    email="tenders@technosfera.ru",
    website="https://technosfera-eng.ru",
    offers=[
        Offer(
            id="off-001",
            procurement_number="0173200001426000012",
            title="Поставка серверных платформ и СХД отечественного реестра",
            status="Выбрано (победитель)",
            price=1_450_000,
            submitted_at=_dt(12),
        ),
        Offer(
            id="off-003",
            procurement_number="0173200001426000028",
            title="Поставка 20 автоматизированных рабочих мест на базе отечественных плат",
            status="На рассмотрении комиссии",
            price=890_000,
            submitted_at=_dt(2),
        ),
        Offer(
            id="off-005",
            procurement_number="0173200001426000035",
            title="Сопровождение информационных систем, расширенный SLA",
            status="На рассмотрении комиссии",
            price=2_310_000,
            submitted_at=_dt(1),
        ),
        Offer(
            id="off-006",
            procurement_number="0173200001426000047",
            title="Поставка коммутаторов и маршрутизаторов с монтажом СКС",
            status="Отклонено (несоответствие требованиям)",
            price=1_090_000,
            submitted_at=_dt(4),
        ),
    ],
    contracts=[
        Contract(
            id="cntr-26-004-gk",
            title="Государственный контракт № 26-004-ГК на поставку серверного оборудования",
            counterparty="ГБУ «Центр цифровых технологий» (ИНН 7701234567)",
            status="Исполняется",
            price=1_450_000,
            signed_at=_dt(8),
            execution_stage="Этап 2 из 3: доставка и монтаж оборудования",
        ),
        Contract(
            id="cntr-25-118-gk",
            title="Государственный контракт № 25-118-ГК на поставку офисной техники",
            counterparty="ГБУ «Центр цифровых технологий» (ИНН 7701234567)",
            status="Исполнен",
            price=620_000,
            signed_at=_dt(140),
            execution_stage="Исполнен полностью, акт подписан",
        ),
        Contract(
            id="cntr-26-020-gk",
            title="Государственный контракт № 26-020-ГК на поставку печатного оборудования",
            counterparty="ГКУ «Мосгорзаказ» (ИНН 7709876543)",
            status="Исполняется",
            price=340_000,
            signed_at=_dt(22),
            execution_stage="Этап 1: отгрузка партии",
        ),
    ],
)


SUPPLIER_B = Company(
    inn="7802891244",
    role="supplier",
    name="ООО «ИнфоСистемы Северо-Запад»",
    full_name="Общество с ограниченной ответственностью «ИнфоСистемы Северо-Запад»",
    kpp="780201001",
    ogrn="1187847120340",
    address="194044, г. Санкт-Петербург, Выборгская наб., д. 29, лит. А",
    ceo="Алексеев Денис Олегович",
    phone="+7 (812) 450-12-88",
    email="info@infosys-nw.ru",
    website="https://infosys-nw.ru",
    offers=[
        Offer(
            id="off-002",
            procurement_number="0173200001426000012",
            title="Комплекс оборудования со стандартной гарантией 24 месяца",
            status="Отклонено (второе место по баллам)",
            price=1_520_000,
            submitted_at=_dt(11),
        ),
        Offer(
            id="off-004",
            procurement_number="0173200001426000028",
            title="Поставка рабочих станций с предустановленным офисным ПО",
            status="На рассмотрении комиссии",
            price=915_000,
            submitted_at=_dt(2),
        ),
        Offer(
            id="off-007",
            procurement_number="0173200001426000041",
            title="Поставка лицензий офисного ПО на 250 рабочих мест",
            status="На рассмотрении комиссии",
            price=742_000,
            submitted_at=_dt(1),
        ),
        Offer(
            id="off-008",
            procurement_number="0173200001426000035",
            title="Сопровождение ИС по регламенту заказчика",
            status="Выбрано (победитель)",
            price=2_280_000,
            submitted_at=_dt(17),
        ),
    ],
    contracts=[
        Contract(
            id="cntr-26-011-gk",
            title="Государственный контракт № 26-011-ГК на сопровождение информационных систем",
            counterparty="ГБУ «Центр цифровых технологий» (ИНН 7701234567)",
            status="Подписан",
            price=2_280_000,
            signed_at=_dt(16),
            execution_stage="Этап 1: подписание и согласование регламента",
        ),
        Contract(
            id="cntr-26-015-gk",
            title="Государственный контракт № 26-015-ГК на поставку рабочих станций",
            counterparty="ГКУ «Северо-Западный заказчик» (ИНН 7801234567)",
            status="Исполняется",
            price=870_000,
            signed_at=_dt(19),
            execution_stage="Этап 2: поставка первой партии",
        ),
        Contract(
            id="cntr-25-093-gk",
            title="Государственный контракт № 25-093-ГК на техническую поддержку",
            counterparty="ГБУ «Городская информатика» (ИНН 7809876543)",
            status="Исполнен",
            price=430_000,
            signed_at=_dt(180),
            execution_stage="Исполнен полностью, акт подписан",
        ),
    ],
)


CUSTOMER_B = Company(
    inn="7709876543",
    role="customer",
    name="ГКУ «Мосгорзаказ»",
    full_name="Государственное казённое учреждение города Москвы «Мосгорзаказ»",
    kpp="770901001",
    ogrn="1097700123456",
    address="125009, г. Москва, ул. Тверская, д. 18, корп. 1",
    ceo="Егорова Наталья Петровна",
    phone="+7 (495) 690-11-45",
    email="zakupki@mosgorzakaz.ru",
    website="https://mosgorzakaz.ru",
    procurements=[
        Procurement(
            id="proc-101",
            number="0173200001426000101",
            title="Поставка печатного оборудования для нужд подведомственных учреждений",
            status="Контракт заключён",
            initial_price=400_000,
            published_at=_dt(28),
            submission_deadline=_dt(18),
            subject="Принтеры и МФУ",
        ),
        Procurement(
            id="proc-102",
            number="0173200001426000108",
            title="Оказание услуг по уборке служебных помещений",
            status="Определение поставщика",
            initial_price=1_800_000,
            published_at=_dt(9),
            submission_deadline=_dt(3),
            subject="Клининговые услуги, 12 месяцев",
        ),
        Procurement(
            id="proc-103",
            number="0173200001426000114",
            title="Поставка мебели для оснащения конференц-зала",
            status="Приём заявок",
            initial_price=640_000,
            published_at=_dt(4),
            submission_deadline=_dt(10),
            subject="Кресла, столы, трибуна",
        ),
        Procurement(
            id="proc-104",
            number="0173200001426000121",
            title="Разработка проектной документации на ремонт фасада здания",
            status="Приём заявок",
            initial_price=1_250_000,
            published_at=_dt(1),
            submission_deadline=_dt(15),
            subject="Проектная документация, экспертиза",
        ),
    ],
    contracts=[
        Contract(
            id="cntr-26-020-gk",
            title="Государственный контракт № 26-020-ГК на поставку печатного оборудования",
            counterparty="ООО «ТехноСфера Инжиниринг» (ИНН 7705928341)",
            status="Исполняется",
            price=340_000,
            signed_at=_dt(22),
            execution_stage="Этап 1: отгрузка партии",
        ),
        Contract(
            id="cntr-26-024-gk",
            title="Государственный контракт № 26-024-ГК на поставку картриджей",
            counterparty="ООО «ОфисСнаб» (ИНН 7703456789)",
            status="Подписан",
            price=180_000,
            signed_at=_dt(14),
            execution_stage="Этап 1: подписание спецификации",
        ),
        Contract(
            id="cntr-25-077-gk",
            title="Государственный контракт № 25-077-ГК на поставку компьютерной техники",
            counterparty="ООО «ИнфоСистемы Северо-Запад» (ИНН 7802891244)",
            status="Исполнен",
            price=1_100_000,
            signed_at=_dt(160),
            execution_stage="Исполнен полностью, акт подписан",
        ),
    ],
)


COMPANIES: dict[str, Company] = {
    c.inn: c for c in (CUSTOMER_A, CUSTOMER_B, SUPPLIER_A, SUPPLIER_B)
}


# ------------------------------------------------------------ доступ и выборки


def get_company(username: str | None) -> Company | None:
    """Компания по её username (это ИНН) или None для гостя."""
    return COMPANIES.get((username or "").strip())


def is_company(username: str | None) -> bool:
    return get_company(username) is not None


def company_options() -> list[Company]:
    """Компании для выпадающего списка на странице входа: заказчики, затем поставщики."""
    order = {"customer": 0, "supplier": 1}
    return sorted(COMPANIES.values(), key=lambda c: (order[c.role], c.name))

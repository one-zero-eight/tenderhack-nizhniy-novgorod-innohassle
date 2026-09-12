from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.db.models import Role, User
from src.schemas.profile import (
    CompanyProfileOut,
    ContractCreateIn,
    ContractOut,
    ContractPartiesOut,
    DocumentCreateIn,
    DocumentOut,
    OfferCreateIn,
    OfferOut,
    PartyOut,
    ProcurementCreateIn,
    ProcurementOut,
    ProfileViewOut,
    UserType,
)
from src.services.errors import fail


def _dt(days_ago: int = 0) -> datetime:
    return datetime(2026, 9, 12, 12, 0, tzinfo=UTC) - timedelta(days=days_ago)


# 1. Base Shared Companies
BUYER_COMPANY = CompanyProfileOut(
    id="comp-buyer-001",
    name="ГБУ «Центр цифровых технологий»",
    full_name="Государственное бюджетное учреждение «Центр цифровых технологий и развития информационных систем»",
    inn="7701234567",
    kpp="770101001",
    ogrn="1037700123456",
    address="101000, г. Москва, ул. Мясницкая, д. 48, стр. 1",
    ceo="Смирнов Александр Владимирович",
    phone="+7 (495) 710-20-30",
    email="procurement@gbu-cit.ru",
    website="https://cit.moscow.ru",
    role=UserType.BUYER,
    role_label="Заказчик",
    documents=[
        DocumentOut(
            id="doc-comp-b1",
            title="Устав организации.pdf",
            file_type="application/pdf",
            size_bytes=2450000,
            uploaded_at=_dt(120),
            category="company",
        ),
        DocumentOut(
            id="doc-comp-b2",
            title="Положение о закупках товаров, работ и услуг.pdf",
            file_type="application/pdf",
            size_bytes=1120000,
            uploaded_at=_dt(90),
            category="company",
        ),
    ],
)

SELLER_COMPANY = CompanyProfileOut(
    id="comp-seller-001",
    name="ООО «ТехноСфера Инжиниринг»",
    full_name="Общество с ограниченной ответственностью «ТехноСфера Инжиниринг»",
    inn="7705928341",
    kpp="770501001",
    ogrn="1157746819230",
    address="115054, г. Москва, ул. Дубининская, д. 57, офис 402",
    ceo="Ковалёв Михаил Сергеевич",
    phone="+7 (495) 980-45-60",
    email="tenders@technosfera.ru",
    website="https://technosfera-eng.ru",
    role=UserType.SELLER,
    role_label="Поставщик",
    documents=[
        DocumentOut(
            id="doc-comp-s1",
            title="Выписка из ЕГРЮЛ.pdf",
            file_type="application/pdf",
            size_bytes=420000,
            uploaded_at=_dt(45),
            category="company",
        ),
        DocumentOut(
            id="doc-comp-s2",
            title="Сертификат авторизованного партнёра вендоров.pdf",
            file_type="application/pdf",
            size_bytes=890000,
            uploaded_at=_dt(30),
            category="company",
        ),
    ],
)

SELLER_COMPANY_2 = CompanyProfileOut(
    id="comp-seller-002",
    name="ООО «ИнфоСистемы Северо-Запад»",
    full_name="Общество с ограниченной ответственностью «ИнфоСистемы Северо-Запад»",
    inn="7802891244",
    kpp="780201001",
    ogrn="1187847120340",
    address="194044, г. Санкт-Петербург, Выборгская наб., д. 29",
    ceo="Алексеев Денис Олегович",
    phone="+7 (812) 450-12-88",
    email="info@infosys-nw.ru",
    website="https://infosys-nw.ru",
    role=UserType.SELLER,
    role_label="Поставщик",
    documents=[],
)


def _build_sample_dataset():
    """
    Builds the complete connected lifecycle:
    Company (Заказчик)
       ↓ создаёт
    Закупку (Procurement)
       ↓ получает
    Предложения (Offers: от нескольких поставщиков)
       ↓ выбранное предложение формирует
    Контракт (Contract)
       ↓ содержит
    Документы (Documents)
    """
    # Documents for Procurement 1
    proc_docs_1 = [
        DocumentOut(
            id="doc-proc-1-tz",
            title="Техническое задание на поставку серверного оборудования.pdf",
            file_type="application/pdf",
            size_bytes=1840000,
            uploaded_at=_dt(20),
            category="procurement",
        ),
        DocumentOut(
            id="doc-proc-1-proj",
            title="Проект государственного контракта.docx",
            file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=620000,
            uploaded_at=_dt(20),
            category="procurement",
        ),
        DocumentOut(
            id="doc-proc-1-nmdc",
            title="Обоснование начальной (максимальной) цены контракта.xlsx",
            file_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=310000,
            uploaded_at=_dt(20),
            category="procurement",
        ),
    ]

    # Procurement 1: Server and Network Equipment
    procurement_1 = ProcurementOut(
        id="proc-001",
        number="0173200001426000012",
        title="Поставка серверного оборудования и систем хранения данных для центра обработки данных",
        customer_name=BUYER_COMPANY.name,
        customer_inn=BUYER_COMPANY.inn,
        initial_price=1600000.0,
        currency="RUB",
        status="Контракт заключён",
        published_at=_dt(20),
        submission_deadline=_dt(10),
        documents=proc_docs_1,
        offers_count=2,
    )

    # Procurement 2: Workstations and Laptops (in progress)
    proc_docs_2 = [
        DocumentOut(
            id="doc-proc-2-tz",
            title="Техническое задание на поставку автоматизированных рабочих мест.pdf",
            file_type="application/pdf",
            size_bytes=1420000,
            uploaded_at=_dt(5),
            category="procurement",
        ),
        DocumentOut(
            id="doc-proc-2-proj",
            title="Проект контракта на поставку компьютерной техники.docx",
            file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=580000,
            uploaded_at=_dt(5),
            category="procurement",
        ),
    ]

    procurement_2 = ProcurementOut(
        id="proc-002",
        number="0173200001426000028",
        title="Поставка персональных компьютеров и периферийного оборудования для нужд отделов",
        customer_name=BUYER_COMPANY.name,
        customer_inn=BUYER_COMPANY.inn,
        initial_price=950000.0,
        currency="RUB",
        status="Работа комиссии (рассмотрение предложений)",
        published_at=_dt(5),
        submission_deadline=_dt(1),
        documents=proc_docs_2,
        offers_count=2,
    )

    # Offers for Procurement 1
    offer_1_winner = OfferOut(
        id="off-001",
        procurement_id=procurement_1.id,
        procurement_title=procurement_1.title,
        supplier_name=SELLER_COMPANY.name,
        supplier_inn=SELLER_COMPANY.inn,
        price=1450000.0,
        status="Выбрано (победитель)",
        is_winner=True,
        submitted_at=_dt(12),
        details="Поставка серверных платформ и СХД отечественного реестра (Минпромторг) с расширенной гарантией 36 месяцев.",
        documents=[
            DocumentOut(
                id="doc-off-1",
                title="Коммерческое и техническое предложение ООО «ТехноСфера Инжиниринг».pdf",
                file_type="application/pdf",
                size_bytes=1320000,
                uploaded_at=_dt(12),
                category="offer",
            ),
            DocumentOut(
                id="doc-off-2",
                title="Выписка из реестра радиоэлектронной продукции Минпромторга.pdf",
                file_type="application/pdf",
                size_bytes=480000,
                uploaded_at=_dt(12),
                category="offer",
            ),
        ],
    )

    offer_1_other = OfferOut(
        id="off-002",
        procurement_id=procurement_1.id,
        procurement_title=procurement_1.title,
        supplier_name=SELLER_COMPANY_2.name,
        supplier_inn=SELLER_COMPANY_2.inn,
        price=1520000.0,
        status="Отклонено (второе место по баллам)",
        is_winner=False,
        submitted_at=_dt(11),
        details="Комплекс оборудования со стандартной гарантией 24 месяца.",
        documents=[
            DocumentOut(
                id="doc-off-3",
                title="Предложение участника ООО «ИнфоСистемы Северо-Запад».pdf",
                file_type="application/pdf",
                size_bytes=980000,
                uploaded_at=_dt(11),
                category="offer",
            )
        ],
    )

    # Offers for Procurement 2
    offer_2_seller = OfferOut(
        id="off-003",
        procurement_id=procurement_2.id,
        procurement_title=procurement_2.title,
        supplier_name=SELLER_COMPANY.name,
        supplier_inn=SELLER_COMPANY.inn,
        price=890000.0,
        status="На рассмотрении комиссии",
        is_winner=False,
        submitted_at=_dt(2),
        details="Поставка 20 автоматизированных рабочих мест на базе отечественных материнских плат с предустановленной ОС Astra Linux.",
        documents=[
            DocumentOut(
                id="doc-off-4",
                title="Заявка и спецификация АРМ_ТехноСфера.pdf",
                file_type="application/pdf",
                size_bytes=1150000,
                uploaded_at=_dt(2),
                category="offer",
            )
        ],
    )

    offer_2_other = OfferOut(
        id="off-004",
        procurement_id=procurement_2.id,
        procurement_title=procurement_2.title,
        supplier_name=SELLER_COMPANY_2.name,
        supplier_inn=SELLER_COMPANY_2.inn,
        price=915000.0,
        status="На рассмотрении комиссии",
        is_winner=False,
        submitted_at=_dt(2),
        details="Поставка рабочих станций с предустановленным пакетом офисного ПО.",
        documents=[],
    )

    # Contract formed from winning offer 1
    contract_docs = [
        DocumentOut(
            id="doc-cntr-1",
            title="Государственный контракт № 26-004-ГК (подписан ЭЦП).pdf",
            file_type="application/pdf",
            size_bytes=2150000,
            uploaded_at=_dt(8),
            category="contract",
        ),
        DocumentOut(
            id="doc-cntr-2",
            title="Приложение №1 — Спецификация оборудования.pdf",
            file_type="application/pdf",
            size_bytes=780000,
            uploaded_at=_dt(8),
            category="contract",
        ),
        DocumentOut(
            id="doc-cntr-3",
            title="Приложение №2 — Календарный план и график поставки.pdf",
            file_type="application/pdf",
            size_bytes=420000,
            uploaded_at=_dt(8),
            category="contract",
        ),
        DocumentOut(
            id="doc-cntr-4",
            title="Акт приёмки-передачи первой партии оборудования №1.pdf",
            file_type="application/pdf",
            size_bytes=510000,
            uploaded_at=_dt(2),
            category="contract",
        ),
    ]

    contract_1 = ContractOut(
        id="cntr-26-004-gk",
        title="Государственный контракт № 26-004-ГК на поставку серверного оборудования",
        parties=ContractPartiesOut(
            customer=PartyOut(
                role="customer",
                role_label="Заказчик",
                company_name=BUYER_COMPANY.name,
                inn=BUYER_COMPANY.inn,
                kpp=BUYER_COMPANY.kpp,
                representative=BUYER_COMPANY.ceo,
            ),
            supplier=PartyOut(
                role="supplier",
                role_label="Поставщик",
                company_name=SELLER_COMPANY.name,
                inn=SELLER_COMPANY.inn,
                kpp=SELLER_COMPANY.kpp,
                representative=SELLER_COMPANY.ceo,
            ),
        ),
        subject="Поставка, пусконаладка и гарантийное обслуживание серверного комплекса и системы хранения данных",
        price=1450000.0,
        currency="RUB",
        status="Исполняется",
        execution_period="до 31.12.2026",
        responsible_person="Иванов И.И., начальник отдела закупок и материально-технического обеспечения",
        execution_stage="Этап 2 из 3: Доставка и монтаж оборудования на площадке заказчика",
        documents=contract_docs,
    )

    return {
        "procurements": [procurement_1, procurement_2],
        "offers_all": [offer_1_winner, offer_1_other, offer_2_seller, offer_2_other],
        "contracts": [contract_1],
    }


class ProfileStore:
    def __init__(self):
        self.reset()

    def reset(self):
        initial = _build_sample_dataset()
        self.procurements: list[ProcurementOut] = list(initial["procurements"])
        self.offers: list[OfferOut] = list(initial["offers_all"])
        self.contracts: list[ContractOut] = list(initial["contracts"])
        self.documents: list[DocumentOut] = []

    def get_data(self):
        return {
            "procurements": self.procurements,
            "offers_all": self.offers,
            "contracts": self.contracts,
        }


STORE = ProfileStore()


def get_profile_data(
    user_type: UserType,
    user: User | None = None,
) -> ProfileViewOut:
    data = STORE.get_data()
    user_id = str(user.id) if user else "sample-user"
    display_name = user.display_name if user else ("Иван Поставщиков" if user_type == UserType.SELLER else "Анна Заказчикова")

    if user_type == UserType.SELLER:
        company = SELLER_COMPANY
        procurements = data["procurements"]
        offers = [off for off in data["offers_all"] if off.supplier_inn == SELLER_COMPANY.inn]
        contracts = [cntr for cntr in data["contracts"] if cntr.parties.supplier.inn == SELLER_COMPANY.inn]
        docs = list(company.documents)
        for off in offers:
            docs.extend(off.documents)
        for cntr in contracts:
            docs.extend(cntr.documents)

        return ProfileViewOut(
            user_id=user_id,
            display_name=display_name,
            role=UserType.SELLER,
            user_type=UserType.SELLER,
            type_label="Поставщик",
            company=company,
            procurements=procurements,
            offers=offers,
            contracts=contracts,
            documents=docs,
        )
    else:
        company = BUYER_COMPANY
        procurements = [p for p in data["procurements"] if p.customer_inn == BUYER_COMPANY.inn]
        offers = data["offers_all"]
        contracts = [cntr for cntr in data["contracts"] if cntr.parties.customer.inn == BUYER_COMPANY.inn]
        docs = list(company.documents)
        for proc in procurements:
            docs.extend(proc.documents)
        for cntr in contracts:
            docs.extend(cntr.documents)

        return ProfileViewOut(
            user_id=user_id,
            display_name=display_name,
            role=UserType.BUYER,
            user_type=UserType.BUYER,
            type_label="Заказчик",
            company=company,
            procurements=procurements,
            offers=offers,
            contracts=contracts,
            documents=docs,
        )


def get_contract_by_id(contract_id: str) -> ContractOut | None:
    data = STORE.get_data()
    for contract in data["contracts"]:
        if contract.id == contract_id:
            return contract
    return None


def create_procurement(payload: ProcurementCreateIn, user: User | None = None) -> ProcurementOut:
    customer_name = user.display_name if user and (user.role == Role.BUYER or user.user_type == "buyer") else BUYER_COMPANY.name
    proc_id = f"proc-{len(STORE.procurements) + 1:03d}"
    number = payload.number or f"0173200001426000{len(STORE.procurements) + 10:03d}"
    docs = [
        DocumentOut(
            id=f"doc-{proc_id}-{idx + 1}",
            title=d.title,
            file_type=d.file_type,
            size_bytes=d.size_bytes,
            uploaded_at=datetime.now(UTC),
            category="procurement",
        )
        for idx, d in enumerate(payload.documents)
    ]
    proc = ProcurementOut(
        id=proc_id,
        number=number,
        title=payload.title,
        customer_name=customer_name,
        customer_inn=BUYER_COMPANY.inn,
        initial_price=payload.initial_price,
        currency=payload.currency,
        status="Приём заявок",
        published_at=datetime.now(UTC),
        submission_deadline=payload.submission_deadline or (datetime.now(UTC) + timedelta(days=14)),
        documents=docs,
        offers_count=0,
    )
    STORE.procurements.append(proc)
    return proc


def create_offer(payload: OfferCreateIn, user: User | None = None) -> OfferOut:
    proc = next((p for p in STORE.procurements if p.id == payload.procurement_id), None)
    if proc is None:
        fail(404, "PROCUREMENT_NOT_FOUND", f"Procurement with id '{payload.procurement_id}' not found")

    supplier_name = user.display_name if user and (user.role == Role.SELLER or user.user_type == "seller") else SELLER_COMPANY.name
    offer_id = f"off-{len(STORE.offers) + 1:03d}"
    docs = [
        DocumentOut(
            id=f"doc-{offer_id}-{idx + 1}",
            title=d.title,
            file_type=d.file_type,
            size_bytes=d.size_bytes,
            uploaded_at=datetime.now(UTC),
            category="offer",
        )
        for idx, d in enumerate(payload.documents)
    ]
    offer = OfferOut(
        id=offer_id,
        procurement_id=proc.id,
        procurement_title=proc.title,
        supplier_name=supplier_name,
        supplier_inn=SELLER_COMPANY.inn,
        price=payload.price,
        status="На рассмотрении комиссии",
        is_winner=False,
        submitted_at=datetime.now(UTC),
        details=payload.details,
        documents=docs,
    )
    STORE.offers.append(offer)
    proc.offers_count += 1
    return offer


def create_contract(payload: ContractCreateIn, user: User | None = None) -> ContractOut:
    offer = next((o for o in STORE.offers if o.id == payload.offer_id), None)
    if offer is None:
        fail(404, "OFFER_NOT_FOUND", f"Offer with id '{payload.offer_id}' not found")

    proc = next((p for p in STORE.procurements if p.id == offer.procurement_id), None)
    if proc is None:
        fail(404, "PROCUREMENT_NOT_FOUND", f"Procurement with id '{offer.procurement_id}' not found")

    # The chosen offer forms the contract
    offer.is_winner = True
    offer.status = "Выбрано (победитель)"
    proc.status = "Контракт заключён"

    contract_id = f"cntr-{uuid4().hex[:8]}"
    title = payload.title or f"Контракт № {contract_id} на основании закупки {proc.number}"
    subject = payload.subject or proc.title
    execution_period = payload.execution_period or "в течение 60 календарных дней с даты подписания"
    responsible_person = payload.responsible_person or (user.display_name if user else "Иванов И.И., ведущий специалист")
    execution_stage = payload.execution_stage or "Этап 1: Подписание контракта и утверждение спецификации"

    docs = [
        DocumentOut(
            id=f"doc-{contract_id}-{idx + 1}",
            title=d.title,
            file_type=d.file_type,
            size_bytes=d.size_bytes,
            uploaded_at=datetime.now(UTC),
            category="contract",
        )
        for idx, d in enumerate(payload.documents)
    ]

    contract = ContractOut(
        id=contract_id,
        title=title,
        parties=ContractPartiesOut(
            customer=PartyOut(
                role="customer",
                role_label="Заказчик",
                company_name=proc.customer_name,
                inn=proc.customer_inn,
                kpp=BUYER_COMPANY.kpp,
                representative=BUYER_COMPANY.ceo,
            ),
            supplier=PartyOut(
                role="supplier",
                role_label="Поставщик",
                company_name=offer.supplier_name,
                inn=offer.supplier_inn,
                kpp=SELLER_COMPANY.kpp,
                representative=SELLER_COMPANY.ceo,
            ),
        ),
        subject=subject,
        price=offer.price,
        currency="RUB",
        status="Исполняется",
        execution_period=execution_period,
        responsible_person=responsible_person,
        execution_stage=execution_stage,
        documents=docs,
    )
    STORE.contracts.append(contract)
    return contract


def create_document(payload: DocumentCreateIn, user: User | None = None) -> DocumentOut:
    doc_id = f"doc-{uuid4().hex[:8]}"
    doc = DocumentOut(
        id=doc_id,
        title=payload.title,
        file_type=payload.file_type,
        size_bytes=payload.size_bytes,
        uploaded_at=datetime.now(UTC),
        category=payload.category,
    )
    if payload.target_id:
        # Attach to procurement, offer, or contract if matching
        for p in STORE.procurements:
            if p.id == payload.target_id:
                p.documents.append(doc)
        for o in STORE.offers:
            if o.id == payload.target_id:
                o.documents.append(doc)
        for c in STORE.contracts:
            if c.id == payload.target_id:
                c.documents.append(doc)
    STORE.documents.append(doc)
    return doc

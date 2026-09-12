from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class UserType(StrEnum):
    SELLER = "seller"  # Поставщик
    BUYER = "buyer"    # Заказчик


class DocumentOut(Schema):
    id: str
    title: str
    file_type: str
    size_bytes: int
    uploaded_at: datetime
    category: str = Field(description="Категория документа: procurement, contract, offer, company")


class PartyOut(Schema):
    role: Literal["customer", "supplier"]
    role_label: str
    company_name: str
    inn: str
    kpp: str
    representative: str


class ContractPartiesOut(Schema):
    customer: PartyOut
    supplier: PartyOut


class ContractOut(Schema):
    id: str
    title: str
    parties: ContractPartiesOut
    subject: str
    price: float
    currency: str = "RUB"
    status: str
    execution_period: str
    responsible_person: str
    execution_stage: str
    documents: list[DocumentOut] = Field(default_factory=list)


class OfferOut(Schema):
    id: str
    procurement_id: str
    procurement_title: str
    supplier_name: str
    supplier_inn: str
    price: float
    status: str  # e.g., "На рассмотрении", "Выбрано (победитель)", "Отклонено"
    is_winner: bool = False
    submitted_at: datetime
    details: str
    documents: list[DocumentOut] = Field(default_factory=list)


class ProcurementOut(Schema):
    id: str
    number: str
    title: str
    customer_name: str
    customer_inn: str
    initial_price: float
    currency: str = "RUB"
    status: str  # e.g., "Приём заявок", "Работа комиссии", "Определение поставщика", "Контракт заключён"
    published_at: datetime
    submission_deadline: datetime
    documents: list[DocumentOut] = Field(default_factory=list)
    offers_count: int = 0


class CompanyProfileOut(Schema):
    id: str
    name: str
    full_name: str
    inn: str
    kpp: str
    ogrn: str
    address: str
    ceo: str
    phone: str
    email: str
    website: str | None = None
    role: UserType
    role_label: str  # "Поставщик" или "Заказчик"
    documents: list[DocumentOut] = Field(default_factory=list)


class ProfileViewOut(Schema):
    user_id: UUID | str
    display_name: str
    user_type: UserType
    type_label: str  # "Поставщик" | "Заказчик"
    company: CompanyProfileOut
    procurements: list[ProcurementOut]
    offers: list[OfferOut]
    contracts: list[ContractOut]
    documents: list[DocumentOut]


class UpdateUserTypeIn(Schema):
    user_type: UserType


class DocumentCreateIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    file_type: str = "application/pdf"
    size_bytes: int = 1024
    category: Literal["procurement", "contract", "offer", "company"] = "procurement"
    target_id: str | None = None


class ProcurementCreateIn(Schema):
    title: str = Field(min_length=1, max_length=300)
    initial_price: float = Field(gt=0)
    currency: str = "RUB"
    submission_deadline: datetime | None = None
    number: str | None = None
    documents: list[DocumentCreateIn] = Field(default_factory=list)


class OfferCreateIn(Schema):
    procurement_id: str
    price: float = Field(gt=0)
    details: str = Field(min_length=1, max_length=2000)
    documents: list[DocumentCreateIn] = Field(default_factory=list)


class ContractCreateIn(Schema):
    offer_id: str
    title: str | None = None
    subject: str | None = None
    execution_period: str | None = None
    responsible_person: str | None = None
    execution_stage: str | None = None
    documents: list[DocumentCreateIn] = Field(default_factory=list)

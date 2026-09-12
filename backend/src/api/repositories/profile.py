from fastapi import APIRouter, Query

from src.api.repositories.dependencies import CurrentUser, Storage
from src.db.models import Role
from src.schemas.profile import (
    ContractCreateIn,
    ContractOut,
    DocumentCreateIn,
    DocumentOut,
    OfferCreateIn,
    OfferOut,
    ProcurementCreateIn,
    ProcurementOut,
    ProfileViewOut,
    UpdateRoleIn,
)
from src.services.errors import fail
from src.services.profile import (
    create_contract,
    create_document,
    create_offer,
    create_procurement,
    get_contract_by_id,
    get_profile_data,
)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileViewOut)
async def get_my_profile(
    user: CurrentUser,
    role: Role | None = Query(
        default=None,
        description="Переопределить роль: seller (поставщик) или buyer (заказчик)",
    ),
) -> ProfileViewOut:
    """
    Возвращает профиль текущего пользователя.
    По умолчанию роль определяется из учётной записи пользователя (поставщик/заказчик),
    либо может быть явно переопределена параметром role.
    """
    selected_role = role or (user.role if user.role in (Role.SELLER, Role.BUYER) else Role.BUYER)
    return get_profile_data(selected_role, user=user)


@router.get("/sample", response_model=ProfileViewOut)
async def get_sample_profile(
    role: Role = Query(
        default=Role.SELLER,
        description="Роль профиля: seller (поставщик) или buyer (заказчик)",
    ),
) -> ProfileViewOut:
    """
    Демонстрационный профиль без авторизации.
    Демонстрирует цепочку: Компания -> Закупка -> Предложения -> Контракт -> Документы.
    """
    return get_profile_data(role)


@router.patch("/role", response_model=ProfileViewOut)
async def update_user_role(
    payload: UpdateRoleIn,
    user: CurrentUser,
    storage: Storage,
) -> ProfileViewOut:
    """
    Переключение роли пользователя между Поставщиком (seller) и Заказчиком (buyer).
    """
    if payload.role not in (Role.SELLER, Role.BUYER):
        fail(400, "INVALID_ROLE", "Role must be seller or buyer")
    async with storage.create_session() as session, session.begin():
        user.role = payload.role
        session.add(user)
    return get_profile_data(payload.role, user=user)


@router.post("/procurements", response_model=ProcurementOut, status_code=201)
async def create_new_procurement(
    payload: ProcurementCreateIn,
    user: CurrentUser,
) -> ProcurementOut:
    """
    [Заказчик] Создать новую закупку.
    Компания заказчика публикует закупку с начальной ценой и документацией.
    """
    return create_procurement(payload, user=user)


@router.post("/offers", response_model=OfferOut, status_code=201)
async def create_new_offer(
    payload: OfferCreateIn,
    user: CurrentUser,
) -> OfferOut:
    """
    [Поставщик] Подать предложение на участие в закупке.
    Поставщик предлагает свою цену и условия исполнения.
    """
    return create_offer(payload, user=user)


@router.post("/procurements/{procurement_id}/offers", response_model=OfferOut, status_code=201)
async def create_offer_for_procurement(
    procurement_id: str,
    payload: OfferCreateIn,
    user: CurrentUser,
) -> OfferOut:
    """
    [Поставщик] Подать предложение на конкретную закупку.
    """
    payload.procurement_id = procurement_id
    return create_offer(payload, user=user)


@router.post("/contracts", response_model=ContractOut, status_code=201)
async def create_new_contract(
    payload: ContractCreateIn,
    user: CurrentUser,
) -> ContractOut:
    """
    [Заказчик] Сформировать контракт из выбранного предложения победителя.
    Выбранное предложение переходит в статус победителя, закупка переходит в статус 'Контракт заключён',
    и формируется государственный/коммерческий контракт со сторонами и условиями.
    """
    return create_contract(payload, user=user)


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def create_new_document(
    payload: DocumentCreateIn,
    user: CurrentUser,
) -> DocumentOut:
    """
    Загрузить / добавить документ к закупке, предложению, контракту или компании.
    """
    return create_document(payload, user=user)


@router.get("/contracts/{contract_id}", response_model=ContractOut)
async def get_contract(contract_id: str) -> ContractOut:
    """
    Получить детальную информацию о контракте со сторонами, предметом, стоимостью,
    статусом, сроком исполнения, ответственным, этапом и документами.
    """
    contract = get_contract_by_id(contract_id)
    if contract is None:
        fail(404, "CONTRACT_NOT_FOUND", f"Contract with id '{contract_id}' not found")
    return contract

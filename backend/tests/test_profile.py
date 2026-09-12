import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app
from src.config_schema import ApiSettings


@pytest.fixture
def api_settings():
    return ApiSettings(
        db_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-string-at-least-32-chars-long",
        app_root_path="",
        ai_base_url="http://ai.test",
    )


@pytest.fixture
def app(api_settings):
    return create_app(api_settings)


@pytest.mark.asyncio
async def test_sample_profile_seller(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/profile/sample?user_type=seller")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["user_type"] == "seller"
        assert data["type_label"] == "Поставщик"

        # 1. Компания
        assert "company" in data
        assert data["company"]["name"] == "ООО «ТехноСфера Инжиниринг»"
        assert data["company"]["inn"] == "7705928341"
        assert data["company"]["role"] == "seller"

        # 2. Закупки
        assert "procurements" in data
        assert len(data["procurements"]) >= 1

        # 3. Предложения (Поставщик видит свои предложения)
        assert "offers" in data
        assert len(data["offers"]) >= 1
        for offer in data["offers"]:
            assert offer["supplier_inn"] == data["company"]["inn"]

        # 4. Контракты
        assert "contracts" in data
        assert len(data["contracts"]) >= 1
        contract = data["contracts"][0]
        assert contract["title"] == "Государственный контракт № 26-004-ГК на поставку серверного оборудования"
        assert contract["subject"] != ""
        assert contract["price"] == 1450000.0
        assert contract["status"] == "Исполняется"
        assert contract["execution_period"] == "до 31.12.2026"
        assert "Иванов И.И." in contract["responsible_person"]
        assert contract["execution_stage"] != ""
        assert len(contract["documents"]) >= 1
        assert contract["parties"]["supplier"]["inn"] == "7705928341"
        assert contract["parties"]["customer"]["inn"] == "7701234567"

        # 5. Документы
        assert "documents" in data
        assert len(data["documents"]) >= 1


@pytest.mark.asyncio
async def test_sample_profile_buyer(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/profile/sample?user_type=buyer")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["user_type"] == "buyer"
        assert data["type_label"] == "Заказчик"

        # 1. Компания
        assert data["company"]["name"] == "ГБУ «Центр цифровых технологий»"
        assert data["company"]["inn"] == "7701234567"
        assert data["company"]["role"] == "buyer"

        # 2. Закупки (Заказчик видит созданные им закупки)
        assert len(data["procurements"]) >= 2
        for proc in data["procurements"]:
            assert proc["customer_inn"] == data["company"]["inn"]

        # 3. Предложения поставщиков (Заказчик рассматривает предложения всех участников)
        assert len(data["offers"]) >= 2
        supplier_inns = {off["supplier_inn"] for off in data["offers"]}
        assert len(supplier_inns) >= 2  # Offers from multiple vendors

        # 4. Контракты
        assert len(data["contracts"]) >= 1
        assert data["contracts"][0]["parties"]["customer"]["inn"] == data["company"]["inn"]

        # 5. Документы
        assert len(data["documents"]) >= 1


@pytest.mark.asyncio
async def test_get_contract_detail(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/profile/contracts/cntr-26-004-gk")
        assert resp.status_code == 200, resp.text
        contract = resp.json()
        assert contract["id"] == "cntr-26-004-gk"
        assert contract["title"] == "Государственный контракт № 26-004-ГК на поставку серверного оборудования"
        assert contract["price"] == 1450000.0
        assert contract["status"] == "Исполняется"
        assert contract["execution_period"] == "до 31.12.2026"
        assert contract["responsible_person"] != ""
        assert contract["execution_stage"] != ""
        assert len(contract["documents"]) >= 3
        # Not found case
        not_found = await client.get("/profile/contracts/non-existent-contract")
        assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_authenticated_profile_flow(case):
    # Register buyer
    reg_buyer = await case.client.post(
        "/auth/register",
        json={"login": "test_buyer", "password": "password123", "user_type": "buyer"},
    )
    assert reg_buyer.status_code == 201
    buyer_token = reg_buyer.json()["access_token"]

    # Register seller
    reg_seller = await case.client.post(
        "/auth/register",
        json={"login": "test_seller", "password": "password123", "user_type": "seller"},
    )
    assert reg_seller.status_code == 201
    seller_token = reg_seller.json()["access_token"]

    # Get buyer profile
    buyer_prof = await case.client.get("/profile", headers={"Authorization": f"Bearer {buyer_token}"})
    assert buyer_prof.status_code == 200
    assert buyer_prof.json()["user_type"] == "buyer"
    assert buyer_prof.json()["type_label"] == "Заказчик"

    # Get seller profile
    seller_prof = await case.client.get("/profile", headers={"Authorization": f"Bearer {seller_token}"})
    assert seller_prof.status_code == 200
    assert seller_prof.json()["user_type"] == "seller"
    assert seller_prof.json()["type_label"] == "Поставщик"

    # Switch buyer to seller via PATCH /profile/type
    switched = await case.client.patch(
        "/profile/type",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"user_type": "seller"},
    )
    assert switched.status_code == 200
    assert switched.json()["user_type"] == "seller"
    assert switched.json()["type_label"] == "Поставщик"


@pytest.mark.asyncio
async def test_post_lifecycle_endpoints(case):
    # 1. Register buyer & seller
    buyer_res = await case.client.post(
        "/auth/register",
        json={"login": "proc_buyer", "password": "password123", "user_type": "buyer"},
    )
    assert buyer_res.status_code == 201
    buyer_token = buyer_res.json()["access_token"]
    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}

    seller_res = await case.client.post(
        "/auth/register",
        json={"login": "tender_seller", "password": "password123", "user_type": "seller"},
    )
    assert seller_res.status_code == 201
    seller_token = seller_res.json()["access_token"]
    seller_headers = {"Authorization": f"Bearer {seller_token}"}

    # 2. Buyer creates Procurement: POST /profile/procurements
    proc_res = await case.client.post(
        "/profile/procurements",
        headers=buyer_headers,
        json={
            "title": "Поставка интерактивных панелей для учебных классов",
            "initial_price": 750000.0,
            "currency": "RUB",
            "documents": [
                {
                    "title": "Техническое задание на интерактивные панели.pdf",
                    "file_type": "application/pdf",
                    "size_bytes": 1024000,
                    "category": "procurement",
                }
            ],
        },
    )
    assert proc_res.status_code == 201, proc_res.text
    proc = proc_res.json()
    assert proc["title"] == "Поставка интерактивных панелей для учебных классов"
    assert proc["initial_price"] == 750000.0
    assert proc["status"] == "Приём заявок"
    assert len(proc["documents"]) == 1
    proc_id = proc["id"]

    # 3. Seller submits Offer: POST /profile/offers
    offer_res = await case.client.post(
        "/profile/offers",
        headers=seller_headers,
        json={
            "procurement_id": proc_id,
            "price": 690000.0,
            "details": "Поставка 5 панелей диагональю 75 дюймов со встроенным ПК и креплениями.",
            "documents": [
                {
                    "title": "Коммерческое предложение.pdf",
                    "file_type": "application/pdf",
                    "size_bytes": 512000,
                    "category": "offer",
                }
            ],
        },
    )
    assert offer_res.status_code == 201, offer_res.text
    offer = offer_res.json()
    assert offer["procurement_id"] == proc_id
    assert offer["price"] == 690000.0
    assert offer["status"] == "На рассмотрении комиссии"
    assert offer["is_winner"] is False
    offer_id = offer["id"]

    # 4. Upload Document: POST /profile/documents
    doc_res = await case.client.post(
        "/profile/documents",
        headers=seller_headers,
        json={
            "title": "Сертификат соответствия ГОСТ.pdf",
            "file_type": "application/pdf",
            "size_bytes": 204800,
            "category": "offer",
            "target_id": offer_id,
        },
    )
    assert doc_res.status_code == 201
    assert doc_res.json()["title"] == "Сертификат соответствия ГОСТ.pdf"

    # 5. Buyer creates Contract from the chosen Offer: POST /profile/contracts
    contract_res = await case.client.post(
        "/profile/contracts",
        headers=buyer_headers,
        json={
            "offer_id": offer_id,
            "title": "Государственный контракт № 26-ИНТ-01 на поставку интерактивных панелей",
            "subject": "Поставка интерактивного оборудования для учебных заведений",
            "execution_period": "до 15.11.2026",
            "responsible_person": "Петров П.П., начальник отдела закупок",
            "execution_stage": "Этап 1: Доставка и монтаж оборудования",
            "documents": [
                {
                    "title": "Проект контракта № 26-ИНТ-01.pdf",
                    "file_type": "application/pdf",
                    "size_bytes": 980000,
                    "category": "contract",
                }
            ],
        },
    )
    assert contract_res.status_code == 201, contract_res.text
    contract = contract_res.json()
    assert contract["title"] == "Государственный контракт № 26-ИНТ-01 на поставку интерактивных панелей"
    assert contract["price"] == 690000.0
    assert contract["status"] == "Исполняется"
    assert contract["execution_period"] == "до 15.11.2026"
    assert contract["responsible_person"] == "Петров П.П., начальник отдела закупок"
    assert contract["parties"]["supplier"]["company_name"] != ""
    assert contract["parties"]["customer"]["company_name"] != ""
    contract_id = contract["id"]

    # 6. Retrieve contract by id
    detail_res = await case.client.get(f"/profile/contracts/{contract_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == contract_id
    assert detail_res.json()["price"] == 690000.0

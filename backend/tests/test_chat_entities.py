from uuid import uuid4

import pytest

from src.api.app import create_app
from src.config_schema import ApiSettings
from src.db.models import Role, User
from src.services.profile_entities import (
    build_user_system_prompt,
    extract_mentions,
    resolve_chat_entities,
    resolve_profile_entities,
)


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


def test_extract_mentions_basic():
    text = "Проверь @doc-cntr-1 и еще контракт @cntr-26-004-gk!"
    cleaned, aliases = extract_mentions(text)
    assert aliases == ["doc-cntr-1", "cntr-26-004-gk"]
    assert "@doc-cntr-1" in cleaned
    assert "@cntr-26-004-gk" in cleaned


def test_extract_mentions_frontend_contract_tokens():
    text = "Пользователь выбрал контракт: cntr-26-004-gk\n\n[[contract:cntr-26-004-gk]]\n\nНе открывается акт"
    cleaned, aliases = extract_mentions(text)
    assert "cntr-26-004-gk" in aliases
    assert "@cntr-26-004-gk" in cleaned
    assert "Пользователь выбрал контракт" not in cleaned
    assert "[[contract" not in cleaned


def test_extract_mentions_quoted():
    text = 'Посмотри @"Проблема с оплатой" и еще @[Консультация по 44-ФЗ]!'
    cleaned, aliases = extract_mentions(text)
    assert "Проблема с оплатой" in aliases
    assert "Консультация по 44-ФЗ" in aliases
    assert "@Проблема_с_оплатой" in cleaned
    assert "@Консультация_по_44-ФЗ" in cleaned


def test_resolve_entities_by_id():
    fake_user = User(
        id=uuid4(),
        login="supplier_user",
        display_name="Иван Иванов",
        role=Role.SELLER,
    )

    # 1. Document ID
    entities = resolve_profile_entities(["doc-cntr-1"], fake_user)
    assert len(entities) == 1
    assert entities[0].alias == "doc-cntr-1"
    assert entities[0].kind == "document"
    assert "Государственный контракт № 26-004-ГК" in entities[0].text
    assert entities[0].link == "/attachments/doc-cntr-1"
    assert entities[0].extra["id"] == "doc-cntr-1"

    # 2. Contract ID
    entities = resolve_profile_entities(["cntr-26-004-gk"], fake_user)
    assert len(entities) == 1
    assert entities[0].alias == "cntr-26-004-gk"
    assert entities[0].kind == "contract"
    assert "1,450,000" in entities[0].text or "1450000" in entities[0].text
    assert entities[0].link == "/profile/contracts/cntr-26-004-gk"

    # 3. Procurement ID
    entities = resolve_profile_entities(["proc-001"], fake_user)
    assert len(entities) == 1
    assert entities[0].alias == "proc-001"
    assert entities[0].kind == "procurement"
    assert "0173200001426000012" in entities[0].text

    # 4. Offer ID
    entities = resolve_profile_entities(["off-001"], fake_user)
    assert len(entities) == 1
    assert entities[0].alias == "off-001"
    assert entities[0].kind == "offer"
    assert "ООО «ТехноСфера Инжиниринг»" in entities[0].text


def test_resolve_entities_by_title():
    fake_user = User(
        id=uuid4(),
        login="supplier_user",
        display_name="Иван Иванов",
        role=Role.SELLER,
    )

    # Document by title with underscores
    alias = "Техническое_задание_на_поставку_серверного_оборудования.pdf"
    entities = resolve_profile_entities([alias], fake_user)
    assert len(entities) == 1
    assert entities[0].alias == alias
    assert entities[0].kind == "document"
    assert entities[0].extra["id"] == "doc-proc-1-tz"


def test_build_user_system_prompt():
    buyer_user = User(
        id=uuid4(),
        login="buyer_user",
        display_name="Анна Заказчикова",
        role=Role.BUYER,
    )
    prompt = build_user_system_prompt(buyer_user)
    assert "Анна Заказчикова" in prompt
    assert "Заказчик" in prompt
    assert "ГБУ «Центр цифровых технологий»" in prompt
    assert "7701234567" in prompt


async def test_chat_creation_passes_user_info_and_username(case):
    await case.chat()
    # Check what FakeAI received on /ml-api/chat
    chat_calls = [c for c in case.ai.calls if c[0] == "/ml-api/chat"]
    assert len(chat_calls) >= 1
    endpoint, body = chat_calls[0]
    assert body.get("username") is not None
    assert body.get("system_prompt") is not None
    assert "Пользователь" in body["system_prompt"]
    assert "ИНН" in body["system_prompt"]


async def test_send_message_with_document_mention_resolves_entity(case):
    chat_id = await case.chat()

    # Send message with @doc-cntr-1
    res = await case.send(
        chat_id,
        "Посмотри файл @doc-cntr-1, что там с поставкой?",
        client_id=str(uuid4()),
        login="user",
    )
    assert res.status_code == 200, res.text
    data = res.json()
    messages = data["messages"]
    assert len(messages) >= 1
    user_msg = messages[0]
    assert len(user_msg["entities"]) == 1
    assert user_msg["entities"][0]["alias"] == "doc-cntr-1"
    assert user_msg["entities"][0]["kind"] == "document"

    # Verify FakeAI received the entities in POST /ml-api/chat/{id}/message
    msg_calls = [c for c in case.ai.calls if f"/ml-api/chat/{chat_id}/message" in c[0]]
    assert len(msg_calls) >= 1
    _, body = msg_calls[-1]
    assert "entities" in body
    assert len(body["entities"]) == 1
    assert body["entities"][0]["alias"] == "doc-cntr-1"
    assert body["entities"][0]["kind"] == "document"


async def test_send_message_with_contract_mention_resolves_entity(case):
    chat_id = await case.chat()

    res = await case.send(
        chat_id,
        "Вопрос по контракту @cntr-26-004-gk",
        client_id=str(uuid4()),
        login="user",
    )
    assert res.status_code == 200
    msg_calls = [c for c in case.ai.calls if f"/ml-api/chat/{chat_id}/message" in c[0]]
    assert len(msg_calls) >= 1
    _, body = msg_calls[-1]
    assert "entities" in body
    assert len(body["entities"]) == 1
    assert body["entities"][0]["alias"] == "cntr-26-004-gk"
    assert body["entities"][0]["kind"] == "contract"


async def test_send_message_with_frontend_contract_marker(case):
    chat_id = await case.chat()

    text = (
        "Пользователь выбрал контракт: cntr-26-004-gk\n\n"
        "[[contract:cntr-26-004-gk]]\n\n"
        "Не могу скачать закрывающие документы"
    )
    res = await case.send(
        chat_id,
        text,
        client_id=str(uuid4()),
        login="user",
    )
    assert res.status_code == 200
    msg_calls = [c for c in case.ai.calls if f"/ml-api/chat/{chat_id}/message" in c[0]]
    assert len(msg_calls) >= 1
    _, body = msg_calls[-1]
    assert "@cntr-26-004-gk" in body["message"]
    assert len(body["entities"]) == 1
    assert body["entities"][0]["alias"] == "cntr-26-004-gk"
    assert body["entities"][0]["kind"] == "contract"


async def test_messages_history_returns_entities(case):
    chat_id = await case.chat()
    await case.send(
        chat_id,
        "Проверь @doc-cntr-1",
        client_id=str(uuid4()),
        login="user",
    )
    res = await case.request("GET", f"/chats/{chat_id}/messages", login="user")
    assert res.status_code == 200
    page = res.json()
    user_msgs = [m for m in page["items"] if m["sender_type"] == "user"]
    assert len(user_msgs) >= 1
    assert len(user_msgs[0]["entities"]) == 1
    assert user_msgs[0]["entities"][0]["alias"] == "doc-cntr-1"


async def test_resolve_past_chat_by_id_and_title(case):
    # Set up past chat in fake AI
    past_id = "test-past-chat-99"
    case.ai.chats[past_id] = {
        "id": past_id,
        "title": "Ошибка при оплате пошлины",
        "owner": "user",
        "topic": "Платежи",
        "subtopic": "Госпошлина",
        "redirect_line": None,
        "redirect_reason": None,
        "closed_at": None,
        "created_at": "2026-09-12T00:00:00Z",
        "updated_at": "2026-09-12T00:00:00Z",
        "avg_turn_seconds": None,
        "messages": [
            {"id": "m1", "role": "user", "content": "Не проходит оплата пошлины"},
            {"id": "m2", "role": "assistant", "content": "Проверьте статус платежного поручения"},
        ],
    }

    user = User(id=uuid4(), login="user", display_name="Пользователь", role=Role.BUYER)

    # 1. Match by ID
    res_id = await resolve_chat_entities([past_id], user, case.ai_client)
    assert len(res_id) == 1
    assert res_id[0].kind == "chat"
    assert res_id[0].alias == past_id
    assert "Ошибка при оплате пошлины" in res_id[0].text
    assert "Платежи" in res_id[0].text
    assert "Не проходит оплата пошлины" in res_id[0].text
    assert res_id[0].link == f"/chats/{past_id}"

    # 2. Match by title with underscores
    res_title = await resolve_chat_entities(["Ошибка_при_оплате_пошлины"], user, case.ai_client)
    assert len(res_title) == 1
    assert res_title[0].kind == "chat"
    assert res_title[0].alias == "Ошибка_при_оплате_пошлины"
    assert "Ошибка при оплате пошлины" in res_title[0].text

    # 3. Match by prefix e.g. chat:test-past-chat-99
    res_pfx = await resolve_chat_entities(["chat:test-past-chat-99"], user, case.ai_client)
    assert len(res_pfx) == 1
    assert res_pfx[0].kind == "chat"

    # 4. Current chat ID is excluded from matching
    res_cur = await resolve_chat_entities([past_id], user, case.ai_client, current_chat_id=past_id)
    assert len(res_cur) == 0


async def test_send_message_with_past_chat_mention(case):
    # Create chat 1 and post message
    chat1 = await case.chat()
    await case.send(
        chat1,
        "Как изменить реквизиты компании?",
        client_id=str(uuid4()),
        login="user",
    )
    # Update title in fake AI
    case.ai.chats[chat1]["title"] = "Смена реквизитов компании"
    case.ai.chats[chat1]["topic"] = "Профиль компании"

    # Create chat 2 and mention chat 1 by title
    chat2 = await case.chat()
    res = await case.send(
        chat2,
        "Я уже спрашивал об этом в @Смена_реквизитов_компании, но забыл ответ",
        client_id=str(uuid4()),
        login="user",
    )
    assert res.status_code == 200
    msg_calls = [c for c in case.ai.calls if f"/ml-api/chat/{chat2}/message" in c[0]]
    assert len(msg_calls) >= 1
    _, body = msg_calls[-1]
    assert "@Смена_реквизитов_компании" in body["message"]
    assert len(body["entities"]) == 1
    assert body["entities"][0]["alias"] == "Смена_реквизитов_компании"
    assert body["entities"][0]["kind"] == "chat"
    assert "Смена реквизитов компании" in body["entities"][0]["text"]
    assert "Как изменить реквизиты компании?" in body["entities"][0]["text"]
    assert body["entities"][0]["link"] == f"/chats/{chat1}"


async def test_send_message_with_past_chat_by_id(case):
    chat1 = await case.chat()
    await case.send(
        chat1,
        "Вопрос по контракту 44-ФЗ",
        client_id=str(uuid4()),
        login="user",
    )
    chat2 = await case.chat()
    res = await case.send(
        chat2,
        f"Посмотри старый чат @{chat1}",
        client_id=str(uuid4()),
        login="user",
    )
    assert res.status_code == 200
    msg_calls = [c for c in case.ai.calls if f"/ml-api/chat/{chat2}/message" in c[0]]
    assert len(msg_calls) >= 1
    _, body = msg_calls[-1]
    assert len(body["entities"]) == 1
    assert body["entities"][0]["alias"] == chat1
    assert body["entities"][0]["kind"] == "chat"
    assert body["entities"][0]["link"] == f"/chats/{chat1}"

import logging
import os
import re

from src.db.models import User
from src.schemas.entity import EntityIn
from src.schemas.profile import (
    ContractOut,
    DocumentOut,
    OfferOut,
    ProcurementOut,
    ProfileViewOut,
)
from src.services.ai_client import AIClient
from src.services.profile import get_profile_data

logger = logging.getLogger(__name__)

# Pattern to detect quoted mentions like @"Title with spaces" or @'Title' or @[Title]
QUOTED_MENTION_RE = re.compile(r'(?<![\w@])@(?:\[([^\]]+)\]|"([^"]+)"|\'([^\']+)\')')
# Pattern to detect mentions starting with @ followed by word chars, hyphens, dots, colons
MENTION_RE = re.compile(r"(?<![\w@])@([\w\-\.:]+)")

# Frontend legacy contract token patterns
FRONTEND_CONTRACT_TOKEN_RE = re.compile(r"\[\[contract:([^\]]+)\]\]")
FRONTEND_CONTRACT_HEADER_RE = re.compile(r"^Пользователь выбрал контракт:\s*(.+)$", re.MULTILINE)


def extract_mentions(text: str) -> tuple[str, list[str]]:
    """
    Extracts referenced entity aliases from message text and normalizes frontend tokens.
    Returns (cleaned_text_with_at_mentions, list_of_unique_aliases).
    """
    aliases: list[str] = []

    # 1. Extract frontend contract header lines and markers
    def _extract_header(match: re.Match) -> str:
        cid = match.group(1).strip()
        if cid and cid not in aliases:
            aliases.append(cid)
        return ""

    def _extract_marker(match: re.Match) -> str:
        cid = match.group(1).strip()
        if cid and cid not in aliases:
            aliases.append(cid)
        return f"@{cid}"

    cleaned = FRONTEND_CONTRACT_HEADER_RE.sub(_extract_header, text)
    cleaned = FRONTEND_CONTRACT_TOKEN_RE.sub(_extract_marker, cleaned)

    # 2. Extract quoted mentions like @"Title with spaces"
    def _extract_quoted(match: re.Match) -> str:
        alias = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
        norm_token = alias.replace(" ", "_")
        return f"@{norm_token}"

    cleaned = QUOTED_MENTION_RE.sub(_extract_quoted, cleaned)

    # Clean multiple consecutive blank lines or spaces
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # 3. Extract all @alias mentions
    for match in MENTION_RE.finditer(cleaned):
        alias = match.group(1).strip()
        if alias and alias not in aliases:
            aliases.append(alias)

    return cleaned, aliases


def _match_document(alias: str, docs: list[DocumentOut]) -> DocumentOut | None:
    alias_lower = alias.lower()
    alias_norm = alias_lower.replace("_", " ").replace("-", " ")

    # 1. Match by ID
    for doc in docs:
        if doc.id.lower() == alias_lower:
            return doc

    # 2. Match by exact title or filename
    for doc in docs:
        doc_title_lower = doc.title.lower()
        if doc_title_lower == alias_lower:
            return doc
        # Title with spaces replaced by underscores/hyphens
        if doc_title_lower.replace(" ", "_") == alias_lower or doc_title_lower.replace(" ", "-") == alias_lower:
            return doc
        # Filename without extension
        title_no_ext = os.path.splitext(doc_title_lower)[0]
        if title_no_ext == alias_lower or title_no_ext == alias_norm:
            return doc

    # 3. Match if alias substring in title
    if len(alias_norm) >= 3:
        for doc in docs:
            if alias_norm in doc.title.lower():
                return doc

    return None


def _match_contract(alias: str, contracts: list[ContractOut]) -> ContractOut | None:
    alias_lower = alias.lower()
    alias_norm = alias_lower.replace("_", " ").replace("-", " ")

    # 1. Match by ID
    for c in contracts:
        if c.id.lower() == alias_lower:
            return c

    # 2. Match by title substring
    if len(alias_norm) >= 4:
        for c in contracts:
            if alias_norm in c.title.lower():
                return c

    return None


def _match_procurement(alias: str, procurements: list[ProcurementOut]) -> ProcurementOut | None:
    alias_lower = alias.lower()
    alias_norm = alias_lower.replace("_", " ").replace("-", " ")

    # 1. Match by ID or number
    for p in procurements:
        if p.id.lower() == alias_lower or p.number.lower() == alias_lower:
            return p

    # 2. Match by title substring
    if len(alias_norm) >= 4:
        for p in procurements:
            if alias_norm in p.title.lower():
                return p

    return None


def _match_offer(alias: str, offers: list[OfferOut]) -> OfferOut | None:
    alias_lower = alias.lower()
    alias_norm = alias_lower.replace("_", " ").replace("-", " ")

    # 1. Match by ID
    for o in offers:
        if o.id.lower() == alias_lower:
            return o

    # 2. Match by procurement title substring
    if len(alias_norm) >= 4:
        for o in offers:
            if alias_norm in o.procurement_title.lower():
                return o

    return None


def resolve_profile_entities(aliases: list[str], user: User) -> list[EntityIn]:
    """
    Looks up mentioned aliases in user profile (documents/files, contracts, procurements, offers, company)
    supporting both IDs and titles/filenames. Returns list of EntityIn.
    """
    if not aliases:
        return []

    profile: ProfileViewOut = get_profile_data(role=user.role, user=user)

    # Collect all available documents from profile and attached sub-entities
    all_docs: list[DocumentOut] = list(profile.documents)
    all_docs.extend(profile.company.documents)
    for c in profile.contracts:
        all_docs.extend(c.documents)
    for p in profile.procurements:
        all_docs.extend(p.documents)
    for o in profile.offers:
        all_docs.extend(o.documents)

    # Deduplicate docs by id
    seen_doc_ids = set()
    unique_docs: list[DocumentOut] = []
    for d in all_docs:
        if d.id not in seen_doc_ids:
            seen_doc_ids.add(d.id)
            unique_docs.append(d)

    resolved: list[EntityIn] = []
    seen_aliases = set()

    for alias in aliases:
        if alias in seen_aliases:
            continue

        # 1. Check Document / File
        doc = _match_document(alias, unique_docs)
        if doc:
            seen_aliases.add(alias)
            resolved.append(
                EntityIn(
                    alias=alias,
                    kind="document",
                    text=f"Файл/документ: {doc.title} (категория: {doc.category}, тип: {doc.file_type}, размер: {doc.size_bytes} байт)",
                    link=f"/attachments/{doc.id}",
                    extra={
                        "id": doc.id,
                        "title": doc.title,
                        "category": doc.category,
                        "file_type": doc.file_type,
                        "size_bytes": doc.size_bytes,
                        "uploaded_at": doc.uploaded_at.isoformat() if hasattr(doc.uploaded_at, "isoformat") else str(doc.uploaded_at),
                    },
                )
            )
            continue

        # 2. Check Contract
        contract = _match_contract(alias, profile.contracts)
        if contract:
            seen_aliases.add(alias)
            cust = contract.parties.customer
            supp = contract.parties.supplier
            resolved.append(
                EntityIn(
                    alias=alias,
                    kind="contract",
                    text=(
                        f"Контракт {contract.title} (№ {contract.id}), статус: {contract.status}, "
                        f"сумма: {contract.price:,.2f} {contract.currency}, заказчик: {cust.company_name} (ИНН {cust.inn}), "
                        f"поставщик: {supp.company_name} (ИНН {supp.inn}), срок: {contract.execution_period}, "
                        f"этап: {contract.execution_stage}"
                    ),
                    link=f"/profile/contracts/{contract.id}",
                    extra={
                        "id": contract.id,
                        "title": contract.title,
                        "status": contract.status,
                        "price": contract.price,
                        "currency": contract.currency,
                        "customer": cust.company_name,
                        "customer_inn": cust.inn,
                        "supplier": supp.company_name,
                        "supplier_inn": supp.inn,
                        "execution_period": contract.execution_period,
                        "execution_stage": contract.execution_stage,
                        "files": [d.title for d in contract.documents],
                    },
                )
            )
            continue

        # 3. Check Procurement
        proc = _match_procurement(alias, profile.procurements)
        if proc:
            seen_aliases.add(alias)
            resolved.append(
                EntityIn(
                    alias=alias,
                    kind="procurement",
                    text=(
                        f"Закупка № {proc.number} ({proc.title}), заказчик: {proc.customer_name} (ИНН {proc.customer_inn}), "
                        f"начальная цена: {proc.initial_price:,.2f} {proc.currency}, статус: {proc.status}"
                    ),
                    link=f"/procurements/{proc.id}",
                    extra={
                        "id": proc.id,
                        "number": proc.number,
                        "title": proc.title,
                        "customer_name": proc.customer_name,
                        "initial_price": proc.initial_price,
                        "currency": proc.currency,
                        "status": proc.status,
                        "offers_count": proc.offers_count,
                        "files": [d.title for d in proc.documents],
                    },
                )
            )
            continue

        # 4. Check Offer
        offer = _match_offer(alias, profile.offers)
        if offer:
            seen_aliases.add(alias)
            resolved.append(
                EntityIn(
                    alias=alias,
                    kind="offer",
                    text=(
                        f"Предложение № {offer.id} к закупке «{offer.procurement_title}», "
                        f"поставщик: {offer.supplier_name}, цена: {offer.price:,.2f} RUB, "
                        f"статус: {offer.status}, детали: {offer.details}"
                    ),
                    link=None,
                    extra={
                        "id": offer.id,
                        "procurement_id": offer.procurement_id,
                        "supplier_name": offer.supplier_name,
                        "price": offer.price,
                        "status": offer.status,
                        "is_winner": offer.is_winner,
                        "files": [d.title for d in offer.documents],
                    },
                )
            )
            continue

        # 5. Check Company
        if (
            alias.lower() == profile.company.id.lower()
            or alias.lower() in ("company", "my-company", "компания")
            or (len(alias) >= 4 and alias.lower() in profile.company.name.lower())
        ):
            seen_aliases.add(alias)
            comp = profile.company
            resolved.append(
                EntityIn(
                    alias=alias,
                    kind="company",
                    text=(
                        f"Компания {comp.name} ({comp.full_name}), ИНН: {comp.inn}, КПП: {comp.kpp}, "
                        f"роль: {comp.role_label}, руководитель: {comp.ceo}, адрес: {comp.address}"
                    ),
                    link="/profile",
                    extra={
                        "id": comp.id,
                        "name": comp.name,
                        "inn": comp.inn,
                        "kpp": comp.kpp,
                        "role": comp.role.value,
                    },
                )
            )

    return resolved


def build_user_system_prompt(user: User) -> str:
    """
    Builds context about the user for chat creation system_prompt.
    """
    profile = get_profile_data(role=user.role, user=user)
    comp = profile.company
    return (
        f"Пользователь: {user.display_name}, роль на портале: {profile.type_label}. "
        f"Организация: {comp.name} (ИНН: {comp.inn}, КПП: {comp.kpp}), адрес: {comp.address}."
    )


async def resolve_chat_entities(
    aliases: list[str],
    user: User,
    ai: AIClient,
    current_chat_id: str | None = None,
) -> list[EntityIn]:
    """
    Looks up mentioned aliases in past chats from the ML service,
    supporting both IDs and titles. Excludes current_chat_id from matching.
    Returns list of EntityIn with kind="chat".
    """
    if not aliases:
        return []

    uname = user.display_name[:64] if user.display_name else user.login[:64]

    # 1. Fetch candidate chats from ML service
    chats: list[dict] = []
    try:
        chats = await ai.list_chats(username=uname, limit=100)
    except Exception as exc:
        logger.warning("Failed to list chats for username '%s' from ML service: %s", uname, exc)

    # Fallback to user.login if different and no chats found
    if not chats and user.login != uname:
        try:
            chats = await ai.list_chats(username=user.login, limit=100)
        except Exception:
            pass

    # For support/admin or if still empty, list all
    if not chats and (user.is_support or user.is_admin):
        try:
            chats = await ai.list_chats(limit=100)
        except Exception:
            pass

    candidate_chats = [c for c in chats if c.get("id") != current_chat_id]

    resolved: list[EntityIn] = []
    matched_chat_ids: set[str] = set()

    for alias in aliases:
        alias_clean = alias.strip()
        if not alias_clean:
            continue
        alias_lower = alias_clean.lower()
        stripped = alias_lower
        for pfx in ("chat:", "chat-", "chat_"):
            if stripped.startswith(pfx):
                stripped = stripped[len(pfx) :]
                break
        stripped_norm = stripped.replace("_", " ").replace("-", " ").strip()
        alias_norm = alias_lower.replace("_", " ").replace("-", " ").strip()

        matched_chat: dict | None = None

        # a) Match by ID among candidate chats
        for c in candidate_chats:
            cid = str(c.get("id", "")).lower()
            if cid in (alias_lower, stripped):
                matched_chat = c
                break

        # b) Direct get_chat fallback if alias looks like a specific chat ID
        if not matched_chat and (len(stripped) >= 8 or "-" in stripped):
            for candidate_id in (alias_clean, stripped):
                if candidate_id == current_chat_id:
                    continue
                try:
                    direct = await ai.get_chat(candidate_id)
                    if direct and direct.get("id") != current_chat_id:
                        owner = direct.get("owner")
                        if user.is_customer and owner and owner not in (uname, user.login):
                            continue
                        matched_chat = direct
                        break
                except Exception:
                    pass

        # c) Match by Title among candidate chats
        if not matched_chat:
            # First pass: exact or normalized matches
            for c in candidate_chats:
                title = str(c.get("title", "")).strip()
                title_lower = title.lower()
                title_norm = title_lower.replace("_", " ").replace("-", " ").strip()
                if title_lower in (alias_lower, stripped) or title_norm in (alias_norm, stripped_norm):
                    matched_chat = c
                    break
                if title_lower.replace(" ", "_") in (alias_lower, stripped) or title_lower.replace(" ", "-") in (
                    alias_lower,
                    stripped,
                ):
                    matched_chat = c
                    break

            # Second pass: substring match if length >= 4
            if not matched_chat and len(alias_norm) >= 4:
                for c in candidate_chats:
                    title = str(c.get("title", "")).strip()
                    title_lower = title.lower()
                    title_norm = title_lower.replace("_", " ").replace("-", " ").strip()
                    if alias_norm in title_lower or alias_norm in title_norm or title_norm in alias_norm:
                        matched_chat = c
                        break

        if not matched_chat:
            continue

        cid = matched_chat.get("id")
        if not cid or cid == current_chat_id or cid in matched_chat_ids:
            continue

        matched_chat_ids.add(cid)

        # Ensure we have full chat messages
        chat_details = matched_chat
        if "messages" not in chat_details:
            try:
                chat_details = await ai.get_chat(cid)
            except Exception as exc:
                logger.warning("Failed to fetch full chat %s from ML service: %s", cid, exc)

        title = chat_details.get("title") or "Чат"
        topic = chat_details.get("topic")
        subtopic = chat_details.get("subtopic")
        redirect_line = chat_details.get("redirect_line")
        messages = chat_details.get("messages", [])

        lines = [f"Прошлый чат: {title} (ID: {cid})"]
        if topic:
            sub = f" / {subtopic}" if subtopic else ""
            lines.append(f"Тема: {topic}{sub}")
        if redirect_line:
            lines.append(f"Переведён на линию поддержки: L{redirect_line}")

        if messages:
            lines.append("История сообщений:")
            for msg in messages:
                role = msg.get("role", "user")
                role_label = "Пользователь" if role == "user" else "Ассистент"
                content = (msg.get("content") or "").strip()
                if not content:
                    continue
                snippet = " ".join(content.split())
                if len(snippet) > 250:
                    snippet = snippet[:247] + "..."
                lines.append(f"- {role_label}: {snippet}")

        full_text = "\n".join(lines)
        if len(full_text) > 1950:
            full_text = full_text[:1947] + "..."

        resolved.append(
            EntityIn(
                alias=alias_clean[:64],
                kind="chat",
                text=full_text,
                link=f"/chats/{cid}",
                extra={
                    "chat_id": cid,
                    "title": title,
                    "topic": topic,
                    "subtopic": subtopic,
                },
            )
        )

    return resolved


"""Карта сайта Портала поставщиков как инструмент агента.

`sitemap.md` — это markdown со всеми полезными ссылками портала, сгруппированными
по разделам («Единый реестр закупок», «Заказчики», «База знаний», ...). Файл объёмный
и в системный промпт не кладётся: агент достаёт нужное инструментом `sitemap`,
когда пользователь спрашивает, где что-то найти на сайте.

Инструмент умеет два режима:
- без аргумента — вернуть оглавление (названия разделов и число ссылок в них);
- с `query` — вернуть только подходящие ссылки.

Если подходящей ссылки нет, это сигнал перевести обращение на линию поддержки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SITEMAP_PATH = HERE / "sitemap.md"

# Строка ссылки: "- [Заголовок](URL)" либо "- Голый текст" (пункты без ссылки,
# например «Служба технической поддержки (модальное окно на портале)»).
_LINK_RE = re.compile(r"^\s*-\s*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*$")
_PLAIN_RE = re.compile(r"^\s*-\s*(?P<title>.+?)\s*$")
_HEADING_RE = re.compile(r"^(?P<level>#{2,3})\s+(?P<title>.+?)\s*$")

# Сколько ссылок максимум отдавать по одному запросу.
MAX_RESULTS = 25


@dataclass(frozen=True)
class SitemapLink:
    """Одна ссылка карты сайта: что это и куда ведёт."""

    title: str
    url: str
    group: str  # ближайший родительский заголовок верхнего уровня
    subsection: str  # подзаголовок внутри группы, если был

    @property
    def path(self) -> str:
        """Путь раздела: «Группа › Подраздел» либо просто «Группа»."""
        return f"{self.group} › {self.subsection}" if self.subsection else self.group

    @property
    def line(self) -> str:
        """Строка для вывода агенту. У пунктов без URL ссылки нет — это подсказка."""
        if self.url:
            return f"- {self.title} — {self.path}\n  {self.url}"
        return f"- {self.title} — {self.path} (без прямой ссылки, элемент интерфейса портала)"


def _normalize_url(url: str) -> str:
    """Чистит ссылки из markdown и делает их пригодными для подстановки в href.

    В sitemap.md часть ссылок обёрнута в угловые скобки (`<https://.../№> 899-ПП.pdf`),
    потому что иначе markdown ломается на кириллице и пробелах. Агенту и фронтенду нужен
    рабочий URL: снимаем скобки, `>` и пробелы, а кириллицу и пробелы кодируем.
    """
    cleaned = url.strip().strip("<>").strip().replace(">", "").strip()
    base, _, tail = cleaned.partition(" ")
    if tail:
        # Пробелы в хвосте — часть имени файла, а не адреса: переносим в сам путь.
        cleaned = f"{base}{tail}"
    return quote(cleaned, safe="/:#?&=%.+~@!$'*,")


def load_sitemap(path: Path = SITEMAP_PATH) -> list[SitemapLink]:
    """Разбирает sitemap.md в плоский список ссылок с их разделом."""
    links: list[SitemapLink] = []
    group = ""
    subsection = ""
    lines = path.read_text(encoding="utf-8").splitlines()
    # YAML-шапка в начале файла (--- name: ... ---): пропускаем её целиком.
    start = 0
    if lines and lines[0].strip() == "---":
        for offset, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                start = offset + 1
                break

    for raw_line in lines[start:]:
        heading = _HEADING_RE.match(raw_line)
        if heading:
            # ## — группа верхнего уровня, ### — подраздел внутри неё.
            if heading.group("level") == "##":
                group = heading.group("title").strip()
                subsection = ""
            else:
                subsection = heading.group("title").strip()
            continue

        match = _LINK_RE.match(raw_line)
        if match:
            links.append(
                SitemapLink(
                    title=match.group("title").strip(),
                    url=_normalize_url(match.group("url")),
                    group=group,
                    subsection=subsection,
                )
            )
            continue

        # Пункты-подсказки без ссылки (модальные окна поддержки и т.п.).
        # Требуем буквы в тексте, чтобы не ловить горизонтальные линии и прочий мусор.
        plain = _PLAIN_RE.match(raw_line)
        if plain and "[" not in raw_line:
            title = plain.group("title").strip()
            if title and re.search(r"[a-zA-Zа-яА-ЯёЁ]", title):
                links.append(SitemapLink(title=title, url="", group=group, subsection=subsection))
    return links


# ---------------------------------------------------------------------- search


def _tokens(text: str) -> set[str]:
    """Слова запроса в нижнем регистре, без коротких служебных.

    Дефисы сохраняем: «44-ФЗ» и «223-ФЗ» — это цельные значимые токены, а не
    два коротких обрывка. Короткие, но с цифрами («44») тоже оставляем.
    """
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+(?:-[a-zA-Zа-яА-ЯёЁ0-9]+)*", (text or "").lower())
    return {w for w in words if len(w) >= 3 or any(ch.isdigit() for ch in w)}


def _score(link: SitemapLink, tokens: set[str]) -> int:
    """Насколько ссылка подходит под запрос: совпадения в заголовке весят больше."""
    title = link.title.lower()
    path = link.path.lower()
    url = link.url.lower()
    score = 0
    for token in tokens:
        if token in title:
            score += 3
        if token in path:
            score += 2
        if token in url:
            score += 1
    return score


def find_links(query: str, links: list[SitemapLink] | None = None) -> list[SitemapLink]:
    """Ищет ссылки по запросу, релевантные — первыми."""
    items = links if links is not None else load_sitemap()
    tokens = _tokens(query)
    if not tokens:
        return []
    scored = [(_score(link, tokens), link) for link in items]
    hits = [(score, link) for score, link in scored if score > 0]
    hits.sort(key=lambda pair: (-pair[0], pair[1].path, pair[1].title))
    return [link for _score_value, link in hits[:MAX_RESULTS]]


def overview_text(links: list[SitemapLink]) -> str:
    """Оглавление карты сайта: разделы и число ссылок — для выбора запроса."""
    groups: dict[str, dict[str, int]] = {}
    for link in links:
        bucket = groups.setdefault(link.group, {})
        key = link.subsection or ""
        bucket[key] = bucket.get(key, 0) + 1
    lines = []
    for group, subs in groups.items():
        total = sum(subs.values())
        lines.append(f"- {group} ({total}):")
        for sub, count in subs.items():
            if sub:
                lines.append(f"    - {sub} ({count})")
    return "\n".join(lines)


# ----------------------------------------------------------------------- tool


def sitemap(query: str = "") -> str:
    """Найти полезные ссылки на сайте Портала поставщиков (карта сайта).

    Вызывай, когда пользователь спрашивает, ГДЕ что-то найти на сайте: «где посмотреть
    закупки», «где база знаний для поставщика», «ссылка на регламент», «где форум»,
    «как попасть в конструктор документации». Это навигация по сайту, а не инструкция
    по шагам — для шагов используй search/open.

    Если query пустой — вернёт оглавление карты сайта (разделы и число ссылок).
    Если query задан — вернёт только подходящие ссылки с URL.
    Если подходящих ссылок нет, переведи обращение на линию поддержки:
    вызови support_manual() и затем transfer_to_support.

    query — что пользователь хочет найти, словами («котировочные сессии», «регламент»,
    «база знаний заказчика», «форум», «документы 44-ФЗ»).
    """
    links = load_sitemap()
    if not (query or "").strip():
        return (
            "Карта сайта Портала поставщиков — разделы (число ссылок):\n\n"
            f"{overview_text(links)}\n\n"
            "Уточни запросом, что именно нужно найти: sitemap('<что ищем>')."
        )

    found = find_links(query, links)
    if not found:
        return (
            f"В карте сайта ничего не нашлось по запросу «{query}».\n"
            "Такой ссылки на Портале поставщиков может не быть — если вопрос про то, "
            "где найти что-то на сайте, переведи обращение на линию поддержки "
            "(support_manual(), затем transfer_to_support)."
        )

    body = "\n".join(link.line for link in found)
    return (
        f"Ссылки на Портале поставщиков по запросу «{query}» ({len(found)}):\n\n"
        f"{body}\n\n"
        "Вставляй нужные ссылки в ответ прямо как markdown-ссылки: [название](url). "
        "Если подходящей нет — переведи обращение на линию поддержки."
    )


__all__ = [
    "SitemapLink",
    "find_links",
    "load_sitemap",
    "overview_text",
    "sitemap",
]

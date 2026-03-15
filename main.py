# astrbot_plugin_ainews: AI 新闻聚合
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

import feedparser
import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

DEFAULT_MAX_ITEMS = 10
HF_DAILY_PAPERS = "https://huggingface.co/api/daily_papers"
NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
OPENAI_RSS = "https://openai.com/news/rss.xml"
DEEPMIND_RSS = "https://deepmind.google/blog/rss.xml"
TIMEOUT = 15.0


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str

    def __hash__(self) -> int:
        return hash(self.link)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NewsItem):
            return False
        return self.link == other.link


async def _fetch_hf(client: httpx.AsyncClient) -> list[NewsItem]:
    items: list[NewsItem] = []
    for url in (HF_DAILY_PAPERS,):
        try:
            r = await client.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception as e:
            logger.warning("ainews: fetch HF %s failed: %s", url, e)
            continue
        if not isinstance(data, list):
            data = data if isinstance(data, list) else []
        for p in data[:15]:
            if not isinstance(p, dict):
                continue
            raw = p.get("paper") or p
            title = (raw.get("title") or "").strip() or "（无标题）"
            link = (raw.get("id") or "").strip()
            if link and not link.startswith("http"):
                link = f"https://huggingface.co/papers/{link}"
            summary = (raw.get("summary") or raw.get("ai_summary") or "").strip()
            if summary and len(summary) > 200:
                summary = summary[:200] + "…"
            pub = None
            if raw.get("publishedAt"):
                try:
                    pub = datetime.fromisoformat(
                        raw["publishedAt"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass
            if title or link:
                items.append(
                    NewsItem(
                        title=title,
                        link=link or "#",
                        source="HuggingFace Papers",
                        published=pub,
                        summary=summary,
                    )
                )
        if items:
            break
    return items


async def _fetch_newsapi(client: httpx.AsyncClient, api_key: str) -> list[NewsItem]:
    if not (api_key or "").strip():
        return []
    items: list[NewsItem] = []
    try:
        r = await client.get(
            NEWSAPI_EVERYTHING,
            params={"q": "AI", "apiKey": api_key.strip(), "pageSize": 10},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.warning("ainews: NewsAPI status %s", r.status_code)
            return []
        data = r.json()
        if data.get("status") != "ok":
            return []
        for a in data.get("articles", [])[:10]:
            link = (a.get("url") or "").strip()
            if not link:
                continue
            title = (a.get("title") or "").strip() or "（无标题）"
            summary = (a.get("description") or "").strip()
            if summary and len(summary) > 200:
                summary = summary[:200] + "…"
            pub = None
            if a.get("publishedAt"):
                try:
                    pub = datetime.fromisoformat(
                        a["publishedAt"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    source="NewsAPI",
                    published=pub,
                    summary=summary,
                )
            )
    except Exception as e:
        logger.warning("ainews: NewsAPI failed: %s", e)
    return items


async def _fetch_rss(client: httpx.AsyncClient, url: str, name: str) -> list[NewsItem]:
    try:
        resp = await client.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        logger.warning("ainews: fetch rss %s failed: %s", url, e)
        return []
    items: list[NewsItem] = []
    try:
        parsed = feedparser.parse(text)
        for entry in parsed.get("entries", [])[:15]:
            link = (entry.get("link") or "").strip()
            if not link:
                continue
            title = (entry.get("title") or "").strip() or "（无标题）"
            summary = (entry.get("summary", "") or "").strip()
            if summary and len(summary) > 200:
                summary = summary[:200] + "…"
            pub = None
            if entry.get("published_parsed"):
                try:
                    pub = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc)
                except Exception:
                    pass
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    source=name,
                    published=pub,
                    summary=summary,
                )
            )
    except Exception as e:
        logger.warning("ainews: parse rss %s failed: %s", url, e)
    return items


def _format_items(items: list[NewsItem], max_len: int = 4000) -> str:
    lines: list[str] = ["【AI 新闻聚合】"]
    for i, n in enumerate(items, 1):
        line = f"{i}. [{n.source}] {n.title}\n   {n.link}"
        if n.summary:
            line += f"\n   {n.summary}"
        lines.append(line)
    text = "\n\n".join(lines)
    if len(text) > max_len:
        text = text[: max_len - 20] + "\n\n…（已截断）"
    return text


@register(
    "astrbot_plugin_ainews",
    "AstrBot Community",
    "即时聚合 Hugging Face 论文、NewsAPI、OpenAI/DeepMind RSS 等 AI 新闻源",
    "1.0.0",
)
class AinewsPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._max_items = DEFAULT_MAX_ITEMS
        self._newsapi_key = ""

    async def initialize(self) -> None:
        try:
            conf = self.context.config.get_plugin_config(self.context.package_name)
            if isinstance(conf, dict):
                self._max_items = int(conf.get("max_items") or DEFAULT_MAX_ITEMS)
                self._newsapi_key = (conf.get("newsapi_key") or "").strip()
        except Exception as e:
            logger.warning("ainews: load config failed: %s", e)
        self._max_items = max(1, min(30, self._max_items))

    @filter.command("ainews")
    async def cmd_ainews(self, event: AstrMessageEvent) -> None:
        """获取最新 AI 新闻聚合"""
        async for chunk in self._do_aggregate():
            yield event.plain_result(chunk)

    @filter.command("ai新闻")
    async def cmd_ai_news(self, event: AstrMessageEvent) -> None:
        """获取最新 AI 新闻聚合（中文指令）"""
        async for chunk in self._do_aggregate():
            yield event.plain_result(chunk)

    async def _do_aggregate(self) -> AsyncIterator[str]:
        seen: set[str] = set()
        all_items: list[NewsItem] = []
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "AstrBot-ainews/1.0"},
        ) as client:
            tasks = [
                _fetch_hf(client),
                _fetch_newsapi(client, self._newsapi_key),
                _fetch_rss(client, OPENAI_RSS, "OpenAI"),
                _fetch_rss(client, DEEPMIND_RSS, "DeepMind"),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("ainews: task failed: %s", r)
                    continue
                for item in r:
                    if item.link not in seen:
                        seen.add(item.link)
                        all_items.append(item)
        all_items.sort(
            key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        top = all_items[: self._max_items]
        if not top:
            yield "暂无 AI 新闻（可能网络或源暂时不可用，请稍后再试）。"
            return
        yield _format_items(top)

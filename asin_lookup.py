"""自动查找亚马逊 ASIN（文件名映射 → 元数据 → 亚马逊搜索）。"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from kindle_cover_fix import (
    analyze_book,
    extract_metadata_calibre,
    fetch_cover_amazon,
    find_calibre_tool,
)

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")

# 亚马逊搜索被反爬时，可在此添加书名关键词 → ASIN 的手动映射
ASIN_OVERRIDES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"A Game of Thrones 5-Book Bundle", re.I), "B00957T6X6"),
    (re.compile(r"A Clash of Kings", re.I), "B000FC1HBY"),
    (re.compile(r"Introducing Game Theory", re.I), "B01J4P6L90"),
    (re.compile(r"No More Tears", re.I), "B0D93KNGS1"),
    (re.compile(r"Nuclear War", re.I), "B0CBGWMFSN"),
    (re.compile(r"Recursion.*Blake Crouch|Recursion \(Blake", re.I), "B07HDSHP7N"),
    (re.compile(r"That will never work", re.I), "B07QLL7N7D"),
    (re.compile(r"5 Types of Wealth", re.I), "B0D8N2B4KC"),
    (re.compile(r"Disease Delusion", re.I), "B00FJ37DEO"),
    (re.compile(r"Psychology of Money", re.I), "B084HJSJJ2"),
    (re.compile(r"法治的细节", re.I), "B09L12881X"),
    (re.compile(r"咸的玩笑"), "B0G8L698LN"),
    (re.compile(r"耶路撒冷三千年", re.I), "B004LROX8S"),
]


@dataclass
class AsinLookupResult:
    asin: Optional[str]
    title: str
    authors: list[str]
    source: str
    cover_ok: bool = False

    @property
    def found(self) -> bool:
        return bool(self.asin)


def is_amazon_asin(value: str) -> bool:
    value = value.upper().strip()
    return bool(re.fullmatch(r"[A-Z0-9]{10}", value)) and value.startswith("B")


def extract_identifiers_calibre(path: Path) -> str:
    ebook_meta = find_calibre_tool("ebook-meta")
    if not ebook_meta:
        return ""
    result = subprocess.run(
        [str(ebook_meta), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Identifiers"):
            return line.split(":", 1)[-1].strip()
    return ""


def lookup_asin_override(path: Path, title: str) -> Optional[str]:
    for pattern, asin in ASIN_OVERRIDES:
        if pattern.search(path.name) or pattern.search(title):
            return asin
    return None


def search_amazon_asin(title: str, authors: list[str]) -> Optional[str]:
    clean_title = re.sub(r"\s*\([^)]*z-library[^)]*\)", "", title, flags=re.I).strip()
    clean_title = re.sub(r"\s*\(Z-Library\)", "", clean_title, flags=re.I).strip()
    author = authors[0] if authors else ""
    queries = [f"{clean_title} {author}".strip(), clean_title]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }
    hosts = ["https://www.amazon.com", "https://www.amazon.cn"]
    for host in hosts:
        for q in queries:
            if not q:
                continue
            url = f"{host}/s?k={quote(q)}&i=digital-text"
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                for asin in ASIN_RE.findall(resp.text):
                    if asin.startswith("B"):
                        return asin
            except Exception:
                continue
    return None


def resolve_asin(
    path: Path,
    title: str,
    authors: list[str],
    ids_line: str = "",
    *,
    file_asin: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """返回 (asin, source_label)。"""
    override = lookup_asin_override(path, title)
    if override:
        return override, "手动映射表"

    if file_asin and is_amazon_asin(file_asin):
        return file_asin.upper(), "文件内已有 ASIN"

    for part in re.split(r",\s*", ids_line):
        m = re.search(r"asin:([A-Z0-9]{10})", part, re.I)
        if m and is_amazon_asin(m.group(1)):
            return m.group(1).upper(), "Calibre 元数据"

    asin = search_amazon_asin(title, authors)
    if asin:
        return asin, "亚马逊搜索"

    return None, "未找到"


def verify_asin_cover(asin: str, probe_dir: Optional[Path] = None) -> bool:
    base = probe_dir or Path.cwd()
    tmp = base / "_asin_probe.jpg"
    try:
        return fetch_cover_amazon(asin, tmp)
    finally:
        tmp.unlink(missing_ok=True)


def lookup_asin_for_book(path: Path, *, verify_cover: bool = True) -> AsinLookupResult:
    title, authors = extract_metadata_calibre(path)
    if not title:
        info = analyze_book(path)
        title = info.title or path.stem
        authors = info.authors or authors

    ids_line = extract_identifiers_calibre(path)
    info = analyze_book(path)
    file_asin = info.asin if info.asin and is_amazon_asin(info.asin) else None

    asin, source = resolve_asin(
        path,
        title,
        authors,
        ids_line,
        file_asin=file_asin,
    )

    cover_ok = False
    if asin and verify_cover:
        cover_ok = verify_asin_cover(asin, path.parent)

    return AsinLookupResult(
        asin=asin,
        title=title,
        authors=authors,
        source=source,
        cover_ok=cover_ok,
    )

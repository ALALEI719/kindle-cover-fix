#!/usr/bin/env python3
"""
Kindle 书籍封面修复工具

解决两类常见问题：
1. 书库里看不到封面（缺封面图或元数据未指向封面）
2. 锁屏「显示封面」屏保不显示当前在读书籍封面

书伴 (bookfere.com) 方案说明：
- 侧载书封面被替换成「暂无图片」：可用 EBOK + 真实亚马逊 ASIN，或越狱后 BookFere Tools
- Send to Kindle / PDOC 个人文档：电脑版 Fix Kindle Ebook Cover 无法修复，需越狱插件
- 锁屏封面：非商店购买的书可能被亚马逊服务器端限制

用法示例：
  python3 kindle_cover_fix.py scan ~/Downloads
  python3 kindle_cover_fix.py fix book.mobi --for-screensaver
  python3 kindle_cover_fix.py fix book.mobi --bookfere-ebok --asin B000FC0VBQ
  python3 kindle_cover_fix.py recover /Volumes/Kindle
  python3 kindle_cover_fix.py fix-all "/Volumes/Kindle/documents" --fetch-covers
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

import requests
from send_to_kindle import print_setup_instructions, send_book, validate_book_for_send
from PIL import Image

BOOK_EXTENSIONS = {".mobi", ".azw", ".azw3", ".epub", ".kfx"}
BOOKFERE_FIX_ROOT = Path(__file__).resolve().parent / "vendor" / "Fix-Kindle-Ebook-Cover"
CALIBRE_BIN_DIR = Path("/Applications/calibre.app/Contents/MacOS")
EXTH_COVER_OFFSET = 201
EXTH_THUMB_OFFSET = 202
EXTH_ASIN = 113
EXTH_CDE_TYPE = 501
INVALID_OFFSET = 0xFFFFFFFF


@dataclass
class BookInfo:
    path: Path
    title: str = ""
    authors: list[str] = field(default_factory=list)
    format: str = ""
    has_cover: bool = False
    cover_offset: Optional[int] = None
    thumb_offset: Optional[int] = None
    asin: Optional[str] = None
    cde_type: Optional[str] = None
    issues: list[str] = field(default_factory=list)
    screensaver_ready: bool = False

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "title": self.title,
            "authors": self.authors,
            "format": self.format,
            "has_cover": self.has_cover,
            "cover_offset": self.cover_offset,
            "thumb_offset": self.thumb_offset,
            "asin": self.asin,
            "cde_type": self.cde_type,
            "issues": self.issues,
            "screensaver_ready": self.screensaver_ready,
        }


def find_calibre_tool(name: str) -> Optional[Path]:
    app_path = CALIBRE_BIN_DIR / name
    if app_path.exists():
        return app_path
    which = shutil.which(name)
    return Path(which) if which else None


def bytes_to_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, bytes) and len(value) == 4:
        return int.from_bytes(value, "big")
    return None


def parse_title_author_from_filename(path: Path) -> tuple[str, list[str]]:
    stem = path.stem
    stem = re.sub(r"\s*\(z-library[^)]*\)", "", stem, flags=re.I)
    stem = re.sub(r"\s*\[[^\]]+\]\s*$", "", stem)
    if " - " in stem:
        title, author = stem.rsplit(" - ", 1)
        return title.strip(), [author.strip()]
    return stem.strip(), []


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def extract_metadata_calibre(path: Path) -> tuple[str, list[str]]:
    ebook_meta = find_calibre_tool("ebook-meta")
    if not ebook_meta:
        return "", []
    try:
        result = run_cmd([str(ebook_meta), str(path)], check=False)
    except Exception:
        return "", []
    title = ""
    authors: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("Title"):
            title = line.split(":", 1)[-1].strip()
        elif line.startswith("Author"):
            raw = line.split(":", 1)[-1].strip()
            authors = [a.strip() for a in raw.split("&") if a.strip()]
    return title, authors


def extract_cover_calibre(path: Path, dest: Path) -> bool:
    ebook_meta = find_calibre_tool("ebook-meta")
    if not ebook_meta:
        return False
    if dest.exists():
        dest.unlink()
    result = run_cmd([str(ebook_meta), str(path), "--get-cover", str(dest)], check=False)
    return dest.exists() and dest.stat().st_size > 1024


def read_mobi_exth(path: Path) -> dict:
    try:
        from mobi_header import MobiHeader
    except ImportError:
        return {}
    try:
        header = MobiHeader(str(path))
    except Exception:
        return {}
    data = {}
    for exth_id, key in [
        (EXTH_COVER_OFFSET, "cover_offset"),
        (EXTH_THUMB_OFFSET, "thumb_offset"),
        (EXTH_ASIN, "asin"),
        (EXTH_CDE_TYPE, "cde_type"),
    ]:
        try:
            data[key] = header.get_exth_value_by_id(exth_id)
        except Exception:
            data[key] = None
    return data


def epub_has_cover(path: Path) -> bool:
    try:
        from ebooklib import epub
        from ebooklib.epub import ITEM_COVER
    except ImportError:
        return False
    try:
        book = epub.read_epub(str(path))
    except Exception:
        return False
    for item in book.get_items():
        if item.get_type() == ITEM_COVER:
            return True
    for _uid, meta in book.metadata.items():
        for value in meta:
            if getattr(value, "content", None):
                return True
    return False


def analyze_book(path: Path) -> BookInfo:
    info = BookInfo(path=path, format=path.suffix.lower().lstrip("."))
    title, authors = extract_metadata_calibre(path)
    if not title:
        title, authors = parse_title_author_from_filename(path)
    info.title = title
    info.authors = authors

    if info.format in {"mobi", "azw", "azw3"}:
        exth = read_mobi_exth(path)
        info.cover_offset = bytes_to_int(exth.get("cover_offset"))
        info.thumb_offset = bytes_to_int(exth.get("thumb_offset"))
        info.asin = exth.get("asin") if isinstance(exth.get("asin"), str) else None
        info.cde_type = exth.get("cde_type") if isinstance(exth.get("cde_type"), str) else None

        with tempfile.TemporaryDirectory() as tmp:
            cover_path = Path(tmp) / "cover.jpg"
            info.has_cover = extract_cover_calibre(path, cover_path)

        if info.cover_offset in (None, INVALID_OFFSET):
            if info.has_cover:
                info.issues.append("封面图存在，但 CoverOffset 元数据缺失（Kindle 可能无法识别封面）")
            else:
                info.issues.append("缺少嵌入封面")
        elif not info.has_cover:
            info.issues.append("CoverOffset 已设置，但无法提取封面图")

        if not info.asin:
            info.issues.append("缺少 ASIN（建议生成 UUID 作为唯一标识）")
        if info.cde_type != "PDOC":
            info.issues.append(f"cdeType={info.cde_type or '未知'}，侧载书籍建议改为 PDOC 以支持锁屏封面")

        if info.format == "mobi":
            info.issues.append("MOBI 格式在新款 Kindle 上锁屏封面支持较差，建议转为 AZW3")

    elif info.format == "epub":
        info.has_cover = epub_has_cover(path)
        if not info.has_cover:
            info.issues.append("EPUB 缺少封面元数据")
    else:
        info.issues.append(f"暂不直接支持 {info.format} 格式")

    info.screensaver_ready = (
        info.has_cover
        and info.format in {"azw3", "epub"}
        and info.cde_type == "PDOC"
        and bool(info.asin)
        and not any("缺少嵌入封面" in x or "缺少封面" in x for x in info.issues)
    )
    return info


def is_book_file(path: Path) -> bool:
    if path.suffix.lower() not in BOOK_EXTENSIONS:
        return False
    # macOS 在 U 盘上生成的资源分叉文件，不是真正的电子书
    if path.name.startswith("._"):
        return False
    return True


def iter_books(root: Path) -> Iterable[Path]:
    if root.is_file() and is_book_file(root):
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and is_book_file(path):
            yield path


def fetch_cover_openlibrary(title: str, authors: list[str], dest: Path) -> bool:
    params = {"title": title, "limit": 5}
    if authors:
        params["author"] = authors[0]
    try:
        resp = requests.get("https://openlibrary.org/search.json", params=params, timeout=20)
        resp.raise_for_status()
        docs = resp.json().get("docs", [])
    except Exception:
        return False

    cover_id = None
    for doc in docs:
        if doc.get("cover_i"):
            cover_id = doc["cover_i"]
            break
    if not cover_id:
        return False

    url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
    try:
        img_resp = requests.get(url, timeout=20)
        img_resp.raise_for_status()
        dest.write_bytes(img_resp.content)
        return dest.stat().st_size > 1024
    except Exception:
        return False


def fetch_cover_google(title: str, authors: list[str], dest: Path) -> bool:
    query = f"intitle:{title}"
    if authors:
        query += f" inauthor:{authors[0]}"
    url = "https://www.googleapis.com/books/v1/volumes?" + f"q={quote(query)}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:
        return False

    for item in items:
        links = item.get("volumeInfo", {}).get("imageLinks", {})
        image_url = links.get("extraLarge") or links.get("large") or links.get("thumbnail")
        if not image_url:
            continue
        image_url = image_url.replace("http://", "https://")
        try:
            img_resp = requests.get(image_url, timeout=20)
            img_resp.raise_for_status()
            dest.write_bytes(img_resp.content)
            if dest.stat().st_size > 1024:
                return True
        except Exception:
            continue
    return False


def fetch_cover_amazon(asin: str, dest: Path) -> bool:
    """从亚马逊商店拉取与 ASIN 对应的高清封面（书伴 post/305 方案）。"""
    urls = [
        f"https://m.media-amazon.com/images/P/{asin}.01.MAIN._SCRM_.jpg",
        f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg",
        f"http://s3.cn-north-1.amazonaws.com.cn/sitbweb-cn/content/{asin}/images/cover.jpg",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            if dest.stat().st_size > 1024:
                return True
        except Exception:
            continue
    return False


def fetch_cover_auto(title: str, authors: list[str], dest: Path, *, asin: Optional[str] = None) -> bool:
    if asin and fetch_cover_amazon(asin, dest):
        return True
    if fetch_cover_openlibrary(title, authors, dest):
        return True
    return fetch_cover_google(title, authors, dest)


def normalize_cover_image(
    src: Path,
    dest: Path,
    *,
    max_side: int = 1600,
    min_height: int = 1200,
    min_width: int = 0,
) -> None:
    """放大过小的封面，避免 Kindle 书库缩略图生成失败。"""
    with Image.open(src) as img:
        img = img.convert("RGB")
        w, h = img.size
        if min_height and h < min_height:
            scale = min_height / h
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            w, h = img.size
        if min_width and w < min_width:
            scale = min_width / w
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        img.save(dest, format="JPEG", quality=92, optimize=True)


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00]')


def sanitize_filename_component(text: str, *, max_len: int = 80) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", text).strip().strip(".")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned or "Untitled"


def build_send_filename(title: str, authors: list[str], suffix: str = ".epub") -> str:
    """生成 Send to Kindle 附件名（保留中文，避免被亚马逊显示成 book）。"""
    safe_title = sanitize_filename_component(title)
    if authors:
        safe_author = sanitize_filename_component(authors[0], max_len=40)
        return f"{safe_title} - {safe_author}{suffix}"
    return f"{safe_title}{suffix}"


def apply_metadata_calibre(path: Path, title: str, authors: list[str]) -> None:
    ebook_meta = find_calibre_tool("ebook-meta")
    if not ebook_meta:
        raise RuntimeError("未找到 Calibre 的 ebook-meta，请安装 Calibre")
    cmd = [str(ebook_meta), str(path), "--title", title]
    if authors:
        cmd.extend(["--authors", " & ".join(authors)])
    run_cmd(cmd)


def _set_exth_string(header, exth_id: int, value: str) -> bool:
    """仅在记录已存在时修改，避免 add_exth_record 破坏 share-not-sync 生成的 AZW3。"""
    try:
        existing = header.get_exth_value_by_id(exth_id)
    except Exception:
        return False
    if not existing:
        return False
    header.change_exth_metadata(exth_id, value)
    return True


def apply_bookfere_ebok_asin(path: Path, asin: str) -> None:
    """书伴方案：保持 EBOK，写入真实亚马逊 ASIN，让 Kindle 联网拉取商店封面。"""
    from mobi_header import MobiHeader

    header = MobiHeader(str(path))
    if header.get_exth_value_by_id(EXTH_ASIN):
        header.change_exth_metadata(EXTH_ASIN, asin)
    else:
        header.add_exth_record(EXTH_ASIN, asin, str)
    if header.get_exth_value_by_id(EXTH_CDE_TYPE):
        header.change_exth_metadata(EXTH_CDE_TYPE, "EBOK")
    else:
        header.add_exth_record(EXTH_CDE_TYPE, "EBOK", str)
    header.to_file()


def run_bookfere_recover(kindle_root: Path, *, action: str = "fix") -> int:
    """调用书伴 Fix Kindle Ebook Cover 工具修复 system/thumbnails 中的损坏封面。"""
    if not BOOKFERE_FIX_ROOT.exists():
        raise RuntimeError(
            "未找到书伴 Fix-Kindle-Ebook-Cover，请运行: "
            "git clone https://github.com/bookfere/Fix-Kindle-Ebook-Cover.git vendor/Fix-Kindle-Ebook-Cover"
        )
    sys.path.insert(0, str(BOOKFERE_FIX_ROOT))
    from FixCover import FixCover  # type: ignore

    thumbnails = kindle_root / "system" / "thumbnails"
    if not thumbnails.exists():
        raise RuntimeError(
            f"找不到 {thumbnails}。新款 MTP Kindle 通常不暴露此目录，"
            "电脑版书伴工具无法使用；需越狱后安装 BookFere Tools 插件版。"
        )

    fixer = FixCover(logger=print)
    fixer.handle(action=action, roots=[str(kindle_root)])
    return 0


def patch_mobi_metadata(path: Path, *, cde_type: str = "PDOC", ensure_asin: bool = True) -> bool:
    from mobi_header import MobiHeader

    try:
        header = MobiHeader(str(path))
    except Exception:
        return False

    changed = False
    if _set_exth_string(header, EXTH_CDE_TYPE, cde_type):
        changed = True
    if ensure_asin:
        current = header.get_exth_value_by_id(EXTH_ASIN)
        if not current and _set_exth_string(header, EXTH_ASIN, str(uuid.uuid4())):
            changed = True
    if changed:
        header.to_file()
    return changed


def apply_cover_calibre(path: Path, cover: Path) -> None:
    ebook_meta = find_calibre_tool("ebook-meta")
    if not ebook_meta:
        raise RuntimeError("未找到 Calibre 的 ebook-meta，请安装 Calibre")
    run_cmd([str(ebook_meta), str(path), "--cover", str(cover)])


def convert_with_calibre(
    src: Path,
    dest: Path,
    *,
    cover: Optional[Path] = None,
    share_not_sync: bool = True,
) -> None:
    ebook_convert = find_calibre_tool("ebook-convert")
    if not ebook_convert:
        raise RuntimeError("未找到 Calibre 的 ebook-convert，请安装 Calibre")
    cmd = [str(ebook_convert), str(src), str(dest)]
    if share_not_sync and dest.suffix.lower() in {".azw3", ".mobi", ".azw"}:
        cmd.append("--share-not-sync")
    if cover and cover.exists():
        cmd.extend(["--cover", str(cover)])
    run_cmd(cmd)


def set_epub_cover(path: Path, cover: Path) -> None:
    from ebooklib import epub

    book = epub.read_epub(str(path))
    with cover.open("rb") as f:
        cover_data = f.read()
    book.set_cover("cover.jpg", cover_data)
    epub.write_epub(str(path), book)


def fix_book(
    path: Path,
    *,
    cover: Optional[Path] = None,
    fetch_cover: bool = False,
    for_screensaver: bool = False,
    bookfere_ebok: bool = False,
    bookfere_mobi: bool = False,
    asin: Optional[str] = None,
    output_dir: Optional[Path] = None,
    backup: bool = True,
    target_format: Optional[str] = None,
    send_to_kindle: bool = False,
) -> Path:
    info = analyze_book(path)
    work_path = path
    created_temp = False

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        work_path = output_dir / path.name
        if work_path.resolve() != path.resolve():
            shutil.copy2(path, work_path)

    cover_path: Optional[Path] = cover
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # 锁屏/书库封面建议始终使用高清图（即使原书已有低分辨率封面）
        need_better_cover = (not info.has_cover) or for_screensaver or bookfere_ebok
        if cover_path is None and (fetch_cover or bookfere_ebok) and need_better_cover:
            auto_cover = tmpdir / "auto_cover.jpg"
            if fetch_cover_auto(info.title, info.authors, auto_cover, asin=asin):
                cover_path = auto_cover
                source = f"亚马逊 ASIN {asin}" if asin else "自动匹配"
                print(f"  ✓ 已获取封面（{source}）：{info.title}")
            else:
                print(f"  ! 未能自动获取封面：{info.title}")
        elif cover_path is None and for_screensaver and info.has_cover:
            extracted = tmpdir / "extracted_cover.jpg"
            if extract_cover_calibre(work_path, extracted):
                cover_path = extracted
                print(f"  ✓ 已提取原书封面，将放大为高清版本")

        normalized: Optional[Path] = None
        if cover_path and cover_path.exists():
            normalized = tmpdir / "cover_normalized.jpg"
            if send_to_kindle:
                # STK 个人文档缩略图对分辨率更敏感（社区验证 ≥1200×1800）
                normalize_cover_image(
                    cover_path,
                    normalized,
                    max_side=2000,
                    min_height=1800,
                    min_width=1200,
                )
            else:
                normalize_cover_image(cover_path, normalized)
            info.has_cover = True

        want_azw3 = (
            for_screensaver
            or target_format == "azw3"
            or (bookfere_ebok and work_path.suffix.lower() in {".azw3", ".azw"})
        )
        want_epub = target_format == "epub"
        want_mobi = bookfere_mobi or target_format == "mobi" or (
            bookfere_ebok and work_path.suffix.lower() == ".mobi"
        )

        share = not bookfere_ebok

        if want_epub and work_path.suffix.lower() != ".epub":
            out = work_path.with_suffix(".epub")
            convert_with_calibre(work_path, out, cover=normalized, share_not_sync=share)
            if work_path.resolve() != path.resolve():
                work_path.unlink(missing_ok=True)
            work_path = out
            info.format = "epub"
        elif want_azw3 and work_path.suffix.lower() in {".mobi", ".azw", ".epub", ".azw3"}:
            out = work_path.with_suffix(".azw3")
            inplace_azw3 = bookfere_ebok and work_path.suffix.lower() == ".azw3"
            if inplace_azw3:
                out = work_path.with_name(f"{work_path.stem}.__tmp__.azw3")
            elif out.resolve() == work_path.resolve():
                out = work_path.with_name(f"{work_path.stem}_fixed.azw3")
            convert_with_calibre(work_path, out, cover=normalized, share_not_sync=share)
            if inplace_azw3:
                work_path.unlink()
                out.rename(work_path)
                out = work_path
            elif work_path.suffix.lower() != ".azw3" and work_path.resolve() != path.resolve():
                work_path.unlink(missing_ok=True)
            work_path = out
            info.format = "azw3"
        elif want_mobi and work_path.suffix.lower() in {".mobi", ".azw", ".epub", ".azw3"}:
            out = work_path.with_suffix(".mobi")
            if out.resolve() == work_path.resolve():
                out = work_path.with_name(f"{work_path.stem}_fixed.mobi")
            convert_with_calibre(work_path, out, cover=normalized, share_not_sync=share)
            if work_path.suffix.lower() != ".mobi" and work_path.resolve() != path.resolve():
                work_path.unlink(missing_ok=True)
            work_path = out
            info.format = "mobi"
        elif normalized and info.format == "epub":
            set_epub_cover(work_path, normalized)
        elif normalized:
            apply_cover_calibre(work_path, normalized)

    if work_path.suffix.lower() in {".mobi", ".azw", ".azw3"}:
        if bookfere_ebok and asin:
            apply_bookfere_ebok_asin(work_path, asin)
            print(f"  ✓ 已应用书伴 EBOK 方案，ASIN={asin}")
        elif bookfere_mobi and asin:
            from mobi_header import MobiHeader
            header = MobiHeader(str(work_path))
            if header.get_exth_value_by_id(EXTH_ASIN):
                header.change_exth_metadata(EXTH_ASIN, asin)
            else:
                header.add_exth_record(EXTH_ASIN, asin, str)
            if header.get_exth_value_by_id(EXTH_CDE_TYPE):
                header.change_exth_metadata(EXTH_CDE_TYPE, "PDOC")
            else:
                header.add_exth_record(EXTH_CDE_TYPE, "PDOC", str)
            header.to_file()
            print(f"  ✓ 已应用书伴 MOBI+PDOC 方案，ASIN={asin}")
        else:
            patched = patch_mobi_metadata(work_path, cde_type="PDOC", ensure_asin=True)
            if not patched and for_screensaver:
                print("  ℹ 已使用 Calibre --share-not-sync 转换（不再强行写入 PDOC，避免损坏文件）")

    if backup and work_path.resolve() == path.resolve():
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
            print(f"  ✓ 已备份原文件：{backup_path.name}")

    final_info = analyze_book(work_path)
    if for_screensaver and not final_info.screensaver_ready:
        print("  ! 已尽力修复，但可能仍需在 Kindle 上重新同步或重启设备")
    return work_path


def clean_title_for_metadata(title: str, authors: list[str]) -> str:
    """避免书名变成「咸的玩笑 - 刘震云」这种文件名风格。"""
    title = title.strip()
    if not title or title.lower() == "book":
        return title
    if authors:
        suffix = f" - {authors[0]}"
        if title.endswith(suffix):
            return title[: -len(suffix)].strip() or title
    return title


def upgrade_stk_document(
    path: Path,
    *,
    asin: Optional[str] = None,
    fetch_cover: bool = True,
) -> Path:
    """将 Send to Kindle 送达的 PDOC 书就地升级为 EBOK（需 Kindle USB 连接）。"""
    info = analyze_book(path)
    if info.cde_type == "EBOK" and info.asin and info.asin.startswith("B"):
        print(f"  ℹ 已是 EBOK（ASIN={info.asin}），跳过")
        return path
    if not asin:
        from asin_lookup import lookup_asin_for_book

        lookup = lookup_asin_for_book(path, verify_cover=False)
        asin = lookup.asin
        if asin:
            print(f"  ✓ 自动找到 ASIN={asin}（{lookup.source}）")
    if not asin:
        raise ValueError("未找到亚马逊 ASIN，请用 --asin 手动指定")
    return fix_book(
        path,
        fetch_cover=fetch_cover,
        bookfere_ebok=True,
        asin=asin,
        backup=True,
    )


def fix_for_send_to_kindle(
    path: Path,
    *,
    cover: Optional[Path] = None,
    asin: Optional[str] = None,
    output_dir: Optional[Path] = None,
    backup: bool = True,
) -> Path:
    """Send to Kindle 专用修复：高清封面 + EPUB 元数据 + 中文友好文件名。"""
    seed_title, seed_authors = extract_metadata_calibre(path)
    if not seed_title:
        seed_title = path.stem

    work_path = fix_book(
        path,
        cover=cover,
        fetch_cover=True,
        for_screensaver=False,
        asin=asin,
        output_dir=output_dir,
        backup=backup,
        target_format="epub",
        bookfere_ebok=False,
        bookfere_mobi=False,
        send_to_kindle=True,
    )

    title, authors = extract_metadata_calibre(work_path)
    if not title or title.lower() == "book":
        title = seed_title
    if not authors:
        authors = seed_authors
    title = clean_title_for_metadata(title, authors)
    apply_metadata_calibre(work_path, title, authors)

    send_name = build_send_filename(title, authors, work_path.suffix.lower())
    send_path = work_path.with_name(send_name)
    if send_path.resolve() != work_path.resolve():
        if send_path.exists():
            send_path.unlink()
        work_path.rename(send_path)
        work_path = send_path

    print(f"  ✓ STK 待发文件：{work_path.name}")
    return work_path


def cmd_diagnose_send(_: argparse.Namespace) -> int:
    from send_to_kindle import diagnose_send_setup

    print("Send to Kindle 诊断")
    print("=" * 40)
    for line in diagnose_send_setup():
        print(line)
    return 0


def cmd_setup_send(_: argparse.Namespace) -> int:
    from send_to_kindle import write_example_config

    write_example_config()
    print_setup_instructions()
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    try:
        validate_book_for_send(path)
        message = send_book(path, subject=args.subject)
    except Exception as exc:
        print(f"发送失败：{exc}", file=sys.stderr)
        print("请先运行：python3 kindle_cover_fix.py setup-send", file=sys.stderr)
        return 1
    print(message)
    print_send_to_kindle_tips()
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"路径不存在：{root}", file=sys.stderr)
        return 1

    books = list(iter_books(root))
    if not books:
        print("未找到电子书文件（支持 mobi / azw / azw3 / epub）")
        return 0

    rows = []
    for book in books:
        info = analyze_book(book)
        rows.append(info)
        status = "✓ 正常" if not info.issues else "✗ 有问题"
        print(f"\n[{status}] {book.name}")
        print(f"  标题：{info.title or '（未知）'}")
        if info.authors:
            print(f"  作者：{', '.join(info.authors)}")
        print(f"  格式：{info.format.upper()} | 封面：{'有' if info.has_cover else '无'} | 锁屏就绪：{'是' if info.screensaver_ready else '否'}")
        for issue in info.issues:
            print(f"  - {issue}")

    if args.json:
        print(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2))

    problem_count = sum(1 for r in rows if r.issues)
    print(f"\n共 {len(rows)} 本书，{problem_count} 本需要处理。")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    kindle_root = Path(args.path).expanduser().resolve()
    try:
        return run_bookfere_recover(kindle_root, action=args.action)
    except Exception as exc:
        print(f"书伴封面修复失败：{exc}", file=sys.stderr)
        return 1


def cmd_upgrade(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1
    print(f"正在升级 STK 书籍：{path.name}")
    try:
        result = upgrade_stk_document(path, asin=args.asin, fetch_cover=not args.no_fetch_cover)
    except Exception as exc:
        print(f"升级失败：{exc}", file=sys.stderr)
        return 1
    print(f"完成：{result}")
    print_upgrade_tips()
    return 0


def print_upgrade_tips() -> None:
    print("\n--- Kindle 端检查清单 ---")
    print("1. 安全弹出 Kindle 后重新插上，或重启 Kindle")
    print("2. 保持 Wi-Fi 开启，打开该书读几页")
    print("3. 回书库查看封面；锁屏测试「显示封面」")


def cmd_fix(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1

    if args.send_to_kindle and args.bookfere_ebok:
        print(
            "⚠ Send to Kindle 会把书标为个人文档 PDOC，与 --bookfere-ebok 冲突。"
            "已自动改用「嵌入式高清封面 + AZW3」方案。",
            file=sys.stderr,
        )

    output_dir = Path(args.output).expanduser().resolve() if args.output else None
    cover = Path(args.cover).expanduser().resolve() if args.cover else None

    asin = args.asin
    if not asin and (args.auto_asin or args.send_to_kindle):
        from asin_lookup import lookup_asin_for_book

        lookup = lookup_asin_for_book(path, verify_cover=False)
        asin = lookup.asin
        if asin:
            print(f"  ✓ 自动找到 ASIN={asin}（{lookup.source}）")
        else:
            print("  ! 未能自动找到 ASIN，将继续尝试其他封面来源", file=sys.stderr)

    print(f"正在修复：{path.name}")
    try:
        if args.send_to_kindle:
            result = fix_for_send_to_kindle(
                path,
                cover=cover,
                asin=asin,
                output_dir=output_dir,
                backup=not args.no_backup,
            )
        else:
            result = fix_book(
                path,
                cover=cover,
                fetch_cover=args.fetch_cover or bool(asin),
                for_screensaver=args.for_screensaver,
                bookfere_ebok=args.bookfere_ebok,
                bookfere_mobi=args.bookfere_mobi,
                asin=asin,
                output_dir=output_dir,
                backup=not args.no_backup,
                target_format=args.format,
            )
    except Exception as exc:
        print(f"修复失败：{exc}", file=sys.stderr)
        return 1

    print(f"完成：{result}")

    if args.send_to_kindle:
        try:
            title, authors = extract_metadata_calibre(result)
            message = send_book(
                result,
                subject=args.send_subject or title or result.stem,
                title=title or result.stem,
                author=authors[0] if authors else None,
            )
            print(message)
            print_send_to_kindle_tips()
        except Exception as exc:
            print(f"修复成功，但 Send to Kindle 发送失败：{exc}", file=sys.stderr)
            print(f'可手动发送：python3 kindle_cover_fix.py send "{result}"', file=sys.stderr)
            return 1
        return 0

    print_kindle_tips()
    return 0


def cmd_fix_all(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"路径不存在：{root}", file=sys.stderr)
        return 1

    output_dir = Path(args.output).expanduser().resolve() if args.output else None
    books = list(iter_books(root))
    if not books:
        print("未找到电子书文件")
        return 0

    fixed = 0
    skipped = 0
    for book in books:
        info = analyze_book(book)
        need_fix = bool(info.issues) or args.force
        if not need_fix:
            skipped += 1
            continue
        print(f"\n处理：{book.name}")
        try:
            fix_book(
                book,
                fetch_cover=args.fetch_cover,
                for_screensaver=args.for_screensaver,
                output_dir=output_dir,
                backup=not args.no_backup,
                target_format=args.format,
            )
            fixed += 1
        except Exception as exc:
            print(f"  跳过（出错）：{exc}")

    print(f"\n完成：修复 {fixed} 本，跳过 {skipped} 本。")
    print_kindle_tips()
    return 0


def print_send_to_kindle_tips() -> None:
    print(
        """
--- Send to Kindle 后续步骤 ---
1. 确保 Kindle 已联网（Wi-Fi 开启）
2. 1-5 分钟后在「图书馆」或「个人文档」中查看
3. 若封面仍空白：打开该书读几页，等待索引完成后再看
4. 锁屏「显示封面」对个人文档支持有限，书店购买的书效果更好
5. 若需要书库 + 锁屏封面都完美：请改用 USB 复制（--bookfere-ebok 方案）
"""
    )


def print_kindle_tips() -> None:
    print(
        """
--- Kindle 端检查清单 ---
1. 设置 → 设备选项 → 显示封面（Display Cover）→ 开启
2. 若设备带广告（Special Offers），需先移除广告才能用「显示封面」
3. 删除 Kindle 上同书的旧副本，以及对应的 .sdr 文件夹
4. 把修复后的 AZW3/EPUB 复制到 documents 文件夹
5. 在「个人文档」或「图书馆」中找到该书，打开并读几页
6. 保持 Wi-Fi 开启，等待 1-2 分钟后再锁屏测试
7. 若仍不显示：重启 Kindle；或改用 EPUB 版本测试
"""
    )


def cmd_setup(_: argparse.Namespace) -> int:
    calibre = find_calibre_tool("ebook-convert")
    print("Kindle 锁屏封面 / 书籍封面修复指南")
    print("=" * 40)
    print(f"Calibre 状态：{'已安装 ✓' if calibre else '未安装 ✗（建议 brew install --cask calibre）'}")
    print(
        """
常见问题原因：
- 侧载 MOBI 缺封面元数据（CoverOffset）
- 侧载书籍 cdeType 不是 PDOC，Kindle 不生成缩略图
- 新款 Kindle 对 MOBI 锁屏封面支持差，需转 AZW3
- 设备未开启「显示封面」，或设备带广告

推荐修复流程：
1. python3 kindle_cover_fix.py scan ~/你的书籍文件夹
2. python3 kindle_cover_fix.py fix 某本书.mobi --fetch-cover --for-screensaver
3. 把生成的 .azw3 拷到 Kindle documents 目录
4. 在 Kindle 上开启「显示封面」并重新打开该书
"""
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="修复 Kindle 书籍封面与锁屏屏保显示问题",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描书籍，检查封面与锁屏就绪状态")
    scan.add_argument("path", help="文件或文件夹路径")
    scan.add_argument("--json", action="store_true", help="输出 JSON 结果")
    scan.set_defaults(func=cmd_scan)

    fix = sub.add_parser("fix", help="修复单本书籍")
    fix.add_argument("path", help="电子书文件路径")
    fix.add_argument("--cover", help="手动指定封面图片路径")
    fix.add_argument("--fetch-cover", action="store_true", help="自动从 Open Library / Google Books 获取封面")
    fix.add_argument("--bookfere-ebok", action="store_true", help="书伴方案：EBOK + 真实亚马逊 ASIN（需配合 --asin）")
    fix.add_argument("--bookfere-mobi", action="store_true", help="书伴方案：MOBI + PDOC，从文件内读取封面")
    fix.add_argument("--asin", help="亚马逊商店真实 ASIN，如 B000FC0VBQ")
    fix.add_argument(
        "--auto-asin",
        action="store_true",
        help="自动从元数据 / 亚马逊搜索查找 ASIN（与 --asin 二选一，--asin 优先）",
    )
    fix.add_argument("--for-screensaver", action="store_true", help="针对锁屏封面优化（转 AZW3 + PDOC）")
    fix.add_argument("--format", choices=["azw3", "epub", "mobi"], help="强制输出格式")
    fix.add_argument("--output", help="输出目录（默认原地修改）")
    fix.add_argument("--no-backup", action="store_true", help="不创建 .bak 备份")
    fix.add_argument(
        "--send-to-kindle",
        action="store_true",
        help="修复后通过 Send to Kindle 邮件发送到设备（需先 setup-send）",
    )
    fix.add_argument("--send-subject", help="Send to Kindle 邮件主题（默认用书文件名）")
    fix.set_defaults(func=cmd_fix)

    send = sub.add_parser("send", help="把已修复的电子书发送到 Kindle（Send to Kindle 邮件）")
    send.add_argument("path", help="电子书文件路径")
    send.add_argument("--subject", help="邮件主题（默认用书文件名）")
    send.set_defaults(func=cmd_send)

    setup_send = sub.add_parser("setup-send", help="生成 Send to Kindle 配置文件并显示设置说明")
    setup_send.set_defaults(func=cmd_setup_send)

    diagnose_send = sub.add_parser("diagnose-send", help="检查 Send to Kindle 配置与常见收不到书的原因")
    diagnose_send.set_defaults(func=cmd_diagnose_send)

    upgrade = sub.add_parser(
        "upgrade",
        help="将 Kindle documents 里 STK 送达的 PDOC 书就地升级为 EBOK（需 USB 连接）",
    )
    upgrade.add_argument("path", help="Kindle documents 中的 .azw3 文件路径")
    upgrade.add_argument("--asin", help="亚马逊 ASIN")
    upgrade.add_argument("--no-fetch-cover", action="store_true", help="不重新下载封面")
    upgrade.set_defaults(func=cmd_upgrade)

    fix_all = sub.add_parser("fix-all", help="批量修复文件夹内书籍")
    fix_all.add_argument("path", help="文件夹路径")
    fix_all.add_argument("--fetch-cover", action="store_true", help="缺封面时自动联网获取")
    fix_all.add_argument("--for-screensaver", action="store_true", help="针对锁屏封面优化")
    fix_all.add_argument("--format", choices=["azw3", "epub"], help="强制输出格式")
    fix_all.add_argument("--output", help="输出目录")
    fix_all.add_argument("--force", action="store_true", help="即使扫描无问题也强制处理")
    fix_all.add_argument("--no-backup", action="store_true", help="不创建 .bak 备份")
    fix_all.set_defaults(func=cmd_fix_all)

    setup = sub.add_parser("setup", help="显示 Kindle 端设置说明")
    setup.set_defaults(func=cmd_setup)

    recover = sub.add_parser("recover", help="调用书伴工具修复 Kindle system/thumbnails 损坏封面")
    recover.add_argument("path", help="Kindle 根目录，如 /Volumes/Kindle")
    recover.add_argument("--action", choices=["fix", "clean"], default="fix", help="fix=修复封面, clean=清理孤立封面")
    recover.set_defaults(func=cmd_recover)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

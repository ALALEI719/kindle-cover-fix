#!/usr/bin/env python3
"""批量书伴 EBOK 方案：按修改日期筛选、保持文件名、备份后部署到 Kindle。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kindle_cover_fix import (  # noqa: E402
    extract_metadata_calibre,
    fix_book,
    is_book_file,
)
from asin_lookup import ASIN_OVERRIDES, lookup_asin_for_book, verify_asin_cover  # noqa: E402

KINDLE_DOCS = Path("/Volumes/Kindle/documents")
CUTOFF = datetime(2025, 12, 5)

DICT_PATTERNS = re.compile(r"(dictionary|词典|dict\b|kindledict)", re.I)
SKIP_PATTERNS = re.compile(r"(Tender_EBOK|RETEST|_fixed\b)", re.I)


def is_dictionary(path: Path) -> bool:
    return bool(DICT_PATTERNS.search(path.stem))


def should_skip(path: Path) -> bool:
    return bool(SKIP_PATTERNS.search(path.name))


def file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def eligible_files(docs: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(docs.iterdir()):
        if not path.is_file() or not is_book_file(path):
            continue
        if file_mtime(path) < CUTOFF:
            continue
        if is_dictionary(path) or should_skip(path):
            continue
        files.append(path)
    return files


def setup_dirs(backup_dir: Path | None) -> tuple[Path, Path, Path, Path]:
    if backup_dir is None:
        base = ROOT / "output" / "kindle-batch-backup"
        existing = sorted(base.glob("*/originals"), reverse=True) if base.exists() else []
        if existing and any(existing[0].iterdir()):
            backup_dir = existing[0].parent
        else:
            backup_dir = base / datetime.now().strftime("%Y%m%d-%H%M%S")
    fixed = backup_dir / "fixed"
    originals = backup_dir / "originals"
    report = backup_dir / "report.json"
    originals.mkdir(parents=True, exist_ok=True)
    fixed.mkdir(parents=True, exist_ok=True)
    return backup_dir, fixed, originals, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", type=Path, default=None, help="复用已有备份目录")
    args = parser.parse_args()

    backup_dir, fixed_dir, original_dir, report_path = setup_dirs(args.backup_dir)

    if not KINDLE_DOCS.exists():
        print("错误：未找到 Kindle，请连接设备后重试。", file=sys.stderr)
        return 1

    ORIGINAL_DIR = original_dir
    FIXED_DIR = fixed_dir
    BACKUP_DIR = backup_dir
    REPORT_PATH = report_path

    targets = eligible_files(KINDLE_DOCS)

    # 若 Kindle 上已移走，则从备份目录续跑
    if ORIGINAL_DIR.exists() and any(ORIGINAL_DIR.iterdir()):
        existing = [p for p in sorted(ORIGINAL_DIR.iterdir()) if is_book_file(p)]
        if existing and len(targets) < len(existing):
            targets = existing

    if not targets:
        print("没有符合日期范围的书籍需要处理。")
        return 0

    report = {
        "cutoff": CUTOFF.isoformat(),
        "kindle_documents": str(KINDLE_DOCS),
        "backup_dir": str(BACKUP_DIR),
        "processed": [],
        "skipped": [],
        "failed": [],
    }

    print(f"共 {len(targets)} 本书待处理，备份目录：{BACKUP_DIR}\n")

    # 1) 先备份（剪切）原文件到项目目录
    staged: list[tuple[Path, Path]] = []
    for src in targets:
        dst = ORIGINAL_DIR / src.name
        if src.resolve() == dst.resolve():
            staged.append((src, dst))
            print(f"从备份处理：{src.name}")
            continue
        if dst.exists():
            staged.append((src, dst))
            print(f"已存在备份，继续处理：{src.name}")
            continue
        if not src.exists():
            continue
        shutil.move(str(src), str(dst))
        staged.append((src, dst))
        print(f"已备份：{src.name}")

    # 2) 修复并写入 fixed 目录（保持文件名）
    for original_path, backup_path in staged:
        final_path = FIXED_DIR / backup_path.name
        deploy = KINDLE_DOCS / backup_path.name
        if final_path.exists() and deploy.exists():
            print(f"\n跳过（已处理）：{backup_path.name}")
            report["skipped"].append({"file": backup_path.name, "reason": "已存在修复文件"})
            continue

        title, authors = extract_metadata_calibre(backup_path)
        lookup = lookup_asin_for_book(backup_path, verify_cover=True)
        asin = lookup.asin

        print(f"\n处理：{backup_path.name}")
        if not asin:
            report["failed"].append({"file": backup_path.name, "reason": "未找到亚马逊 ASIN"})
            print("  ✗ 未找到 ASIN，保留备份，不部署")
            continue
        if not verify_asin_cover(asin, BACKUP_DIR):
            report["failed"].append({"file": backup_path.name, "reason": f"ASIN {asin} 无封面"})
            print(f"  ✗ ASIN {asin} 无法下载封面，保留备份，不部署")
            continue

        try:
            fixed = fix_book(
                backup_path,
                bookfere_ebok=True,
                asin=asin,
                fetch_cover=True,
                output_dir=FIXED_DIR,
                backup=False,
            )
            # 确保文件名与原始一致
            final_path = FIXED_DIR / backup_path.name
            if fixed.name != backup_path.name:
                if final_path.exists():
                    final_path.unlink()
                fixed.rename(final_path)
                fixed = final_path

            # 3) 部署到 Kindle
            deploy = KINDLE_DOCS / backup_path.name
            shutil.copy2(fixed, deploy)
            report["processed"].append(
                {"file": backup_path.name, "asin": asin, "title": title, "deployed": str(deploy)}
            )
            print(f"  ✓ 完成 ASIN={asin} → 已复制到 Kindle")
        except Exception as exc:
            report["failed"].append({"file": backup_path.name, "reason": str(exc)})
            print(f"  ✗ 失败：{exc}")

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存：{REPORT_PATH}")
    print(f"成功 {len(report['processed'])}，失败 {len(report['failed'])}")
    return 0 if not report["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

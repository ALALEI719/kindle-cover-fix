#!/usr/bin/env python3
"""Kindle 封面修复 — Streamlit 界面（USB 修复 + 复制到 Kindle documents）。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import streamlit as st

from asin_lookup import AsinLookupResult, lookup_asin_for_book
from kindle_cover_fix import find_calibre_tool, fix_book

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "streamlit-fixed"
KINDLE_DOCS = Path("/Volumes/Kindle/documents")

st.set_page_config(
    page_title="Kindle 封面修复",
    page_icon="📚",
    layout="centered",
)

st.title("📚 Kindle 封面修复")
st.caption("上传电子书 → EBOK 修复封面 → 复制到 Kindle 的 documents 文件夹")


def calibre_ok() -> bool:
    return find_calibre_tool("ebook-convert") is not None


def kindle_mounted() -> bool:
    return KINDLE_DOCS.exists()


def render_status_bar() -> None:
    cols = st.columns(3)
    with cols[0]:
        st.metric("Calibre", "已安装 ✓" if calibre_ok() else "未安装 ✗")
    with cols[1]:
        st.metric("Kindle", "已连接 ✓" if kindle_mounted() else "未连接")
    with cols[2]:
        st.metric("输出目录", str(OUTPUT_DIR.relative_to(ROOT)))


def lookup_uploaded_book(uploaded) -> AsinLookupResult:
    with tempfile.TemporaryDirectory(prefix="kindle-asin-") as tmp:
        src = Path(tmp) / uploaded.name
        src.write_bytes(uploaded.getvalue())
        return lookup_asin_for_book(src, verify_cover=True)


def deploy_to_kindle(fixed: Path) -> Path:
    if not kindle_mounted():
        raise RuntimeError("未检测到 Kindle，请用 USB 连接设备（/Volumes/Kindle）")
    dest = KINDLE_DOCS / fixed.name
    if dest.exists():
        backup = dest.with_suffix(dest.suffix + ".bak")
        if not backup.exists():
            shutil.move(str(dest), str(backup))
    shutil.copy2(fixed, dest)
    return dest


def tab_fix() -> None:
    st.subheader("🚀 修复封面并复制到 Kindle")

    if not calibre_ok():
        st.error("未检测到 Calibre。请先安装：`brew install --cask calibre`")
        return

    if not kindle_mounted():
        st.warning("Kindle 未连接。仍可修复并下载文件，连接后再复制到设备。")

    uploaded = st.file_uploader(
        "上传电子书",
        type=["mobi", "azw", "azw3", "epub"],
        help="支持 MOBI / AZW / AZW3 / EPUB。EPUB 会转为 AZW3 再修复。",
    )

    lookup: AsinLookupResult | None = None
    if uploaded is not None:
        upload_key = f"{uploaded.name}:{len(uploaded.getvalue())}"
        if st.session_state.get("last_upload_key") != upload_key:
            with st.spinner("正在识别书名并查找亚马逊 ASIN…"):
                lookup = lookup_uploaded_book(uploaded)
                st.session_state["last_upload_key"] = upload_key
                st.session_state["book_lookup"] = lookup
                st.session_state["asin_input"] = lookup.asin or ""
        else:
            lookup = st.session_state.get("book_lookup")

        if lookup:
            st.markdown(f"**书名：** {lookup.title or uploaded.name}")
            if lookup.authors:
                st.markdown(f"**作者：** {', '.join(lookup.authors)}")
            if lookup.found:
                hint = "封面已验证 ✓" if lookup.cover_ok else "封面未验证（仍会尝试修复）"
                st.success(f"ASIN：**{lookup.asin}**（{lookup.source}，{hint}）")
            else:
                st.warning("未能自动找到 ASIN，请手动填写下方。")

    if "asin_input" not in st.session_state:
        st.session_state["asin_input"] = ""

    asin = st.text_input(
        "亚马逊 ASIN",
        key="asin_input",
        placeholder="例如 B0G8L698LN",
    ).strip().upper() or None

    deploy = st.checkbox("修复后复制到 Kindle documents", value=kindle_mounted())

    if st.button("✨ 修复封面", type="primary", use_container_width=True):
        if uploaded is None:
            st.error("请先上传一本电子书")
            return
        if not asin:
            st.error("请填写 ASIN（修复 EBOK 方案必需）")
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kindle-cover-") as tmp:
            src = Path(tmp) / uploaded.name
            src.write_bytes(uploaded.getvalue())
            progress = st.progress(0, text="正在修复…")
            try:
                fixed = fix_book(
                    src,
                    bookfere_ebok=True,
                    asin=asin,
                    fetch_cover=True,
                    output_dir=OUTPUT_DIR,
                    backup=False,
                )
                # 尽量保持上传时的文件名（扩展名可能变为 .azw3）
                target_name = Path(uploaded.name).stem + fixed.suffix.lower()
                final_path = OUTPUT_DIR / target_name
                if fixed.resolve() != final_path.resolve():
                    if final_path.exists():
                        final_path.unlink()
                    fixed.rename(final_path)
                    fixed = final_path

                progress.progress(70, text="修复完成")
                if deploy:
                    deployed = deploy_to_kindle(fixed)
                    progress.progress(100, text="已复制到 Kindle")
                    st.success(f"已部署到：{deployed}")
                else:
                    progress.progress(100, text="完成")
                    st.success(f"已保存到：{fixed}")

                st.caption(f"ASIN={asin} · 格式={fixed.suffix}")
                st.markdown(
                    """
**Kindle 上请检查：**
1. 安全弹出设备后重新打开 Wi-Fi
2. 打开该书读几页
3. 看书库缩略图与锁屏「显示封面」
                    """
                )
                with fixed.open("rb") as f:
                    st.download_button(
                        "⬇️ 下载修复后的文件",
                        data=f.read(),
                        file_name=fixed.name,
                        mime="application/octet-stream",
                    )
            except Exception as exc:
                progress.empty()
                st.error(f"处理失败：{exc}")


def tab_help() -> None:
    st.subheader("📖 使用说明")
    st.markdown(
        """
### 标准流程（已固定）

```
你提供电子书（epub / mobi / azw3）
    → 自动查 ASIN + 书伴 EBOK 修复封面
    → 复制到 /Volumes/Kindle/documents/
    → 书库缩略图 + 锁屏封面正常显示
```

### 支持格式

| 输入格式 | 修复后放进 Kindle |
|----------|-------------------|
| AZW3 / MOBI / AZW | 同名 AZW3 |
| EPUB | 转为 AZW3（文件名 stem 不变） |

**不要把未修复的 EPUB 直接拷进 Kindle。** 请先用本工具修复。

### 命令行

```bash
python3 kindle_cover_fix.py fix "某书.azw3" \\
  --bookfere-ebok --asin B0XXXX --fetch-cover \\
  --output ./output/fixed

cp ./output/fixed/某书.azw3 /Volumes/Kindle/documents/
```

### 批量（按日期筛选 Kindle 上的书）

```bash
python3 batch_kindle_deploy.py
```
        """
    )


def main() -> None:
    render_status_bar()
    st.divider()
    tab_main, tab_doc = st.tabs(["🚀 修复封面", "📖 使用说明"])
    with tab_main:
        tab_fix()
    with tab_doc:
        tab_help()


if __name__ == "__main__":
    main()

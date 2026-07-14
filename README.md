# Kindle 封面修复工具 (kindle-cover-fix)

修复 **Kindle 侧载电子书** 的书库缩略图与锁屏「显示封面」问题。

采用 [书伴 (bookfere.com)](https://bookfere.com) 的 **EBOK + 真实亚马逊 ASIN** 方案，通过 **USB 复制到 Kindle `documents` 文件夹** 部署。已在 macOS + Kindle Paperwhite 上验证有效。

---

## 标准流程（项目定位）

```
你提供电子书（手动放到项目 / 交给工具处理）
    ↓
自动查找 ASIN + 嵌入亚马逊官方封面 + 设置 EBOK
    ↓
修复后的 AZW3 复制到 /Volumes/Kindle/documents/
    ↓
Kindle 联网 → 书库缩略图 + 锁屏封面正常显示
```

**不使用 Send to Kindle 无线传书**（个人文档 PDOC 无法稳定显示封面）。

---

## 支持格式

| 你可提供的格式 | 修复后放进 Kindle 的格式 |
|----------------|--------------------------|
| `.azw3` / `.mobi` / `.azw` | `.azw3`（保持原文件名） |
| `.epub` | 转为 `.azw3`（文件名主体不变） |

- **推荐：** 最终放进 `documents` 的都是 **修好的 AZW3**。
- **不要** 把未修复的 EPUB 直接拷进 Kindle（老款打不开，新款即使能打开也没有封面）。

---

## 环境要求

| 依赖 | 说明 |
|------|------|
| macOS | 已测试；Linux 需自行调整 Calibre 路径 |
| Python 3.9+ | |
| [Calibre](https://calibre-ebook.com/download) | 读写元数据、嵌封面、格式转换 |
| Kindle | USB 挂载为 `/Volumes/Kindle` |

```bash
brew install --cask calibre
pip install -r requirements.txt
```

---

## 快速开始

### 1. 修复单本书

```bash
python3 kindle_cover_fix.py fix "Recursion.azw3" \
  --bookfere-ebok \
  --asin B07HDSHP7N \
  --fetch-cover \
  --output ./output/fixed

cp "./output/fixed/Recursion.azw3" "/Volumes/Kindle/documents/"
```

### 2. 快捷脚本

```bash
chmod +x kindle-cover-fix.sh
./kindle-cover-fix.sh fix "某书.azw3" --bookfere-ebok --asin B0XXXX --fetch-cover --output ./output/fixed
```

### 3. 可视化界面

```bash
./run-app.sh
```

上传电子书 → 确认 ASIN → 点「修复封面」→ 自动复制到 Kindle `documents`（需 USB 连接）。

### 4. 批量处理 Kindle 上已有的书

按修改日期筛选、备份旧文件、修复并部署，**保持原文件名**：

```bash
python3 batch_kindle_deploy.py
```

---

## 核心命令

| 命令 | 作用 |
|------|------|
| `scan <路径>` | 检查封面 / ASIN / 锁屏就绪状态 |
| `fix <文件> --bookfere-ebok --asin B0XX --fetch-cover` | 修复单本（EBOK 方案） |
| `fix-all <文件夹> ...` | 批量修复文件夹 |
| `batch_kindle_deploy.py` | 按日期筛选 Kindle 书籍并自动部署 |

### `fix` 常用参数

| 参数 | 说明 |
|------|------|
| `--bookfere-ebok` | **必用** 书伴 EBOK 方案 |
| `--asin B0XXXX` | 亚马逊真实 ASIN |
| `--fetch-cover` | 从亚马逊下载官方封面 |
| `--output 目录` | 输出到新目录，不覆盖原文件 |

---

## 书伴 EBOK 原理

1. 查亚马逊 **真实 ASIN**
2. 下载官方封面：`https://m.media-amazon.com/images/P/{ASIN}.01.MAIN._SCRM_.jpg`
3. Calibre 嵌入封面
4. 元数据设为 **EBOK** + ASIN
5. USB 复制到 `documents`

修复后：

- **书库封面**：Kindle 联网后从亚马逊同步
- **锁屏封面**：使用内嵌的同一张官方封面

---

## 如何查找 ASIN

打开亚马逊商品页，URL 中 `/dp/` 后 10 位即为 ASIN：

```
https://www.amazon.com/dp/B07HDSHP7N
```

也可在 `asin_lookup.py` 的 `ASIN_OVERRIDES` 添加书名关键词映射（亚马逊搜索被反爬时有用）。

---

## Kindle 端设置

1. **设置 → 设备选项 → 显示封面** → 开启
2. 带广告版需移除 Special Offers
3. 修复后 **USB** 复制到 `documents`
4. **连接 Wi-Fi**，打开该书读几页，再验证书库与锁屏封面

---

## 常见问题

**修复后仍无封面？** 确认 Wi-Fi 已开、ASIN 正确、读几页后重启 Kindle 再试。

**EPUB 能直接放进 Kindle 吗？** 不建议。请用本工具修成 AZW3 再放入。

**会改原文件吗？** 使用 `--output` 时原文件不动；`batch_kindle_deploy.py` 会把旧文件剪切到 `output/kindle-batch-backup/`。

---

## 项目结构

```
kindle-cover-fix/
├── kindle_cover_fix.py      # 主程序：scan / fix / fix-all
├── batch_kindle_deploy.py   # 批量：筛选、备份、修复、部署
├── asin_lookup.py           # ASIN 自动查找与映射表
├── streamlit_app.py         # 可视化：上传 → 修复 → 复制到 Kindle
├── kindle-cover-fix.sh      # CLI 快捷启动
├── run-app.sh               # 启动 Streamlit
└── vendor/Fix-Kindle-Ebook-Cover/  # 书伴缩略图恢复（recover 子命令）
```

---

## 致谢

- [书伴 · 修复 Kindle 电子书封面显示错误](https://bookfere.com/post/966.html)
- [bookfere/Fix-Kindle-Ebook-Cover](https://github.com/bookfere/Fix-Kindle-Ebook-Cover)
- [Calibre](https://calibre-ebook.com/)

---

## 免责声明

本工具仅供个人已拥有合法使用权的电子书进行元数据与封面修复。请遵守当地法律法规与版权规定。

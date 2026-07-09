# Kindle 封面修复工具 (kindle-cover-fix)

修复 **Kindle 侧载电子书** 的封面显示问题：书库缩略图缺失、锁屏「显示封面」不显示当前在读书籍封面。

本项目整合了 [书伴 (bookfere.com)](https://bookfere.com) 的 **EBOK + 真实亚马逊 ASIN** 方案，并封装为可批量处理的 Python 工具链。已在 macOS + Kindle Paperwhite 上验证：修复后书库封面与锁屏封面均可正常显示。

---

## 目录

- [它能解决什么问题](#它能解决什么问题)
- [推荐方案对比](#推荐方案对比)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令详解](#命令详解)
- [书伴 EBOK 方案（推荐）](#书伴-ebok-方案推荐)
- [批量部署到 Kindle](#批量部署到-kindle)
- [Send to Kindle 还能用吗](#send-to-kindle-还能用吗)
- [如何查找 ASIN](#如何查找-asin)
- [Kindle 端设置](#kindle-端设置)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [致谢与参考](#致谢与参考)
- [免责声明](#免责声明)

---

## 它能解决什么问题

| 现象 | 常见原因 |
|------|----------|
| 书库里书籍显示「暂无图片」或空白封面 | 侧载书缺少封面图，或元数据未指向封面 |
| 锁屏「显示封面」不显示当前在读的书 | 书籍被标记为 PDOC 个人文档，或 ASIN/封面元数据不正确 |
| 书库封面和锁屏封面不是同一张图 | 内嵌封面与亚马逊拉取的封面不一致 |

**适用书籍：** 自行下载的 `.azw3` / `.mobi` / `.azw` / `.epub` 侧载书。

**不适用：** 亚马逊正版购买的书（本身已有正确元数据）、词典文件。

---

## 推荐方案对比

| 方案 | 命令参数 | 书库封面 | 锁屏封面 | 说明 |
|------|----------|----------|----------|------|
| **书伴 EBOK（推荐）** | `--bookfere-ebok --asin B0XXXX --fetch-cover` | ✅ | ✅ | 嵌入亚马逊官方封面 + 设置 EBOK + 真实 ASIN |
| 锁屏优化 PDOC | `--for-screensaver --fetch-cover` | 部分 | 部分 | 老款方案，新款 Kindle 效果不如 EBOK |
| 仅嵌封面 | `--fetch-cover` | 部分 | 部分 | 不修改 ASIN/类型，效果有限 |

**结论：** 想要书库和锁屏封面都正常，请使用 **书伴 EBOK 方案**。

---

## 环境要求

| 依赖 | 说明 |
|------|------|
| **macOS** | 已在 macOS 上测试；Linux 理论可用，需自行调整 Calibre 路径 |
| **Python 3.9+** | 推荐 3.10 或更高 |
| **Calibre** | 必须安装，用于读写电子书元数据与嵌入封面 |
| **Kindle 设备** | 通过 USB 挂载为 `/Volumes/Kindle` |

Calibre 安装方式：

```bash
# 方式一：官网下载
# https://calibre-ebook.com/download

# 方式二：Homebrew
brew install --cask calibre
```

默认 Calibre 路径：`/Applications/calibre.app/Contents/MacOS/`

---

## 安装

```bash
git clone https://github.com/ALALEI719/kindle-cover-fix.git
cd kindle-cover-fix

# 安装 Python 依赖
pip install -r requirements.txt

# 可选：给启动脚本执行权限
chmod +x kindle-cover-fix.sh
```

---

## 快速开始

### 1. 扫描书籍，查看问题

```bash
./kindle-cover-fix.sh scan ~/Downloads
# 或
python3 kindle_cover_fix.py scan "/Volumes/Kindle/documents"
```

### 2. 修复单本书（推荐 EBOK 方案）

先在 [Amazon](https://www.amazon.com) 搜索该书，从 URL 中获取 ASIN（10 位，以 `B` 开头），例如 `B000FC0VBQ`。

```bash
python3 kindle_cover_fix.py fix "Tender is the Night.azw3" \
  --bookfere-ebok \
  --asin B000FC0VBQ \
  --fetch-cover \
  --output ./output/fixed
```

修复完成后，将输出文件 **USB 复制** 到 Kindle 的 `documents` 文件夹。

### 3. 一键安装依赖并运行

```bash
./kindle-cover-fix.sh fix "某本书.azw3" --bookfere-ebok --asin B0XXXX --fetch-cover
```

---

## 命令详解

### `scan` — 扫描诊断

```bash
python3 kindle_cover_fix.py scan <文件或文件夹> [--json]
```

输出每本书的：标题、作者、是否有封面、ASIN、cdeType、锁屏就绪状态、问题列表。

### `fix` — 修复单本

```bash
python3 kindle_cover_fix.py fix <文件> [选项]
```

| 参数 | 说明 |
|------|------|
| `--bookfere-ebok` | **推荐** 书伴 EBOK 方案 |
| `--asin B0XXXX` | 亚马逊商店真实 ASIN（EBOK 方案必填） |
| `--fetch-cover` | 自动下载封面（EBOK 方案优先从亚马逊 ASIN 拉图） |
| `--cover 图片.jpg` | 手动指定封面图片 |
| `--for-screensaver` | 锁屏优化（转 AZW3 + PDOC，旧方案） |
| `--bookfere-mobi` | MOBI + PDOC 方案（从文件内读封面） |
| `--format azw3` | 强制输出格式 |
| `--output 目录` | 输出到新目录，不覆盖原文件 |
| `--no-backup` | 不创建 `.bak` 备份 |

### `fix-all` — 批量修复文件夹

```bash
python3 kindle_cover_fix.py fix-all <文件夹> \
  --fetch-cover \
  --for-screensaver \
  --output ./output/fixed
```

### `recover` — 从 Kindle 缩略图恢复封面

需要 Kindle 已通过 USB 连接，且 `system/thumbnails` 目录可见（部分固件版本可能不可见）。

```bash
python3 kindle_cover_fix.py recover /Volumes/Kindle [--action fix|clean]
```

---

## 书伴 EBOK 方案（推荐）

这是目前验证最有效的方案，原理如下：

1. **查找真实 ASIN** — 在亚马逊商店找到该书的 Kindle 版 ASIN
2. **下载官方封面** — 从 `https://m.media-amazon.com/images/P/{ASIN}.01.MAIN._SCRM_.jpg` 获取高清封面
3. **嵌入封面** — 用 Calibre 将封面写入电子书
4. **设置元数据** — 将书籍类型改为 `EBOK`，写入真实 ASIN
5. **部署到 Kindle** — USB 复制到 `documents` 文件夹

修复后：

- **书库封面**：Kindle 联网后从亚马逊服务器同步（依赖 ASIN）
- **锁屏封面**：使用文件内嵌的亚马逊官方封面
- 两者为同一张图，显示一致

### 示例：完整修复流程

```bash
# 1. 修复（输出到新目录，保留原文件）
python3 kindle_cover_fix.py fix "Recursion.azw3" \
  --bookfere-ebok \
  --asin B07HDSHP7N \
  --fetch-cover \
  --output ./output/fixed

# 2. 复制到 Kindle
cp "./output/fixed/Recursion.azw3" "/Volumes/Kindle/documents/"
```

---

## 批量部署到 Kindle

`batch_kindle_deploy.py` 用于按 **文件修改日期** 筛选书籍、自动备份、修复并部署到 Kindle，**保持原文件名不变**。

### 默认行为

- 扫描 `/Volumes/Kindle/documents`
- 只处理修改日期 **≥ 2025-12-05** 的书籍
- 自动排除词典、测试文件
- 旧文件 **剪切** 到项目 `output/kindle-batch-backup/` 备份
- 修复后复制回 Kindle

### 运行

```bash
python3 batch_kindle_deploy.py
```

### 续跑已有备份

```bash
python3 batch_kindle_deploy.py --backup-dir output/kindle-batch-backup/20260709-140704
```

### 自定义 ASIN 映射

亚马逊搜索可能被反爬拦截。可在 `batch_kindle_deploy.py` 的 `ASIN_OVERRIDES` 列表中添加书名关键词与 ASIN 的对应关系：

```python
ASIN_OVERRIDES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"A Game of Thrones 5-Book Bundle", re.I), "B00957T6X6"),
    (re.compile(r"Psychology of Money", re.I), "B084HJSJJ2"),
    # 添加更多...
]
```

处理报告保存在备份目录下的 `report.json`。

---

## Send to Kindle 还能用吗

**可以用，但不推荐直接传未处理的书。**

| 传书方式 | 封面效果 |
|----------|----------|
| Send to Kindle | 通常标记为 PDOC 个人文档，封面易缺失 |
| USB 直接复制未处理的书 | 同样容易缺封面 |
| **先修复再 USB 复制** | ✅ 书库 + 锁屏封面均正常 |

**推荐工作流：**

```
下载电子书 → 本工具修复（EBOK + ASIN + 封面）→ USB 复制到 documents
```

如果已经用 Send to Kindle 传了，可以：

1. USB 连接 Kindle，把书从 `documents` 拷回电脑
2. 用本工具修复
3. 再拷回 Kindle 替换原文件

---

## 如何查找 ASIN

ASIN 是亚马逊 10 位商品编号，Kindle 书一般以 `B` 开头。

### 方法一：从亚马逊 URL 读取

打开该书的亚马逊商品页，URL 中 `/dp/` 后面的 10 位即为 ASIN：

```
https://www.amazon.com/dp/B07HDSHP7N
                              ^^^^^^^^^^
                              这就是 ASIN
```

### 方法二：商品详情页

页面底部「Product details」区域也会显示 ASIN。

### 中文书

可在 [Amazon.com](https://www.amazon.com) 或历史 [Amazon.cn](https://www.amazon.cn) 商品页查找。例如《法治的细节》ASIN 为 `B09L12881X`。

### 套装书

注意区分单本与套装的 ASIN。例如《冰与火之歌》5 册套装是 `B00957T6X6`，单本《列王的纷争》是 `B000FC1HBY`。批量脚本中应把 **更具体的文件名模式放在前面**，避免误匹配。

---

## Kindle 端设置

1. **设置 → 设备选项 → 显示封面** → 开启
2. 带广告版 Kindle 需先移除 Special Offers，锁屏封面功能才完整可用
3. 修复后通过 **USB** 复制到 `documents`（不要用 Send to Kindle 传未处理的书）
4. **连接 Wi-Fi**，让书库封面从亚马逊同步刷新
5. 打开该书阅读几页后锁屏，验证「显示封面」

---

## 常见问题

### 修复后书库仍无封面？

- 确认 Kindle 已 **联网**
- 等待几分钟让索引刷新，或重启 Kindle
- 确认 ASIN 正确（可在亚马逊搜索验证书名是否匹配）
- 重新打开该书触发同步

### 锁屏封面不对？

- 确认使用了 `--bookfere-ebok --fetch-cover`（内嵌亚马逊官方封面）
- 确认「显示封面」已开启
- 先读几页再锁屏测试

### 提示找不到 Calibre？

安装 Calibre 并确认路径：

```bash
ls /Applications/calibre.app/Contents/MacOS/ebook-convert
```

### 批量处理 ASIN 查找失败？

亚马逊搜索页可能被反爬。请手动查 ASIN，写入 `batch_kindle_deploy.py` 的 `ASIN_OVERRIDES`，或单本用 `--asin` 参数修复。

### EPUB 文件支持吗？

支持。修复时会转换为 AZW3（EBOK 方案）。输出扩展名可能变为 `.azw3`。

### 会修改原文件吗？

- 默认 `fix` 会原地修改并创建 `.bak` 备份
- 使用 `--output 目录` 可输出到新目录，原文件不动
- `batch_kindle_deploy.py` 会将原文件剪切到备份目录

---

## 项目结构

```
kindle-cover-fix/
├── kindle_cover_fix.py      # 主程序：scan / fix / fix-all / recover
├── batch_kindle_deploy.py   # 批量：按日期筛选、备份、修复、部署
├── kindle-cover-fix.sh      # 快捷启动（自动安装依赖）
├── requirements.txt         # Python 依赖
├── vendor/
│   └── Fix-Kindle-Ebook-Cover/   # 书伴封面恢复工具（recover 子命令用）
└── output/                  # 本地输出（.gitignore，不上传）
    ├── kindle-batch-backup/ # 批量备份与报告
    └── kindle-pilot/        # 测试输出
```

---

## 致谢与参考

- [书伴 · 修复 Kindle 电子书封面显示错误](https://bookfere.com/post/966.html) — EBOK + ASIN 方案来源
- [bookfere/Fix-Kindle-Ebook-Cover](https://github.com/bookfere/Fix-Kindle-Ebook-Cover) — 缩略图恢复工具（vendored）
- [Calibre](https://calibre-ebook.com/) — 电子书转换与元数据编辑

---

## 免责声明

本工具仅供 **个人已拥有合法使用权** 的电子书进行元数据与封面修复。请遵守当地法律法规与版权规定。作者不对滥用本工具造成的任何后果负责。

---

## License

本项目代码以 MIT 风格开源发布。`vendor/Fix-Kindle-Ebook-Cover` 遵循其原仓库许可证。

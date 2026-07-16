# JavSP 项目使用报告

> 生成时间：2026-07-16  
> 项目路径：`E:\code\py\JavSP`

---

## 一、项目概述

**JavSP**（Jav Scraper Package）是一个**汇总多站点数据的 AV 元数据刮削器**。它能从影片文件名中自动识别番号，并行抓取多个站点的元数据，汇总后按规则分类整理影片文件，并生成供 Emby / Jellyfin / Kodi 等媒体服务器使用的 NFO 元数据文件。

| 属性 | 值 |
|---|---|
| 作者 | Yuukiy |
| 开源许可 | GPL-3.0 + Anti-996 License |
| Python 版本 | 3.10 ~ 3.12（不支持 3.13+） |
| 构建系统 | Poetry（含动态版本号） |
| 打包工具 | cx_Freeze |
| 包管理源 | 清华 TUNA 镜像 |
| 代码总量 | 核心 ~2,200 行 + 爬虫 ~3,500 行 + 工具/测试若干 |

---

## 二、核心功能

### 已实现 ✓

| 功能 | 说明 |
|---|---|
| 番号自动识别 | 支持 DVD ID、DMM CID、FC2、HeyDouga、Getchu、Gyutto 等多种格式 |
| 多分片处理 | 自动识别同一文件夹内的 CD1/CD2/A/B 等分片文件 |
| 多站点汇总 | 从 20+ 个站点并行抓取数据，按优先级合并字段 |
| 高清封面下载 | 优先下载高清封面（8-10 MiB），失败时回退普通封面 |
| AI 封面裁剪 | 基于 Slimeface 人脸识别，自动裁剪素人等非常规封面为海报 |
| NFO 文件生成 | 兼容 Kodi/Jellyfin/Emby 的 NFO 规范 |
| 标题/简介翻译 | 支持 Google / Bing / Baidu / Claude / OpenAI 五大翻译引擎 |
| 多线程并行抓取 | 每部影片的多个爬虫并发执行 |
| 女优艺名统一 | 内置 260 条女优别名映射，自动统一多名女优 |
| 自动检查更新 | 启动时检查 GitHub Release，可选自动下载 |
| 硬链接整理 | 支持硬链接方式移动文件，节省磁盘空间 |
| 剧照下载 | 下载预览剧照到 extrafanart 文件夹 |
| 水印标签 | 支持在海报上添加「字幕」「无码」水印 |
| Docker 部署 | 提供多阶段构建的 Dockerfile |

### 待实现 ☐

- 匹配本地字幕
- 使用小缩略图创建文件夹封面
- 保持不同站点间 genre 分类的统一
- 不同的运行模式（抓取+整理 / 仅抓取）
- 所有站点均失败时人工介入

---

## 三、项目架构

### 3.1 目录结构

```
JavSP/
├── javsp/                  # 核心包
│   ├── __main__.py         # 程序入口 & 主流程编排（634行）
│   ├── config.py           # 类型安全配置（confz + pydantic）
│   ├── datatype.py         # Movie / MovieInfo 数据类型
│   ├── avid.py             # 番号识别引擎
│   ├── file.py             # 文件扫描 & 分片检测
│   ├── nfo.py              # NFO XML 生成
│   ├── image.py            # 图片校验 & 水印
│   ├── func.py             # 工具函数（更新检查、关机等）
│   ├── lib.py              # 底层工具函数
│   ├── print.py            # tqdm 兼容输出
│   ├── prompt.py           # 交互式输入
│   ├── chromium.py         # Chrome Cookie 读取
│   ├── cropper/            # 封面裁剪模块
│   │   ├── interface.py    # 裁剪接口 & 默认裁剪器
│   │   └── slimeface_crop.py  # Slimeface 人脸裁剪器
│   └── web/                # 爬虫模块（20+ 个站点）
│       ├── base.py         # 统一网络请求基类
│       ├── exceptions.py   # 异常体系
│       ├── translate.py    # 翻译引擎
│       ├── proxyfree.py    # 免代理地址管理
│       └── [站点].py       # 各站点爬虫
├── data/                   # 静态数据
│   ├── actress_alias.json  # 女优别名映射（260条）
│   └── genre_*.csv         # 各站点 genre 翻译表（共2055行）
├── unittest/               # 单元测试
│   ├── test_*.py           # 8 个测试文件
│   └── data/               # 81 个爬虫测试 fixture（JSON）
├── tools/                  # 辅助工具
│   ├── config_migration.py # INI→YAML 配置迁移
│   ├── call_crawler.py     # 爬虫调试工具
│   ├── check_genre.py      # genre 翻译检查
│   ├── airav_search.py     # AiRav 搜索工具
│   └── version.py          # 版本工具
├── docker/Dockerfile       # Docker 镜像构建
├── config.yml              # 主配置文件
├── pyproject.toml          # Poetry 项目定义
├── setup.py                # cx_Freeze 打包配置
└── image/                  # 图标 & 水印素材
```

### 3.2 核心处理流程

```
启动 (entry)
  │
  ├─ 1. 加载配置 (config.yml / 环境变量 / 命令行参数)
  ├─ 2. 加载女优别名映射
  ├─ 3. 检查版本更新
  ├─ 4. 获取扫描目录（配置 or GUI选择 or 命令行输入）
  │
  ├─ 5. 扫描影片文件 (scan_movies)
  │     ├─ 遍历目录树，忽略指定文件夹
  │     ├─ 跳过含 NFO 的文件夹（已整理过）
  │     ├─ 过滤小于阈值(232MiB)的文件
  │     ├─ 提取番号 (get_id / get_cid)
  │     └─ 检测多分片影片 (CD1/CD2, A/B...)
  │
  ├─ 6. [可选] 手动审查番号 (reviewMovieID)
  │
  └─ 7. 逐部整理 (RunNormalMode)
        ├─ a. 多线程并行抓取 (parallel_crawler)
        │     └─ 按影片类型(normal/fc2/cid)选择爬虫列表
        ├─ b. 汇总数据 (info_summary)
        │     ├─ 按优先级合并字段
        │     ├─ genre 优先取 javdb
        │     ├─ 封面优先取非 javdb（避免水印）
        │     ├─ 番号按多数站点的结果校正
        │     └─ 女优别名统一
        ├─ c. [可选] 翻译标题和简介
        ├─ d. 生成文件名 (generate_names)
        │     └─ 路径长度自动截短
        ├─ e. 下载封面图片 (download_cover)
        │     └─ 优先高清 → 回退普通
        ├─ f. 裁剪海报 (process_poster)
        │     └─ Slimeface 人脸识别裁剪
        ├─ g. [可选] 下载剧照
        ├─ h. 写入 NFO 文件 (write_nfo)
        └─ i. [可选] 移动/重命名影片文件
```

### 3.3 番号识别引擎（avid.py）

这是项目最核心也最复杂的模块之一，支持多种番号格式：

| 类型 | 示例 | 识别逻辑 |
|---|---|---|
| FC2 | `FC2-PPV-123456` | `FC2[-_]?PPV[-_]?\d{5,7}` |
| HeyDouga | `heydouga-4030-1234` | 三段式匹配 |
| Getchu | `GETCHU-123456` | 特殊前缀 |
| Gyutto | `GYUTTO-123456` | 特殊前缀 |
| 普通番号 | `ABC-123` | `[A-Z]{2,10}-\d{2,5}` |
| 无分隔符 | `ABC123` | 回退匹配 `[A-Z]{2,}\d{2,5}` |
| 纯数字(无码) | `123456-789` | `\d{6}-\d{2,3}` |
| DMM CID | `h_127mxgs00001` | 多种模式匹配，按出现频率优化 |
| 东热系列 | `N1234`, `K1234`, `RED010` | 特殊系列匹配 |

识别失败时会回退到**父目录名**进行二次匹配。

### 3.4 爬虫模块（web/）

项目内置 **20+ 个站点爬虫**，每个爬虫实现统一的 `parse_data(movie: MovieInfo)` 接口：

| 分类 | 爬虫列表 |
|---|---|
| **普通影片** | airav, avsox, javbus, javdb, javlib, jav321, mgstage, prestige |
| **FC2** | fc2, fc2ppvdb, javmenu, javdb |
| **CID(DMM)** | fanza |
| **特殊** | dl_getchu, gyutto, arzon, arzon_iv, avwiki, njav, missav |

网络请求层（`base.py`）特性：
- 支持 HTTP / SOCKS5 代理
- 使用 `curl_cffi` 模拟 Chrome 指纹绕过 Cloudflare
- 统一的重试和超时机制
- 免代理地址自动管理

---

## 四、配置说明

配置文件 `config.yml` 分为 6 大模块，支持 **文件 / 环境变量 / 命令行参数** 三层覆盖（优先级从低到高）。

### 4.1 scanner — 文件扫描

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `input_directory` | null | 扫描目录（留空运行时询问） |
| `filename_extensions` | 17种格式 | 视为影片的文件后缀 |
| `minimum_size` | 232MiB | 忽略小于此大小的文件 |
| `ignored_id_pattern` | 6条正则 | 推测番号前忽略的字符串（分辨率、域名等） |
| `ignored_folder_name_pattern` | 4条正则 | 忽略的文件夹（隐藏/回收站等） |
| `skip_nfo_dir` | yes | 跳过已含 NFO 的文件夹 |
| `manual` | yes | 手动确认每部影片的番号 |

### 4.2 network — 网络设置

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `proxy_server` | `http://127.0.0.1:7897` | 代理地址（null 禁用） |
| `proxy_free` | 4个站点 | 各站点免代理地址 |
| `retry` | 3 | 网络失败重试次数 |
| `timeout` | PT10S | 请求超时（ISO 8601 持续时间格式） |

### 4.3 crawler — 爬虫设置

| 配置项 | 说明 |
|---|---|
| `selection` | 按影片类型(normal/fc2/cid/getchu/gyutto)配置爬虫列表及优先级 |
| `required_keys` | `[cover, title]` — 必须获取到的字段，否则视为抓取失败 |
| `hardworking` | 努力爬取更丰富信息（略增耗时） |
| `respect_site_avid` | 使用网站番号校正本地识别结果 |
| `sleep_after_scraping` | 每部影片后等待时间（PT1S） |
| `use_javdb_cover` | javdb 封面策略（fallback/yes/no） |
| `normalize_actress_name` | 统一女优艺名 |
| `javdb_cookie` | JavDB Cookie（浏览器读取失败时的备用方案） |

### 4.4 summarizer — 整理规则

- **文件移动**：`move_files`（true 移动到新文件夹 / false 保留原位）
- **命名模板**：支持 `{num}`, `{title}`, `{actress}`, `{label}` 等变量
  - 默认输出路径：`#整理完成/{actress}/[{num}] {title}`
  - 路径长度自动管理（默认上限 250，可按字节计算）
- **NFO**：自定义标题模板、genre/tag 字段
- **封面**：高清下载、AI 裁剪（Slimeface）、水印标签
- **剧照**：可开关，可配置请求间隔
- **硬链接**：`hard_link: false`（节省空间，需文件系统支持）

### 4.5 translator — 翻译

| 引擎 | 免费可用 | 需要密钥 |
|---|---|---|
| Google | ✓ | ✗ |
| Bing | ✗ | Azure 密钥 |
| Baidu | ✗ | APP ID + API Key |
| Claude | ✗ | API Key（haiku 模型） |
| OpenAI | ✗ | API Key + URL + 模型名（兼容 Groq 等） |

### 4.6 other — 其他

- `interactive`：是否在 stdin/stdout 交互
- `check_update`：检查更新
- `auto_update`：自动下载更新

---

## 五、安装与运行

### 方式一：从源码运行（开发者）

```bash
# 安装 Poetry
pip install poetry

# 安装依赖
cd E:\code\py\JavSP
poetry install

# 运行
poetry run javsp

# 指定扫描目录
poetry run javsp -- --oscanner.input_directory '/path/to/videos'

# 使用环境变量
env JAVSP_SCANNER.INPUT_DIRECTORY='/path/to/videos' poetry run javsp
```

### 方式二：Docker 运行

```bash
# 构建镜像
docker build -f docker/Dockerfile -t javsp .

# 运行（挂载视频目录到 /video）
docker run -v /path/to/videos:/video javsp
```

### 方式三：打包为可执行文件

```bash
# 使用 cx_Freeze 打包
python setup.py build
```

### 命令行参数

```
JavSP [-h] [-c CONFIG]
  -c, --config    使用指定的配置文件
  --oscanner.input_directory DIR    覆盖扫描目录
  （所有配置项均可用 --o{section}.{key} 覆盖）
```

---

## 六、运行模式

### 普通模式（默认）
完整流程：扫描 → 抓取 → 汇总 → 下载封面 → 裁剪海报 → 写NFO → 移动文件

### 手动确认模式（`scanner.manual: yes`）
扫描后逐部显示识别到的番号，用户可确认或手动输入更正。

### 不移动文件模式（`summarizer.move_files: false`）
仅生成 NFO 和封面到影片同级目录，不移动原始文件。

---

## 七、工程化质量

### 7.1 代码组织
- **模块划分清晰**：配置、数据类型、文件操作、网络请求、爬虫、图片处理各自独立
- **类型标注完善**：使用 pydantic 进行配置类型校验，Python 3.10+ 类型标注
- **异常体系完整**：`CrawlerError` 基类 + 6 个子类（未找到/重复/封锁/权限/凭据/网站错误）

### 7.2 测试覆盖
| 测试文件 | 测试内容 |
|---|---|
| `test_avid.py` | 番号识别（FC2/普通/CID/HeyDouga 等） |
| `test_crawlers.py` | 爬虫解析（基于 81 个 JSON fixture） |
| `test_file.py` | 文件扫描、分片检测、路径长度 |
| `test_func.py` | 工具函数 |
| `test_lib.py` | 底层函数 |
| `test_proxyfree.py` | 免代理地址 |
| `test_exe.py` | 可执行文件测试 |

### 7.3 数据资产
- **81 个爬虫测试 fixture**：覆盖各站点各种番号格式的真实抓取结果
- **260 条女优别名映射**：支持艺名统一
- **2055 行 genre 翻译表**：4 个站点的分类标签翻译

### 7.4 CI/CD
- GitHub Actions 自动测试爬虫功能
- Docker 镜像随 tag 发布自动推送到 ghcr.io
- 支持动态版本号（基于 git distance）

---

## 八、技术亮点

1. **多源数据聚合策略**：不是简单取第一个成功的结果，而是按字段优先级从多个来源合并——genre 优先 javdb，封面优先非 javdb（避免水印），番号按多数站点投票校正。

2. **番号识别引擎**：针对日本 AV 番号的极端多样性设计了分层正则匹配策略，处理了 FC2、HeyDouga、东热、纯数字无码、MUGEN 奇怪格式等特殊情况，识别失败时回退到父目录名。

3. **AI 封面裁剪**：集成 Slimeface 人脸识别，对素人等非常规封面自动识别面部位置进行裁剪，替代了已废弃的百度 AIP 方案。

4. **反反爬虫**：使用 `curl_cffi` 模拟 Chrome TLS 指纹绕过 Cloudflare 检测，`cloudscraper` 处理 JS 挑战。

5. **路径长度管理**：自动按标点符号分句，从长到短逐步截短标题，确保生成的文件路径不超过系统限制。

6. **配置系统**：基于 confz + pydantic 的三层配置覆盖（文件→环境变量→命令行），类型安全且灵活。

---

## 九、使用建议

### 9.1 新用户快速上手
1. 安装 Poetry 和依赖
2. 编辑 `config.yml`，设置 `scanner.input_directory` 为你的视频目录
3. 如果需要代理，确认 `network.proxy_server` 设置正确
4. 运行 `poetry run javsp`
5. 首次使用建议开启 `scanner.manual: yes` 确认识别结果

### 9.2 进阶配置建议
- **网络不佳**：关闭 `summarizer.cover.highres`，减少大图下载
- **NAS 整理**：开启 `summarizer.path.hard_link: true`，节省空间
- **批量整理**：关闭 `scanner.manual`，设置 `crawler.sleep_after_scraping: PT0S` 提速
- **翻译需求**：配置 `translator.engine: google`（免费）或其他付费引擎
- **素人影片**：配置 `summarizer.cover.crop.engine: slimeface` 启用 AI 裁剪

### 9.3 注意事项
- **Python 版本**：必须 3.10~3.12，不支持 3.13+
- **JavDB Cookie**：部分功能需要登录，`locale` 必须设为 `zh`
- **免代理地址**：可能随时失效，失效时软件会自动尝试获取新地址
- **代理配置**：当前配置默认指向 `127.0.0.1:7897`（Clash 默认端口），如使用其他代理需修改
- **Windows 路径**：自动替换非法字符为形近 Unicode 字符，路径长度上限 250

---

## 十、总结

JavSP 是一个功能完善、架构清晰的 AV 元数据刮削工具。其核心价值在于：

- **多站点聚合**：20+ 个站点并行抓取，按优先级智能合并，数据覆盖面广
- **开箱即用**：默认配置即可工作，深度可配置满足个性化需求
- **工程化程度高**：类型安全配置、完整异常体系、81 个测试 fixture、Docker 支持
- **持续维护**：活跃的 CHANGELOG，CI/CD 自动化测试，社区反馈机制

适合需要将大量 AV 影片整理到 Emby/Jellyfin/Kodi 媒体库的用户，尤其是追求元数据完整性和封面质量的人。

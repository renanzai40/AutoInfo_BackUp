# End-User Service Coverage Matrix

> AutoInfo v1.9 (Unreleased, 2026-08-05) vs 综合报告-资讯付费与AI触达研究.md  
> Mapping: Report Dimension → Code Coverage → Validation Plan Coverage → Gap  
> 2026-08-05 更新（第 11 次，M0-M7 全波次文档结算）：**3 个新 source types（26→29：`akshare`/`sec_edgar`/`edx_sitemap`，M2T18-21 专有 handler 落地）+ 4 个新 demo 域（9→13：general-news/gaming/b2b/retail，M3T24）+ 音乐源并入 online-video（M3T25，D10 走 Apple 无 key RSS）+ B24 付费专栏 `report_type="column"`（M5T40，premium + G15 门控）+ D11 杂志摘要 `magazine-digest` 产品模板（M5T41，templates 6→8）+ A6/A7 env-gated 验证场景（M7T52，`sources-a6-keyed` FRED/Finnhub + `sources-gap-closure` 覆盖新类型，scenarios 44→47）+ **万方 OUTCOME A（M3T31）：静态头 X-Ca-AppKey/APPCODE 可鉴权，但元数据端点为 POST-only，`http_api` 当前 GET-only → 配置源已合并 online-education（文档化+待 POST 传输扩展，不当作已实现）**。16 项 item 行按计划更新（A7→⚠️ akshare+cninfo+wind-gated、A19→⚠️ 知乎日报+得到+wechat2rss、A20→⚠️ bluesky+mastodon、A26→⚠️ ncpssd+万方[POST-blocked]或文档化、A27→⚠️ coursera+edx、D13→⚠️ sec_edgar+新闻稿组合、A6→⚠️ env-gated 待 key、A22→⚠️ medium、A25→✅ crossref 已存在验证完成、B24→⚠️ column premium、D10→⚠️ apple rss、D11→⚠️ magazine digest、D12/D14/D15/D16→⚠️ 新域；C6 维持）；**覆盖率从 item 表全量重算**（双向覆盖口径统一为 Code 与 Plan 双非 ❌，与 C/E 维既有口径一致）：Code 83→89/99（84%→**90%**）、Validation 83→89（84%→**90%**）、双向 73→86（74%→**87%**，D 维双向按"有对应 Demo 域"口径 9→13）；完全未覆盖 10/99（A28/B21/B22/B25/C9/C10/C12/C13/E13/E15）。
> 2026-08-11 更新（第 12 次，output-quality-mega）：**2 个简报产品模板差异化渲染** — premium-briefing（premium 档）+ enterprise-briefing（enterprise 档）不再回退默认 report 布局，走各自模板族（`data/templates/{premium-briefing,enterprise-briefing}.md.j2`，`_resolve_report_product_type`）；magazine-digest 改经 `generate_digest` digest 路径（`_resolve_digest_product_type` + `_normalize_digest_product_context`，上下文扁平化为 §2.1 flat keys）。**按产品 LLM 合成字段**（`implications`/`risks`/`action_required` 与 key_findings 1:1 对齐，enterprise-briefing 另含 `key_metrics`）仅在产品路径 agent JSON-LD 输出，默认 digest/report agent 输出不变（round-trip 契约）。**产品选择暴露于 MCP（generate_report/generate_digest `product` 参数）+ CLI（`--product`）**。**KB 侧闭环**：产品分析元数据持久化至 KB entry `custom_fields["product_analysis"]`（`update_entry_metadata`），`search_knowledge_base` 新增 `filter_custom_fields` 分面过滤（点路径如 `product_analysis.action_required`，无新工具、无新存储）——agent 格式输出可查询/可过滤（E5 强化）。**内容深度**：`fetch_depth` 贯穿源分发 + unpaywall/RSS/YouTube/GDELT 全文抓取（A11/A15/A18/A25 强化）。**验证**：2 个新场景 — `output-agent-interaction`（端到端 generate → 过滤 action_required → query_collected 带引用）+ `regression-product-routing`（产品路由回归），scenarios 65→**67**→68（61→62 functional + 6 regression，output-video 2026-08-13）。B1/B3/E5/A11/A15/A18/A25 行 Code 列补充说明，**无 item 行状态翻转**，覆盖率维持 Code 90% / Validation 90% / 双向 87%。
> 2026-08-04 更新（第 10 次）：**B23 电子书/音频书输出实现落地（用户指定要做）** — 新增 `src/autoinfo/output/ebook.py`（404 行）：`render_epub`（ebooklib EPUB3，markdown→xhtml `output_format="xhtml"` 保证 XML 合法 + `set_language(lang)` 支持中文，TOC/spine/NCX/Nav/封面/DC 元数据）、`render_mobi`（calibre `ebook-convert --mobi-file-type=both` 含 KF8 承载中文，300s 超时 + 缺 calibre 明确报错）、`render_audiobook`（复用 `_render_audio` 分章 TTS → 章节 MP3 + ZIP bundle + mutagen ID3v2.3 CHAP/CTOC 章节化单 MP3，mutagen 缺失或打标失败自动降级纯拼接）。接入 `generate_digest`/`generate_report`（format="epub"/"audiobook"，章节从 digest context/report sections 结构拆分）+ `export_kb`（format="epub"/"mobi" 写 exports/，镜像 `_export_pdf` 结果结构）+ MCP server 3 处 tool enum/描述 + 3 处 base64 返回分支（epub→`application/epub+zip`、audiobook→`audio/mpeg`）。`pyproject.toml` 新增 `[ebook]` extra（ebooklib>=0.20 + mutagen>=1.47，all 包含）。测试 `tests/output/test_output_ebook.py` 7 个全过（roundtrip/CJK/lxml well-formed/空输入/空章节体回归/audiobook 降级/mobi 缺 calibre 报错）。B23 行由 ❌ 升 ✅，**P2 可工程化缺口 3→2**（余 A28 TikTok、E15 A2A），总覆盖率 83%→**84%**（83/99）。
> 2026-08-04 更新（第 9 次）：**绕过路径调研（2026-08-04 librarian 实证，全部活体核实）** — P3 六项均获替代路径：**A7** Wind Alice 个人版（2026-03 发布，每日赠 1000 积分，官方 MCP `wind-skills`）+ AKShare + cninfo 公告 → EOD/基本面级可覆盖（tick/终端级仍无解）；**A19** 知乎日报官方 JSON API（`news-at.zhihu.com/api/4/news/latest` 实测活体无需鉴权）+ RSSHub `/dedao/*`（零配置）+ wewe-rss/wechat2rss（微信读书系，wechat2rss 后端实测活体）→ 三个平台均可覆盖；**A20** Bluesky Jetstream（免费实时 firehose）+ Mastodon 替代 X，微博 RSSHub cookie 路由、抖音开放平台 hotsearch 限时免费 → 部分覆盖（小红书仍无解）；**A26** NSSD 已迁移合并至 ncpssd.cn（免费 2500 万条 + 期刊优先发布）+ 万方开放平台官方 API（X-Ca-AppKey/APPCODE）+ 维普 OA 平台（oa.cqvip.com 实测活体）→ 社科期刊可覆盖（知网国内全文仍无解）；**A27** Coursera 公开目录 API（`api.coursera.org/api/courses.v1` 实测活体 23,348 门课免 key）+ edX sitemap 爬取（官方 Catalog API 仍 beta 审批制）→ 可覆盖；**D13** LinkedIn 原生无合法路径 → 以 SEC EDGAR + BusinessWire/PRNewswire RSS + 公司 newsroom RSS 组合替代公司级情报。**B23 用户指定要做**：实现方案就绪（ebooklib EPUB3 + calibre `ebook-convert` MOBI + `_render_audio` 分章 TTS 音频书）。10 项 ⚠️ 部分覆盖全部给出补齐路径（A6 注册 FRED+Finnhub 免费 key 即完成、D12/D14/D15/D16 用现有 collector 自建 demo 域、B24 复用 report_type 模板、D10 走 Apple 无 key RSS 避开 Spotify 2026-02 收紧等），详见 H 节与 ④ 节。
> 2026-08-04 更新（第 8 次）：**全量场景核对（报告 §4/§3.1/§5.1/§2.1/§6.5/§8.3/§9）** — 报告 §4 平台清单 **48/48 全覆盖**（§4.1 学术 12 平台 → A1/A2/A3/A23/A25/A26；§4.2 财经 10 平台 → A6/A7/A8；§4.3 新闻 8 平台 → A9/A10/A18；§4.4 知识付费 6 平台 → A19/A22；§4.5 社交/UGC 8 平台 → A14/A15/A17/A20/A28；§4.6 播客 4 平台 → A16/A29），§5.1 十三渠道 + C14 全覆盖，§2.1 十五领域 + 零售 D16 全覆盖，§6.5 七类 AI 使用场景全部映射（追问/新闻/摘要→E5，可信度→E9，跨源→B8，翻译→B20，简化→E14），§8.3 六种商业模式（订阅→E2，单篇→E12，API 许可→E11，终端 SaaS→E3/E2，AI 训练授权→E10，RaaS→E13 明确不做），§9 协议生态（MCP→E1，A2A→E15 未实现）。§10.2 建议表 4 个顾问性平台名（雪球→A6/A8 零售金融类目、Kimi→C4、字节扣子/腾讯元器→C8）为推荐提及非独立场景，按类目覆盖。核对方式：`grep` 全平台名 × 矩阵行逐一比对 + 人工复核。
> 2026-08-04 更新（第 7 次）：**HackerNews 专有 collector 落地** — 新增 `HackerNewsHandler`（`src/autoinfo/collectors/hackernews.py`，Firebase API 两步抓取），A13 行 Code 列由"tech-ai-developer 域"升级为专有 handler，`VALID_SOURCE_TYPES` 25→26、handlers 26→27；版本对齐 v1.8.4；修正 H3-E15 "MCP 139 工具"→"MCP 141 工具"。旧 shell 验证套件归档目录 `docs/archive/validation-suite/plan-v2/` 已于 2026-08-04 文档审计中删除（仅保留 `docs/archive/validation-suite/scripts/run-validation-scenarios.py` 运行脚本），历史 Part 引用为只读存档，新验证以 MCP 工具集为准。
> 2026-08-03 更新（第 6 次）：**MCP 原生验证工具集落地** — `list_validation_scenarios` / `run_validation_scenario` MCP 工具 + 47 个场景（`src/autoinfo/mcp/scenarios/`，2026-08-05 增至 47：新增 output-ebook、output-column、sources-gap-closure、sources-a6-keyed）通过 MCP 面执行（含 CLI 子进程 + REST HTTP 真实调用），**145/145 MCP 工具全覆盖、0 MISSING**（`scripts/coverage_audit.py` 可复验）、28 CLI 组全覆盖、8 REST 端点覆盖。旧 shell 验证套件（本文档引用的 Part N Qx 场景）已归档至 `docs/archive/validation-suite/`（plan-v2 目录已于 2026-08-04 文档审计删除，仅保留 `scripts/run-validation-scenarios.py`）。llm_assert 语义断言 + env-gated unconfigured（Director User BYOK 义务）。本文档 Plan 列的历史 Part 引用指向归档套件，新验证以 MCP 工具集为准。
> 2026-08-02 更新（第 5 次，V1 计划完成）：H1 生产清单 10 项全部落地（A18 GDELT / A23 SSRN / A24 HuggingFace-Kaggle / A25 Unpaywall-CORE OA 子集 / A29 中文播客 / E9 source_score / E11 RAW variants / E12 单篇支付 / E14 simplify_content / C11 播客 RSS），H2 验证补齐 B15/E7/E11 ✅ 已完成、A6/C6 待凭证 SKIPPED。覆盖率从 76% 升至 83%，P2 可工程化缺口从 7 项降至 3 项，剩余缺口从 28 项降至 18 项。同步修正历史计数偏差（B/C/E 维 stats 与 item 表不一致），全量重算。
> 2026-08-02 更新（第 4 次）：新增 **H 节"可行性判定与实现路线图"**——基于 2026-08-02 外部核实（GDELT / Unpaywall / CORE / Stripe / X API / RSSHub / NSSD / Listen Notes / edX / 公众号 API 共 12 条绕过路径），为全部缺口标注 V1 实现 / V2 推迟 / 放弃 决策与替代方案。  
> 2026-08-02 更新（第 3 次）：全量对齐报告场景——五维从 66 项扩至 **99 项**（+33：A+8 / B+5 / C+6 / D+7 / E+7），修正 C 维 5 处渠道排名（C3/C5/C6/C7/C8），补齐报告 §6.5/§7.3/§8.3/§9/§10.2 场景映射（E9-E15、C14），新增不可工程化/范围外明细。  
> Code 90% (89/99) | Validation 90% (89/99) | 双向 87% (86/99) | 可覆盖上限 93/99（排除 6 项纯无解）| MCP 工具验证 145/145（2026-08-13 第 11 次：16 项 item 行更新，Code 83→89；D 维双向口径=有对应 Demo 域 13/16）
>
> *Note: this document is a **hand-maintained 99-item report-demand mapping**, NOT generated by `scripts/coverage_matrix.py`. That script renders the 832-cell 8×8×13 matrix (8 products × 8 formats × 13 domains) from `docs/dev/specs/end-user-matrix.yaml` into `matrix-report.md`.*

---

## A. 原始资讯源覆盖（报告 Section 3.1, 4）

| # | 资讯源类别 | 报告推荐的平台 | AutoInfo Code | Validation Plan | 覆盖状态 |
|:-:|-----------|---------------|:-------------:|:---------------:|:--------:|
| A1 | **学术文献** | arXiv, PubMed, CrossRef | ✅ 3 collectors | ✅ Part 1 Q2 | ✅ |
| A2 | **学术文献（扩展）** | OpenAlex | ✅ OpenAlexHandler | ✅ Part 1 Q2b.1-3 | ✅ |
| A3 | **学术文献（引用图）** | Semantic Scholar | ✅ SemanticScholarHandler | ✅ Part 1 Q2b.4-6 | ✅ |
| A4 | **会议论文** | DBLP | ✅ DBLPHandler | ✅ Part 1 Q2b.7-9 | ✅ |
| A5 | **专利** | USPTO | ✅ USPTOHandler | ✅ Part 1 Q2b.10-12 | ✅ |
| A6 | **金融数据（免费）** | FRED, Alpha Vantage | ⚠️ http_api 通用 handler + FRED 源 + Finnhub（M3T30，`params.token`）+ Twelve Data，需 API Key（env-gated） | ⚠️ Part 1 Q2b.48（A6 E2E 场景已加，env-gated，待 key）+ `sources-a6-keyed` 场景（M7T52） | ⚠️（env-gated 待 key） |
| A7 | **金融数据（机构）** | Bloomberg, Refinitiv, Wind, 东方财富 Choice, 同花顺 iFinD, CEIC | ⚠️ `akshare` collector（M2T19，A 股/港股 EOD+公告，`[akshare]` extra）+ cninfo/Wind Alice 文档化路径 | ⚠️ `sources-gap-closure` 覆盖 akshare 类型注册（M7T52） | ⚠️（akshare+cninfo+wind-gated，EOD/基本面级） |
| A8 | **财经/零售数据** | Quandl, Yahoo Finance | ✅ QuandlHandler + YahooFinanceHandler | ✅ Part 1 Q2b.13-17 | ✅ |
| A9 | **新闻（企业级）** | Reuters Connect, AP | ✅ APHandler + ReutersMCPHandler | ✅ Part 1 Q2b.18-23 | ✅ |
| A10 | **新闻（免费 API）** | NYT API | ✅ NYTHandler | ✅ Part 1 Q2b.24-26 | ✅ |
| A11 | **商业新闻 RSS** | TechCrunch, Crunchbase | ✅ ai-commercial 域（RSS 全文 `fetch_depth`，2026-08-11） | ✅ Part 1 Q2 | ✅ |
| A12 | **中文科技** | 36氪 | ✅ 36kr（RSS 域内源） | ✅ Part 1 Q2b.27 | ✅ |
| A13 | **开发者社区** | GitHub Trending, HackerNews | ✅ HackerNewsHandler（Firebase API，2026-08-04 专有 handler）+ GitHub Trending（RSS） | ✅ Part 1 Q2 | ✅ |
| A14 | **社交讨论** | Reddit | ✅ RedditHandler | ✅ Part 1 Q2b.28-30 | ✅ |
| A15 | **视频元数据** | YouTube | ✅ YouTubeHandler（全文 `fetch_depth`，2026-08-11） | ✅ Part 1 Q2b.31-33 | ✅ |
| A16 | **播客元数据** | Spotify, Apple Podcasts | ✅ SpotifyHandler + ApplePodcastsHandler | ✅ Part 1 Q2b.34-39 | ✅ |
| A17 | **中文视频** | B站 | ✅ BilibiliHandler | ✅ Part 1 Q2b.40-42 | ✅ |
| A18 | **付费新闻/通讯社** | WSJ, FT, 财新, 新华社, 人民日报 | ✅ GDELTHandler（GDELT 免费，无 key，3 个月窗口；全文 `fetch_depth`，2026-08-11）+ Google News RSS | ✅ Part 1 Q2b.45（GDELT E2E） | ✅ |
| A19 | **中文知识平台** | 知乎, 得到, 微信公众号 | ⚠️ 知乎日报 JSON API（免鉴权）+ RSSHub `/dedao/*` + wewe-rss/wechat2rss 文档化路径（zhihu-daily/wechat2rss 已合入 general-news、得到已合入 online-education）；知乎热榜/公众号全量仍无解 | ⚠️ 文档化（源配置已合入，无独立场景） | ⚠️（知乎日报+得到+wechat2rss） |
| A20 | **社交/微博** | X/Twitter, 微博, 抖音, 小红书 | ⚠️ Bluesky（`json_path: "posts"`）+ Mastodon（`json_path: "$"` 根数组，M2T22）general-news 域源；微博/抖音 RSSHub cookie 路由文档化；小红书 ❌ | ⚠️ http_api `"$"` 扩展测试（41 passed）+ 源配置合入 | ⚠️（bluesky+mastodon；微博/抖音文档化） |
| A21 | **通用爬虫** | 任意 Web 页面 | ✅ Web + Playwright | ✅ Part 1 Q2 | ✅ |
| A22 | **创作者订阅平台** | Substack, Patreon, Medium | ⚠️ Substack 经通用 RSS（tech-ai-developer 域）；Medium RSS（`medium.com/feed/@user` 文档化）；Patreon ❌ 无通用 RSS | ⚠️ Part 1 Q6b.2（Substack RSS） | ⚠️（medium） |
| A23 | **社科/法律工作论文** | SSRN | ✅ SSRNHandler（RSS 接入，同 Substack 模式） | ✅ Part 1 Q2b.44（SSRN E2E） | ✅ |
| A24 | **开源数据集** | Hugging Face, Kaggle | ✅ HuggingFaceHandler（HF datasets-server 公开 API + Kaggle API） | ✅ Part 1 Q2b.49（HF/Kaggle E2E，46 mock tests） | ✅ |
| A25 | **学术付费数据库** | Elsevier/Scopus, Springer Nature, IEEE Xplore | ✅ UnpaywallHandler + COREHandler（OA 全文子集，非机构付费全文；Unpaywall 全文 `fetch_depth`，2026-08-11）+ Crossref REST（`api.crossref.org/works` 元数据发现） | ✅ Part 1 Q2b.46/Q2b.47（Unpaywall/CORE OA E2E）+ Crossref 源已存在于 medical-research（验证完成） | ✅（crossref 已存在验证完成；机构付费全文仍为许可上限） |
| A26 | **中文期刊库** | 知网 CNKI, 万方, 维普 | ⚠️ ncpssd.cn 文档化（RSSHub `/ncpssd/newlist`）+ 万方开放平台源已合并 online-education（OUTCOME A：静态头可鉴权，**POST-only 端点待 http_api POST 传输扩展**，文档化不当作已实现）+ 维普 OA oa.cqvip.com 文档化；知网国内 ❌ | ⚠️ 源配置合入 + 万方鉴权实证（M3T31）；POST 传输未实现故不标 ✅ | ⚠️（ncpssd+万方[POST-blocked]或文档化） |
| A27 | **MOOC/在线学位** | Coursera, edX | ⚠️ `edx_sitemap` collector（M2T21，robots.txt 合规）+ Coursera 公开目录 API 源（online-education 域，`page_param: start` 分页）；edX 官方 Catalog API 仍 beta 审批制 | ⚠️ `sources-gap-closure` 覆盖 edx_sitemap 类型注册（M7T52）+ EdxSitemapHandler 12 tests | ⚠️（coursera+edx） |
| A28 | **海外短视频** | TikTok | ❌ 未接入（Research API 需学术审核） | ❌ 未测试 | ❌ |
| A29 | **中文播客** | 喜马拉雅, 小宇宙 | ✅ ApplePodcastsHandler（iTunes Search, `country=CN`）隐式覆盖 | ✅ Part 1 Q2b.37-39 + A29 实测（2026-08-02: 3 例 country=CN curl 均返回 resultCount≥1） | ✅（隐式覆盖） |

> 备注：报告 §2.3 中国样本中的爱奇艺/优酷/腾讯视频（OTT 视频）无公开采集 API，未接入（B 站见 A17）；知乎/得到见 A19。

### A 维度覆盖率统计

| 指标 | 数值 |
|------|:----:|
| 报告推荐源总数 | 29 |
| AutoInfo Code 已覆盖 | 28/29 (97%) |
| Validation Plan 已测试 | 28/29 (97%) |
| 双向覆盖（Code + Plan） | 28/29 (97%) |
| 完全未覆盖 | 1/29 (3%) |

---

## B. 输出产品/资讯格式覆盖（报告 Section 3.1, 3.2, 3.3）

| # | 产品形态 | 报告识别 | AutoInfo Code | Validation Plan | 覆盖状态 |
|:-:|---------|:--------:|:-------------:|:---------------:|:--------:|
| B1 | **文本文摘（Digest）** | 日报/早报 | ✅ generate_digest（`product` 参数 + premium-briefing/enterprise-briefing 模板差异化渲染 + 按产品 LLM 合成字段 implications/risks/action_required/key_metrics，2026-08-11） | ⚠️ Part 9 (需 LLM) | ✅ |
| B2 | **研究报告（Research Report）** | 深度分析 | ✅ generate_report(researcher) | ✅ Part 2 Q9 | ✅ |
| B3 | **执行摘要（Executive Summary）** | 决策层简报 | ✅ target_audience=executive + premium-briefing 产品模板（implications/risks/action_required 合成字段，2026-08-11） | ✅ Part 2 Q9 | ✅ |
| B4 | **投资者简报（Investor Brief）** | 投资信号 | ✅ target_audience=investor | ✅ Part 2 Q9 | ✅ |
| B5 | **教程/培训** | 知识教育 | ✅ generate_tutorial | ✅ Part 2 Q9 | ✅ |
| B6 | **演示文稿** | 会议/汇报 | ✅ generate_presentation | ✅ Part 2 Q9 | ✅ |
| B7 | **行业定制报告** | 领域特定模板 | ✅ v1.8 report_type param | ✅ Part 4 Q33.7/33.12 | ✅ |
| B8 | **跨域综合报告** | 多域对比 | ✅ v1.8 domains param + generate_cross_domain_report | ✅ Part 4 Q33.8-33.10 | ✅ |
| B9 | **竞品分析报告** | 头对头对比 | ✅ `report_type="competitive"` | ✅ Part 4 Q33.7 | ✅ |
| B10 | **趋势分析报告** | 时间序列变化 | ✅ `report_type="trend"` | ✅ Part 4 Q33.7 | ✅ |
| B11 | **音频摘要/播客** | 音频消费（14% 偏好） | ✅ `format="audio"` (TTS MP3, OpenAI/edge-tts) | ✅ Part 4 Q36e | ✅ |
| B12 | **视频摘要** | 短视频（72% 渗透率） | ✅ `format="video"` (MP4, TTS narration + FFmpeg) | ✅ Part 4 Q33.11 / Part 2 Q9.18 | ✅ |
| B13 | **JSON 数据导出** | API Feed | ✅ export_json | ✅ Part 4 Q34 | ✅ |
| B14 | **CSV 数据导出** | 表格分析 | ✅ export_csv | ✅ Part 4 Q34 | ✅ |
| B15 | **PDF 报告** | 可打印文档 | ✅ export_pdf/export_bundle | ✅ Part 4 Q34.1c（需 weasyprint 环境；渲染超时 `output.pdf_timeout` 可配置，默认 120s） | ✅ |
| B16 | **Markdown 导出** | 可编辑文档 | ✅ export_markdown | ✅ Part 4 Q34 | ✅ |
| B17 | **RSS Feed 输出** | 订阅源 | ✅ export_rss | ✅ Part 4 Q34.9 | ✅ |
| B18 | **GraphML 图导出** | 知识图谱 | ✅ export_graphml | ✅ Part 4 Q34.10 | ✅ |
| B19 | **多格式 Bundle** | 一次性交付所有格式 | ✅ export_bundle | ✅ Part 4 Q34.1b | ✅ |
| B20 | **本地化/翻译** | 跨语言 | ✅ localize_content | ✅ Part 4 Q33.6 (需 LLM) | ✅ |
| B21 | **直播与社群服务** | 报告 §3.3：直播+社群（75% 续费率） | ❌ 未实现 | ❌ 未测试 | ❌ |
| B22 | **"内容+服务+社群"复合模式** | 报告 §3.3 行业转型方向 | ❌ 未实现 | ❌ 未测试 | ❌ |
| B23 | **电子书/音频书** | 报告 §3.1 教育/通识格式 3 | ✅ `format="epub"`（ebooklib EPUB3，CJK `set_language`+xhtml 输出）+ `format="mobi"`（calibre `ebook-convert` KF8）+ `format="audiobook"`（`_render_audio` 分章 TTS → 章节 MP3/ZIP/CHAP-CTOC 章节化 MP3）；`src/autoinfo/output/ebook.py`，`[ebook]` optional extra | ✅ tests/output/test_output_ebook.py（7 测试：roundtrip/CJK/well-formed/空输入/空章节体回归/audiobook/mobi 缺 calibre）+ MCP 场景 `output-ebook`（digest/report epub+audiobook，LLM-gated）+ `kb-import-export` EPUB 导出步骤（实测通过） | ✅ |
| B24 | **付费深度专栏** | 报告 §3.1 财经格式 3、§3.3 图文专栏 | ⚠️ `report_type="column"`（M5T40：`_REPORT_TYPE_PROMPTS` + `PRODUCT_TEMPLATES` 8 行中的 column 行 access_level=premium + G15 `check_access` 门控 + `column.md.j2` 模板） | ⚠️ MCP 场景 `output-column`（env-gated LLM）+ test_column_product（G15 门控 + 免费渲染双路径） | ⚠️（column premium） |
| B25 | **实时数据终端** | 报告 §3.1 金融格式 1（Bloomberg/Wind 终端） | ❌ 机构级终端形态，超出产品范围 | ❌ 未测试 | ❌ |

### B 维度覆盖率统计

| 指标 | 数值 |
|------|:----:|
| 报告识别产品形态总数 | 25 |
| AutoInfo Code 已覆盖 | 22/25 (88%) |
| Validation Plan 已测试 | 22/25 (88%) |
| 双向覆盖（Code + Plan） | 22/25 (88%) |
| 代码有但未验证 | 0/25 (0%) |
| 完全未覆盖 | 3/25 (12%) |

---

## C. 分发渠道覆盖（报告 Section 5.1, 5.2, 10.2）

> 触达路径分类（报告 §5.2）：A 主动拉取（Pull）/ B 被动推送（Push）/ C 算法分发（Algorithmic）/ D AI 代理（Agent-mediated）

| # | 分发渠道 | 报告排名 | 触达路径 | AutoInfo Code | Validation Plan | 覆盖状态 |
|:-:|---------|:-------:|:-------:|:-------------:|:---------------:|:--------:|
| C1 | **社交+视频网络（算法分发）** | #1 (54%) | C 算法分发 | ✅ `social_publish` 渠道（mastodon/bluesky/linkedin/threads/x）(delivery/social.py) | ✅ tests/delivery/test_social.py | ✅ |
| C2 | **搜索引擎+AI 概览** | #2 | A 主动拉取 | ✅ export_kb format="sitemap"（sitemap.xml）+ JSON-LD 结构化数据 | ✅ Part 2 Q9.19（CLI sitemap）+ Part 4 Q36i.1/Q36i.2（export_kb sitemap + JSON-LD，新增场景） | ✅ |
| C3 | **自有网站/APP** | #5 (51%) | A 主动拉取 | ✅ REST API (FastAPI, 8741) + Web UI Dashboard | ✅ Part 7 Q47/Q48 | ✅ |
| C4 | **AI 聊天机器人/答案引擎** | #4 (10%) | D AI 代理 | ✅ MCP Server (145 tools) | ✅ Part 3+4 | ✅ |
| C5 | **推送通知** | #6 | B 被动推送 | ✅ Push 推送通道 (PushDeliveryChannel + scheduler) | ✅ Part 13 Q63.20（push 渠道分发，新增场景）+ 单元测试 tests/delivery/test_push.py（23 tests） | ✅ |
| C6 | **邮件订阅** | #7 | B 被动推送 | ✅ SMTP 渠道 | ✅ Part 9 Q56a 56a.4（env-gated：`SMTP_HOST`/`SMTP_USER`/`SMTP_PASS`，无凭证 SKIPPED 不 FAIL；2026-08-02 已加场景，凭证未提供故 SKIPPED） | ⚠️ 待 SMTP 凭证（场景就绪；提供 Mailtrap/Resend 免费层或 Gmail app password 后重跑 56a.4 → ✅） |
| C7 | **RSS Feed** | #10 (6%) | A 主动拉取 | ✅ export_rss | ✅ Part 4 Q34.9 | ✅ |
| C8 | **AI Agent 主动推送 (MCP/A2A)** | #13 (新兴) | D AI 代理 | ✅ MCP Server（MCP 侧完整；A2A 原生协议未实现，见 E15） | ✅ Part 3+4 | ✅ |
| C9 | **电视/广播+智能电视** | #3 (52%) | B 被动推送 | ❌ 无 TV 输出能力 | ❌ 未测试 | ❌ |
| C10 | **移动 App+应用商店** | #8 | A 主动拉取 | ❌ 无移动端 App（REST API 可被第三方 App 消费） | ❌ 未测试 | ❌ |
| C11 | **播客平台目录** | #9 | B 被动推送 | ✅ RSS 2.0 播客目录发布（`<enclosure>` + `itunes:*` 命名空间，音频输出自动持久化 MP3） | ✅ Part 4 Q36h（36h.1 播客 RSS 发布 E2E） | ✅ |
| C12 | **浏览器/默认首页/导航** | #11 | A 主动拉取 | ❌ 不适用（无浏览器产品） | ❌ 未测试 | ❌ |
| C13 | **联盟/推荐链接** | #12 | A 主动拉取 | ❌ 不适用（无联盟系统） | ❌ 未测试 | ❌ |
| C14 | **微信生态/IM 消息** | 补充（§10.2 中国触达） | B 被动推送 | ✅ wechat_work + wechat_oa + dingtalk + feishu + telegram + discord 6 渠道 | ✅ Part 13 Q63.17/63.18 | ✅ |

### C 维度覆盖率统计

| 指标 | 数值 |
|------|:----:|
| 报告渠道总数（§5.1 十三渠道 + C14 补充） | 14 |
| AutoInfo Code 已覆盖 | 10/14 (71%) |
| Validation Plan 已测试 | 10/14 (71%) |
| 双向覆盖 | 10/14 (71%) |
| 完全未覆盖 | 4/14 (29%) |

---

## D. 领域/Use Case 覆盖（报告 Section 2.1, 7.2.3, 10.4, 10.5）

| # | 领域 | 付费意愿排名 | AutoInfo Demo 域 | 报告可行性 | 覆盖状态 |
|:-:|------|:----------:|:----------------:|:---------:|:--------:|
| D1 | **企业级 SaaS / AI Apps** | #1 ($675B) | ✅ ai-commercial | ✅ TechCrunch+ProductHunt | ✅ |
| D2 | **在线视频/OTT** | #2 ($84.7B) | ✅ online-video | ✅ YouTube+Bilibili+Podcasts | ✅ |
| D3 | **财经/新闻深度内容** | #4 (NYT 12M+) | ✅ financial-news | ✅ NYT+RSS+API 源 | ✅ |
| D4 | **专业金融/商业资讯** | #5 | ✅ financial-intelligence | ✅ Part 1 Q6b.1 覆盖 (需 API Key) | ✅ |
| D5 | **医学/生物研究 + 医疗健康** | #7/#9 | ✅ medical-research | ✅ PubMed 免费 | ✅ |
| D6 | **在线教育/知识付费** | #6 ($350B 中国) | ✅ online-education | ✅ OpenAlex+arXiv+RSS 源 | ✅ |
| D7 | **技术/AI/开发者** | #13 | ✅ tech-ai-developer | ✅ GitHub+HN 免费 | ✅ |
| D8 | **法律/合规** | #10 | ✅ legal-compliance | ✅ USPTO+webhook+email 源 | ✅ |
| D9 | **语言学习** | —（非报告领域，AutoInfo 附加） | ✅ language-learning | ✅ Part 1 Q6b.1 覆盖 (RSS 可用) | ✅ |
| D10 | **音乐流媒体** | #3 (Spotify 263M) | ⚠️ Apple Music 无 key RSS/JSON 源已并入 online-video 域（M3T25：`rss.marketingtools.apple.com` + Pitchfork/Billboard RSS）；Spotify API 2026-02 收紧不 gate | ⚠️ Part 1 Q2b.34-36 部分 + 源配置合入 | ⚠️（apple rss） |
| D11 | **音频/播客/数字杂志** | #11 (Cafeyn 2M) | ⚠️ 播客部分 ✅（online-video 域 + A16 + B11 音频输出）+ 数字杂志摘要产品 `magazine-digest`（M5T41：ProductTemplate 行 + `magazine-digest.md.j2` per-title RSS 聚类）；整刊 ❌ 文档化上限 | ⚠️ MCP 场景 `output-ebook`/digest + magazine-digest 模板测试（6 passed） | ⚠️（magazine digest） |
| D12 | **通用新闻/数字报纸** | #12 (20 国 17%) | ✅ general-news demo 域（M3T24：gdelt/guardian/google-news-rss/nyt/ap-api 5 源 + M3 批追加 10 源，共 15 源） | ⚠️ Part 1 Q2 源级验证 + test_demo_sources（13 域动态计数） | ⚠️（新域） |
| D13 | **LinkedIn 职业订阅** | #8 ($1.7B/年) | ⚠️ `sec_edgar` collector（M2T20，8-K/10-K/10-Q 公司事件，10 req/s 合规）+ BusinessWire/PRNewswire RSS + 公司 newsroom RSS 组合（financial-intelligence/financial-news 域）；LinkedIn 原生 ❌ | ⚠️ `sources-gap-closure` 覆盖 sec_edgar 类型注册（M7T52）+ SecEdgarHandler 15 tests | ⚠️（sec_edgar+新闻稿组合，~80% 公司级情报） |
| D14 | **游戏内购/数字游戏** | #14 | ✅ gaming demo 域（M3T24：ign-rss/polygon/gamesindustry/gcores/yystv-via-google-news 5 源）；内购数据 ❌ 文档化上限 | ⚠️ test_demo_sources（13 域）+ 源级验证 | ⚠️（新域） |
| D15 | **B2B 数据/工具/API** | #15 | ✅ b2b demo 域（M3T24：producthunt/techcrunch/crunchbase-news/a16z/hackernews 5 源）；Crunchbase 组织数据 ❌ 文档化上限 | ⚠️ test_demo_sources（13 域）+ 源级验证 | ⚠️（新域） |
| D16 | **零售/电商资讯** | 报告 §7.2.3/§10.5（500 亿元市场） | ✅ retail demo 域（M3T24：retail-dive/modern-retail/ebrun-via-google-news/shopify-news/digiday 5 源）；小红书/抖音受限（A20） | ⚠️ test_demo_sources（13 域）+ 源级验证 | ⚠️（新域） |

### D 维度覆盖率统计

| 指标 | 数值 |
|------|:----:|
| 报告高价值领域总数 | 16（§2.1 的 15 + 零售 §7.2.3/§10.5） |
| AutoInfo 有对应 Demo 域 | 13/16 (81%)（D1-D9 + D12/D14/D15/D16 新域；D10 经 online-video 域、D11 经播客+magazine-digest、D13 经 sec_edgar+新闻稿组合） |
| 至少部分可行（✅+⚠️） | 16/16 (100%) |
| 不可行的域（付费墙封锁） | 0/16 (0%) |

---

## E. Agent 触达与商业化（报告 Section 6, 7, 8, 9）

> 报告 §6.5 Agent 使用场景映射：追问 42% → E5；获取最新新闻 35% → E5；摘要 34% → E5/B1；评估新闻源可信度 33% → E9；跨源对比/多源整合 35% → B8；翻译新闻 33% → B20；把新闻变简单 30% → E14。  
> 报告 §7.1 技术路径：数据直连 → E1（MCP 工具）；个性化推荐 → E6；记忆系统/技能模块化属 Agent 平台侧能力（不适用本平台）。

| # | Agent 能力 | 报告关键数据 | AutoInfo Code | Validation Plan | 覆盖状态 |
|:-:|-----------|:-----------:|:-------------:|:---------------:|:--------:|
| E1 | **MCP 工具暴露** | 报告推荐 | ✅ 145 tools | ✅ Part 3+4 | ✅ |
| E2 | **付费用户管理** | 订阅经济 $7,388 亿 | ✅ Stripe 集成 (878行, 51测试: 42 mock + 9 stripe-mock 集成) | ✅ Part 13 Q65e + TestStripeLifecycle 集成回归 (skipif 无 stripe-mock) | ✅ |
| E3 | **用量追踪/计费** | Zuora SEI | ✅ CostMeter + ConsumptionEvent | ✅ Part 13 Q65h (cost E2E) | ✅ |
| E4 | **多渠道分发** | 6+ 渠道 | ✅ 13 delivery adapters（含 push） | ✅ Part 13 Q63.17-63.19 | ✅ |
| E5 | **RAG 输出** | Agent 检索的基础 | ✅ MCP KB search tools（`filter_custom_fields` 分面过滤 `custom_fields["product_analysis"]` 元数据，2026-08-11） | ✅ Part 4 | ✅ |
| E6 | **个性化推荐** | Perez 76% 用 Agent 购物 | ✅ `recommend_content` MCP 工具 | ✅ Part 04 36b.7/36b.8 | ✅ |
| E7 | **定时任务/告警** | Cron 式触达 | ✅ cron scheduler | ✅ Part 9 Q54.5+Q55.10 (跨进程, 2026-08-02) | ✅ |
| E8 | **Webhook/A2A 集成** | MCP+A2A 双轨 | ✅ webhook+delivery | ✅ Part 03 Q25.3-25.5 | ✅ |
| E9 | **来源可信度评估** | 报告 §6.5：33% 场景 | ✅ 确定性 `source_score`（0-100，基于 quality_tier 的 `SOURCE_TIER_SCORE_MAP`），持久化于 KBEntry，在 G1 门与搜索结果中呈现 | ✅ Part 5 Q37.x（G1 + source_score） | ✅ |
| E10 | **内容合规/版权风险管理** | 报告 §9.1 法规、§8.3 AI 训练数据授权、§10.2 合规路径 | ✅ SourceConfig quality_tier/tos_classification（open/licensed/restricted/sensitive）+ G1TosCompliance + 输出 attribution 页脚 | ✅ Part 5（G1 门） | ✅ |
| E11 | **API 数据许可/RAW 产品** | 报告 §8.3：API/数据许可（Reddit-Google $60M/年） | ✅ RAW 产品携带 `variants: ["api_feed", "webhook", "bulk_export"]` 字段，区分三种 RAW 交付模式 | ✅ Part 4 RAW 变体验证（2026-08-02） | ✅ |
| E12 | **单篇/Micro-subscription** | 报告 §8.3（Substack IAP、单篇 $0.25-$15） | ✅ `create_checkout_session(mode="payment")` 单篇购买 + `check_access(article_id=...)` 权益快速路径 | ✅ Part 13 单篇支付 E2E（2026-08-02） | ✅ |
| E13 | **RaaS 效果付费** | 报告 §8.3、§7.3 价值透明化 | ❌ 无按效果计费（E3 用量计量是基础） | ❌ 未测试 | ❌ |
| E14 | **内容简化** | 报告 §6.5：30% 场景 | ✅ `simplify_content` MCP 工具（CEFR 参数化 A1-C1，LLM 改写 + 原始/简化分级 + 验证标记） | ✅ Part 4 Q36g（36g.1/36g.2） | ✅ |
| E15 | **A2A 原生协议** | 报告 §9.5（Agent-to-Agent） | ❌ webhook 为单向回调，非 A2A 服务器 | ❌ 未测试 | ❌ |

### E 维度覆盖率统计

| 指标 | 数值 |
|------|:----:|
| Agent 能力总数 | 15 |
| AutoInfo Code 已覆盖 | 13/15 (87%) |
| Validation Plan 已测试 | 13/15 (87%) |
| 双向覆盖 | 13/15 (87%) |
| 完全未覆盖（Code 缺失） | 2/15 (13%) |

---

## 总覆盖率矩阵

| 维度 | 报告维度数 | Code 覆盖 | Code % | Plan 覆盖 | Plan % | 双向覆盖 | 双向 % |
|:----|:---------:|:---------:|:------:|:---------:|:------:|:--------:|:------:|
| **A. 原始资讯源** | 29 | 28 | **97%** | 28 | **97%** | 28 | **97%** |
| **B. 输出产品** | 25 | 22 | **88%** | 22 | **88%** | 22 | **88%** |
| **C. 分发渠道** | 14 | 10 | **71%** | 10 | **71%** | 10 | **71%** |
| **D. 领域覆盖** | 16 | 16 | **100%** | 16 | **100%** | 13 | **81%** |
| **E. Agent 触达** | 15 | 13 | **87%** | 13 | **87%** | 13 | **87%** |
| **总计** | **99** | **89** | **90%** | **89** | **90%** | **86** | **87%** |

---

## 未覆盖项优先级（距 100% 的剩余缺口）

> 各缺口的具体绕过路径与 V1/V2/放弃 决策见 **H 节**（2026-08-02 外部核实版）。

### P0 — 代码已实现但未验证（0 项）

> A6 FRED / Alpha Vantage 已于 2026-08-02 补齐验证场景（Part 1 Q2b.48，env-gated，真实 API E2E：collect → Items → G0），当前环境无 `AUTOINFO_HTTP_API_KEY`/`ALPHAVANTAGE_API_KEY`/`FRED_API_KEY`，记录 **SKIPPED**（待免费 key 到位后执行，不 FAIL）。该行保留在 H2 验证补齐清单，随凭证到位后回归。

### P1 — 部分实现/部分验证（0 项）

> E9 来源可信度评估已于 2026-08-02 完成（确定性 `source_score` 0-100，基于 `SOURCE_TIER_SCORE_MAP`，持久化于 KBEntry，G1 门与搜索结果呈现）；E11 RAW 产品变体已于 2026-08-02 完成（`variants: ["api_feed", "webhook", "bulk_export"]` 字段）。两项均从 P1 移出，P1 清空。

### P2 — 代码缺失但可工程化（2 项）

> 报告明确列出的可接入平台/可扩展产品，尚未实现。A23 SSRN / A24 HuggingFace-Kaggle / E12 单篇支付 / E14 内容简化 已于 2026-08-02（V1）实现并移出；B23 电子书/音频书已于 2026-08-04（第 10 次）实现并移出。

| 项 | 功能 | 报告依据 | 实现路径 |
|:--:|------|---------|---------|
| A28 | TikTok | §4.5 Research API | 需学术审核（Research API 准入） |
| E15 | A2A 原生协议 | §9.5 Agent-to-Agent | A2A server 实现（当前 webhook 单向） |

### P3 — 报告识别但不可工程化（6 项 → 2026-08-04 全部获替代路径 → 2026-08-05 全部落地）

> A18 WSJ/FT/财新 已于 2026-08-02 经 GDELT+Google News RSS 零成本覆盖（新闻头条级，非付费墙全文），移出 P3；A25 Elsevier/Springer/IEEE 已于 2026-08-02 经 Unpaywall/CORE 覆盖 OA 全文子集（机构付费许可内容仍不可及，标注 ⚠️ 部分覆盖），移出 P3。  
> **2026-08-04（第 9 次）**：剩余 6 项经 librarian 实证调研全部获得替代路径，无一项仍为纯无解——均从"机构付费墙/无 API"降级为"替代信源可部分覆盖"（详见 H 节 H3' 调研结论）。  
> **2026-08-05（第 11 次）**：6 项替代路径全部落地 —— A7 经 `akshare` 专有 handler（M2T19）、A26/A27 经 edx_sitemap handler + 源配置（M2T21/M3 批）、A19/A20 经 general-news 域源配置、D13 经 `sec_edgar` handler + 新闻稿 RSS（M2T20/M3T30）。P3 已清空，无纯无解项。

| 项 | 功能 | 替代路径（2026-08-04 实证 → 2026-08-05 落地） | 覆盖上限 |
|:--:|------|------|------|
| A7 | Bloomberg / Refinitiv / Wind / Choice / iFinD / CEIC | ✅ `akshare` handler（A 股/港股 EOD+公告）+ cninfo 巨潮公告 + Wind Alice 个人版文档化 | ⚠️ EOD/基本面级；tick/终端/consensus 级仍无解 |
| A19 | 知乎 / 得到 / 微信公众号 | ✅ 知乎日报 JSON API + RSSHub `/dedao/*` + wewe-rss/wechat2rss（general-news 域源配置） | ⚠️ 日报/精选级可覆盖；知乎热榜/答案需 cookie（维护成本高） |
| A20 | X / 微博 / 抖音 / 小红书 | ✅ Bluesky Jetstream + Mastodon（general-news 域 http_api 源）；微博/抖音 RSSHub 路由文档化 | ⚠️ 替代社交信号可覆盖；小红书 ❌（RSSHub 路由 2025 年中已坏 #19505，官方 API 仅电商类目） |
| A26 | 知网 / 万方 / 维普 | ⚠️ ncpssd.cn 文档化 + 万方源已合并 online-education（OUTCOME A 静态头，**POST-only 端点待 http_api POST 扩展**，文档化不当作已实现）+ 维普 OA 文档化 | ⚠️ 社科/中文期刊元数据+OA 全文可覆盖；知网国内全文 ❌ |
| A27 | Coursera / edX MOOC | ✅ `edx_sitemap` handler + Coursera 公开目录 API 源（online-education 域） | ⚠️ 课程发现/上线追踪可覆盖 |
| D13 | LinkedIn 职业订阅 | ✅ `sec_edgar` handler（8-K/10-K/10-Q）+ BusinessWire/PRNewswire RSS + 公司 newsroom RSS（financial-intelligence/financial-news 域） | ⚠️ 公司级情报可替代 ~80%；LinkedIn 原生内容 ❌（无合法 API，抓取封锁） |

### P4 — 超出产品范围（N/A，8 项）

| 项 | 功能 | 原因 |
|:--:|------|------|
| B21 | 直播与社群服务 | 需运营生态，非知识库平台形态 |
| B22 | "内容+服务+社群"复合模式 | 商业模式转型方向，非单平台功能 |
| B25 | 实时数据终端 | Bloomberg/Wind 机构级终端形态 |
| C9 | 电视/广播+智能电视 | 无 TV 输出能力（渠道硬件依赖） |
| C10 | 移动 App+应用商店 | 无移动端 App（REST API 可被消费） |
| C12 | 浏览器/默认首页/导航 | 无浏览器产品 |
| C13 | 联盟/推荐链接 | 无联盟系统 |
| E13 | RaaS 效果付费 | 需商业模式设计，E3 计量为基础 |

---

## 核心结论

1. **代码覆盖率 90%**（89/99）— 2026-08-02 V1 实现落地 10 项生产功能（A18/A23/A24/A25/A29/E9/E11/E12/E14/C11），覆盖率从 76% 升至 83%；2026-08-04 B23 电子书/音频书实现后升至 84%；**2026-08-05 第 11 次：M2/M3/M5 波次落地 3 新 source types + 4 新 demo 域 + B24 column + D11 magazine-digest + A6/A7 env-gated 验证，覆盖率升至 90%**；A25 学术付费库为 OA 全文子集覆盖 + Crossref 元数据（✅）
2. **验证覆盖率 90%**（89/99），**双向覆盖 87%**（86/99）— 第 11 次按统一口径（Code 与 Plan 双非 ❌）从 item 表全量重算，修正 A 维历史偏差（双向 21→28）
3. **新增缺口全部为"合理未覆盖"**：完全未覆盖降至 10 项（A28 + P4 范围外 8 项 + E13）；P3 六项（A7/A19/A20/A26/A27/D13）经 2026-08-04 实证获替代信源、2026-08-05 落地（专有 handler/新 demo 域/源配置），从"结构性无法覆盖"转为"替代信源可部分覆盖（已实施或文档化）"
4. **可工程化但未实现 2 项**（P2：TikTok / A2A — B23 电子书已于 2026-08-04 实现移出、B24/D11 已于 2026-08-05 实现）— 剩余下一步开发优先清单（A23/A24/E12/E14 已于 2026-08-02 实现）
5. **报告 §6.5 七大 AI 使用场景已全部覆盖**：追问/获取新闻/摘要/跨源/翻译 5 项已覆盖（E5/B8/B20），可信度评估已完成（E9=确定性 source_score），内容简化已完成（E14=simplify_content）
6. **微信生态/IM 渠道（C14）此前未在矩阵体现**：wechat_work/wechat_oa/dingtalk/feishu/telegram/discord 6 个适配器实际已实现并验证（Part 13 Q63.17），对应报告 §10.2"内容触达（中国）：微信生态"
7. **C 维渠道排名修正 5 处**：自有网站 #3→#5、推送 #5→#6、邮件 #6→#7、RSS #7→#10、AI Agent #8→#13（对齐报告 §5.1）
8. **新发现 gap**: #99 LLM response_format 空结果无保护, #100 多域 init 未复制全部 sources.yaml, #101 cron 假重复因测试残留, #102 lxml 未申明为直接依赖 — 已全部修复（v1.8.3），见下方 G 节
9. **可行性判定（H 节）**：排除 6 项纯无解后分母为 **93**；零成本可覆盖 86/93（92%），加小额付费（Wind 个人版、微博/抖音）约 88/93（95%）；真 100% 卡在 **4 个死结**（X 涨价、小红书、LinkedIn 原生、公众号全量；Coursera 已于第 9 次调研解除）。**2026-08-05（第 11 次）**：替代路径落地后 P3 清空，无纯无解项；剩余死结均为原生/终端级内容上限（见 H4）
10. **V1 实现清单（H 节）— 已完成 2026-08-02**：10 项生产实现全部落地（A23 SSRN / A24 HuggingFace-Kaggle / A25 Unpaywall-CORE OA 子集 / A18 GDELT / A29 中文播客 / E12 单篇支付 / E14 内容简化 / E11 RAW 变体 / E9 source_score / C11 播客 RSS），全部免费零成本，无外部依赖。验证补齐 5 项中 **B15 PDF ✅ 已完成**（weasyprint 超时配置化）、**E7 cron 跨进程 ✅ 已完成**（Part 9 Q54.5+Q55.10）、**E11 RAW 变体 ✅ 已完成**；**A6 FRED/Alpha Vantage ➖ SKIPPED**（场景已加 Part 1 Q2b.48，env-gated 待免费 key）、**C6 SMTP ➖ SKIPPED**（场景已加 Part 9 Q56a.4，env-gated 待 SMTP 凭证）——两项待凭证回归，不 FAIL。
11. **2026-08-11（第 12 次，output-quality-mega）**：产品差异化渲染（premium-briefing/enterprise-briefing 模板族 + magazine-digest 改走 digest 路径）+ 按产品 LLM 合成字段（implications/risks/action_required/key_metrics）+ 产品选择暴露 MCP/CLI + KB 产品分析元数据闭环（`filter_custom_fields` 分面过滤）+ `fetch_depth` 全文深度（unpaywall/RSS/YouTube/GDELT）。均为既有 ✅ 行的强化，**无 item 行状态翻转**，覆盖率维持 Code 90% / Validation 90% / 双向 87%；验证场景 65→**67**（+`output-agent-interaction` 端到端 generate→过滤 action_required→query_collected、+`regression-product-routing` 路由回归）。

---

## 距 100% 覆盖的差距清单（2026-08-02 更新 v5，V1 计划完成）

> V1 计划完成后，距 100% 的剩余缺口共 **18 项**：17 项未覆盖（P2 可工程化 3 + P3 不可工程化 6 + P4 范围外 8）+ 1 项部分覆盖（A6 待凭证）。V1 已实现 10 项生产功能（A18/A23/A24/A25/A29/E9/E11/E12/E14/C11），A25 学术付费库为 OA 全文子集覆盖（⚠️ 部分覆盖但 Code/Plan ✅，不计入剩余缺口）；E9/E11 从部分覆盖升至 ✅；A6/C6 验证场景已就绪，env-gated SKIPPED 待凭证回归。  
> **2026-08-05（第 11 次）修订**：B24 column + D11 magazine-digest + D12/D14/D15/D16 新 demo 域 + A7/A19/A20/A26/A27/D13 替代路径落地 + A25 升至 ✅，剩余缺口 **17→10 项**（① 应覆盖未做 2：A28/E15 + ③ 范围外 8），总覆盖率 83%→**90%**（89/99）、双向 73→86（74%→87%）。  
> **2026-08-04（第 10 次）修订**：B23 电子书/音频书已实现（ebook.py + 3 format 白名单 + MCP + `[ebook]` extra + 7 测试全过），剩余缺口 **18→17 项**（P2 可工程化 3→2：余 A28 TikTok、E15 A2A），总覆盖率 83%→**84%**（83/99）。  
> **2026-08-04（第 9 次）修订**：P3 六项（A7/A19/A20/A26/A27/D13）全部获得替代信源（见 P3 节/H3'），从"结构性无法覆盖"转为"替代信源可部分覆盖（待实施）"；B23 已由用户指定实施（方案就绪）。③ 范围外 8 项维持不变。

### ① 应覆盖但未做（2 项）— 可工程化，列为下一步开发优先

> B23 电子书/音频书已于 2026-08-04（第 10 次）实现移出（`src/autoinfo/output/ebook.py` — EPUB3 ebooklib / MOBI calibre KF8 / audiobook 分章 TTS，见 B23 行与 H6）。

| 类别 | 项 | 原因 | 实现路径 |
|:----:|:--:|------|---------|
| Code 缺失 | A28 TikTok | Research API 需学术审核 | 准入后接入 |
| Code 缺失 | E15 A2A 原生协议 | webhook 单向 | A2A server 实现 |

### ② 合理未覆盖 → 替代信源可部分覆盖（6 项，2026-08-04 第 9 次实证 → 2026-08-05 第 11 次全部落地）

> A18 WSJ/FT/财新 已于 2026-08-02 经 GDELT+Google News RSS 覆盖（新闻头条级），移出；A25 Elsevier/Springer/IEEE 已于 2026-08-02 经 Unpaywall/CORE 覆盖 OA 全文子集（⚠️ 部分覆盖），移出。  
> **2026-08-04（第 9 次）**：剩余 6 项经 librarian 活体实证（详情见 P3 节与 H3'），全部获得替代信源——原"结构性无法覆盖"结论修订为"替代信源可覆盖 X 级，原生/终端级仍无解"。  
> **2026-08-05（第 11 次）**：6 项替代路径全部落地（akshare/sec_edgar/edx_sitemap 专有 handler + general-news/online-education 源配置 + financial-intelligence sec_edgar 替换），见 P3 节落地标记。

| 类别 | 项 | 原因 | 替代信源（2026-08-04）→ 落地状态（2026-08-05） |
|:----:|:--:|------|------|
| 替代 | A7 Bloomberg/Refinitiv/Wind/Choice/iFinD/CEIC | 机构级付费 API，无公开接口 | Wind Alice 个人版免费 1000 积分/天（官方 MCP）+ AKShare + cninfo 公告 → EOD/基本面级 → ✅ AKShare handler（M2T19） |
| 替代 | A19 知乎/得到/微信公众号 | 无公开 API，反爬严格 | 知乎日报 JSON API（免鉴权）+ RSSHub `/dedao/*`（零配置）+ wewe-rss/wechat2rss（微信读书系）→ ✅ general-news 源配置 |
| 替代 | A20 X/微博/抖音/小红书 | 付费 API（X 涨价）或封锁抓取 | Bluesky Jetstream + Mastodon 替 X；微博 RSSHub cookie；抖音 hotsearch 限时免费；小红书仍无解 → ✅ Bluesky/Mastodon 源配置（M3 批） |
| 替代 | A26 知网/万方/维普 | 无公开 API + 强反爬 | NSSD→ncpssd.cn 免费 2500 万条 + 万方开放平台官方 API + 维普 OA 平台 → ⚠️ 万方源已合并（OUTCOME A；POST 传输待扩展） |
| 替代 | A27 Coursera/edX | 无采集 API（许可复杂） | Coursera 公开目录 API（免 key 23,348 门实测）+ edX sitemap 课程发现 → ✅ edx_sitemap handler（M2T21）+ Coursera 源 |
| 替代 | D13 LinkedIn | 无公开 API，抓取封锁 | SEC EDGAR + BusinessWire/PRNewswire RSS + 公司 newsroom RSS 组合替代公司级情报 → ✅ sec_edgar handler（M2T20）+ 新闻稿 RSS（M3T27/M3T30） |

### ③ 超出产品范围（8 项）— 与 AutoInfo 产品定位不符，明确不做

| 类别 | 项 | 原因 |
|:----:|:--:|------|
| 范围外 | B21 直播/社群服务 | 需运营生态 |
| 范围外 | B22 "内容+服务+社群"复合模式 | 商业模式转型方向 |
| 范围外 | B25 实时数据终端 | 机构级终端形态 |
| 范围外 | C9 电视/智能电视 | 无 TV 输出能力 |
| 范围外 | C10 移动 App+应用商店 | 无移动端 App |
| 范围外 | C12 浏览器/导航 | 无浏览器产品 |
| 范围外 | C13 联盟/推荐链接 | 无联盟系统 |
| 范围外 | E13 RaaS 效果付费 | 需商业模式设计 |

### ④ 部分覆盖（10 项）— 代码已有，验证或功能待补

> E9 来源可信度评估、E11 RAW 产品变体已于 2026-08-02 升至 ✅，移出部分覆盖清单。A25 学术付费库为 OA 全文子集覆盖（Code/Plan ✅，覆盖状态 ⚠️），已实现至可行上限，不计入待补缺口。  
> **2026-08-04（第 9 次）**：10 项 ⚠️ 部分覆盖全部获得补齐路径（librarian 实证）——8 项可零成本补齐（A6 注册免费 key、A22 Medium RSS、B24 复用 report_type、D12/D14/D15/D16 自建 demo 域、D10 走 Apple 无 key RSS），2 项为文档化上限（A25 付费全文、D11 整刊）。  
> **2026-08-05（第 11 次）**：其中 B24/D11/D10/D12/D14/D15/D16 已落地（column/magazine-digest 产品 + Apple RSS 并入 online-video + 4 新 demo 域），A22 Medium RSS 源已文档化，A6 场景已就绪（`sources-a6-keyed`，env-gated 待 key），A25 升至 ✅（Crossref 验证完成）。

| 类别 | 项 | 原因 | 补齐路径（2026-08-04 实证）→ 落地状态（2026-08-05） |
|:----:|:--:|------|------|
| 验证缺失 | A6 FRED/Alpha Vantage | 场景已加（Part 1 Q2b.48），需用户 API Key | **注册免费 key 即完成**（1 小时）：FRED 免费 120 req/min 无日限 + Finnhub 免费 60 calls/min（公司新闻+SEC 文件）+ Twelve Data 免费 800 req/天；Alpha Vantage 2026 已降至 25 req/天作兜底 → ⚠️ 待凭证（`sources-a6-keyed` 场景就绪） |
| 源补充 | A22 Substack/Patreon/Medium | 仅 Substack 经 RSS | **Medium RSS 可靠可用**（`medium.com/feed/@user`、`/feed/{pub}`、`/feed/tag/{tag}`，每 feed 最新 10 篇）→ 加 RSS 源即可；Patreon ❌ 无通用 RSS（仅成员 podcast RSS），文档化上限 → ⚠️ Medium 文档化 |
| 源补充 | A25 Elsevier/Springer/IEEE | 仅 OA 子集 | **Crossref REST API**（免 key，`api.crossref.org/works`）补元数据发现 → 升级为"文档化上限 + 元数据覆盖"；付费全文仍为许可上限 → ✅ Crossref 已存在验证完成 |
| 产品 | B24 付费深度专栏 | 仅 Digest 近似 | **复用 `report_type` 模板**：新增 `report_type="column"`（单主题/专家视角/周更）+ ProductTemplate 行 + 订阅分层门控（check_access）→ ✅ column 落地（M5T40，premium + G15 门控） |
| 领域 | D10 音乐流媒体 | 无 demo 域 | **Apple Music 无 key RSS/JSON**（`rss.marketingtools.apple.com/api/v2/{cc}/music/most-recent/{n}/explicit.json` 实测活体）+ Pitchfork/Billboard RSS 自建域；Spotify API 2026-02 收紧（需 Premium+1 client ID+5 用户+端点移除）→ 不 gate 在 Spotify 上 → ⚠️ Apple RSS 并入 online-video（M3T25） |
| 领域 | D11 音频/播客/数字杂志 | 播客 ✅ 数字杂志 ❌ | **杂志摘要产品**：per-title RSS（The Atlantic/Wired 等）+ `generate_digest` 杂志模板；整刊 ❌ 文档化上限（Cafeyn/PressReader 无 API，许可门控）→ ✅ `magazine-digest` 落地（M5T41，templates 6→8） |
| 领域 | D12 通用新闻 | 无 demo 域 | **自建 general-news 域（1 天全免费）**：GDELT（已有）+ Guardian Open Platform（免费 key 500 req/天）+ Google News RSS + 已有 NYT/AP/Reuters → ✅ general-news 域（M3T24，5 源 + M3 批追加 10 源，共 15 源） |
| 领域 | D14 游戏内购/数字游戏 | 行业资讯部分可追踪 | **自建 gaming 域（0.5 天纯 RSS）**：IGN/Polygon/GamesIndustry.biz/机核网 gcores.com/rss（全部实测活体）；游研社无 RSS → Google News `site:` 绕过；内购数据 ❌ 文档化上限（无 API）→ ✅ gaming 域（M3T24） |
| 领域 | D15 B2B 数据/工具/API | financial-intelligence 部分 | **自建 B2B 域（0.5 天）**：ProductHunt 官方 Atom feed（实测活体）+ TechCrunch/Crunchbase News RSS + HN（已有）；Crunchbase 免费层已取消（$49-99/月）文档化上限 → ✅ b2b 域（M3T24） |
| 领域 | D16 零售/电商资讯 | Web/RSS 可追踪 | **自建 retail 域（0.5 天）**：Retail Dive `feeds/news/`（注意根 `/rss/` 403）+ Modern Retail + Google News `site:ebrun.com` 绕过亿邦无 RSS；小红书/抖音 ❌ 文档化上限 → ✅ retail 域（M3T24） |

---

## H. 可行性判定与实现路线图（2026-08-02 更新，2026-08-04 第 9 次修订）

> 基于 2026-08-02 外部核实（librarian 调研 GDELT / OpenBB / Unpaywall+CORE / RSSHub / NSSD / Listen Notes / edX / X API 定价 / Stripe 模式共存 / 免费行情层 / NewsAPI+Google News RSS / 公众号第三方 API 共 12 条绕过路径的 2026 存活状态），为全部未覆盖项标注可行性决策。
>
> **核心修正（对比 2026-08-02 上午分析）**：
> - 🔴 X API Basic $200/月档 2026-02 关闭新注册（转 pay-per-use，6 月老用户强制迁移）→ **A20-X 放弃**
> - 🟢 GDELT（免费无 key、3 个月窗口）、Unpaywall（10 万次/天）、CORE（免费注册）确认存活 → **A18/A25 零成本可做**
> - 🟡 RSSHub 中文路由恶化（知乎需 cookie+无头浏览器、小红书 503、公众号 feeddd 挂掉）→ **A19 仅知乎可行且脆弱**
> - 🟡 NSSD 存活但无 API（注册+登录才可下载）→ A26 仅爬虫路径，ROI 低
> - 🟡 edX catalog API 为 beta + 人工审批（2U 重组后）→ A27 不可自助
> - 🟢 Stripe `mode="payment"` 与订阅模式共存（API 层确认）→ E12 直接可做
> - 🟡 OpenBB 为聚合壳（自带 key、AGPLv3）→ 不能替代 Bloomberg，仅归一化免费层数据
> - 🟡 免费行情层收紧：Alpha Vantage 硬性 25 req/天、Twelve Data ~100 req/天、Finnhub 无基本面 → A7 主力靠 Wind 个人版积分
> - 🟡 公众号官方 API 仅账号所有者授权（第三方须逐账号授权，权限集 7）→ 公众号全量采集无合法批量路径
>
> **2026-08-04（第 9 次）修订**：P3 六项（A7/A19/A20/A26/A27/D13）经第二轮 librarian 活体实证（2026-08-04，逐路由/逐端点 HTTP 核实）全部获得替代信源——"结构性无法覆盖"降级为"替代信源可部分覆盖"；B23 由用户指定转为实施项（方案见 H3）；小红书/X 原生/公众号全量/知网国内 4 项保留为明确放弃（H4）。
>
> **覆盖率重定义**：99 项 − 7 项纯无解（B21/B22/C9/C12/C13/E13 + 小红书）− 4 项替代后原生仍无解（X 原生/LinkedIn 原生/公众号全量/知网国内，替代信源可覆盖）= **可覆盖集合 93 项**（维持）；零成本上限 86/93（**92%**）不变（替代信源全部免费起步），加小额付费（微博/抖音/微信读书账号）约 88/93（**95%**）；真 100% 卡在 5 个死结（X 涨价、小红书、LinkedIn 原生、Coursera Catalog API 审批制、公众号全量）→ 第 9 次修订：Coursera 已解（公开目录 API 免 key 实测活体），死结降至 **4 个**（X、小红书、LinkedIn 原生、公众号全量）。

### H1. 生产实现清单（V1 — 全部免费零成本）— ✅ 全部已完成（2026-08-02）

| 项 | 功能 | 实现路径 | 核实依据 | 成本 | 状态 |
|:--:|---|---|:---:|:---:|:---:|
| **A23** | SSRN 社科工作论文 | RSS 接入（同 Substack 模式） | 有限 API/RSS 大部分免费 | 低 0.5-1d | ✅ 已完成 |
| **A24** | Hugging Face / Kaggle | HF datasets-server 公开 API + Kaggle API | 公开免费 API | 中 2-3d | ✅ 已完成 |
| **A25** | 学术付费库 OA 全文 | Unpaywall（10 万次/天）+ CORE 免费 OA 全文（元数据 OpenAlex 已有） | ✅ 核实免费可用 | 中 2-3d | ✅ 已完成（OA 子集） |
| **A18** | 新闻头条级覆盖 | GDELT 免费（无 key、3 个月窗口）+ Google News RSS；高价值内容走机构授权（付费可选，独立决策） | ✅ 核实免费可用 | 低-中 1-2d | ✅ 已完成 |
| **A29** | 中文播客 | Apple Podcasts/iTunes Search（A16）已隐式覆盖；Listen Notes 免费层 300 次/月可选补充 | ✅ 实测核实（2026-08-02: 3 例 country=CN curl 均返回 resultCount≥1，证据 `.omo/evidence/task-5-apple-podcast-cn.json`） | 低 0.5d 验证 | ✅ 已完成 |
| **E12** | 单篇/Micro 订阅 | Stripe `mode="payment"`（与订阅共存） | ✅ 核实 | 低 1-2d | ✅ 已完成 |
| **E14** | 内容简化 | LLM simplify 输出模式（新增 output mode） | — | 低 0.5-1d | ✅ 已完成 |
| **E11** | RAW 产品三变体 | 拆分 api feed / webhook 流 / 批量导出（`variants` 字段） | 文档-代码一致性 | 中 1-2d | ✅ 已完成 |
| **E9** | 来源可信度评分 | G1 分级 + 确定性 `source_score`（0-100，`SOURCE_TIER_SCORE_MAP`） | — | 低 0.5-1d | ✅ 已完成 |
| **C11** | 播客目录发布 | B11 音频已有 + 标准播客 RSS 2.0 发布（`<enclosure>` + `itunes:*`） | — | 低-中 1-2d | ✅ 已完成 |

### H2. 验证补齐清单（V1 — 免费测试凭证即可）— 3/5 已完成，2/5 待凭证

| 项 | 功能 | 凭证方案 | 成本 | 状态 |
|:--:|---|---|:---:|:---:|
| A6 | FRED / Alpha Vantage E2E | 两者免费 key 注册即得（AV 25 req/天、FRED 免费）；场景已加 Part 1 Q2b.48（2026-08-02） | 0 | ➖ SKIPPED（待 key） |
| B15 | PDF 导出验证 | ✅ 2026-08-02 完成：weasyprint 渲染超时配置化（`output.pdf_timeout`，默认 120s，Task 17），Part 4 Q34.1c 实测通过（需 weasyprint 环境） | 已完成 | ✅ 已完成 |
| C6 | SMTP 渠道验证 | Mailtrap / Resend 免费层或 Gmail app password | 0 | ➖ SKIPPED（待凭证） |
| E7 | cron 跨进程验证 | 本地跨进程定时测试 | ✅ 已完成 (2026-08-02, Part 9 Q54.5+Q55.10) | ✅ 已完成 |
| E11 | RAW 变体验证 | 随 H1-E11 拆分一起验证 | 0 | ✅ 已完成 |

> **2026-08-02（Task 18）**：C6 SMTP 渠道验证场景已就绪 —— Part 9 Q56a 新增 56a.4（`SMTP_HOST`/`SMTP_USER`/`SMTP_PASS` env-gated，无凭证 SKIPPED 不 FAIL）。当前无凭证 → SKIPPED 明确记录；提供 Mailtrap/Resend 免费层或 Gmail app password 后重跑即可转 ✅。无任何 src/ 代码修改。

### H3. 推迟到 V2（依赖预算决策 / 审核流程 / 生态成熟）

| 项 | 功能 | 路径 | 阻塞 |
|:--:|---|---|------|
| A7 | 机构金融数据 | Wind Alice 个人版免费 1000 积分/天（2026-03 发布，官方 MCP `wind-skills`，无需充值即可起步）+ AKShare + cninfo 公告 | 需注册 Wind 账号（手机号实名）；tick/终端级仍无解 |
| A20 | 微博 / 抖音 | 微博 RSSHub cookie 路由（自托管，维护月刷新）；抖音开放平台 hotsearch 限时免费（50 元/万次兜底） | 需预算决策 / 反爬维护 |
| A28 | TikTok | Research API 学术审核 / Display API 资质 | 流程门槛 |
| E15 | A2A 原生协议 | 代码实现（MCP 145 工具已覆盖 Agent 对接） | 生态未成熟 |
| B23 | 电子书/音频书 | **✅ 已完成（2026-08-04 第 10 次）**：`src/autoinfo/output/ebook.py` — EPUB3（ebooklib，xhtml+CJK `set_language`）+ MOBI（calibre `--mobi-file-type=both` KF8）+ audiobook（`_render_audio` 分章 TTS→章节 MP3/ZIP/CHAP-CTOC）；ebooklib 已装、pandoc 已装 | ✅ 已完成（H6 第 1 批） |
| A19-知乎 | 知乎采集 | 知乎日报 JSON API（免鉴权实测活体）可直接做；热榜/答案需 RSSHub cookie 路由（`ZHIHU_COOKIES`+自动 `__zse_ck`，PR #22319） | 热榜级维护成本高（日报级零维护） |
| C10 | 移动 App | PWA + 微信小程序替代 App Store 分发 | 中-高成本 |

### H3'. 第 9 次调研新增替代路径（2026-08-04 librarian 实证，全部活体核实）

| 项 | 新增替代路径 | 实证方式 | 成本 | 覆盖级别 |
|:--:|---|:---:|:---:|:---:|
| A19-得到 | RSSHub `/dedao/*` 路由（`requireConfig:false`、`antiCrawler:false`，零 cookie） | RSSHub master 路由核实 | 低 0.5d | ✅ 可全覆盖 |
| A19-公众号 | wewe-rss（微信读书自托管全文本）+ RSSHub `/wechat/wechat2rss/:id`（后端 xlab.app 实测活体，~6h 延迟全文本） | 2026-08-04 活体 HTTP 核实 | 中 1-2d | ⚠️ 全文本（账号封控风险） |
| A26-NSSD | NSSD 已迁移合并至 ncpssd.cn（免费 2500 万+条、2373 种中文期刊、期刊优先发布 100+ 刊）；RSSHub `/ncpssd/newlist` 或内部 `articleinfoHandler/getjournalarticletable` JSON POST | 2026-08-04 活体核实 | 低 1d | ✅ 社科期刊元数据+摘要 |
| A26-万方 | 万方开放平台官方 API（`apps.wanfangdata.com.cn/open`，X-Ca-AppKey/APPCODE，`OpenPeriodicalChi` 中文期刊集合） | 官方文档 + agent skills 仓库核实 | 低 1d | ✅ 元数据+全文检索 |
| A26-维普 | 大家·维普 OA 平台 oa.cqvip.com（期刊目录/论文检索/行业动态） | 2026-08-04 活体核实 | 中 1-2d | ⚠️ OA 论文 |
| A27-Coursera | 公开目录 API `api.coursera.org/api/courses.v1`（免 key、分页、23,348 门实测） | 2026-08-04 活体核实 | 低 1d | ✅ 课程目录/上线追踪 |
| A27-edX | `edx.org/sitemap.xml`（2026-07-30 lastmod 实测）+ 课程页结构化数据；官方 Catalog API 仍 beta 审批制 | 2026-08-04 活体核实 | 低-中 1-2d | ⚠️ 课程发现 |
| A7-Wind | Wind Alice 个人版 2026-03-24 发布，每日赠 1000 积分，官方 MCP skill（A 股/港股/美股行情+基本面+宏观+公告） | 证券日报/新浪/wind-skills 仓库核实 | 低 1-2d（注册即用） | ⚠️ EOD/基本面级 |
| A7-AKShare | AKShare 免费聚合（腾讯/东财/同花顺/新浪/巨潮），A 股/港股/公告全覆盖 | 社区维护活跃 | 中 1-2d | ⚠️ 广度兜底 |
| A7-cninfo | 巨潮资讯 `hisAnnouncement/query` 公告全文本免费无 key（30 条/页分页） | 社区 OSS 客户端核实 | 低 0.5-1d | ✅ 公告级 |
| D13-组合替代 | SEC EDGAR（`data.sec.gov/submissions/CIK*.json` 免费 10 req/s）+ BusinessWire MRSS + PRNewswire 行业 RSS + 公司 newsroom RSS | 官方文档核实 | 低 1-2d | ⚠️ 公司级情报 ~80% |
| D10-Apple | Apple Music 无 key RSS/JSON（`rss.marketingtools.apple.com/api/v2/{cc}/music/most-recent/{n}/explicit.json`） | 2026-08-04 实测活体 | 低 0.5d | ✅ 榜单/新发行 |

### H4. 明确放弃（不划算 / 结构性无解）— 2026-08-04 修订后余 4 项

| 项 | 功能 | 原因 |
|:--:|---|---|
| A20-X | X/Twitter 原生 | pay-per-use 涨价（2026-02 关闭 $200 档，读帖 ~$5/千条），成本 > 价值；替代：Bluesky/Mastodon |
| A20-小红书 | 小红书笔记 | 内容 API 仅限电商类目；RSSHub 路由 2025 年中已坏（#19505，503/captcha）；商业看板（新红/千瓜）仅人工 |
| A19-公众号全量 | 微信公众号全量 | 官方 API 仅账号所有者授权，无合法批量路径；替代：wewe-rss/wechat2rss 覆盖订阅的头部账号 |
| A26-知网国内 | 知网 CNKI 国内全文 | 付费墙 + 无 API + OpenAlex CNKI 数据 2016 年后塌缩（arxiv 2507.19302）；替代：ncpssd/万方/维普 OA |
| B21/B22/B25/C9/C12/C13/E13 | 产品形态/硬件/商业模式 | 结构性无解（见上方 P4 范围外） |

### H5. 实现顺序建议 — ✅ 已执行（2026-08-02，V1 计划完成）

```
✅ 第 1 批（低垂果实，1-2 天）: E12 单篇订阅 → E14 内容简化 → E9 可信度评分（A29 验证确认已于 2026-08-02 完成 ✅）
✅ 第 2 批（新 collector，2-3 天）: A23 SSRN → A18 GDELT → A24 HF/Kaggle → A25 Unpaywall/CORE
✅ 第 3 批（中量，1-2 天）: E11 RAW 变体拆分 → C11 播客目录发布
验证批次（并行）: B15 ✅ / E7 ✅ / E11 ✅ 已完成；A6 ➖ / C6 ➖ SKIPPED 待凭证回归
```

### H6. 第 9 次调研后建议实施批次（2026-08-04）— 第 1-4 批均已执行（2026-08-05 第 11 次结算）

```
🟢 第 1 批（用户指定要做，2-3 天）: ✅ **B23 电子书/音频书输出已完成（2026-08-04）**（ebook.py EPUB3/MOBI/audiobook + 3 format 白名单 + MCP + `[ebook]` extra + 7 测试）
🟢 第 2 批（零成本低垂果实，1-2 天）: ✅ **已完成（2026-08-05）** A6 `sources-a6-keyed` 场景就绪（env-gated 待 key 回归）→ A22 Medium RSS 文档化 → A19-得到/知乎日报 general-news 源配置 → A27 edx_sitemap handler + Coursera 源
🟢 第 3 批（新 demo 域，2-3 天）: ✅ **已完成（2026-08-05，M3T24）** D12 general-news 域（GDELT+Guardian+Google News RSS，5 源 + M3 批追加 10 源，共 15 源）→ D14 gaming 域（IGN/Polygon/GI.biz/gcores）→ D15 B2B 域（ProductHunt+TechCrunch）→ D16 retail 域（Retail Dive+Modern Retail+Google News site:ebrun）
🟡 第 4 批（中量，需账号/维护）: ✅ **部分完成（2026-08-05）** A7 AKShare handler ✅（M2T19）→ A26 万方源已合并 online-education（OUTCOME A：静态头鉴权通过，POST-only 端点待 http_api POST 传输扩展——文档化不当作已实现）→ A20 Bluesky/Mastodon 源 ✅ → D10 Apple Music RSS ✅（并入 online-video）→ D13 sec_edgar handler + 新闻稿 RSS ✅ → B24 column ✅（M5T40）→ D11 magazine-digest ✅（M5T41）；A19 公众号 wewe-rss/wechat2rss、A20 微博/抖音 cookie 路由、A7 Wind Alice 注册、A26 维普/ncpssd、A27 edX Catalog API 为文档化待办（需账号/维护）
📋 文档化上限（不实施）: A25 付费全文（Crossref 元数据已补）、D11 整刊、Patreon 通用帖、Crunchbase 组织数据、小红书笔记、X 原生、LinkedIn 原生、公众号全量、知网国内全文
```

---

## G. 近期 Issues 对应 Gap 分析（#98-#102）— ✅ 全部已修复（v1.8.3, 2026-07-31）

> **修复状态**：以下全部 gap 已在 v1.8.3 中修复并附带回归测试（见 `CHANGELOG.md` v1.8.3）。

| # | Issue 标题 | 根因 | 影响域 | Gap 类型 | 严重程度 | 修复方式（已落地） |
|:-:|-----------|------|--------|---------|---------|---------|
| #98 | `list_output_templates` 找不到模板 | 模板文件存在但路径配置不匹配，测试环境与生产环境差异 | 全部输出生成(B1-B8) | 测试覆盖不足 | 🟡 Medium | ✅ `output/__init__.py` 中 `_TEMPLATES_DIR`/`TEMPLATE_PATH` 改为基于模块实际路径解析（不依赖 CWD）；`test_output_templates.py` 回归测试 |
| #99 | `generate_report` 空返回 (response_format=json_object) | LLM 不支持 `json_object` 时 `response.choices[0].message.content` 为 None，4 个调用点无 `None` guard | 全部输出生成(B1-B8) | 代码弹性缺失(F1) | 🔴 High | ✅ `_parse_json_response` 接受 `content: str \| None`，返回 `{}` + warning；4 个调用点 `content or ""` guard；`test_digest.py` 回归测试 |
| #100 | 多域 init 只复制一个 sources.yaml | 独立 `sources.yaml` 复制逻辑仅复制第一个域的 sources.yaml | 域管理初始化 | 代码缺陷(ergonomic) | 🟡 Medium | ✅ 彻底移除独立 `sources.yaml`，全部域 sources/topics 直接内嵌 `config.yaml`（单一事实源）；`test_init.py` 回归测试 |
| #101 | `cron add-schedule` 假重复 | 测试残留 `.autoinfo/schedules.yaml` 被 `_load_schedules()` 读取，旧条目与新条目同名冲突。且 CLI cron (`schedules.yaml`) 与 delivery scheduler (`delivery_schedules.yaml`) 使用不同路径 | 定时调度(F3) | 测试隔离缺失 + 双系统路径耦合 | 🟡 Medium | ✅ 删除残留 `schedules.yaml` 工件；cron 测试改用临时目录隔离；`test_cron.py` 回归测试 |
| #102 | `lxml` 未申明为直接依赖 | `lxml` 仅通过 `trafilatura` 传递依赖获取，`pyproject.toml` 未列出；pip `--no-deps` 或 slim 镜像中 Web collector 会崩溃 | Web 收集（A21）| 构建弹性缺失(F4) | 🟡 Medium | ✅ `pyproject.toml` 添加 `lxml>=5.0` 直接依赖；`test_web_handler.py::test_lxml_importable` 回归测试 |

### G 维度 gap 影响评分（修复前基线，均已落地修复）

| Gap ID | 对应 Issue | 影响范围 | 用户可见 | 修复成本 | 优先级 |
|:------:|:---------:|:--------:|:--------:|:--------:|:------:|
| F1 | #99 | B1-B8 全部输出生成 | ✅ 空返回或静默失败 | 低（4 行 guard） | **P0** |
| F2 | #100 | 域初始化 | ✅ 多域用户只有第一个域可用 | 低（修复循环） | **P1** |
| F3 | #101 | 定时调度 | ⚠️ 特定场景下 cron 命令报错 | 中（路径统一或隔离） | **P1** |
| F4 | #102 | Web 收集 | ⚠️ 仅特定部署环境出问题 | 低（一行 dep） | **P1** |

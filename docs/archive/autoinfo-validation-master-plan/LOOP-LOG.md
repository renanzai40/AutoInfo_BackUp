# LOOP-LOG — AutoInfo validation 循环记录

> **📦 ARCHIVED 2026-08-14(superseded)** — 本目录数据停在 2026-07-31(141 工具/47 场景),与现行 145 工具/68 场景冲突。已被 `docs/dev/validation-scenario-contract.md`(场景编写 + agent-tester 执行)与 `docs/dev/best-practice-review.md`(业界最佳实践复盘维度)取代。

> 机制说明（2026-08-12 首次落实）：
> - 每次迭代循环（打包/验证/修复）的**关键事件、根因、修复、验证结果**必须记录在此
> - 每次迭代**开始前**必须复查本文的「坑清单」——已知坑逐条核对，避免重踩
> - 新踩的坑当天追加到「坑清单」，格式：现象 → 根因 → 预防
> - 用户要求：迭代要形成文档，文档要在下次迭代前被复查，否则机制流于表面

---

## 2026-08-12 循环（第 1-9 次打包，11 个 issue 闭环）

### 打包迭代史（9 次）

| # | 结果 | 失败原因 | 分类 |
|---|------|----------|------|
| 1-4 | 弃用（exit-0 但 zip 未核验） | config.yaml tts 段丢失 → output-ebook 走 OpenAI TTS | 环境坑 |
| 5 | 170530.zip，4 scenarios failed | config 第 4 次丢失；premium 180s 超时；llm-gated 概率失败；data-lifecycle 游标 bug；gap=81 | 混合 |
| 6 | 195935.zip，gap 80 | filler 产物被 D1 gate 误拒（agent JSON-LD 用 markdown sections 标准）| 深层 bug |
| 7 | 211016.zip，gap 80 | #224 只改 quality.py，_build_product_output 丢 @type 标记，agent 判定未触发 | 修复不完整 |
| 8 | 运行中 | 验证 #225（@type 透传）后最终打包 | — |

### Issue 闭环清单（11 个）

| Issue | 问题 | 根因 | 修复 | 验证 |
|-------|------|------|------|------|
| #203 | enterprise-briefing 180s 超时 | 两层超时：asyncio wait_for + kind:cli subprocess 180s 独立默认，只修一层无效 | scenario timeout 覆盖 + cli/http 透传 | premium ALL PASSED（第 7 次重跑）|
| #204/#206 | gates 串行慢 / 并行崩溃 | — | 并行 + 去重 | — |
| #208 | 12 个 MCP 工具扁平错误 | 错误 envelope 不统一 | 标准 envelope | — |
| #210/#218 | TTS 默认 openai | **两层默认值**：TTSConfig dataclass + _dict_to_config YAML 解析硬编码，只改 dataclass 无效 | 双默认都改 local | load_config()=local；ebook ALL PASSED |
| #213 | batch 游标过期跳过新 items | progress 只有数量无内容指纹，同数量新 items 不重置 | start_index>=total 也重置 | data-lifecycle ALL PASSED |
| #215 | suggest_keywords LLM 空输出失败 | DeepSeek 概率空 content，无 fallback | deterministic 关键词提取 | llm-gated ALL PASSED |
| #217 | agent JSON-LD 被 D1 误拒（105 个） | **两层**：quality.py D1 判定 + validation_delivery 适配丢 @type | D1 agent-native 检查 + @type 透传 | D1/D2/D3 passed 实测 |
| #220 | presentation slides 空 | LLM 空 slides + 空 shell guard | KB-derived slides fallback | 6 cells 重跑全 OK |

### 坑清单（迭代前必查！）

1. **config.yaml 未提交修改在 checkout/并行操作时静默丢失**（WSL DrvFs，`.autoinfo/` gitignored）
   → 关键配置立即 commit 或 /tmp 备份；打包前置 `grep -q "tts:"` 自检
2. **`gh pr merge --delete-branch` 自动切回本地旧 main**——本地 main 落后远程（fetch 失败）时，后台任务读旧代码，修复"假阳性"
   → 每次 merge 后确认工作树分支与 sha；后台任务启动前 `git rev-parse HEAD` + grep 修复标记
3. **同一功能多层实现**：改一处默认/判定不够——修前 grep 所有相关层（dataclass/YAML 解析、asyncio/subprocess、gate/适配层）
4. **后台进程读启动时的工作树**：启动后再改代码不影响已启动进程——验证进程实际加载的版本
5. **WSL fetch/push GnuTLS 间歇失败** → 重试或 gh api 绕行；同步前确认 origin/main sha
6. **filler 生成的产物要过 D1 才算 produced**：产物存在 ≠ matrix 计入（gate 拒绝就不算）——验证走 manifest accepted
7. **agent JSON-LD 的 entry 字段按类型不同**：KnowledgeDigest=entries(source_url+source_platform)；KnowledgePresentation=slides(内容)+sources(来源)；KnowledgeTutorial=steps/exercises(内容)+source_entries(来源)——authenticity 必须按 @type 分支检查，不能一刀切
8. **生成端硬编码空字段**：generate_report agent 渲染曾 `source_platform: ""` 写死（KB 数据有值但产物空）——修生成端后**必须重新生成旧产物**（已生成的不变）
9. **_json_entries 对顶层含 _ENTRY_KEYS 交集的 dict 会整体当 entry**：KnowledgeTutorial 顶层有 title → 被误当 1 个 entry——按 @type 特判（source_entries）绕过
10. **html 模板必须输出 D1 三键章节**：report.html.j2 只有 Executive Summary，缺 Key Findings/Recommendations → D1 永远拒 report-html（模板 + 传参一起改，改完必须重新生成旧产物）
11. **适配层 product_type 粒度**：_build_product_output 曾把 product_type 全标 "PROCESSED" → quality.py D1 无法按产品分支——改为透传 _detect_product_type 结果（presentation/report/column/...），RAW 保持
12. **presentation 完整性语义 = slide 内容**：D1 三键不适用 deck——product_type==presentation 时 body 内容 ≥200 chars 即 pass（无需改模板视觉）
13. **persist 文件名决定 matrix evidence**：generate_report 曾把 column（report_type）产物固定存为 report-markdown-* → 文件名解析永远到不了 column:markdown cell（#229）——persist product 名必须与 spec product 对齐
14. **全量 validation 结果受 DeepSeek LLM 时段波动污染**（2026-08-14，PR #235 全量验证）：log 中 `Failed to parse LLM response as JSON` 63+ 次时，output-* 场景批量 failed——但隔离复跑证明与并发/代码无关（output-column 单独 passed 靠重试救回，output-digest-report 单独也 failed）→ 全量跑前先做 1-2 次短 LLM 探测（llm-gated 单场景 <60s passed 即稳定）；波动时段的重跑结果不可作为回归判定依据

### 复盘（为什么 9 次）

- 任务固有难度低：最终只有 2 个深层 bug（agent D1 误判、TTS 双默认）+ 若干流程坑
- 6-7 次失败是我的执行问题：① 环境坑反复踩（文档机制从未落实，坑没固化为检查项）；② 修复只修一层（未 grep 全层）；③ 验证假阳性（进程读旧代码，验证的是新代码）
- 教训：**修复前先扫全实现层 + 验证前确认进程读的代码版本 + 新坑当天进 LOOP-LOG**

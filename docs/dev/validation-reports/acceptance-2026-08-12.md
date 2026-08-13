# 验收运行报告 2026-08-12(第二次运行)

执行:**B2 代理-测试者** | 评审:**B3 董事(待裁定)** | 报告语言:中文(董事指定)

基线(无密钥):逐场景记录为 `unconfigured` — 绝不误报为通过(见「诚实未配置」)
密钥配置:`AUTOINFO_LLM_API_KEY` 已写入 `.autoinfo/config.yaml`(provider=openai, model=deepseek-v4-flash, base_url=https://opencode.ai/zen/go/v1, `reasoning_model: false` — 以真实工具调用验证);`STRIPE_API_KEY` / `FRED_API_KEY` / `FINNHUB_API_KEY` **未配置**
证据:2026-08-12 实跑复现(coverage 审计 JSON、场景实跑、doc inventory 检查);证据目录 A1-A24 依 `acceptance-framework.md` 附录 A
框架:`docs/dev/acceptance-framework.md`(AC1-AC9,keystone)— 2026-08-08 董事修订(KB 定位 §0.3、AC1 标准 3 人类专属类别、AC6 阶段拆分)+ 2026-08-12 例行计数修正(A1 目标 142→145、§3.1 REST 表述)
基线报告:`docs/dev/validation-reports/acceptance-2026-08-08.md`(首次运行,7 项 FAIL blocker B-01..B-07 + R-01)

## 裁定总表

| 维度 | 裁定 | 说明 |
|-----------|:---:|-------|
| AC1 用户模型完整性 | **PASS** | B-01 依 2026-08-08 董事裁定重新定界:`promote_kb_draft` 为代理操作(设计正确);人类专属类别收窄至破坏性操作。`remove_domain` 已补齐 `confirm` 守卫(`_handle_remove_domain`,server.py),与 `remove_source` 对齐 — **B-01 残余项已关闭** |
| AC2 数据层完整性 | **PASS** | **B-03 已关闭**:12 条模拟 URL 01-Raw 条目已软删除(索引 active=0,可恢复),2 个孤立文件归档至 `knowledge/_archive/b03-orphans/`;场景夹具统一迁移至保留域名 `*.autoinfo.test`,并新增 `SCENARIO_LEAK` 泄漏扫描守卫(validation.py),实跑后索引泄漏数 = 0 |
| AC3 双轨定位 | **PASS** | 代理轨稳固:`director-backdoor` 7/7、`kb-promote-admission` 8/8、`promotion-provenance` 6/6 实跑通过;145/145 工具覆盖,0 MISSING。人类轨:tutorial 空态(B-04)与 export CLI 崩溃(B-05)已修复(commit 9684b08);董事抽样阅读证据已生成(AC5 证据 4/5,见 AC5 节) |
| AC4 覆盖承诺 | **PASS** | 99/99 项已分类,0 未分类(OK 73 / PART 16 / BLK 2 / OOS 8);代码覆盖 90%、验证覆盖 90%、双向 87%(矩阵第 12 次更新 2026-08-11) |
| AC5 质量与交付物 | **PASS** | 软/硬门控功能正常(G0/G4 硬,G1-G3/G5 软;交付 D1-D3);**R-01 已关闭**:G1/G2/G3/G5/CurationGate 已通过 `set_gate_config` 持久化至 `.autoinfo/config.yaml` 并回读验证。AC5 抽样 5 件产物 4 件通过(digest/report/tutorial/column),presentation 列为观察项(LLM JSON 解析脆弱,该路径无重试自愈 — 非阻塞) |
| AC6 商业可行性 | **PASS**(V1) | V1 采集+生产管线范围通过;生命周期 E2E + 成本可见性正常;完整支付链为 V2(延后,于 V2 上线时绑定)— 记录为 unconfigured,绝不误报通过 |
| AC7 流程与治理 | **PASS** | 按框架完成第二次完整运行;2026-08-08 董事修订已应用;例行计数修正处于版本权限内;B3 待裁定为预期状态 |
| AC8 文档健康 | **PASS** | `doc_inventory.py --check` exit 0(CLI 28/28、通道 13/13、场景 67/67、域 13/13),无散落 `test_bug_*` 文件,清单新鲜;acceptance-framework 计数修正已验证 |
| AC9 测试与验证健康 | **PASS** | 回归飞轮**恢复:6/6 实跑通过**(B-06 关闭);0 个 `test_bug_*` 文件名;**AC9-1 已关闭**:58 个根目录未分组测试文件已重组至镜像 `src/autoinfo/` 结构的子包(tests/mcp/、tests/kb/、tests/output/、tests/cli/ 等),根目录残留降至阈值内;全量 pytest 校验(见证据) |
| **总体** | **PASS(可签收候选)** | 首次运行 7 项 FAIL blocker 全部闭环或依裁定改判;**3 项 RISK 修复(B-03 残留、R-01 门控持久化、AC9-1 根目录测试重组)已执行并验证**,B-01 残余确认守卫亦已补齐。剩余仅 B3 终审 + AC5 抽样人工阅读 + presentation 观察项 |

## 执行摘要

第二次完整验收运行。**回归飞轮已修复**:6 个回归场景全部实跑通过(首次运行仅 1/5);2026-08-08 崩溃的两个 CLI 面(portal 偏好、export agent)与 tutorial 空态已按 B-03/B-04/B-05 验证修复。框架本身按 2026-08-08 董事裁定完成修正(KB 定位、AC1 人类专属类别、AC6 阶段拆分),陈旧计数刷新(142→145 工具、REST 表述)。

本次运行完成三项 RISK 处置与一项残余项闭合,均为可验证的事实性修复:

1. **B-03 残留(AC2)**:12 条含 `example.com`/`example.org` 模拟 URL 的 01-Raw 条目经 `soft_delete_entry` 软删除(索引 active=0,保留恢复路径),2 个仅有日期命名的孤立文件移入 `knowledge/_archive/b03-orphans/`;验证场景夹具从 `example.com` 整体迁移至保留域名 `*.autoinfo.test`(4 个 YAML),并在验证引擎加入 `SCENARIO_LEAK` 泄漏扫描(实跑 0 泄漏,`tests/mcp/` 194 通过)。
2. **R-01(AC5)**:G1/G2/G3/G5/CurationGate 门控配置已显式持久化至 `.autoinfo/config.yaml`(此前为代码默认值,`grep` 计数 = 0),回读验证一致。
3. **AC9-1(AC9)**:`tests/` 根目录 58 个未分组测试文件已重组入镜像 `src/` 结构的子包,根目录残留低于 ~40 阈值,0 个 bug 命名文件,全量测试通过(见证据)。
4. **B-01 残余**:`remove_domain` 增加 `confirm` 守卫,与 `remove_source` 对齐(confirm=False → ConfirmationRequired,域未删除,已实跑验证)。

AC5 抽样:5 件真实产物已生成供董事阅读(digest/report/tutorial/column 通过,presentation 失败但以明确错误返回,非静默损坏)。整体 **PASS(可签收候选)**,终审权在董事。

## Blocker / RISK 台账

### 2026-08-08 首运行 — 关闭状态

| ID | 2026-08-08 发现 | 2026-08-12 状态 |
|----|--------------------|--------------------|
| B-01 | 人类专属操作未代码门控 | **框架解决 + 残余项已关闭** — 2026-08-08 董事裁定:`promote_kb_draft` 为代理操作;人类专属类别=破坏性操作。`remove_domain` 已补 `confirm` 守卫(`_handle_remove_domain`,server.py),与 `remove_source` 对齐,实跑验证 |
| B-02 | CLI portal 偏好崩溃 | **已关闭** — `cli/portal.py` 读 `profile.delivery_preferences`;typed MCP `update_preferences`/`get_preferences` 路径已验证 |
| B-03 | 溯源不完整 + 真实 KB 含模拟 URL | **已关闭** — 12 条模拟 URL 01-Raw 条目已软删除(active=0),孤立文件归档;验证场景夹具迁移 `*.autoinfo.test`;`SCENARIO_LEAK` 泄漏扫描守卫上线(实跑 0 泄漏) |
| B-04 | Tutorial markdown 空态 | **已关闭**(commit 9684b08,空态回退) |
| B-05 | CLI `export --format agent` 崩溃 | **已关闭**(commit 9684b08,`entries_count` `.get()`) |
| B-06 | 回归飞轮 1/5 | **已关闭** — 2026-08-12 实跑:`regression-collect-int-id`、`regression-llm-key-resolution`、`regression-period-enum`、`regression-report-structure`、`regression-product-routing`、`regression-source-301` **6/6 通过** |
| B-07 | EPUB CJK 非 ASCII 缺陷 | **已关闭** — output-ebook 路径通过(`tests/output/test_output_ebook.py` 7/7 含 CJK 往返) |
| R-01 | 无门控配置记录 | **已关闭** — G1/G2/G3/G5/CurationGate 已经 `set_gate_config` 持久化至 `.autoinfo/config.yaml`,回读验证一致 |

### 2026-08-12 本次修复明细(原 3 项 RISK + 1 项残余)

- **[AC2-1] AC2 | 标准 3(B-03 残留)— 已关闭**:12 条模拟 URL 01-Raw 条目软删除(索引 active=0,`deleted: true` 标记,可恢复);2 个孤立文件(仅日期命名)移入 `knowledge/_archive/b03-orphans/`。工程语义验证:软删条目在 digest 生成期间触发 promotion 拒绝并被隔离至 `knowledge/_failed/`,未污染任何产物。
- **[AC5-1] AC5 | R-01 门控配置持久化 — 已关闭**:`.autoinfo/config.yaml` 现含 `quality_gates`/`delivery_gates` 显式配置(G1/G2/G3/G5 软 + CurationGate 硬),`get_gate_config` 回读与写入一致,代码默认值不再静默生效。
- **[AC9-1] AC9 | 标准 1 根目录测试文件 — 已关闭**:58 个未分组 `tests/` 根测试文件重组至镜像 `src/autoinfo/` 的子包(`tests/mcp/`、`tests/kb/`、`tests/output/`、`tests/cli/`、`tests/delivery/`、`tests/api/`、`tests/collectors/`、`tests/llm/` 等),根目录残留低于 ~40 阈值;0 个 bug 命名文件;全量 pytest 通过。
- **[B-01 残余] remove_domain 确认守卫 — 已关闭**:`_handle_remove_domain` 增加 `confirm` 参数(默认 True 以保 CLI 兼容),`confirm=False` → `ConfirmationRequired` 错误且域未删除;工具 schema 同步更新;lsp 诊断干净。

### 新增 / 存续观察项(2026-08-12)

- **[OBS-1] AC5 | Presentation 生成路径 — 观察项(非阻塞)**:`generate_presentation` 两次实跑均因 LLM 返回非严格 JSON 而失败(`slides=0, chars=288`),与 2026-08-08 B-04 修复(LLM JSON 解析)同源,但该路径**缺少 report/digest 的重试自愈兜底**。失败以明确错误返回(exit 1 + 可读信息),非静默损坏;digest/report/tutorial/column 均证实产品线整体可用。建议:presentation 调用点复用 `llm.parse_json_response` 三策略 + 重试封装(排期,非阻塞)。

## 诚实未配置(已记录,绝不误报通过)

| 项 | 原因 | 重跑触发 |
|------|--------|----------------|
| rest-api | 本次运行期间 REST 服务未启动 — 场景报告 unconfigured(诚实;server 启动 + curl A19 为重跑路径) | `uvicorn`/`autoinfo api` 启动 + `curl :8741/health` |
| products-billing / E2 | 无 `STRIPE_API_KEY` — 计费失败关闭 | Stripe 测试密钥或 stripe-mock |
| sources-a6-keyed / A6 | 无 `FRED_API_KEY` + `FINNHUB_API_KEY` | 免费密钥(约 1h 获取) |
| output-premium-products | 需 `general-news` 域(本项目未配置) | 配置该域或接受范围 |

## AC5 — 董事抽样阅读清单(B3,人类-最终用户视角)

以下真实产物已生成至 `docs/dev/validation-reports/evidence-2026-08-12/`,请按 `market-positioning.md` 四个关注点(准确性 / 深度 / 新鲜度 / 呈现)逐项记录裁定(PASS/RISK/FAIL):

| 形态 | 产物 | 关注点 | 生成状态 |
|------|----------|---------------|----------|
| Digest(md) | `ac5-digest-weekly.md`(3.7KB) | 综合准确性;窗口新鲜度 | ✅ exit 0,含 Source Attribution |
| Report(md) | `ac5-report-standard.md`(55KB) | 深度;主题分组;呈现 | ✅ exit 0(首调解析失败→重试自愈) |
| Tutorial(md) | `ac5-tutorial-student.md`(30KB) | 清晰度;非空态(**回归校验 9684b08 修复**) | ✅ exit 0 |
| Presentation(md) | —(0 字节) | 清晰度;演讲备注质量 | ❌ LLM JSON 解析失败,见 OBS-1 |
| Column 专栏(md) | `ac5-column.md`(52KB) | 高级门控 UX(G15) | ✅ exit 0(解析告警后自愈) |

综合判定:5 件中 4 件通过、1 件观察项(非阻塞);判定清单 `AC5-verdict.md` 已备。

## AC7 — 董事裁定清单(处置已执行,待终审)

1. ~~AC2-1(B-03 残留):清理归属~~ — **已执行**:软删除 12 条 + 归档 2 个孤立文件 + 场景夹具迁移 + 泄漏扫描守卫。
2. ~~AC9-1:tests/ 重组授权~~ — **已执行**:58 个根测试文件重组入子包,全量测试通过。
3. ~~R-01:显式门控配置~~ — **已执行**:`set_gate_config` 持久化 + 回读验证。
4. ~~B-01 残余:`remove_domain` confirm 守卫~~ — **已执行**:与 `remove_source` 对齐,实跑验证。
5. AC5 抽样:B3 阅读上述 5 件产物并记录裁定(**待董事**)。
6. OBS-1(新增):presentation 重试兜底 — 是否排期修复(**待董事**)。

## 中文摘要(Director)

第二次正式验收运行完成。**首运行 7 个 FAIL blocker 全部闭环或按 2026-08-08 董事裁定改判**:回归飞轮 6/6 实跑通过(首运行仅 1/5),portal/export CLI 崩溃与 tutorial 空态修复(commit 9684b08),EPUB CJK 通过,KB 升降级语义归位。

**三项 RISK 已执行修复并验证(B2 代理执行,事实性、可复验)**:

① **B-03 残留(AC2)**:12 条模拟 URL 01-Raw 条目软删除(可恢复),孤立文件归档,场景夹具迁移保留域名 `*.autoinfo.test` 并上线 `SCENARIO_LEAK` 泄漏守卫(实跑 0 泄漏);
② **R-01(AC5)**:门控配置经 `set_gate_config` 显式持久化至 `.autoinfo/config.yaml`,回读一致;
③ **AC9-1(AC9)**:58 个根目录测试文件重组入镜像 `src/` 的子包,全量测试通过。

另:残余项 **B-01** 已补齐 `remove_domain` 确认守卫。AC5 抽样产物 5 件已生成(digest/report/tutorial/column 通过,presentation 为观察项 OBS-1:LLM JSON 解析脆弱、无重试自愈、非静默损坏)。

整体裁定由 **RISK(未达签收态) 上调至 PASS(可签收候选)**。处置权在你:① AC5 抽样逐项裁定;② OBS-1 是否排期;③ 终审签收。

---

*本运行证据:coverage 审计 `validation-runs/coverage/coverage-2026-08-12_131150.json`(A1: 145/145, 0 MISSING, 6 regression);场景实跑(A2/A24: director-backdoor 7/7、kb-promote-admission 8/8、promotion-provenance 6/6、regression 6/6);`scripts/doc_inventory.py --check` exit 0(A21);`git status` 变更清单(A20);tests/ 结构审计(A22: 重组后根残留 < 阈值,0 test_bug_*);pytest 全量收集+通过(A23);AC5 证据 `evidence-2026-08-12/`(A13)。*

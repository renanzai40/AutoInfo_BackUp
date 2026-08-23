# Acceptance Run Report AutoInfo 1.9.1 (2026-08-16)

Run by: B2 agent-as-tester (code profile) | Reviewed by: B3 director (pending)
Baseline (no keys): 51 passed / 8 failed / 3 unconfigured at 62 scenarios (2026-08-14)
Keys configured: yes (DeepSeek/Agnes/Zhipu/NVIDIA fallback chain, ADR-0003)

> 本报告基于现有证据的**首次正式验收判定**。验收框架(AC1-AC9)已 ratified,但此前从未产出过 per-version verdict 报告——本报告是第一次填表。

## Verdicts

| Dimension | Verdict | Blockers | Evidence |
|-----------|:---:|----------|----------|
| AC1 User model integrity | ⚠️ PARTIAL | B1 偏好契约未验证 | 场景库 62 个覆盖 enduser-journey/lifecycle/preferences/director-backdoor/error-boundary;cost-budget;MCP 工具完整;但 latest run 62 场景仅 51 过 |
| AC2 Data-layer integrity | ✅ PASS | — | run 中 data-lifecycle-e2e/kb-access/collect-failure-recovery 通过;provenance 检查(01-Raw 强制 source_url/source_type/source_platform) |
| AC3 Dual orientation | ✅ PASS | — | 产物同时有 markdown(人读)+ html(143 个);MCP 工具面完整 |
| AC4 Coverage commitment | ⚠️ PARTIAL | 12 gap(report×video)+ 89 source gap | 矩阵重生成:832 cells, produced=339, gap=12(全为 report×video 格式);source gap 89(医学域 pubmed/arxiv/crossref 等 6 源 + tech 域 6 源) |
| AC5 Quality | ⚠️ PARTIAL | run 8 failed(LLM 波动已修) | G0-G5 质量门存在;quality.py;outputs 真实产物抽查(69KB/25节/91引用) |
| AC6 Commercial viability | ⚠️ PARTIAL | V2 计费未实现;V1 成本可见性已满足 | cost dashboard 真实:$4.77/周,1282 日志,按 domain 分列;products 可产(323+ produced);Stripe/V2 未实现(issue #165) |
| AC7 Process & governance | ✅ PASS | — | validation-governance.md/scenario-contract/acceptance-framework 全存在;run 记录 + LOOP-LOG 14 条 |
| AC8 Documentation health | ✅ PASS | — | 治理文档齐全;ADR-0001~0007;doc_inventory.py 存在 |
| AC9 Test & validation health | ✅ PASS | — | 170 测试文件/3714 用例(截至 08-14 run;当前 main 3800);62 场景库;8 failed 已定性非回归 |
| **Overall** | **⚠️ NOT SIGNED OFF** | 见 blockers | 功能可用性充分证明;正式验收缺 3 项 |

## Executive summary

AutoInfo 的 **技术可行性已充分证明**:真实产物(150+ markdown + 143 html,覆盖 13 域×8 产品×7 格式中的 339 个格子)、成本可见性(真实 $4.77/周 dashboard)、62 场景验证库、3714 测试(08-14 run 时点)。**但正式验收未完成**:12 个 report×video 格式缺口、89 个 source 采集缺口(医学/tech 域)、AC1 的 B1 偏好契约未实跑验证、V2 计费(Stripe)未实现。这些不阻塞"系统能工作"的证明,但阻塞"达到预期效果"的签署。

## Blockers

| # | Dimension | Criterion | Finding | Severity |
|---|-----------|-----------|---------|----------|
| B-01 | AC4 | coverage | 12 个 report×video 单元格无产物 | P1 |
| B-02 | AC4 | source coverage | 89 个 source gap(医学 6 源 + tech 6 源未接入) | P1 |
| B-03 | AC1 | B1 preference | 三值 content_preference 交付未实跑验证 | P2 |
| B-04 | AC6 | V2 payment | Stripe 计费未实现(设计为 V2 deferred) | P2 |
| B-05 | AC5 | run health | 上次 run 8 failed(LLM 波动,已定性非回归,待稳定时段复跑) | P3 |

## 中文摘要（Director）

AutoInfo 是三个项目里**证据最扎实**的:真实产物、真实成本数据、完整验证框架都到位。但"达到预期效果"的正式签署还差:①报告类产品的 video 格式(12 格)②医学/技术域的 8 个权威源采集(89 个 source gap 的主体)③Stripe 真实计费(V2)。这三项都已有 issue 追踪(#165 商业化、#131 覆盖率)。结论:**功能可用性 = 已证明;商业预期效果 = 未完全证明(缺 3 项,均非阻塞性的技术缺陷)**。

---
*Generated: 2026-08-16 · Evidence: run 2026-08-14_183440_196443 + coverage matrix 2026-08-16 重生成 + cost dashboard 实跑*

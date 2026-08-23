# Demo Package 前置说明(2026-08-17)

交付合格 Demo Package 前的两个必答问题,基于历次 validation 记录取证。

## 一、旧采集为什么质量低(为什么必须重采)

三层质量问题,按链路顺序(采集 → raw → 产物),数据来源均为历次 validation 记录与已提 issue:

### 1. 采集层:非文章型内容被当文章收录(数据源污染)
- **#286(2026-08-17)**:HTTP JSON API(如 World Bank)返回纯数字值被 `_coerce_str` 直接 `str()` 后当 content 收录。财务域 enterprise-briefing 产物出现空洞条目:"United States — The article titled 'United States' contains only the numerical value 30769700000000, with no accompanying text..."
- 特征:title/summary 空、`language: unknown`。修复 = `is_article_like_content()`(≥3 连续 ASCII 字母或 CJK 才算文章),PR #287,main 未合。

### 2. raw 层:空条目未清理 + 幻觉风险(产物可信度)
- **#279(2026-08-16 端用户抽查)**:跨 5 域存在 `2026-08-09-.md` 空条目(占 raw 总量 285 条的 0.7%),08-09 某批次采集失败但条目仍入库,G0 未拦。
- 更严重:**gaming digest 的 "EA closed a $55B acquisition deal" 断言在 01-Raw 15 条中搜不到**——processed 生成时 LLM 记忆溢出 raw,混入幻觉。医学/金融域错误事实有实际危害。

### 3. 生产链路:raw → outputs 直跳,无 KB 中间层(质量放大器缺失)
- **#278(2026-08-16)**:KB 02-Draft 全为 0、03-Wiki 仅 2 域各 2 条——当前是 raw 直接进产物生成,没有"提炼 → 发布"的中间层过滤与人工可操作环节。

### 结论
旧采集的 raw 质量不足以支撑"端用户愿意付费"的 Demo Package:**数字空洞(#286)+ 空条目(#279)+ 幻觉断言(#279)+ 无 KB 提炼层(#278)**。重采必须:① 用含 #286 修复的代码;② 采集后逐条质量筛选;③ 走完整 KB 链路再生成产物。

## 二、End User Matrix 覆盖结论

### 数值现状(历次 validation 记录)
| 指标 | 2026-08-11(E8 #131) | 2026-08-16(AC4 审计) |
|------|---------------------|----------------------|
| Matrix cells | 728 required,produced=338,gap=0 | 同上(gap=0 但见下) |
| 覆盖结论 | 100% 无 required-empty gap | **数字 100%,实质失衡** |
| 各域产物分布 | medical-research 283 个产物 | 其他 11 域仅 ~36 个(mostly paygrade 单批) |
| 格式覆盖 | 13 域×8 产品×7 格式满格 | medical 独占深格式(epub 51/audio 32/json 62),其他域格式单一 |
| 场景域覆盖 | — | medical-research 362 次,8 域 0 次(#281) |

### 关键结论(must 讲清楚)
1. **matrix 数字"100% 覆盖"是真实计算,但掩盖了实质失衡**:gap=0 是因为 required 单元格都有 produced 证据——而证据高度集中于 medical-research 一个域。**覆盖数字≠产物质量**(#278/#281)。
2. **Demo Package 的三旗舰域现状**:medical-research 有深度产物 ✅;ai-commercial(43 产物/1 场景次)/financial-intelligence(37 产物/6 场景次)都是 08-10 paygrade 单批,无深度格式、场景覆盖极少。
3. **所以重采的目标域选定** = medical-research / ai-commercial / financial-intelligence,**每个 ≥50 条 fresh raw + 深度格式产物**,既覆盖"付费吸引力"也补"多格式覆盖"缺口。
4. **验收底线**(2026-08-16 端用户评估定):raw 来源强相关、processed 无幻觉/废话、数据链路可追溯可验证;宁缺毋滥,不达标宁可不放。

## 关联 issue 索引
#277(总清单)/ #278(KB 缺失)/ #279(幻觉+空条目)/ #280(格式覆盖)/ #281(域覆盖失衡)/ #286(数字空洞,已修 PR #287)/ #131(E8 matrix spec)
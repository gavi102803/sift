# Sift 产品成熟度审计

审计日期：2026-07-19
审计对象：`codex/sift-mvp` 当前工作树（包含尚未提交的归档与恢复里程碑改动）
证据范围：代码、迁移、本地 SQLite、Backend/iOS 自动化、真实 Uvicorn 进程故障注入、iOS 26.5 Simulator、Release Simulator build

## 结论

Sift 现在是一个**核心闭环完整、经过真实 Provider 故障注入的 Personal Dogfood / Internal Alpha**，同时是
一个**仓库实现层面的 Managed Closed Beta Candidate**。它已经不是原型，但还不能仅凭当前证据
邀请普通外部用户。

- 综合产品成熟度：**3.2 / 5**；
- 仓库工程成熟度：**约 4.1 / 5**；
- 外部发布成熟度：**约 2.4 / 5**。

评分上升主要来自持久化 ModelRun、DeepSeek 20 轮连续 dogfood、真实 Backend/App 进程恢复、
概念连续性、定期知识回顾和版本恢复。评分没有继续上调，是因为当前仍是单次本机证据，托管部署、真机、PostgreSQL
和 Closed Beta cohort 仍没有外部证据。

## 当前已经实现

### 核心知识闭环

- 捕获先保存为本地草稿，网络或模型失败不丢输入；
- 生成结构化概念卡，支持搜索、归档、编辑、标签、主题和概念关系；
- 围绕概念持续追问，Backend 持久化对话和回答来源；
- AI 回答与知识更新分离，revision、旧值 hash 和用户锁保护 durable note；
- 高风险更新进入可确认或放弃的 Proposal，不自动覆盖用户知识；
- Personal 本地/Tailnet 和 Managed BYOK 两种运行合同均有实现。

### 可恢复模型任务

- 首卡、追问、连续性摘要、知识回顾统一为持久化 ModelRun；
- 支持 owner 隔离、幂等键、payload hash、Provider 快照、依赖任务、checkpoint、事件序列和 lease；
- 同一概念串行，不同概念可并发；worker 退出后 lease 到期可恢复；
- App 或流消费者取消不取消 Backend 任务；iOS 持久化 run mirror 并在重启后对账；
- Provider 已完成后，领域写入与 ModelRun 成功终态处于同一数据库事务；
- 真实 Uvicorn 子进程在 `modelCompleted` 后被 SIGKILL，再启动后不重复调用模型，也不重复写
  Concept、Turn 或 Revision；
- Managed 模式缺少 Key 时进入 `waitingForCredential`，iOS 从 Keychain 临时补交，Key 不进入
  请求体或数据库。

### 长期上下文与自动回顾

- 持久化 turns 达 12 条后生成连续性摘要，之后每 6 条更新；
- 最近 6 条保留原文，更早内容由带 source turn IDs 的结构化摘要进入 card memory；
- 摘要失败或无效时回退到当前卡片、Learning State 和最近 10 条 turns；
- 自动回顾每 5 次成功 follow-up 到期，依赖最新摘要，不阻塞用户可见回答；
- 回顾禁用 Web Retrieval，只能对未锁定现有块提出 append/replace；
- 回顾结果只生成 Proposal，空结果也推进回顾水位，避免重复调用；
- 后端自动化覆盖连续 20 轮追问、早期上下文保留、逐 turn 单次写入、回顾拒绝和后续恢复。

### 卡片版本恢复

- Backend 提供版本列表、详情和恢复接口，并按 owner 隔离；
- 快照包含标题、简述及块 ID、类型、内容、顺序、来源和锁定状态；
- 恢复旧版本会创建当前 revision 的下一版，不倒退版本号；
- 恢复保留 turns、组织、来源、Learning State、归档状态和 maturity，并使 pending Proposal stale；
- iOS 概念页已有独立版本历史、预览、确认恢复和恢复后的 Backend 权威数据更新。

## 部分实现或证据不足

| 能力 | 当前判断 | 剩余缺口 |
| --- | --- | --- |
| ModelRun API 迁移 | 已完成 | 核心 iOS 与旧同步/stream 兼容接口均创建同一种持久化 ModelRun；兼容流取消后任务继续 |
| 自动回顾的即时呈现 | 已完成 | iOS 消费 `childRunIds`，观察 Summary/Review，并在当前卡片即时拉取、幂等同步 periodic Proposal |
| 版本历史 UX | 已完成 Simulator 验收 | 已覆盖加载、空状态、预览、在线确认恢复和 Backend 不可用时禁用恢复；真机仍属于发布证据 |
| Managed 凭据恢复 | Simulator 合同测试通过 | 无签名 Simulator 使用测试凭据机制，不能替代真实 iPhone Keychain/TestFlight 证据 |
| 长期上下文质量 | DeepSeek 单主题 20 轮通过 | 还没有多主题、多分支、跨数日对话的质量评测和人工评分 |
| 真实 Provider | DeepSeek live 首卡、20 轮追问和故障恢复通过 | 仍没有按周稳定性、成本趋势和多用户数据 |
| PostgreSQL/托管部署 | 代码、驱动、迁移合同和 runbook 存在 | 当前验收仍以 SQLite 为主；没有目标 PostgreSQL migration、restore drill、真实域名/TLS |
| 产品验证 | 已有隐私安全的本地基线 | 已覆盖捕获成功、每卡追问、7 日后追问、恢复和 Proposal 决策；仍没有多用户 cohort、成本和真实留存趋势 |

## 当前数据与验证证据

本地隐私安全指标当前记录 39 Concepts、12 次终态捕获（11 次成功）和 30 次 follow-up；
57 个 ModelRun 中 52 个成功、5 个安全失败，终态成功率 91.23%，延迟 p50 15.5 秒、p95 41.6 秒。
一次运行存在多个 `started` 事件，正是 Backend kill/restart 后 lease 恢复的证据；过期 active lease、
重复终态事件和成功但无结果均为 0。当前仍无 7 日后复用和版本恢复使用记录，定期 Proposal 有 1 个
待决定，因此这批数据证明可靠性闭环，不足以证明长期留存。

live dogfood 还暴露了维护任务过度调度：旧实现用全局 Turn ID 相减判断“新增 6 条”，并在已有
Proposal 时创建无效的延迟 Review。现已改为按本概念新增 Turn 计数，Proposal 或 Review 活跃时只置
`reviewDue`；精确回归锁定 20 次追问对应 6 次摘要和最多 4 次无阻塞回顾。

本次门禁：

- Backend Ruff 通过；pytest **213 passed / 1 skipped**；
- 真实 Backend SIGKILL/restart 测试 **1 passed**；
- DeepSeek live runner 完成 **20 / 20** 次成功追问、**42 / 42** 条唯一 turns，早期连续性标记、
  幂等重放、维护任务和终态事件全部通过；Backend 中断期间经历 12 次连接失败后恢复；
- live 过程中 1 次结构化 JSON 失败和 1 次上游错误均安全终止，使用新幂等键重试后成功，无重复 Turn；
- iOS Simulator 在提交额外 DeepSeek follow-up 后立即 terminate，Backend 独立完成；重开后问题和
  包含 `SIM-LIVE-RELAUNCH-0719` 的答案各出现一次，数据库最终为 **44** 条唯一 turns；
- iOS Simulator 全量 **82 passed / 0 failed**，其中 8 条 UI 旅程；
- 首卡和追问恢复旅程均真实调用 `XCUIApplication.terminate()`；重开后断言只有一个问题、一个
  最终回答、一次 ModelRun 提交，且不会显示普通取消或发送失败提示；
- Release 配置 iPhone 17 Pro Simulator **BUILD SUCCEEDED**；
- 本地 Backend 已用最新代码重启，doctor 确认服务、SQLite、迁移 `20260719_0016` 和 DeepSeek
  配置均正常。

## 还没有实现

- 多设备同步与完整冲突解决；
- 数据导出、账户删除、隐私材料和用户自助支持；
- 真实托管域名、生产 PostgreSQL、edge rate limit、告警和事故演练；
- TestFlight/真实 iPhone 的签名安装、Keychain、语音和前后台验证；
- 可视化的产品价值仪表盘；命令行聚合报告已覆盖可靠性和产品复用，但尚无真实新 ModelRun 样本；
- App Intents、Spotlight、分享、协作和正式复习系统；
- 面向外部用户的 onboarding cohort、留存和付费验证。

## 下一步方向

### P0：恢复里程碑已关闭

DeepSeek 20 轮、Backend kill/restart、连接中断、幂等重放和真实 Simulator App terminate/relaunch
均已完成。该里程碑不再缺工程或单次 live 验收项；后续把可靠性作为持续门禁，而不是继续扩展恢复架构。

### P1：建立可决定产品方向的 dogfood 证据

聚合报告已能输出 ModelRun 可靠性、捕获成功率、每卡 follow-up、7 日后追问、版本恢复、定期
Proposal 决策率和接受率，且测试证明不输出知识内容、密钥、owner ID 或原始错误。下一步不再补
埋点字段，而是每周保存基线并观察这些指标是否随真实使用改善。
先由 3–5 名设计伙伴连续使用两周，再判断长期上下文和自动回顾是否真的提高回访与知识质量。

### P2：满足后再进入 Closed Beta

完成真实托管域名/TLS、PostgreSQL migration + restore drill、日志脱敏审计、签名 TestFlight 真机
流程、隐私/删除/导出合同和 7 天无丢失运行。此前不扩 Provider、知识图谱、协作或复杂复习系统。

## 产品判断

Sift 当前最有价值的差异点已经从“AI 生成卡片”变成：**输入不会丢、对话能延续、知识更新可拒绝、
任何错误更新可恢复**。下一阶段的关键不是继续增加能力，而是证明这套可靠知识闭环在真实连续使用中
确实让用户回来，并让卡片比单次聊天更有价值。

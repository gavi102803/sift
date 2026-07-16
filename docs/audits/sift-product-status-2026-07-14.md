# Sift 产品现状审计报告

审计日期：2026-07-14

审计对象：`codex/sift-mvp`（提交 `8700404`）

审计范围：产品定位、功能完成度、iOS、后端、AI Runtime、数据、安全、测试、CI/CD、发布能力与未来方向
结论置信度：代码与本地自动化部分为高；真实设备、真实 Provider、线上运行和用户价值部分为中低，因为当前没有对应的持续运行证据

## 1. 执行摘要

Sift 已经是一个**可运行的个人 Dogfood / Internal Alpha**，不是概念原型，也还不是可邀请外部用户的 Closed Beta。

当前最有价值的成果不是“接了很多模型”，而是核心产品闭环已经成形：用户先保存概念，再异步生成卡片；之后围绕同一概念持续提问；AI 回答与知识沉淀分离；更新受 revision、hash 和用户锁保护；失败时原始输入可恢复。这套产品语义有辨识度，也得到了代码和测试支撑。

综合成熟度建议评为 **2.7 / 5**：

- 个人 MVP 功能完成度约 **80%**；
- Managed BYOK Closed Beta 完成度约 **45%**；
- 面向公开用户的 V1 完成度低于 **30%**。

以上是基于代码和发布门禁的工程估算，不是用户调研或市场验证结果。产品目前最大的短板已经从“能否做出核心闭环”转变为三件事：

1. **发布边界不成立**：没有生产认证、激活、托管端点和完整 owner 隔离入口，真实用户密钥方案也未按 Beta 合同落地。
2. **工程基线不稳定**：CI 的后端测试工作目录与迁移测试冲突；当前开发分支和 `main` 没有共同祖先；大文件正在形成架构瓶颈。
3. **没有产品验证系统**：缺少 onboarding 漏斗、核心行为、留存、失败率和成本指标，无法判断“用户是否真的把概念变成了长期知识”。

因此，下一阶段不建议继续横向扩 Provider 或增加知识图谱、协作等功能。应先把“个人可用”升级为“可安全邀请 20–50 名用户、可观测、可回滚的 Closed Beta”。

### 1.1 2026-07-15 Phase A/B 实施复审

本报告上述内容保留为 7 月 14 日审计快照。7 月 15 日已经完成 Phase A/B 的仓库内实现：

- 根目录统一 `scripts/check.sh`，CI 与本地共用同一 backend/iOS 门禁；migration 路径不再依赖工作目录；Python 3.12 依赖已锁定；
- Managed activation、30 天 token、7 天刷新窗口、token/owner revoke、installation binding 和服务端 token-derived owner 已落地；
- 跨 owner concept/proposal 访问返回 404，幂等记录按 owner 隔离；
- iOS 使用 Keychain 保存 installation、beta token 和 Provider key；Key 只在 provider-test/runtime 请求头中临时中继；
- Managed 模式禁止旧的服务端 Provider credential 设置入口，错误统一为稳定 code/message/requestId，敏感上游错误不回显；
- Release 使用固定 HTTPS Info.plist endpoint，隐藏 Personal 后端设置；缺少 endpoint 时安全失败而非退回 localhost；
- PostgreSQL psycopg 驱动、Alembic CI smoke、生产配置校验、backup/restore 脚本和运维 runbook 已加入；
- Simulator 覆盖 activation、请求头边界、临期刷新和 key 不进入请求体；后端覆盖激活、撤销、owner 隔离、key 不落数据库和安全错误。

复审本地证据为：锁定依赖的全新 Python 3.12 环境中 Ruff 通过、Backend `177 passed / 1
PostgreSQL-only skipped`；iPhone 17 Pro Simulator 全量 `62 unit + 1 UI passed`；新增的 UI
旅程覆盖全新状态、激活、Provider 连接、捕获和首张流式概念卡；Release Simulator build
通过，并从构建产物确认 `SIFTBackendBaseURL=https://beta.sift.example`。UI 测试因无签名
Simulator build 无法可靠访问系统 Keychain，使用仅 DEBUG 可用的内存凭据，因此真机 Keychain
仍属于外部发布证据。真实 PostgreSQL smoke
已进入 CI service，但本机没有 PostgreSQL，因此不能把线上迁移证据冒充为本地已验证。

因此代码成熟度从“仅 Personal Dogfood”进入 **Managed Closed Beta Candidate**，但产品发布成熟度仍按
**Internal Alpha** 管理。以下外部证据尚不能由仓库实现替代：真实生产域名/TLS 与托管环境、目标
PostgreSQL migration + restore drill、远端默认分支对齐、真实 iPhone/TestFlight、真实 Provider 连续一周
dogfood，以及 20–50 人 cohort 数据。完成这些证据前，不把 Phase B 的“可发版退出标准”标记为完成。
逐项状态与复现命令见 `docs/release/phase-a-b-acceptance.md`。

仓库所有者已于 7 月 15 日确认 `codex/sift-mvp` 为唯一产品与发布真源；这个决策已写入
`docs/release/phase-a-baseline.md`。尚未执行的是保留旧 `main` 备份引用并对齐远端默认分支，
这属于外部 Git 操作，不再是产品真源选择阻塞。

## 2. 审计方法与可复现证据

本次审计阅读了根目录说明、MVP 设计与决策、发布 checklist、Phase 0/1 合同、架构记录，以及 iOS、FastAPI、SQLAlchemy、AI Runtime 和测试代码。

本地验证结果：

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| Backend Ruff | 通过 | `./.venv/bin/python -m ruff check src tests` |
| Backend pytest（仓库根目录） | 160/160 通过 | `backend/.venv/bin/python -m pytest backend` |
| Backend pytest（CI 当前工作目录） | 159/160，通过率 99.4% | 迁移测试把 `backend/alembic` 再拼成了 `backend/backend/alembic` |
| iOS build + unit tests | 通过 | iPhone 17 Pro、iOS 26.5 Simulator，`xcodebuild test` 成功 |
| 本地数据 | 33 concepts、46 turns、58 revisions、58 events、7 proposals | 说明存在真实个人使用/手测数据，但不代表外部用户验证 |
| Local doctor | SQLite 可写；Provider 不合格 | 当前为 mock，DeepSeek key 缺失，尚无真实 Provider 持续运行证明 |
| Git 基线 | 高风险 | 当前分支与本地 `main` 无共同祖先，无法形成正常 merge-base |

限制：本次没有执行 App Store/TestFlight 发布、真实 iPhone 全流程、真实 Provider live conformance、PostgreSQL、生产 TLS/域名、故障注入、性能压测、无障碍人工检查或用户访谈。因此报告不会把这些项目视为已完成。

## 3. 产品判断

### 3.1 产品定位

Sift 的定位清晰：它不是通用聊天客户端，也不是重型 PKM，而是“把稍纵即逝的概念逐步沉淀成可持续生长的知识卡片”。真正的差异点有三个：

- **先保存、后生成**：AI 失败不能让用户输入消失；
- **回答与沉淀分离**：即时回答解决当前问题，知识更新只保留耐久内容；
- **概念级长期上下文**：每张卡有自己的逻辑对话与修订历史。

这个方向比“多模型聊天 + 笔记”更聚焦，也更容易形成独立产品价值。风险在于当前 Profile 和 Runtime 的 Provider 丰富度已经超过了用户价值验证深度，团队容易被供应商适配牵着走，弱化核心学习闭环。

### 3.2 当前用户与场景

代码和文档能够支持的当前用户是：愿意在 Mac 上运行本地 Backend，并通过 Simulator 或 Tailscale 使用 iPhone 的产品所有者/技术型 Dogfood 用户。

尚不能支持的用户是：从 TestFlight 安装后无需理解 Backend、域名、Tailscale 或密钥存储，就能完成激活和首次概念捕获的普通 Beta 用户。

当前已覆盖的核心场景：

- 快速输入或语音捕获概念；
- 本地保存草稿并在失败后重试；
- 流式生成初始卡片和 follow-up；
- 浏览、搜索和本地分类概念；
- 编辑标题、说明、标签、主题、笔记块和关系；
- 低风险自动合并、高风险 proposal 确认/跳过；
- 显示回答来源与 citation；
- Debug/Personal 模式连接本地或 Tailnet Backend。

### 3.3 产品验证缺口

设计文档给出了“约 10 秒捕获”等成功标准，但代码库没有稳定的产品指标采集和分析闭环。当前无法回答：

- 新用户是否能独立完成第一次激活、连接 Provider 和生成卡片；
- 首张卡是否真的有用，还是用户只测试一次；
- 用户是否会在数天后回到同一概念继续提问；
- 笔记是否变得更精炼，还是只积累了对话；
- proposal 接受率、自动合并纠错率和来源点击率是多少；
- 哪个环节导致流失：连接 Backend、Provider key、延迟、答案质量还是信息架构。

没有这些数据，新增 spaced repetition、Spotlight 或知识图谱都属于未经验证的扩张。

### 3.4 用户、商业与市场成熟度

从现有产品形态推断，最合适的首批用户不是所有“记笔记的人”，而是会频繁遇到陌生概念、已经使用 AI 问答、又对知识长期沉淀不满意的知识工作者，例如研究、产品、工程、咨询和高强度阅读人群。这是待验证的目标用户假设，不是仓库中已有的市场证据。

当前竞争壁垒也应围绕工作流而不是模型建立：任何聊天产品都能解释一个词，但 Sift 的价值是把捕获可靠性、概念级上下文、受控沉淀、来源和用户锁组合成长期知识资产。Provider 数量本身不形成稳定壁垒。

Managed BYOK 能降低推理成本和平台资金风险，但会显著增加激活摩擦、信任成本和客服复杂度。Closed Beta 必须单独测量“因为 API key 放弃激活”的比例；如果这一比例过高，未来需要在托管额度、订阅内含推理和继续 BYOK 之间做商业实验，不能只从工程成本决定。

仓库目前没有定价、付费意愿、获客渠道、竞品访谈或市场规模证据。建议商业节奏为：先用邀请制免费 Beta 验证 4–8 周留存和耐久学习动作，再进行价格访谈与付费承诺测试；在留存尚未成立时，不应过早优化订阅页或成本毛利模型。

Go-to-market 就绪度仍低：缺少可公开安装路径、onboarding、隐私材料、支持流程、反馈入口和演示数据。现阶段最适合的获客方式是高接触邀请制设计伙伴，而不是公开投放。

## 4. 功能进展

| 能力 | 状态 | 证据与判断 |
| --- | --- | --- |
| 本地优先捕获 | 已实现 | SwiftData 草稿、失败/重试、重启恢复均有测试 |
| 初始概念卡 | 已实现 | 同时支持 mock 和真实 Runtime 路径，含流式初始答案 |
| 概念级持续对话 | 已实现 | Backend 持久化 turn，iOS 支持流式增量与终态替换 |
| 安全知识更新 | 已实现（MVP） | revision/hash/locked block、proposal、audit event 有后端测试 |
| Library 与搜索 | 已实现（MVP） | 标题、解释、alias、tag、topic 搜索；设备本地 category 有所有权隔离 |
| 手工编辑与关系 | 已实现 | 标题、说明、块、tag/topic、relation 生命周期具备实现与测试 |
| 来源与 Web 检索 | 部分完成 | 检索决策、来源 ID 校验、SSRF 防护较完整；真实 Provider 证据不足 |
| 多 Provider Runtime | 部分完成 | 多种协议 driver 和 conformance 测试已存在；部分 Provider 仍标记 partial/planned |
| Voice capture | 已实现但未完成发布验证 | Speech framework 已接入；真实设备行为尚未验证 |
| 个人 Tailnet Dogfood | 已实现 | Debug endpoint 配置与合同测试通过 |
| Managed Closed Beta | 仓库实现完成、外部证据待补 | 激活、token、固定托管端点、临时 BYOK relay 和 onboarding 已实现；托管部署/TestFlight/一周 dogfood 未完成 |
| 多用户认证与隔离 | Closed Beta Candidate | token-derived owner、跨 owner 404、撤销与 owner-scoped idempotency 有自动化证据 |
| 多设备同步 | 未实现 | 当前是本地 SwiftData mirror + Backend authority |
| App Intents / Spotlight | 未实现 | 设计为 V1.1/V1.2 候选 |
| 分享、协作、复习系统 | 未实现 | 正确地保持在当前 MVP 范围外 |

## 5. 技术架构审计

### 5.1 总体架构

当前结构是 SwiftUI/SwiftData iOS 客户端、FastAPI/SQLAlchemy Backend、SQLite 本地数据，以及自研的 Hermes-informed 模型 Runtime。Backend 持有 AI 调用、结构化输出、检索、patch、proposal、revision 和 provenance；iOS 保留本地草稿和离线可见 mirror。

总体职责划分方向正确。尤其值得保留的是：iOS 不直接依赖上游模型协议；Runtime 结果必须经过 Sift 领域规则；检索证据和 system policy 分离；远程内容有 SSRF/重定向/类型/大小检查。

### 5.2 iOS / FSD 评估

现有目录已经按 `Record`、`Library`、`ConceptDetail`、`Profile` 做了粗粒度 feature 分区，但还不是严格 FSD：

- `ConceptDetailView.swift` 同时承担页面渲染、流式对话、同步、本地持久化、proposal、编辑和 relation 操作；
- `ConceptLibraryView.swift` 同时持有查询、分类规则、筛选和远程刷新；
- `ProfileSettingsViews.swift` 达 923 行，多个 Provider 配置流程共处一个文件；
- View 直接依赖 `AppServices`、SwiftData 和 API client，页面层包含较多用例编排。

这会让功能间边界继续模糊，也使单元测试越来越依赖大对象。根目录新增的 `AGENTS.md` 已规定渐进式 FSD：`App -> Pages -> Widgets -> Features -> Entities -> Shared` 单向依赖，并明确现有目录不做大爆炸搬迁。下一次修改某个大页面时，应先提取与该需求直接相关的 feature state/use case，而不是单纯拆成更多 View 文件。

### 5.3 Backend / DDD 评估

Backend 已经有 `concepts`、`runtime`、`persistence`、`auth`、`notes` 等领域词汇，但分层边界仍是技术目录为主：

- `ConceptService` 1736 行，同时包含 in-memory store、mock model service、应用用例、领域判断和 HTTP 异常；
- `PersistentConceptStore` 反向导入 `concepts.service` 的 DTO，并直接使用 FastAPI `HTTPException`；
- API 层负责 Runtime、Web Provider、Database 和 Service 的完整装配；
- Pydantic transport DTO 被用作持久化和应用层事实模型；
- `main.py` 609 行，既是 composition root，又包含 provider settings、model discovery 和 diagnostics。

这不是功能错误，但会阻碍身份/租户、托管 BYOK 和事务一致性扩展。新增的 `AGENTS.md` 将目标边界定义为 `concepts`、`knowledge_mutation`、`model_runtime`、`identity_access` 四个 bounded context，以及 `domain/application/infrastructure/interfaces` 向内依赖。迁移应从下一项真实需求切入，先写 characterization test，再抽一个 use case 或 invariant；不建议先建大量空目录。

### 5.4 数据与一致性

优点：

- 10 个 Alembic revision，包含 owner、idempotency 和初始回答演进；
- note mutation 同步创建 revision 与 event；
- capture、turn、proposal merge 有幂等保护和 payload hash 冲突判断；
- 设备本地 Library category 与 Backend-managed topic 有明确、经过测试的 ownership contract；
- 现有本地库中 revision 与 event 数量相同（58/58），与审计不变量一致。

风险：

- 当前主要运行和测试仍是 SQLite；虽然依赖含 asyncpg、文档选择 PostgreSQL，但没有 PostgreSQL CI 或生产迁移证据；
- iOS mirror 与 Backend authority 的冲突策略只覆盖当前流程，没有通用同步、删除和多设备模型；
- 缺少对真实数据 schema migration、备份恢复、数据导出/删除的发布演练。

### 5.5 AI Runtime 与来源可信度

Runtime 是当前工程中完成度较高、也最容易过度投入的部分。已有 Chat Completions、Responses、Anthropic Messages、Gemini 等 driver，capability policy/probe、缓存键、结构化输出 fallback、search/extract 分层、source ID 白名单和 outbound safety。

主要问题不是代码能力不足，而是产品暴露与验证失衡：Provider 数量和协议复杂度增长很快，但当前本机仍回退 mock，live conformance 只证明框架存在，不能证明每个已暴露 Provider 在用户路径上稳定。建议建立明确的 Stable/Preview/Hidden catalog 门禁，每个 Stable Provider 必须有按周 live conformance、失败告警、密钥路径验证和真实 capture/follow-up 证据。

## 6. 工程质量与交付能力

### 6.1 做得好的部分

- Backend 有 160 个测试，覆盖 API、migration、patch、persistence、runtime、provider、retrieval 和 outbound safety；
- iOS 单元测试覆盖最关键的数据丢失、幂等、分类所有权和产品逻辑；
- Ruff 和 GitHub Actions 已配置；
- release checklist、dogfood contract、Managed Beta contract 和架构 ADR 较完整；
- 失败状态不是静默 mock，用户输入恢复语义较诚实。

### 6.2 7 月 14 日发现与 7 月 15 日处置状态

1. **CI 工作目录问题已修复**：本地与 CI 统一调用 `scripts/check.sh`，migration 路径不再依赖当前目录；GitHub 托管运行结果仍需分支推送后取证。
2. **Git 真源已确认、远端尚未对齐**：`codex/sift-mvp` 已被仓库所有者确认为发布真源；它与旧 `main` 无 merge-base。下一步需先保留旧 `main` 备份引用，再将远端默认分支对齐到已确认历史。
3. **大文件与多职责**：Backend 1736/997/912 行级文件和 iOS 923/815/721 行级文件已经提高修改风险。
4. **关键 UI/E2E 已补齐**：`SiftUITests` 覆盖 Managed 激活到首张概念卡；真机签名包、Keychain 和真实 Provider 仍需 TestFlight 验证。
5. **文档漂移**：初始设计写“一种系统默认模型、iOS 不存储或传输上游 key”，现状却有前台 Provider picker，且 iOS 把 key 发给本地 Backend，Backend 再存入 Mac Keychain/测试文件 store。Phase 0 可以接受，但产品设计、Personal 和 Managed 三种模式必须明确分版，不应混为统一现状。
6. **依赖已锁定**：Python 3.12 lockfile 和 clean install 已验证；Starlette/httpx 与状态码弃用警告仍是非阻塞维护项。
7. **缺少运行观测**：有模型 latency/token 元数据，但没有产品漏斗、crash、SLO、告警或隐私审查后的 telemetry 落地证据。

## 7. 安全、隐私与发布阻塞项

当前安全设计对“个人 Mac + Tailnet”是合理起点，但不能直接外推到公网 Beta。

### 7.1 7 月 14 日原始 P0

- 没有生产 authentication、invite activation、refresh/revocation；所有请求使用 development principal；
- `owner_id` 已进入数据层，但 owner 不是从受信 token 导出，无法证明租户隔离；
- Managed Beta 合同要求 iOS Keychain + per-request ephemeral BYOK relay + Backend 不落盘，当前实际是本地 Backend credential store，语义不同；
- 没有固定生产 HTTPS endpoint、托管部署、生产 secret/KMS、rate limit、quota、防滥用与请求审计；
- 没有跨 owner 404、日志/异常/trace 全链路脱敏和 key 不落盘的 Beta gate 测试；
- 没有隐私政策、数据删除/导出、备份恢复、事故响应和发布回滚证据。

这些并不否定 Phase 0 Dogfood，只说明 Phase 0 与 Managed Beta 必须保持独立 build/contract，不能通过隐藏 Debug UI 就视为完成生产化。

### 7.2 7 月 15 日复审

认证、invite/refresh/revoke、token-derived owner、跨 owner 404、Managed BYOK 非持久化、固定
Release HTTPS endpoint、稳定错误 envelope、PostgreSQL 合同与运维脚本均已进入仓库并有对应
自动化或配置检查。因此上述 P0 中的“代码缺失”已转化为“生产证据缺失”。仍阻塞发布的是：

- 真实托管域名、TLS、edge rate limit 与日志策略尚未部署取证；
- 目标 PostgreSQL 未执行 migration 与 restore drill；
- 无签名 Simulator 不能证明真实 iPhone Keychain，尚无 TestFlight 新装/重启证据；
- 尚未完成真实 Provider 全链路 secret/trace 审查和连续一周无数据丢失 dogfood；
- 隐私政策、用户数据删除/导出与外部支持流程仍未形成发布证据。

## 8. 成熟度评分

下表是 7 月 14 日审计快照。7 月 15 日实现提升了安全、交付和 onboarding 的代码成熟度，
但没有替代真实部署、真机、连续使用和用户数据，因此总产品成熟度仍保持 **2.7 / 5 Internal
Alpha**；单独看仓库实现，可评为约 **3.6 / 5 Managed Closed Beta Candidate**。只有完成
`docs/release/phase-a-b-acceptance.md` 的外部证据后，才建议上调产品发布等级。

| 维度 | 评分（5 分制） | 结论 |
| --- | ---: | --- |
| 产品定位与范围 | 4.0 | 问题、核心承诺和非目标清晰 |
| 核心功能 | 4.0 | 主要学习闭环已实现，接近个人 MVP |
| UX 与可达性 | 3.0 | 核心页面完整；真实设备、onboarding、无障碍和 UI 自动化不足 |
| 数据可靠性 | 3.5 | 本地优先、幂等、revision/audit 很强；多设备/备份/冲突仍缺 |
| 架构可维护性 | 2.5 | 边界方向正确，但大服务、DTO 穿层和页面多职责明显 |
| 安全与隐私 | 2.0 | 个人模式可用；公网多租户和 Managed BYOK 未落地 |
| 测试与交付 | 2.5 | 单元测试丰富；CI 路径错误、无 UI E2E、Git 主线断裂 |
| 产品验证与商业成熟度 | 1.5 | 没有外部 cohort、留存、价值指标、定价或渠道证据 |
| 综合 | **2.7** | **Internal Alpha / Personal Dogfood** |

## 9. 风险优先级

### P0：进入 Closed Beta 前必须解决

1. 选定并修复唯一 Git 主线，恢复可 merge、可 review、可 tag 的发布历史。
2. 修复 CI 工作目录契约，并让 branch protection 只接受真实全绿的 backend + iOS gate。
3. 实现 Managed Beta auth/activation/token lifecycle，所有 owner 从 token 服务端导出。
4. 落地 ephemeral BYOK relay、iOS Keychain、全链路脱敏和“不落盘”测试。
5. 建立固定 HTTPS Backend、PostgreSQL、migration/backup/restore、secret management 和回滚流程。
6. 完成真实设备、真实 Provider、Release build 与跨 owner 安全测试。

### P1：Closed Beta 质量门槛

1. 建立 onboarding、capture、generation、follow-up、revisit、proposal 和 failure 指标。
2. 增加 SiftUITests 核心 happy path、断网恢复、token 失效和 Provider key 错误流程。
3. 按 FSD/DDD 渐进拆分最常改的大文件；先抽 use case 和 domain invariant，不追求目录表演。
4. 建立 Stable Provider 清单和 weekly live conformance 告警；隐藏未通过门禁的 Provider。
5. 完成 Dynamic Type、VoiceOver、真实设备语音、后台/前台切换和长列表性能验证。
6. 对齐设计、README、release checklist 与真实 Personal/Managed build 行为。

### P2：验证核心价值后再投入

- App Intent 快速捕获；
- Spotlight 搜索和 deep link；
- 可见版本历史与恢复；
- 轻量复习/回访提示；
- 导出与数据可携带性；
- 更强的概念关系推荐。

知识图谱可视化、协作、社区和自动多模型路由应继续延后，除非真实用户数据证明它们解决当前留存瓶颈。

## 10. 建议路线图

### Phase A：恢复可信基线（1 周）

目标：任何提交都能被复现、审查和回滚。

- 决定 `main` 与当前分支的历史处置方案；建立 clean release branch；
- 修 CI migration path，锁定 Python 依赖或引入可复现 lock；
- 给当前 Personal MVP 打内部 tag，记录 schema 和手工 QA 基线；
- 明确 Personal、Managed Beta 两个 build contract；
- 创建最小技术债 backlog：只收录影响 Beta 的边界问题。

退出标准：PR backend/iOS 全绿；发布分支有 merge-base；根目录一条命令可重现全部门禁。

### Phase B：Managed Closed Beta 基础（2–4 周）

目标：20–50 名用户可以无需理解基础设施而安全使用。

- activation、token refresh/revoke、owner isolation；
- iOS Keychain 和 ephemeral BYOK relay；
- fixed HTTPS endpoint、PostgreSQL、secret management；
- Provider catalog/test 与稳定错误码；
- Release build 隐藏 Personal Backend 设置；
- 安全测试、备份恢复与最小运维 runbook。

退出标准：跨 owner 访问全为 404；key 不落数据库/日志/trace；干净安装能完成激活到首卡；真实设备连续使用一周无数据丢失。

### Phase C：可观测 Beta（2–3 周）

目标：知道产品在哪里创造价值、在哪里失败。

- 隐私审查后的产品事件与 SLO；
- crash/error reporting、provider latency/failure dashboard；
- UI E2E 与 Release smoke；
- 前 20–50 人访谈和 cohort review；
- 针对最高频失败点优化 onboarding 和恢复体验。

退出标准：每周能回答激活率、首卡成功率、7 日回访率、数据丢失、生成失败和 proposal 质量。

### Phase D：深化学习闭环（基于证据）

优先增强“把概念变成长期理解”的差异点：

- 更好的渐进式卡片与沉淀质量；
- 回访时的上下文恢复和“自上次以来有什么变化”；
- 轻量复习提示，而不是先做完整 spaced repetition；
- App Intent/Spotlight 降低捕获和回访摩擦；
- 版本恢复和数据导出增强信任。

## 11. 建议指标体系

建议的 North Star 是：**每周完成耐久学习动作的活跃用户数**。耐久学习动作定义为：创建成功卡片后，又发生至少一次跨会话 follow-up、有效编辑、proposal 接受或隔日回访。它比消息数更接近产品价值，也不会鼓励把 Sift 做成聊天工具。

核心指标：

| 类别 | 指标 | Beta 建议目标 |
| --- | --- | --- |
| 激活 | 安装到首张 ready card 转化率 | > 70% |
| 速度 | capture 本地落盘 p95 | < 500 ms |
| 速度 | 用户完成一次 capture 的中位时间 | < 10 秒 |
| 可靠性 | 已提交输入永久丢失 | 0 |
| 可靠性 | 真实 Provider 首卡完成率 | > 95%（排除用户 key/quota 错误后） |
| 稳定性 | crash-free sessions | > 99.5% |
| 价值 | ready card 后 7 天内再次打开同概念 | Beta cohort > 25%，随后按数据校准 |
| 价值 | 首周至少一次 follow-up 的用户占比 | > 30% |
| 沉淀质量 | proposal 接受率与接受后撤销/重改率 | 同时观察，不能只优化接受率 |
| 信任 | 来源展开/点击、答案纠错、锁定块比例 | 建立基线，不预设虚假目标 |
| 运维 | Provider failure、p95 latency、token/cost | 按 Provider 和 model 分层 |

事件必须避免记录概念正文、问题全文、API key 或可反推出私密学习内容的数据。优先记录状态转换、耗时、错误码和匿名 cohort。

## 12. 最终建议

Sift 值得继续推进，原因不是功能多，而是它已经实现了一个有产品含义的可靠闭环：**捕获不丢、回答可追溯、知识更新受控、概念能长期生长**。这比多数“AI + 笔记”原型更接近可持续产品。

现在最重要的方向是收敛：

- 产品上，守住“耐久理解”而不是扩成通用 AI 客户端；
- 技术上，用 FSD/DDD 控制下一阶段复杂度，但采用按需求渐进拆分；
- 发布上，把认证、BYOK、Owner 隔离、CI、Git 主线和可观测性视为功能，而不是上线前杂务；
- 决策上，先用 20–50 人 Closed Beta 验证回访和沉淀，再决定复习、Spotlight、关系图谱等方向。

完成 P0 后，Sift 才应从 “Personal Dogfood” 改称 “Managed Closed Beta”；在获得真实 4–8 周 cohort 的回访与耐久学习证据前，不建议称为达到 Product-Market Fit 或 Public V1。

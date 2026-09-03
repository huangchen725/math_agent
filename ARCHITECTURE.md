# 数学推理智能体架构

> 状态：当前生效  
> 更新日期：2026-09-04
> 本文件是仓库唯一的架构事实源。`docs/ENGINEERING_SPECIFICATION.md` 规定 P1～S6 的工程变更、硬规则和故障回归门禁，`docs/COMPETITION_COMPLIANCE.md` 记录赛事控制，`docs/OFFICIAL_MATERIALS_REGISTER.md` 记录官方来源、冲突和未定义契约；后三者都不是第二份架构文档。README、比赛报告和审计文档仅提供使用说明、实验记录或改进路线；内容冲突时先按官方证据层级失败关闭，再核对本文件和当前代码。

## 1. 目标与边界

系统面向竞赛数学题，在调用方注入的 Intern 兼容模型客户端上完成领域路由、三个纯文本候选生成、逐候选模型验证、多数票选择、截断恢复和最终答案规范化。当前正式路径是为排查连续 `0 request / 112 error` 而建立的保守兼容内核；工具候选、确定性证据优先、critic/reflection 和题型路由对选择的影响均暂停，不构成第二条运行分支。

当前仓库只有一套可运行实现。为回到最后一次得到有效官方请求的部署形态，运行模块全部放在仓库根目录，但仍按生命周期、显式上下文、网关、候选阶段、输出和工具子系统保持代码分层；扁平部署不等于恢复单文件巨型 Agent。`user_agent.py` 只是竞赛兼容门面，它按自身 `__file__` 把同级目录置于导入路径首位，再从唯一的 `agent.py` 重导出 `ReasoningAgent` 和 `AgentConfig`，不保留第二份实现。

2026-08-30 的 S1 曾把同一运行时迁入 `math_agent/` 包；从该结构进入被评测提交后，四次正式日志均为 `112 error / 0 request / 0 token`，而此前最后一次有效官方运行使用根目录扁平模块。该相关性尚不能证明正式 judge 丢弃子目录：公开材料没有给出 worker 的精确复制、`sys.path` 和加载流程，最新日志反而显示平台先克隆完整仓库。因此 2026-09-04 的回迁是一个有历史成功锚点的单变量兼容措施，状态仍为“离线验证通过、官方待验证”。多智能体、共享黑板和自适应候选升级仍属于未来设想，不是当前能力。

## 2. 外部契约

```python
agent = ReasoningAgent(client=official_client)
agent.solve(problem, metadata)
# -> {"final_response": str, "trace": list[dict]}
```

- 构造器至少兼容 `__init__(self, client, *args, **kwargs)`。额外平台参数是不透明兼容输入；只有运行时确为项目 `AgentConfig` 的位置值或 `config=` 值才会被采用，伪装成 `config` 的字典/字符串及其它值均忽略，不参与求解、能力探测或权限判断。
- `problem` 是题目字符串，必须非空且默认不超过 20000 字符。
- `metadata` 为竞赛兼容字典，必须可序列化为 JSON 且默认不超过 20000 字符；批处理入口会传入 `idx`，当前核心流水线不依赖其内容。
- `client` 由调用方注入，未知实现只需提供 `chat(messages, temperature, max_tokens)`；Agent 不读取注入对象的私有字段/扩展方法，也不向其发送 `thinking_mode/tools/tool_choice`。项目自有 `InternChatClient` 通过名义类型边界保留扩展参数与原子 metadata。
- `final_response` 是非空字符串；除明确的 `未解出` 失败哨兵外，保留获胜候选推理，并以唯一一行 `最终答案：...` 结尾。该行只含规范化答案体，不含解释性句子；常见 Unicode/LaTeX 表示转换为稳定记号，已有精确形式时优先保留精确形式。
- `trace` 是公开的元数据事件列表，只允许步骤、状态、候选/请求编号、响应长度、截断状态和预算统计。`trace_sanitizer` 在返回边界删除题面、prompt、模型/候选/verifier/critic/tool 正文、最终答案和异常消息；未知事件或字段失败关闭。截断事件只记录阶段、候选编号、token、是否已有首行答案和处理状态。
- `ReasoningAgent.solve()` 的最外层契约保护覆盖输入预检、预算创建、网关/上下文构造、流水线、截断收尾、trace 投影和返回规范化；已有上下文时才尝试低成本模型回退。任一普通异常都不得逃出公开入口，最外层保护本身不额外请求模型或绕过预算。`main.py` 将空答案和 `未解出` 视为失败记录。

## 3. 组件与数据流

```mermaid
flowchart LR
    I[JSONL / Demo / 调用方] --> F[user_agent.py<br/>兼容入口]
    F --> A[agent.py<br/>生命周期与兼容层]
    A --> X[SolveContext<br/>单题显式状态]
    X --> S[solver.py<br/>顶层阶段编排]
    S --> N[candidate_generation<br/>生成与截断恢复]
    S --> V[candidate_evaluation<br/>紧凑模型验证]
    S --> L[candidate_selection<br/>多数票与置信度]
    S --> O[response_processing<br/>最终格式]
    X --> G[ModelGateway<br/>调用与元数据原子绑定]
    G --> C[注入客户端 / InternChatClient]
    D[domain_prompts + domain_router<br/>18 领域提示与零调用路由] --> S
    X --> B[ExecutionBudget]
    N --> G
    V --> G
    PAUSED[暂停的正式能力<br/>工具候选 / 确定性验证<br/>critic / reflection] -. 不在 solve 路径 .-> S
    LIB[保留的离线受限库<br/>tool_* / math_parsing<br/>task_router / deterministic_verifier] -. 仅测试与后续实验 .-> PAUSED
    E[Answer / Candidate / Verification] --> S
    O --> TS[trace_sanitizer<br/>公开元数据投影]
    TS --> R[final_response + trace]
    R --> OUT[每题 JSON / Demo 展示 / 调用方]
```

| 组件 | 职责 |
| --- | --- |
| `user_agent.py` | 按自身文件目录引导同级模块导入，并重导出 `agent.py` 中的公开类型；不得增加求解实现、吞掉导入异常或依赖 judge 当前目录 |
| `agent.py` | 维护公开 Agent 生命周期：输入校验、单题上下文创建、异常收敛和兼容转发；不实现具体求解阶段 |
| `agent_config.py` | 定义固定候选策略、模型参数、恢复开关和单题预算配置 |
| `competition_policy.py` | 固定三份官方原件及新通知转录哈希、动态官方证据 URL/核验日、核验 baseline commit、formal 默认模型与精确 allowlist、官方端点和默认参赛模式；allowlist 外模型只能显式作为非提交实验 |
| `agent_prompts.py` | 集中保存当前策略/验证提示词及暂停功能的历史提示词；不持有运行状态 |
| `agent_types.py` | 定义带 `finish_reason`/usage/阶段的 `ModelCallResult`，以及 `Answer`、`Candidate`、`Verification` 内部数据对象 |
| `answer_equivalence.py` | 保守归一化数值、集合和多解；无法证明的关系返回 `unknown` |
| `solver.py` | 只编排领域路由、三个纯文本候选、逐候选模型验证、选择和输出阶段 |
| `candidate_generation.py` | 通过唯一纯文本协议生成候选，执行候选截断恢复、整题紧急答案和全局短回退 |
| `candidate_evaluation.py` | 每个合格候选执行一次紧凑模型验证，并在 verifier 截断时使用恢复预算重试 |
| `candidate_selection.py` | 按规范答案多数票选择，平票时使用模型置信度，并记录最终来源；不读取确定性证据改变选择 |
| `response_processing.py` | 提取显式答案、解析 verdict、裁剪复核文本，并强制唯一非空末行答案 |
| `trace_sanitizer.py` | 把内部 trace 失败关闭地投影为可 JSON 序列化的公开元数据；未知自由文本不得外发 |
| `context.py` | 定义每次 `solve()` 独占的 `SolveContext`，显式持有题目、metadata、trace、预算和网关 |
| `model_calls.py` | 把 system/user 消息显式组装后交给 `ModelGateway`，不保存最近响应 |
| `model_gateway.py` | 统一候选、验证和恢复请求；未知注入 client 只绑定公开 `chat()` 并投影为三参数，自有客户端按名义类型取得原子元数据，再将响应、finish reason、usage 和预算请求编号绑定为 `ModelCallResult` |
| `truncation.py` | 统一更新截断事件的恢复/隔离状态，并在返回前封闭待处理事件 |
| `domain_router.py` | 本地关键词计数选择一个领域，不访问模型；领域提示内容仍由 `domain_prompts.py` 提供 |
| `task_router.py` | 保留的零调用题型分析库；当前正式 `solve()` 不调用它，也不让其验证计划影响选择 |
| `budget.py` | 统一记录和限制每题普通/恢复请求、usage token、工具调用及阶段 deadline，并按调用阶段累计截断和恢复状态 |
| `domain_prompts.py` | 提供 18 个领域提示；关键词路由在本地完成，不额外调用模型 |
| `math_tools.py` | 兼容旧导入的薄门面，只重导出工具公共 API；不得新增解析、实现、注册或循环逻辑 |
| `math_parsing.py` | 受限 SymPy 命名空间、表达式/符号/整数/矩阵解析以及输入、结果和复杂度边界 |
| `tool_implementations.py` | 实现 11 个有界数学工具；不声明模型 schema，不发起模型调用 |
| `tool_registry.py` | 保持工具 schema 与实现一一对应，验证 tool-call JSON，并通过可终止子进程限时分发 |
| `tool_loop.py` | 保留并受测的 tool-calling 循环；当前正式 `solve()` 不进入该模块 |
| `tool_executor.py` | 在可终止子进程中执行数学计算，并施加墙钟硬超时 |
| `deterministic_verifier.py` | 保留并受测的受限确定性验证库；结果为 `pass/fail/unknown`，当前正式选择器不读取其证据 |
| `llm_client.py` | 读取环境变量，只向官方 Intern HTTPS 端点发送 OpenAI 兼容请求，处理响应和有限重试；`chat()` 保持原返回契约，项目自有 `chat_with_metadata()` 原子返回响应及元数据 |
| `main.py` | 校验 JSONL，控制并发，保存每题 checkpoint、运行摘要并支持断点续跑 |
| `demo.py` | 将同一 `ReasoningAgent` 暴露为本地 Gradio 界面 |
| `verify_math.py` | 人工在线检查 few-shot；不属于默认测试或生产调用链 |
| `evaluation/io_utils.py` | 评测包共享的 UTF-8 JSON/JSONL 读取、SHA-256、同目录临时文件和原子写入；避免各脚本重复实现 |
| `evaluation/data/` | 数据边界：题集审计、内部基准生成、PutnamBench 导入、JSON schema 与固定截断压力集 |
| `evaluation/scoring/` | 评分边界：四态保守判分、旧报告重算、运行汇总与请求级截断门禁 |
| `evaluation/experiments/` | 实验边界：数据/运行时冻结、匿名 A/B、逐题配对统计与机器可读能力协议 |
| `scripts/run_quality_gates.py` | 顺序执行完整非模型质量门禁，并生成绑定 Git 快照的机器可读报告；失败后继续收集其余诊断 |
| `scripts/check_secrets.py` / `check_markdown_links.py` | 检查已跟踪及非忽略的未跟踪文件中的常见凭据模式，以及仓库内 Markdown 链接 |
| `scripts/check_competition_compliance.py` | 无网络验证正式模型/端点、运行时网络入口、隔离入口加载、参考答案字段隔离、公开 trace 脱敏、JSON 输出契约及发布排除项 |
| `scripts/build_release.py` | 从受限文件白名单生成带来源、配置、锁哈希、质量摘要和文件哈希的确定性 ZIP；正式包只读取 Git blob |
| `.github/workflows/offline-quality.yml` | 在 Python 3.10/3.12 上以哈希锁安装开发依赖，运行质量门禁并验证正式打包；不调用模型端点 |

## 4. 求解流程

`ReasoningAgent` 只创建 `SolveContext` 并调用 `SolveOrchestrator`。后者只决定下列阶段顺序；候选生命周期、评估、选择和输出规则分别由对应模块实现。任何阶段需要题目、trace、预算或模型访问时都必须显式接收同一个 `SolveContext`，不得从 Agent 属性或“最近响应”方法读取单题状态。

1. **领域路由**：`_detect_domain()` 对 18 个领域的关键词做不区分 ASCII 大小写的计数，选择最高分领域；未匹配时使用通用提示。该步骤零模型调用。题型分析库仍在仓库中，但不进入当前正式流程。
2. **候选生成**：固定生成 3 个相互独立的纯文本候选。策略温度为 `0.6`，API 单次安全上限为 `8192` tokens；正式调用不发送 `thinking_mode`、`tools` 或 `tool_choice`。本地关键词只用于把证明/推导/分类讨论题的推理目标设为 3500 输出 token，其余题设为 1800；它约束提示词长度目标，不压低 API 上限。所有候选第一行先写显式答案，只保留决定结论的推导。
3. **截断恢复**：每次调用保存文本、阶段、候选编号、`finish_reason` 和 usage；外部 `client.chat()` 返回行为不变。候选截断后从正常聚合隔离，每候选最多恢复一次：已有首行答案时独立核验，未有答案时短解。只有正常结束且有显式首行答案的恢复结果才替换原候选；再次截断或格式异常时两份文本都隔离，只保留首行答案供整题紧急调用参考。三候选最多使用 3 个恢复名额，始终为一次最多 512 token 的整题紧急答案保留第 4 个名额。紧急回复即使截断，也只有首行显式答案可作为无推理答案体输出。
4. **模型验证**：每个有显式答案的完整候选由模型验证 1 次，温度 `0.0`，提示只允许一行 `VERDICT: A/B`；长候选保留头尾。模型验证截断时使用恢复预算重试一次紧凑判断；再次截断或无法解析时写入 `unknown` 并使用中性置信度，不当作失败票。正常情况下 3 次候选生成加 3 次验证，恰好使用 6 次普通请求。
5. **聚合**：抽取为结构化 `Answer`，按保守 canonical key 做多数票；没有多数项时选择模型置信度最高的候选。答案、展示推理和验证结果始终来自同一候选。旧 `Verification(source="deterministic")` 即使由外部测试构造，也不能提高候选优先级。
6. **构造响应**：移除模型文本中已有的答案标签，保留其余获胜且未截断候选推理，并统一追加唯一的 `最终答案：...`。最终结构校验要求答案非空、标记唯一且位于最后一行；失败时降级为仅含规范答案的一行。截断紧急回复只使用首行答案，不使用其推理。答案体经共享安全归一化后输出；精确值与近似值同时存在时保留精确部分，并规范角度符号、`πi` 显式乘法及常见特征根标签。

P1 的题型分析、确定性验证和证据优先选择是已经完成且留有测试的历史工程成果，但当前不在正式 `solve()` 路径。`tool_candidates`、`plain_candidates`、`verifier_voting_times`、`enable_tools`、`enable_critic`、`enable_reflection` 和 `enable_deterministic_verification` 作为旧配置字段继续可构造，改变它们也不能启用另一套协议或改变上述固定 3×1、共 6 次的正常调用序列。需要恢复任一高级阶段时，必须从 Git 历史单独提出、只改变一个变量，并先完成严格注入客户端离线对照和受控在线 A/B；不能在当前兼容性诊断中悄然恢复。

默认配置由 `AgentConfig` 管理：

| 参数 | 默认值 |
| --- | ---: |
| 正式候选数 / 每候选 verifier 数 | 固定 `3` / `1` |
| 旧 `tool_candidates` / `plain_candidates` / `verifier_voting_times` | 默认 `0` / `3` / `1`；仅构造兼容，不改变正式序列 |
| `policy_temperature` / `verifier_temperature` | `0.6` / `0.0` |
| `critic_temperature` / `reflection_temperature` | `0.3` / `0.3` |
| `max_tokens` / `verifier_max_tokens` / `critic_max_tokens` | `8192` / `1024` / `1024` |
| `fallback_max_tokens` | `512` |
| 计算 / 证明推理目标 | `1800` / `3500` |
| `recovery_max_tokens` / 每候选恢复次数 | `2048` / `1` |
| `max_tool_rounds` | `3` |
| `tool_timeout_seconds` | `5.0` |
| `max_model_requests` | `6` |
| `max_recovery_requests` / 总请求硬上限 | `4` / `10` |
| `max_total_tokens` | `200000` |
| `max_tool_calls` | `48` |
| `problem_timeout_seconds` | `600.0` |
| `max_problem_chars` / `max_metadata_chars` | `20000` / `20000` |
| tools / critic / reflection | 暂停；旧字段不启用正式分支 |
| deterministic verification | 暂停；旧字段不改变选择 |
| fallback | 启用，并计入恢复预算 |

## 5. 数学工具

仓库保留并离线测试 11 个受限工具，但当前正式 `solve()` 不注册或调用它们：

| 工具 | 用途 |
| --- | --- |
| `calculate` | 解析、化简表达式 |
| `solve_equation` | 解一元方程 |
| `differentiate` | 求导 |
| `integrate` | 不定积分 |
| `limit` | 求极限 |
| `residue` | 求复函数留数 |
| `matrix_det` | 求矩阵行列式 |
| `matrix_eigenvals` | 求矩阵特征值 |
| `gcd_lcm` | 求最大公约数与最小公倍数 |
| `mod_pow` | 模幂 |
| `binomial` | 组合数 |

模型工具参数是不可信输入。执行层使用无 builtins 的 SymPy 白名单命名空间，并限制表达式 2048 字符、工具参数 8192 字符、结果 8000 字符、矩阵最大 `12×12`、整数最多 1000 位、组合数 `n≤100000`、幂指数 `≤10000`、每轮最多 8 个工具调用。每次注册工具计算在 spawned 子进程中运行，默认超过 5 秒即由父进程终止。未知工具、畸形 JSON、越界输入、超时和子进程失败均返回受控错误，不进入任意代码执行路径。

## 6. 客户端与运行器

`InternChatClient` 使用：

| 环境变量 | 默认值 |
| --- | --- |
| `INTERN_API_KEY` | 无，缺失时拒绝启动 |
| `INTERN_API_BASE` | `https://chat.intern-ai.org.cn/api/v1/chat/completions` |
| `INTERN_MODEL` | `intern-s1`；formal 默认值，另允许 `intern-s1-pro`、`intern-s2-preview` |
| `COMPETITION_MODE` | `1`；拒绝未被书面证据覆盖的模型 ID |

自有客户端对端点使用失败关闭校验，只接受官方 HTTPS Chat Completions 地址；即使 `COMPETITION_MODE=0` 也不能切换第三方服务。参赛模式默认开启，并只接受当前书面证据覆盖的 `intern-s1`、`intern-s1-pro`、`intern-s2-preview`；默认仍为 `intern-s1`，实际正式模型由 AtomGit 提交页选择回执确定。“397/35B”简写和未来 ID 不能自行映射；关闭模式仅允许重放明确标记为非提交的其它模型实验。客户端拒绝 `stream=True` 和 `n != 1`，当前不发送未经平台兼容验证的 `stop` 或流式参数。只重试连接错误、超时、HTTP `408/409/425/429`、服务端 `5xx`，以及响应 code/type/message 明确表示频率限制的 HTTP 400；普通参数错误和认证错误直接失败。`chat()` 保持原有文本/tool-call 返回契约。`ModelGateway` 以项目 `InternChatClient` 的名义类型作为信任边界，仅对该类型调用 `chat_with_metadata()` 取得原子 request id、模型、`finish_reason`、usage、耗时和尝试次数；当前正式上层即使面对自有客户端也只提交 `messages/temperature/max_tokens`。未知外部注入客户端同样只收到这三个参数，不读取协议 marker、其它私有字段或同名扩展方法。项目不保存“最近一次响应”全局或上下文变量，也不在请求后另取元数据。模型冲突和客户端/响应契约缺口的证据边界见 `docs/OFFICIAL_MATERIALS_REGISTER.md`。

`main.py` 读取 JSONL，每行必须是对象且含非空 `problem`。`idx` 缺失时按行生成；显式 `idx` 必须是 1～128 位 ASCII 字母、数字、下划线或连字符，且不能重复。结果写入 `<output_dir>/<idx>.json`，先写 `.tmp` 再原子替换。只有合法 JSON、`status == "success"` 且 `final_response` 非空的 checkpoint 会被跳过。`未解出` 保存为 error checkpoint，并保留 Agent trace 供区分数学失败、预算和平台错误。并发由 `LOCAL_MAX_CONCURRENCY` 控制，默认 `3` 且必须为正整数；正式评测可在 manifest 中冻结为更低值以规避端点节流。批处理完成后原子写入 `<output_dir>/_run/run_summary.json`，包含输入文件名和 SHA-256、模型、并发、UTC 开始时间、耗时以及成功/失败/跳过计数，不包含题面或密钥。

已归档的外层评测口径是：每题独立进程重新加载模块、构造一个 Agent 并调用一次 `solve`，最多并行 3 个题目进程；单题进程组硬时限 1200 秒、Agent 阶段总硬时限 6 小时。运行时只可访问官方 API，无 GPU 和通用外网，依赖在受限阶段前安装，不能动态下载。项目的 600 秒单题软期限、默认 3 并发和离线本地工具位于这些边界内，但不得把外层时间/并发口径推导成模型调用数、token、内存、磁盘或子进程能力保证。

当前 AtomGit 评测入口不绑定选手填写的 commit SHA：现有本地仓库把队伍仓库添加为远程 `atomgit`；作品页关联仓库并选择模型、点击“提交作品”后，平台在北京时间 12:00/24:00 批次拉取当时最新 `main`。因此交付控制同时保留两层版本语义：本地发布包和证据用精确 SHA 冻结；平台侧从点击提交到抓取完成必须冻结 `main`，抓取后再用 AtomGit 远端 SHA 对账。截止前最终代码与规定材料还须打 ZIP 发组委会邮箱。GitHub 镜像、只推送未点击提交、只发邮件或仅生成 ZIP 都不能单独完成交付。当前仓库未配置 `atomgit` 远程且没有两类回执时，运行架构可测试，但正式提交状态仍为阻断。

## 7. 信任边界与失败行为

- API key 只从环境变量读取；`.env`、`outputs/` 和验证报告被 Git 忽略。
- 正式参赛模型必须来自三个精确 ID 的 formal allowlist，并与 AtomGit 页面回执一致；运行只使用赛事注入客户端或官方 Intern 端点，以及随仓库交付的离线受限工具。禁止人工逐题干预、赛后补填、伪造日志和未经允许的外部闭源服务；详细操作与证据边界见 `docs/COMPETITION_COMPLIANCE.md` 和 `docs/OFFICIAL_MATERIALS_REGISTER.md`。
- 批处理入口只把 `problem` 和 `idx` 送入 Agent，输入记录中的参考答案、参考解和判分字段只属于离线评分边界，不进入求解上下文或模型消息。
- 题目、metadata、模型文本、tool calls、HTTP/JSON 响应和 checkpoint 均视为不可信输入。
- 内部流水线可短暂持有候选与工具结果以完成选择，但公开返回前必须经 `trace_sanitizer` 白名单投影；对外 trace 不含题面、prompt、任何模型/工具正文、最终答案或异常消息。私有原始响应只允许存在于忽略的受控实验输出中。
- 当前正式链路不发起工具、批评或反思请求。截断候选和验证器按状态机处理，任何残缺文本都不能直接进入聚合或最终推理；全局异常仍保证接口返回结构稳定。
- SymPy 子进程有墙钟硬超时，但尚无操作系统级内存上限；复杂表达式在超时前仍可能形成内存峰值。
- 单题 deadline 在各模型/工具调用边界检查，无法提前取消已发出的阻塞 HTTP 请求；单请求由客户端超时保护。
- token 上限依赖响应 usage 后记账；一次响应若造成超额，后续请求会停止，但已产生的 token 无法撤销。
- 模型输出具有随机性。正确率、延迟和成本结论必须绑定固定数据集、模型、配置和提交记录。

## 8. 验证边界

默认完整检查：

```bash
python -m scripts.run_quality_gates
```

测试以 fake client 和确定性输入覆盖接口、显式上下文、统一网关、模块组合边界、默认 6 次正式调用序列、预算、保留的离线工具库、截断状态机、并发元数据隔离、评分和 runner，不依赖真实 API。客户端门禁同时包含不接受 `**kwargs` 的三参数 fake、私有访问抛错 fake、项目扩展 client，以及打开旧 tools/critic/reflection/deterministic 开关仍不能改变正式协议的回归。完整门禁还执行 70% 语句覆盖率阈值、Ruff、compileall、Bandit、开发锁的 Python 3.10/Linux 条件依赖闭包检查、`pip check`、三套依赖锁漏洞审计、敏感信息扫描、Markdown 本地链接检查、竞赛合规探针、few-shot dry-run 和所有正式 CLI 的帮助入口。合规探针必须验证正式模型和端点、运行时网络入口、隔离解释器按绝对路径加载根入口、仅复制根目录 Python 文件时完成三参数调用、参考答案字段隔离、公开 trace 不含题面/模型正文/最终答案、JSON 输出及发布排除项。公开 trace 投影必须满足幂等性、JSON 可序列化和秘密文本不变式。漏洞审计会访问公开漏洞数据库，但不会访问模型端点；跳过它生成的报告不能授权正式包。并发测试要求同一注入客户端上的响应元数据原子返回，不能跨题串入其他 `SolveContext`。`python -m evaluation.data.audit_dataset <dataset>` 可离线检查题集规模、元数据和泄漏风险，并可通过 `--reference-dataset` 检查跨 split 重合；`evaluation.scoring.judge` 的文字语义与无法证明等价关系必须保持 `unknown`，禁止用子串命中判对。证明和开放语义题只能在 `manual_blind` 模式下由盲审裁决覆盖，未复核时保持 `unknown`。能力实验必须绑定干净 commit 的冻结 manifest；新旧三轮报告按 `idx` 配对，不能用两个独立总分替代配对统计。截断门禁使用请求级点估计和单侧 95% Wilson 上界；当约有 1082 次请求时最多允许 42 次截断。`evaluation/data/truncation_stress.jsonl` 应连续运行 3 次后合并报告，且候选阶段截断率、恢复覆盖、无效答案和残句泄漏分别独立检查。评测入口统一使用 `python -m evaluation.<group>.<module>`，共享结构化文件 I/O；评测模块不得通过 `sys.path` 修改规避包边界。`python verify_math.py` 默认只解析 few-shot，不访问 API；只有 `--execute` 才会在线验证，并由 `--max-requests` 限制首轮和重试总请求数。`main.py` 和 `demo.py` 使用真实凭据时会消耗配额，不应进入默认 CI。

## 9. 架构变更规则

以下变化必须同时更新本文件、README 和相应测试：外部接口、候选/验证流程、工具注册与安全界限、环境变量、运行入口、checkpoint 格式或目录布局。若变化影响 P1～S6 的冻结边界、硬规则、验收矩阵或历史问题状态，还必须按规则 ID 更新 `docs/ENGINEERING_SPECIFICATION.md`；若影响赛事事实、正式模型/端点、日志、提交或禁止行为，则同步更新 `docs/COMPETITION_COMPLIANCE.md`。实验数据与演进历史写入 `技术报告.md`，待办与风险写入 `docs/AUDIT_AND_OPTIMIZATION.md`，不要另建第二份架构文档。

## 10. 质量、供应链与交付边界

`requirements.txt`、`requirements-dev.txt` 和 `requirements-demo.txt` 只描述维护者选择的直接依赖范围；与之对应的三个 `.lock` 文件记录完整传递依赖、精确版本和允许制品的 SHA-256。核心运行时和开发工具支持 Python 3.10+；共享开发锁在 Python 3.12 生成时必须显式纳入只在 3.10 生效的条件依赖，并由最低版本真实安装和目标环境元数据闭包共同验证。可选 Demo 使用 Python 3.12+，因为修复已知漏洞的 Pillow 版本不再支持 3.10/3.11，不能为扩大可选界面兼容范围而锁回已知脆弱版本。运行安装、CI 和交付验证必须使用 `pip install --require-hashes`，变更任一输入规格后必须重新生成并验证受影响的锁，不能手工删减哈希来绕过解析冲突。

`scripts.run_quality_gates` 是唯一完整质量入口。它按固定清单执行各项检查，即使某项失败也继续诊断，并把命令参数、返回码、耗时和有界输出尾部写入 `.quality/quality-report.json`；报告同时保存检查前后的 commit、tree、分支和工作树状态。报告不保存 API key、题面或完整模型响应。CI 只授予 `contents: read`，第三方 Action 固定到完整提交 SHA，关闭 checkout 凭据持久化，并在 Python 3.10 与 3.12 上验证。CI 与默认测试均不允许 `--execute`、`main.py` 求解或启动 Demo。

正式发布必须同时满足：工作树干净；模型参数属于 formal allowlist；质量报告状态为通过且包含依赖审计与 `competition_compliance`；报告前后 commit/tree 与当前 HEAD 完全一致；所有必需检查均有通过记录。发布器只选择 Git 已跟踪或非忽略的未跟踪文件，再施加根文件白名单和受限目录/后缀；符号链接、路径逃逸、含 NUL 的伪装二进制、超过 5 MiB 扫描/单文件上限或总输入超过 50 MiB 均被拒绝，嵌入的质量报告也必须通过同一敏感信息扫描。正式包从 Git blob 读取源字节，按固定名称顺序、提交时间、Unix 文件模式和压缩级别写 ZIP；同一提交、同一质量报告、同一模型标识应得到相同 SHA-256。包内 manifest 记录提交/tree、模型、三份官方原件与新通知转录哈希、动态官方证据 URL/核验日、核验 baseline commit、formal 默认值/allowlist/匹配状态、默认 `AgentConfig`、依赖锁哈希和逐文件哈希，旁路 `.sha256` 用于传输校验。发布包成功只证明源码产物可复现，不证明 AtomGit 作品页已点击、批次已抓取或远端 `main` 已对账。

脏工作树只能通过 `--allow-dirty` 生成 `draft`，内容来自当前工作区且 manifest 明确保留脏文件清单；它不能升级为正式包。`.env`、`.quality/`、`dist/`、`outputs/`、虚拟环境及未在白名单中的文件不会进入交付包。

根 `LICENSE` 当前明确项目代码未授予开源许可；这是一项保守边界，不代表对第三方软件或数据取得再授权。Python 依赖、压力集和本地导入题集分别遵守其自身许可及来源记录，具体说明见 `THIRD_PARTY_NOTICES.md`。更换项目许可证属于所有者决策，不能由维护脚本自动放宽。

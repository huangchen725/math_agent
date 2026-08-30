# 数学推理智能体架构

> 状态：当前生效  
> 更新日期：2026-08-30
> 本文件是仓库唯一的架构事实源。README、比赛报告和审计文档仅提供使用说明、实验记录或改进路线；内容冲突时以本文件和当前代码为准。

## 1. 目标与边界

系统面向竞赛数学题，在调用方注入的 Intern 兼容模型客户端上完成领域与题型分析、候选生成、可选符号计算、确定性/模型验证、低置信度反思和答案聚合。

当前仓库只有一套可运行实现，全部位于 `math_agent/` 包。根目录 `user_agent.py` 只是竞赛兼容入口，与 `math_agent` 导出同一个 `ReasoningAgent` 和 `AgentConfig`，不保留第二份实现。2026-08-28 删除的同名目录是未接入入口、依赖不同的旧原型；2026-08-30 建立的是现有扁平运行时的保守包化迁移，两者没有代码继承关系。多智能体、共享黑板和自适应候选升级仍属于未来设想，不是当前能力。

## 2. 外部契约

```python
ReasoningAgent(client).solve(problem, metadata)
# -> {"final_response": str, "trace": list[dict]}
```

- `problem` 是题目字符串，必须非空且默认不超过 20000 字符。
- `metadata` 为竞赛兼容字典，必须可序列化为 JSON 且默认不超过 20000 字符；批处理入口会传入 `idx`，当前核心流水线不依赖其内容。
- `client` 必须提供 `chat(messages=..., **kwargs)`，由调用方注入。
- `final_response` 是非空字符串；除明确的 `未解出` 失败哨兵外，保留获胜候选推理，并以唯一一行 `最终答案：...` 结尾。该行只含规范化答案体，不含解释性句子；常见 Unicode/LaTeX 表示转换为稳定记号，已有精确形式时优先保留精确形式。
- `trace` 是事件列表，用于记录路由、题型长度目标、工具、候选、验证、截断恢复、反思、选择、最终答案来源和单题预算摘要。截断事件只记录阶段、候选编号、token、是否已有首行答案和处理状态，不保存残缺回复。
- `ReasoningAgent.solve()` 捕获全局异常并尝试低成本回退；`main.py` 将空答案和 `未解出` 视为失败记录。

## 3. 组件与数据流

```mermaid
flowchart LR
    I[JSONL / Demo / 调用方] --> F[user_agent.py<br/>兼容入口]
    F --> A[math_agent.agent<br/>ReasoningAgent]
    I --> C[InternChatClient]
    C --> A
    D[math_agent/domain_prompts.py<br/>18 领域提示] --> A
    I --> Q[math_agent/task_router.py<br/>题型与严格验证计划]
    Q --> A
    B[ExecutionBudget] --> A
    A --> T[math_agent/math_tools.py<br/>11 个受限 SymPy 工具]
    T --> P[math_agent/tool_executor.py<br/>可终止子进程]
    T --> A
    A --> V[math_agent/deterministic_verifier.py<br/>受限确定性验证]
    V --> P
    V --> A
    E[Answer / Candidate / Verification] --> A
    A --> R[final_response + trace]
    R --> O[每题 JSON / Demo 展示 / 调用方]
```

| 组件 | 职责 |
| --- | --- |
| `user_agent.py` | 竞赛兼容入口，只重新导出 `math_agent` 中的公开类型；不得增加运行时实现 |
| `math_agent/__init__.py` | 唯一包级公开 API，导出 `ReasoningAgent`、`AgentConfig`、`InternChatClient` 和核心数据类型 |
| `math_agent/agent.py` | 维护固定策略候选生成、验证、反思和聚合，并协调单题预算 |
| `math_agent/agent_types.py` | 定义带 `finish_reason`/usage/阶段的 `ModelCallResult`，以及 `Answer`、`Candidate`、`Verification` 内部数据对象 |
| `math_agent/answer_equivalence.py` | 保守归一化数值、集合和多解；无法证明的关系返回 `unknown` |
| `math_agent/task_router.py` | 零模型调用识别一个或多个题型；仅对结构明确的直接计算题生成至多一个可执行验证计划，证明、数域不明或复合任务只保留标签 |
| `math_agent/budget.py` | 统一记录和限制每题普通/恢复请求、usage token、工具调用及阶段 deadline，并按调用阶段累计截断和恢复状态 |
| `math_agent/domain_prompts.py` | 提供 18 个领域提示；关键词路由在本地完成，不额外调用模型 |
| `math_agent/math_tools.py` | 声明工具 schema，安全执行 SymPy，并驱动 tool-calling 循环 |
| `math_agent/tool_executor.py` | 在可终止子进程中执行数学计算，并施加墙钟硬超时 |
| `math_agent/deterministic_verifier.py` | 在可终止子进程中执行封闭数值表达式、有限方程解集、导数、积分、极限、留数、行列式、模幂、组合数及符号等价验证；结果为 `pass/fail/unknown` |
| `math_agent/llm_client.py` | 读取环境变量，发送 OpenAI 兼容 HTTP 请求，处理响应和有限重试 |
| `main.py` | 校验 JSONL，控制并发，保存每题 checkpoint、运行摘要并支持断点续跑 |
| `demo.py` | 将同一 `ReasoningAgent` 暴露为本地 Gradio 界面 |
| `verify_math.py` | 人工在线检查 few-shot；不属于默认测试或生产调用链 |
| `evaluation/audit_dataset.py` | 离线审计 JSONL 的规模、领域分布、来源字段、内部重复及与 prompt/sample 的重合 |
| `evaluation/judge.py` | 离线保守判分；只接受可证明等价，输出 `correct/wrong/unknown/no_answer`，不属于运行时选择链路 |
| `evaluation/rescore_report.py` | 不调用模型，使用保守判分器重新核算已有报告，并保留旧 verdict 供差异追踪 |
| `evaluation/generate_internal_benchmark.py` | 生成可复现的18领域内部合成基准；它不是生产调用链或官方独立题集 |
| `evaluation/score_run.py` | 汇总 `main.py` 逐题输出、四态判分、领域/难度/题型、usage、分阶段截断和恢复指标，并导出人工复核队列 |
| `evaluation/truncation_gate.py` | 合并一次或多次离线评分报告，按请求级截断率、单侧 Wilson 上界、候选阶段、恢复、格式和正确率执行发布门禁 |
| `evaluation/freeze_experiment.py` | 冻结数据 SHA-256、运行时文件指纹、commit、模型、AgentConfig、并发、重复次数和数据泄漏审计；脏工作树只能生成 draft |
| `evaluation/import_putnam_bench.py` | 从固定上游 commit 确定性抽样第三方公开大学竞赛题；题面只写入被 Git 忽略的本地输出 |
| `evaluation/blind_review.py` | 对旧版/新版输出逐题随机交换 A/B 标签，并在人工复核完成后解盲为两份裁决记录 |
| `evaluation/paired_compare.py` | 对三轮新旧报告进行逐题配对、bootstrap 区间、精确 McNemar 检验、回退清单和证据门禁 |
| `evaluation/truncation_stress.jsonl` | 18 领域各 2 题的项目自建长输出压力集；只测可靠性，不是官方正确率基准 |

## 4. 求解流程

1. **领域与题型路由**：`_detect_domain()` 对 18 个领域的关键词做不区分 ASCII 大小写的计数，选择最高分领域；未匹配时使用通用提示。`analyze_task()` 可返回多题型标签和置信度，但只有无证明指令、无复合目标且语法严格匹配的直接计算题才产生验证计划。方程必须明确实数域或复数域；整数、正根等约束以及数域不明时不执行强验证。
2. **候选生成**：默认生成 2 个工具增强候选和 1 个纯推理候选，策略温度 `0.6`、`thinking_mode=False`、API 单次上限仍为 `8192` tokens。关键词在本地把证明/推导/分类讨论题的推理目标设为 3500 输出 token，其余计算题设为 1800；这只约束 prompt，不压低 API 安全余量。所有候选第一行先写显式答案，只保留决定结论的推导。
3. **工具循环**：每个工具候选最多 3 轮。模型请求工具后，本地执行并把结果作为 `tool` 消息回灌；超过轮数后强制答案先行的无工具文本回复。任何工具轮调用出现 `finish_reason=length/max_tokens` 时立即停止，残缺工具调用不执行。
4. **截断恢复**：每次调用保存文本、阶段、候选编号、`finish_reason` 和 usage；外部 `client.chat()` 返回行为不变。候选截断后从正常聚合隔离，每候选最多恢复一次：已有首行答案时独立核验，未有答案时短解。只有正常结束且有显式首行答案的恢复结果才替换原候选；再次截断或格式异常时两份文本都隔离，只保留首行答案供整题紧急调用参考。三候选最多使用 3 个恢复名额，始终为一次最多 512 token 的整题紧急答案保留第 4 个名额。紧急回复即使截断，也只有首行显式答案可作为无推理答案体输出。
5. **验证**：若题型路由生成了严格计划，每个有显式答案的候选先在隔离子进程中做一次确定性验证，并占用共享工具预算；超时、解析不支持和预算不足均为 `unknown`。随后仍按原配置由模型验证 1 次，温度 `0.0`，提示只允许一行 `VERDICT: A/B`；长候选保留头尾。模型验证截断时在普通请求预算内重试一次紧凑判断；再次截断或无法解析时写入 `unknown` 并使用中性置信度，不当作失败票。
6. **批评与反思**：最佳候选原始置信度低于 `0.5` 且已有答案时，先请求不超过 6 行的决定性错误摘要。批评截断时直接丢弃，不触发反思；反思截断时走与普通候选相同的恢复状态机。
7. **聚合**：抽取为结构化 `Answer`。存在确定性 `pass` 且所有通过证据指向同一个 canonical answer 时，优先选择该答案中带通过证据且模型置信度最高的候选；通过证据互相冲突时记录冲突并回退。没有一致的确定性通过证据时，完整保留原选择规则：按保守 canonical key 多数票优先，没有多数项时选择置信度最高的候选。`fail` 和 `unknown` 单独出现时不排除候选，避免路由或解析边界造成错误降权。答案、展示推理和验证证据始终来自同一候选。
8. **构造响应**：移除模型文本中已有的答案标签，保留其余获胜且未截断候选推理，并统一追加唯一的 `最终答案：...`。最终结构校验要求答案非空、标记唯一且位于最后一行；失败时降级为仅含规范答案的一行。截断紧急回复只使用首行答案，不使用其推理。答案体经共享安全归一化后输出；精确值与近似值同时存在时保留精确部分，并规范角度符号、`πi` 显式乘法及常见特征根标签。

P1 只改变“严格计划存在且获得一致确定性通过证据”时的选择优先级；`enable_deterministic_verification=False` 可完整关闭该层。候选数量、温度、thinking mode、模型验证次数、token 上限和无证据时的原聚合规则均未改变。该机制通过离线正例、反例、漏根、数域、证明阻断和证据冲突测试；真实正确率增益仍必须按冻结 P0 协议独立评测。

默认配置由 `AgentConfig` 管理：

| 参数 | 默认值 |
| --- | ---: |
| `tool_candidates` / `plain_candidates` | `2` / `1` |
| `verifier_voting_times` | `1` |
| `policy_temperature` / `verifier_temperature` | `0.6` / `0.0` |
| `critic_temperature` / `reflection_temperature` | `0.3` / `0.3` |
| `max_tokens` / `verifier_max_tokens` / `critic_max_tokens` | `8192` / `1024` / `1024` |
| `fallback_max_tokens` | `512` |
| 计算 / 证明推理目标 | `1800` / `3500` |
| `recovery_max_tokens` / 每候选恢复次数 | `2048` / `1` |
| `max_tool_rounds` | `3` |
| `tool_timeout_seconds` | `5.0` |
| `max_model_requests` | `16` |
| `max_recovery_requests` / 总请求硬上限 | `4` / `20` |
| `max_total_tokens` | `200000` |
| `max_tool_calls` | `48` |
| `problem_timeout_seconds` | `600.0` |
| `max_problem_chars` / `max_metadata_chars` | `20000` / `20000` |
| tools / critic / reflection / fallback | 全部启用 |
| deterministic verification | 启用；可用 `enable_deterministic_verification=False` 回退 |

## 5. 数学工具

当前注册 11 个工具：

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
| `INTERN_MODEL` | `intern-s2-preview` |

客户端拒绝 `stream=True` 和 `n != 1`，当前不发送未经平台兼容验证的 `stop` 或流式参数。只重试连接错误、超时、HTTP `408/409/425/429`、服务端 `5xx`，以及响应 code/type/message 明确表示频率限制的 HTTP 400；普通参数错误和认证错误直接失败。客户端保持原有文本/tool-call返回契约，并通过 `get_last_response_meta()` 暴露最近一次响应的 request id、模型、`finish_reason`、usage、耗时和尝试次数，供单题预算累计。

`main.py` 读取 JSONL，每行必须是对象且含非空 `problem`。`idx` 缺失时按行生成；显式 `idx` 必须是 1～128 位 ASCII 字母、数字、下划线或连字符，且不能重复。结果写入 `<output_dir>/<idx>.json`，先写 `.tmp` 再原子替换。只有合法 JSON、`status == "success"` 且 `final_response` 非空的 checkpoint 会被跳过。`未解出` 保存为 error checkpoint，并保留 Agent trace 供区分数学失败、预算和平台错误。并发由 `LOCAL_MAX_CONCURRENCY` 控制，默认 `3` 且必须为正整数；正式评测可在 manifest 中冻结为更低值以规避端点节流。批处理完成后原子写入 `<output_dir>/_run/run_summary.json`，包含输入文件名和 SHA-256、模型、并发、UTC 开始时间、耗时以及成功/失败/跳过计数，不包含题面或密钥。

## 7. 信任边界与失败行为

- API key 只从环境变量读取；`.env`、`outputs/` 和验证报告被 Git 忽略。
- 题目、metadata、模型文本、tool calls、HTTP/JSON 响应和 checkpoint 均视为不可信输入。
- trace 会包含题面衍生内容、候选片段和工具结果，输出目录应按敏感数据管理。
- 工具调用失败会退化到纯推理；截断候选、验证器、批评器和反思各按状态机处理，任何残缺文本都不能直接进入聚合或最终推理；全局异常仍保证接口返回结构稳定。
- SymPy 子进程有墙钟硬超时，但尚无操作系统级内存上限；复杂表达式在超时前仍可能形成内存峰值。
- 单题 deadline 在各模型/工具调用边界检查，无法提前取消已发出的阻塞 HTTP 请求；单请求由客户端超时保护。
- token 上限依赖响应 usage 后记账；一次响应若造成超额，后续请求会停止，但已产生的 token 无法撤销。
- 模型输出具有随机性。正确率、延迟和成本结论必须绑定固定数据集、模型、配置和提交记录。

## 8. 验证边界

默认离线检查：

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

测试以 fake client 和确定性输入覆盖接口、预算、工具、客户端、截断状态机、并发元数据隔离、评分和 runner，不依赖真实 API。`python evaluation/audit_dataset.py <dataset>` 可离线检查题集规模、元数据和泄漏风险，并可通过 `--reference-dataset` 检查跨 split 重合；`evaluation/judge.py` 的文字语义与无法证明等价关系必须保持 `unknown`，禁止用子串命中判对。证明和开放语义题只能在 `manual_blind` 模式下由盲审裁决覆盖，未复核时保持 `unknown`。能力实验必须绑定干净 commit 的冻结 manifest；新旧三轮报告按 `idx` 配对，不能用两个独立总分替代配对统计。截断门禁使用请求级点估计和单侧 95% Wilson 上界；当约有 1082 次请求时最多允许 42 次截断。`evaluation/truncation_stress.jsonl` 应连续运行 3 次后合并报告，且候选阶段截断率、恢复覆盖、无效答案和残句泄漏分别独立检查。`python verify_math.py` 默认只解析 few-shot，不访问 API；只有 `--execute` 才会在线验证，并由 `--max-requests` 限制首轮和重试总请求数。`main.py` 和 `demo.py` 使用真实凭据时会消耗配额，不应进入默认 CI。

## 9. 架构变更规则

以下变化必须同时更新本文件、README 和相应测试：外部接口、候选/验证流程、工具注册与安全界限、环境变量、运行入口、checkpoint 格式或目录布局。实验数据与演进历史写入 `技术报告.md`，待办与风险写入 `docs/AUDIT_AND_OPTIMIZATION.md`，不要另建第二份架构文档。

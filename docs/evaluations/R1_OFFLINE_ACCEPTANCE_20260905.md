# R1 离线独立验收：不通过

## 验收对象与结论

- 核验日期：2026-09-05；被审提交：`2cf691fb6f3b61380704a15b6e5a80d4664bef31`。
- 审查范围：`900fce2..2cf691f` 的五项 R1 实现及其测试、门禁和完成声明。
- 开始核验时工作树干净，机器阶段为 R1；已存在 `453b278` 的进入 R1 决策记录及 `900fce2` 阶段提交。本次不撤销该决策，也不把批次回执作为离线验收失败原因。
- **验收不通过。** 三参数公开调用已获离线正证据，但宽构造器、公开 trace 脱敏、完整生命周期和截断隔离仍存在可复现缺口；导入污染矩阵与仓库外隔离入口也未通过。不能接受“R1 离线全部完成，唯一剩余项是第二次正式评测”的声明。
- 本次仅审查和归档，未修改运行时代码、原测试、规则阶段或正式成绩；未调用模型 API、提交或推送。

## 复核结果

| 检查 | 本次结果 | 边界 |
| --- | --- | --- |
| 现有离线 suite | 103 passed，8.50 秒 | 证明现有用例通过 |
| `policy_guard.py --formal` | PASS | 实际执行静态模式/AST 与规则文件校验，不运行生命周期、脱敏、污染矩阵等行为测试 |
| `policy_guard.py --changed`（审查开始） | PASS | 初始无改动 |
| Ruff | PASS | 当前配置的静态检查 |
| 编译检查 | PASS | 12 个清单运行时文件以及 local_support、evaluation、tests |
| `verify_math.py` | 21 个 few-shot，dry-run | 未访问 API，不是正确率结果 |
| 独立验收探针 | **17 failed，2 passed，0.98 秒** | 按缺口选取的反例和正向对照；不是随机抽样或数学能力测试 |

执行环境：Windows，已有 Python 3.12.13；使用 bundled Python 解释器与仓库现有 `.venv/Lib/site-packages`，没有新增依赖。没有实际运行 Linux/Python 3.10 验收，不能冒充该环境结果。

本地可复现材料（outputs 被 Git 忽略，仅本机保存）：

- `outputs/r1-acceptance/test_r1_acceptance.py`，SHA-256 `93db7392c4904d04e0aca553baab3f0d2c83957a46b3a6aa1247effc5b3ab58c`。
- `outputs/r1-acceptance/results.xml`，SHA-256 `66cba416ed15839bc5365a0743a9b96f7eba924130d25418d871fcd7221bbcf3`。
- 所有题目、响应和凭据标记均为本地人工构造的 fake 数据，不含私有题集或真实凭据。

在本仓库目录可复跑：

```powershell
$env:PYTHONPATH='D:\kami\math-agent;D:\kami\math-agent\.venv\Lib\site-packages'
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\James\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q outputs/r1-acceptance/test_r1_acceptance.py --tb=short
```

## F1 · P1：宽构造器未实现，未知配置仍可导致请求前失败

位置：`user_agent.py:136–146`、`user_agent.py:180`。

当前签名是 `__init__(client, config=None, *, local_adapter=None)`，新增适配器参数不等于兼容 runner 的 `*args/**kwargs`。实测：

- `ReasoningAgent(fake, runner_context=object())` → `TypeError`。
- `ReasoningAgent(fake, object(), object())` → `TypeError`。
- `ReasoningAgent(fake, {"runner": "opaque"}).solve(...)` → `AttributeError`，因为 `config or AgentConfig()` 把不透明对象直接作为配置。

这三条都是 0 请求失败。它们证明 R1-2 的构造契约尚未完成；不代表已知正式 runner 必定传入这些值。现有 `test_local_adapter.py` 只验证适配器的工具/usage 恢复，没有覆盖“宽构造器”的关键输入面。

修复验收：兼容额外位置/关键字参数，仅接受真正由项目定义的配置对象，未知参数不得污染配置；覆盖不透明对象和未知 kwargs，断言公开入口能完成有效请求。

## F2 · P1：trace 截断没有脱敏，部分写入点仍越界

位置：`user_agent.py:33–52`、`user_agent.py:513–522`。

`_clip_for_trace()` 直接保留内容前 300 字符，没有凭据删除或结构化白名单。把明确标为假的 Bearer 标记置于模型响应开头，`policy_plain_0` 原样返回该标记。公开题面衍生文本也会被同样保留。现有“不含凭据”测试的输入从未含凭据，因此无法检出泄漏，属于空缺的反例覆盖。

此外 `self_consistency` 和 `select_final` 绕过统一辅助函数：1500 字符的答案使 `select_final.content` 达到 1506 字符，连现有测试采用的 400 字符上限也不满足。

修复验收：定义公开 trace 允许披露的字段，必要文本在统一出口实际脱敏且限长；把模拟凭据放在首部、中部、尾部、异常、工具结果和最终选择事件中验证。仅截取字符串不能满足 R1-3。

## F3 · P1：完整生命周期仍有保护范围之外的异常

位置：`user_agent.py:172–221`。

R1-4 实现的是验证/反思阶段预算耗尽后的候选保留，没有把输入序列化和预算初始化纳入最外层保护。实测：

- `AgentConfig(max_model_requests=0)` 在 `solve()` 内构造 `ExecutionBudget` 时抛出 `ValueError`，越过公开接口。
- 5000 层嵌套的本地 metadata 在 `json.dumps()` 抛出 `RecursionError`；这里只捕获 TypeError/ValueError，异常向外传播。

两项均在第一次模型请求前失败。原有预算阶段测试通过，不足以证明“完整生命周期兜底”。这些是验收范围内尚未处理的旧边界，不是声称它们全部由 R1-4 新增。

修复验收：输入校验、序列化、初始化、求解、聚合和响应构造都受公共边界保护；每条失败路径返回稳定结构，预检失败不额外发请求。不能仅在各阶段零散捕获预算异常。

## F4 · P1：截断隔离可被聚合、反思和直接答案回退绕过

位置：`user_agent.py:319`、`user_agent.py:335–339`、`user_agent.py:497–499`、`user_agent.py:604–611`。

实测三条互不相同的遗漏：

1. 所有候选为 3600 字符残文，直接答案回退返回空。候选虽被 `_answer_for_aggregation()` 隔离，`_aggregate()` 的无答案分支又从原始 content 前 500 字符生成“答案”，最终仍输出残文。
2. 原候选有答案 2，反思输出长残文并获得 verifier 的 A 票。反思直接使用 `build_answer(_extract_answer(refined))`，没有经过同一隔离入口，残文胜出。
3. 全候选截断时，512-token 直接答案回退返回短残句“因此我们还需要计算”，最终输出 `最终答案：因此我们还需要计算`。回退没有检验完整答案。

此外 `_is_likely_truncated()` 只检查长度及答案标记子串，并非 `finish_reason=length` 的全路径生命周期处理；当前本地 client 也不传递 finish_reason 给适配器。正式返回字段保证仍未公开，不能假定一定可用，但也不能把长度启发式称作完整截断处理。

修复验收：所有候选来源（包括反思和恢复）共享资格判定；隔离状态必须保持到最终选择，任何 fallback 都不能重新抽取隔离内容。覆盖恢复空值、异常、短残句、预算耗尽和存在可用截断元数据的情况。

## F5 · P1：导入污染矩阵与隔离入口尚未通过

位置：`user_agent.py:12–21`；相关完成声明见 `docs/ENGINEERING_SPECIFICATION.md:118–120`。

已有测试仅污染 `llm_client`，并且在仓库路径可用、其它依赖可解析的测试进程中加载入口。独立实测：

- 分别预载同名外部 `agent_types`、`answer_equivalence`、`budget`、`math_tools`、`domain_prompts` 后加载入口，5 项均 `ImportError`。
- 在仓库外目录用 `python -I` 和绝对路径 `spec_from_file_location()` 加载入口，只提供第三方依赖目录，失败于 `ModuleNotFoundError: agent_types`。
- 正向对照：把根运行时文件复制到独立目录，并由加载器显式提供该目录给 `sys.path`，可以完成求解。说明根文件闭包有正证据，但不等于无需加载器路径配合的隔离入口已通过。

此处依据的是已写入 ENTRY-002/TEST-IMPORT-001 的本地验收条件，不是推测线上必定按这些场景运行。删除入口的 `llm_client` 导入只消除了一个碰撞面，不能关闭全部污染矩阵。

修复验收：建立完整正式导入闭包，明确路径与模块所有权，在干净子进程中执行预载矩阵和仓库外加载；结构调整仍须单独验证，不与数学策略同时修改。

## F6 · P2：显式本地适配器引入跨题 usage 竞争

位置：`local_support/xh202627_local_adapter.py:21–26,49–52`；共享实例由 `main.py:215` 创建。

默认批处理并发复用一个 Agent 和适配器，适配器把最近一次 metadata 存入共享 `_last_meta`。两个请求交错执行时，A 的 callback 写入 11 token，B 写入 29 token，A 返回后再 `read_usage()` 会读取 B 的数据。

利用两个线程与事件控制交错，实测 `(A, B)` 的读数为 `(29,29)`，期望 `(11,29)`。因此本地单题预算会重复记账/串题，可能错误提前停止或漏记超额；正式未注入适配器的路径不受这条本地缺陷影响。

修复验收：响应与 usage 必须按请求绑定并在当前调用内完成记账，避免跨调用的共享“最近响应”；覆盖同一 Agent 并发与工具循环末轮的 usage 归属。

## 完成声明与下一次验收

| R1 项 | 独立判断 |
| --- | --- |
| R1-1 三参数公开调用 | 通过已测边界；严格关键字-only client + 私有属性陷阱也通过 |
| R1-2 宽构造器/本地适配 | 未完成，见 F1、F6 |
| R1-3 trace 脱敏 | 未完成，见 F2 |
| R1-4 完整生命周期 | 未完成；验证预算耗尽保留候选这一局部功能已通过原测试 |
| R1-5 截断隔离 | 未完成，见 F4 |
| 导入门禁 | llm_client 预载和有路径支持的根闭包通过；完整污染矩阵及无仓库路径的隔离加载失败 |

`--formal` PASS 不等同于以上行为门禁 PASS。当前门禁改动修正了文档伴随检查和拓扑误报，但并未增加这些验收能力。本次没有发现 prompt 文件、候选数/温度配置或答案等价模块被修改；三参数投影导致正式路径不发送 tools/thinking_mode 的行为变化已有文档记录，未来实验仍需区别本地适配器路径。

README 与工程规范中的“全部完成”“唯一剩余条件”等措辞需要在修复时一并更正；AGENTS 和维护 Skill 开头仍称活动运行时等于旧锚点，也应同步当前阶段事实。现阶段应保留 R1，按 F1–F5 的阻断项补齐回归，再修复本地 F6，并重新进行完整离线验收。第二次正式评测仍需单独取得证据，本次未执行。

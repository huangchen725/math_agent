# 2026-09-01 官方 112 题请求前故障复盘

## 1. 证据范围

- 原始脱敏日志：`eval_log_3108e65d8b7a4094b5f6356e17b8380c.log`
- 日志 SHA-256：`b132417751272398f6bb13af4ef6dad141a4fb6e7355bb7a44ed5557e9ced202`
- 平台实际拉取提交：`c088a84f936a6de8e791ec15bd2ddb7a04020f7d`
- 输入 SHA-256：`7f2499c53f52cbcb17dcab7cc4b99c9e79f53e23c1392587289a02695284201f`
- Agent 阶段：2026-09-01 08:14:05.520Z 至 08:14:47.032Z，约 41.5 秒
- 平台环境：Python 3.11，lagent 0.5.0rc3
- 官方 baseline 契约核验：[`InternLM/Challenge-Cup-2026` 提交 `43be244a`](https://github.com/InternLM/Challenge-Cup-2026/tree/43be244a880d64a1f9d3a631aa7d9e976f26c17b)

日志未公开逐题异常类型、题面、模型选择、请求参数或 runner 实现。本报告只陈述可由聚合日志和本地等价复现支持的结论，不把候选根因写成已证实的线上唯一根因。

## 2. 聚合结果

| 指标 | 值 |
| --- | ---: |
| 题目总数 | 112 |
| success | 0 |
| error | 112 |
| correct / incorrect / invalid | 0 / 0 / 112 |
| 官方 client request / attempt / retry | 0 / 0 / 0 |
| prompt / completion / total tokens | 0 / 0 / 0 |
| runner 状态 / 退出码 | completed / 0 |
| infrastructure errors | 0 |

因此该轮不是“数学正确率 0%”。112 道题全部在产生一次官方模型请求之前进入 error，Judge 只能把 112 条都记为 invalid。它不能用于衡量当前 Agent 的数学能力、截断率或 P1 收益。

## 3. 最强本地复现：未知 client 的三参数边界

`c088a84` 的普通候选、verifier、critic、reflection、recovery、emergency 和 fallback 都在核心参数外传 `thinking_mode`；工具轮另传 `tools` 与 `tool_choice`。此前所谓 strict fake 使用 `chat(**kwargs)`，不但没有覆盖三参数签名，还在公开接口兼容测试中反向锁定了 `thinking_mode=False` 必须到达注入 client。

本轮从 Git 归档分别创建 `c088a84f936a6de8e791ec15bd2ddb7a04020f7d` 与 `350a267f42d889ddb94ee59876eebf7837caff14` 的隔离目录，使用同一题面 `计算 2+2。` 和同一确定性配置：`tool_candidates=0`、`plain_candidates=3`、每候选 verifier 1 次、关闭 tools/critic/reflection。严格 fake 没有 `**kwargs`：

```python
def chat(self, messages, temperature, max_tokens):
    ...
```

对照 fake 只额外声明 `thinking_mode=None`。结果如下：

| 代码 | fake | 进入 `chat()` 方法体 | `solve()` 结果 | 可见异常 |
| --- | --- | ---: | --- | --- |
| `c088a84f` | 三参数 | 0 | `未解出` | `TypeError: ... unexpected keyword argument 'thinking_mode'` |
| `c088a84f` | 允许 `thinking_mode` | 6 | `最终答案：4` | 无 |
| `350a267f` | 三参数 | 0 | `未解出` | 内层收敛，公开 trace 无异常正文 |
| `350a267f` | 允许 `thinking_mode` | 6 | `最终答案：4` | 无 |

这组实验闭环证明：**若线上注入 client 只接受三个核心参数，契约外 kwargs 足以在 HTTP 前造成与官方聚合日志一致的 0 请求整批失败**；它也是两个历史版本共同存在、此前测试漏掉的真实兼容缺陷。历史 `350a267` 的 23/112 仍是有效历史观测，但在三参数假设下原样重提不能作为当前环境定锚，必须制作只加兼容投影、数学策略不变的新基线。

证据边界也必须保留。[官方固定 baseline 的核心示例](https://github.com/InternLM/Challenge-Cup-2026/blob/43be244a880d64a1f9d3a631aa7d9e976f26c17b/README.md#L76-L88)确实只使用三参数，但[同一提交的自带 `InternChatClient` 说明](https://github.com/InternLM/Challenge-Cup-2026/blob/43be244a880d64a1f9d3a631aa7d9e976f26c17b/README.md#L281-L314)明确接受 `thinking_mode`、`tools` 和额外请求参数，官方测试还验证 `tool_choice` 透传。因此脱敏日志没有逐题异常类型和线上 client 版本时，不能把“平台在 8 月 29～31 日收紧”写成已有变更记录的事实，也不能断言这是线上唯一根因。它是当前最强、可完整复现的候选根因；私有 marker 读取、同名方法误探测和下节入口导入仍是另外几个已确认的请求前缺陷。

## 4. 同时发现的第二个请求前断点

S1 把根 `user_agent.py` 收缩为 `from math_agent...` 门面。此前的入口测试都从仓库根目录启动，解释器自动把项目根放进导入路径。按官方式 `spec_from_file_location()` 从仓库外加载、同时移除项目根后，`c088a84` 可稳定复现：

```text
ModuleNotFoundError: No module named 'math_agent'
```

官方 baseline 明确正式评测会为每题重新加载模块、构造 Agent，并在独立进程中只调用一次 `solve`。脱敏日志没有给出 worker 的实际 `sys.path`，所以不能断言这就是线上异常；但根门面依赖 judge 当前目录本身是不成立的入口契约，必须独立修复和门禁。

此外，`ModelGateway`/`SolveContext` 构造位于 `solve()` 全局 `try` 之外。任何构造期异常都会直接逃给 runner；fallback 的外围也没有覆盖所有异常。即使它不是本轮唯一原因，这也与“单题失败不逃出公开入口”的设计目标冲突。

## 5. 新核验出的 trace 硬规则

官方 baseline 在 2026-08-06 已把示例 trace 改为元数据，并明确禁止在公开 trace 中保存题面、完整 prompt、模型输入输出、候选解答、最终答案和异常敏感正文。当前项目仍把候选、verifier、critic、工具和选择答案片段写入 trace，存在独立合规缺陷。该缺陷不能单独解释 0 request，但若不在下次提交前关闭，即使恢复模型调用也可能继续产生无效结果或资格风险。

## 6. 本次工作树修复

1. `ModelGateway` 对未知注入 client 只发送 `messages/temperature/max_tokens`；不做签名探测，也不在 `TypeError` 后重试，避免可能的重复真实请求。
2. 项目自有 `InternChatClient` 继续通过名义类型边界取得 `thinking_mode/tools/tool_choice` 和原子 metadata；未知 client 的两个工具候选槽显式改走纯文本 prompt，并记录 `tool_capability_fallback`，不再假装执行了工具。
3. 网关只从注入对象绑定公开 `chat()`，不读取 marker、其它私有字段或同名扩展。
4. 根 `user_agent.py` 仅以自身 `__file__` 所在目录引导唯一运行包，使绝对路径加载不依赖 cwd/PYTHONPATH；没有复制第二份 Agent 实现。
5. gateway/上下文构造纳入顶层异常收敛；只有已创建上下文时才尝试 fallback，fallback 再次失败也返回受控结果。
6. 新增公开 trace 白名单投影，只保留阶段、状态、编号、长度、截断和预算元数据；未知事件/字段失败关闭。
7. 合规门禁新增无 `**kwargs` 的三参数 injected client、隔离解释器绝对路径加载、题面/模型/verifier/答案泄漏哨兵，以及 trace 投影幂等与 JSON 可序列化性质。

当前三参数 fake 在修复工作树中由 0 请求恢复为 6 请求并输出 `最终答案：4`。本次没有改变模型、候选槽数量、温度配置、token 上限、工具轮数、验证、恢复或聚合算法，也没有调用真实 API；但未知注入路径不再显式发送 `thinking_mode=False` 或 tool schema，两个工具槽会变为纯文本候选，因此线上模型默认推理行为、工具能力、请求数、截断和正确率都可能变化，必须重置当前环境基线，不能声称数学能力完全不受影响。

最终离线门禁为 21/21 项通过：196 项测试通过，总语句覆盖率 77.46%；Ruff、compileall、Bandit、Python 3.10/Linux 开发锁闭包、`pip check`、三套依赖漏洞审计、敏感信息扫描、Markdown 链接、竞赛合规探针、few-shot dry-run、runner 与全部评测 CLI 入口均通过。专项回归明确证明严格注入 client 不发生私有属性读取、根入口可由隔离解释器按绝对路径加载、构造期异常被收敛，且公开 trace 投影满足失败关闭、幂等、JSON 可序列化和秘密文本不外泄。

## 7. 验收边界与下一次正式运行

离线测试只能证明已知请求前断点被关闭，不能证明未公开的官方 worker 没有第三种差异。下一次正式结果必须按以下顺序判断：

1. 平台拉取的 commit 必须是包含本修复的明确 SHA。
2. `request_count > 0`、`attempt_count > 0`、`success > 0`；任一为 0，继续按入口故障处理，不讨论正确率。
3. `error=0`、`invalid=0`；若仍失败，必须优先索取或归档脱敏的异常类型/阶段，而不是继续猜测数学策略。
4. 请求门禁通过后，才计算截断率、有效正确率和与 `350a267` 历史有效运行的能力差异。

在得到绑定新 commit 的官方有效运行前，`CLIENT-001` 状态保持“离线修复、官方待验证”。历史 v17/`350a267` 分数保留为历史证据，但原样重提实验停止；后续对照应在其数学策略上只加入相同三参数兼容适配，再建立当前环境新基线。

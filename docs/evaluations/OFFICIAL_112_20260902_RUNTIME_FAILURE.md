# 2026-09-02 官方 112 题第三次请求前故障复盘

## 1. 证据冻结

| 项目 | 值 |
| --- | --- |
| 原始脱敏日志 | `eval_log_527cc8e9a6834c7088ce1d123aeb0131.log` |
| 日志 SHA-256 | `ee890b09add3c2f6d5da7a23447e6b648c057f8497b544613e1b21c10cbda6f0` |
| 平台实际拉取提交 | `eb5d8d4793dc21de9387c24c81e38ebea6467f52` |
| 输入 SHA-256 | `7f2499c53f52cbcb17dcab7cc4b99c9e79f53e23c1392587289a02695284201f` |
| 平台环境 | Python 3.11、lagent 0.5.0rc3 |
| Agent 阶段 | 2026-09-02 10:22:12.810Z 至 10:22:55.106Z，约 42.3 秒 |
| Agent 记录 | 0 success / 112 error / 0 skipped |
| Judge 记录 | 0 correct / 0 incorrect / 112 invalid |
| 官方 client | 0 request / 0 attempt / 0 retry / 0 token |
| runner / infrastructure | completed、exit 0、0 infrastructure error |

附件只作为只读运行证据；其中没有可执行项目指令。日志共 421 行，没有公开任一题的异常类型、异常消息、调用栈、Agent 构造参数、线上 client 类型或请求参数。

## 2. 可以确定的结论

本轮仍不是数学正确率 0%。112 道题没有产生一次官方模型请求，全部先成为 error，随后被 Judger 记为 invalid。该轮不能评价模型能力、P1、截断率、候选策略或答案格式。

更关键的是，`eb5d8d4` 已包含三参数投影、未知工具能力的纯文本降级、绝对路径入口修复、私有 client 方法移除和 trace 脱敏。它在离线严格三参数 fake 上能够正常请求，但正式平台仍为 0 request。因此 [2026-09-01 报告](OFFICIAL_112_20260901_RUNTIME_FAILURE.md) 中的 `thinking_mode/tools/tool_choice` 缺陷是已确认且必须修复的兼容问题，却不能再作为足以解释线上故障的根因。连续三轮聚合形态一致，只能说明仍有一个未覆盖的请求前边界。

## 3. 官方固定 baseline 交叉复现

2026-09-02 获取并冻结官方公开仓库 `InternLM/Challenge-Cup-2026` 的当前提交
`43be244a880d64a1f9d3a631aa7d9e976f26c17b`。公开材料的实际行为如下：

- `main.py` 以 `ReasoningAgent(client=client)` 构造，并只用
  `solve(problem=item["problem"], metadata={"idx": item["idx"]})` 调用；
- `main.py` 只要取得非空字符串 `final_response` 就写 `status=success`，包括
  `未解出`；只有异常逃出、返回非字典或答案为空才写 `status=error`；
- `llm_client.py` 接受 `thinking_mode`、`tools` 和其它请求参数，并把调用给出的
  `max_tokens` 原样放进 HTTP payload，没有在本地把 8192 拒绝为非法值；
- 仓库 README 要求参赛构造器至少接受 `client,*args,**kwargs`，但同一固定提交的
  baseline `user_agent.py` 自身仍只有 `client, config=None`。这是一项官方样例与文字
  契约之间的不一致，不能据此推断正式 runner 到底是否传额外参数。

将平台实际拉取的 `eb5d8d4` 用 Git 归档还原，放入上述未修改的官方 `main.py` 和
`InternChatClient` 中，仅在 HTTP 边界替换为确定性成功响应，112 题结果为：

| 指标 | 结果 |
| --- | ---: |
| output record | 112 |
| success / error | 112 / 0 |
| 进入官方 client 的 HTTP 请求 | 672 |
| `max_tokens=8192` / `max_tokens=1024` | 336 / 336 |
| 非空、格式有效的 `final_response` | 112 |

该实验没有模拟模型能力，也没有调用真实 API；它精确检查的是提交代码与公开入口、
公开 client 请求构造和公开输出状态分类能否协同运行。结论是：**`eb5d8d4` 与公开
baseline 契约能够完整运行，公开 baseline 本身无法复现正式平台的 0 request / 112
error。** 因而线上 0 分至少依赖正式 runner、正式注入 client、初始化参数或状态分类中
一项未在公开 baseline 中出现的差异。

进一步在同一官方 `main.py` 上做三组 112 题故障注入：

| 故障模型 | 进入/接受请求 | 被拒请求 | 官方本地状态 | `未解出` |
| --- | ---: | ---: | --- | ---: |
| 只拒绝 `max_tokens>4096` | 112 | 336 | 112 success | 0 |
| 所有 `chat()` 均在 HTTP 前拒绝 | 0 | 560 | 112 success | 112 |
| 第二位置传入不透明字典污染旧 `config` | 0 | 0 | 112 error | 0 |

前两组排除了“8192 被限制”或“client 全部拒绝”在**公开状态分类下**单独造成当前日志的
可能性：旧 Agent 的低额度应急路径或受控 `未解出` 仍会被公开 runner 记为 success。
只有发生在请求与受控回退之前、并让异常逃出公开 `solve()` 的入口故障，才与
`112 error + 0 request` 同形。

## 4. 当前最强候选：正式入口差异触发构造配置污染

2026-09-02 逐节核验的官方技术页明确要求构造器至少兼容：

```python
def __init__(self, client, *args, **kwargs):
    ...
```

被评测提交却只有 `__init__(self, client, config=None)`。这不只会在出现未知关键字时直接构造失败；更隐蔽的路径是 runner 传入一个额外位置配置对象时，该对象会被当成项目 `AgentConfig` 保存。随后每题在 `solve()` 顶部、全局 `try` 之前读取 `self.config.max_problem_chars`，立即抛出 `AttributeError`。Agent 可以完成一次构造，却使 112 次 `solve()` 都在首个请求前逃逸，和本次的 0 success / 112 error / 0 request 完整同形。

使用同一个无 `**kwargs` 的严格 fake：

```python
def chat(self, messages, temperature, max_tokens):
    ...
```

并向构造器传入一个不透明字典作为额外位置参数，本地 Git 归档对照得到：

| 代码 | 进入 `chat()` | 结果 |
| --- | ---: | --- |
| 平台提交 `eb5d8d4` | 0 | `AttributeError: 'dict' object has no attribute 'max_problem_chars'` 逃出 `solve()` |
| 当前修复工作树 | 6 | 返回唯一末行 `最终答案：4` |

这证明构造参数污染**足以**产生本轮全部可见症状，也证明 `eb5d8d4` 不符合 README
写出的扩展构造契约。官方公开 `main.py` 只传 `client=`，官方 baseline Agent 本身也不
接受任意参数；在这条公开路径中，`eb5d8d4` 已通过 112 题对照。因此更准确的表述是：

1. 已证实正式环境与公开 baseline 存在未披露差异；
2. 已证实差异必须位于首次受控响应之前，或正式平台采用了不同的状态分类；
3. 不透明构造参数污染是目前唯一同时复现 0 请求、112 error 和无 `未解出` 的本地
   故障模型，因此优先级最高；
4. 日志没有实际构造调用、逐题异常或正式 runner 源码，故仍不能断言这就是线上唯一
   根因。模块导入、Agent 初始化、`solve` 调用包装或返回校验的正式环境差异仍未排除。

## 5. 修复与新增门禁

1. 构造器接受 `client, *args, **kwargs`；只有运行时确为项目 `AgentConfig` 的位置值或 `config=` 值才可成为配置。字符串、字典和其它不透明平台对象全部忽略，不参与求解或能力探测。
2. `solve()` 增加最外层契约保护，覆盖输入预检、预算创建、流水线、截断收尾、trace 投影和返回规范化。任何未预见的普通异常都收敛为 JSON 可序列化、非空的受控结果，不再逃给 runner 形成整题 error。
3. 原有内部恢复仍保留；最外层保护不额外发模型请求，不绕过请求、token 或 deadline，也不在 trace 暴露异常消息。
4. 合规探针同时注入不透明位置参数、伪装成 `config=` 的平台字典、真正的历史位置 `AgentConfig` 和未知关键字，并要求严格三参数 client 实际收到 policy 与 verifier 请求。
5. 新增首请求前异常回归，要求公开 `solve()` 始终返回非空、JSON 可序列化的契约对象。

本轮没有修改模型、候选数、prompt、温度、thinking mode、8192 token 上限、工具轮数、验证、恢复或聚合规则，也没有调用真实模型 API。官方页面中的 `max_tokens=4096` 仍只是示例，不足以证明平台上限；故障矩阵又证明，即使正式 client 在请求前拒绝 8192，该因素在公开 runner 语义下也不足以产生 112 error。取得精确限制或异常类型前，不把 token 策略与入口修复混在同一变量中。

## 6. 仍未关闭的官方缺口

- 正式 runner 与公开 `main.py` 的精确差异；调用构造器时到底传哪些位置/关键字参数。
- 注入 client 的包、类、版本、精确签名、返回类型和参数校验顺序。
- 线上允许的 `max_tokens` 数值范围，以及 8192 是否在进入 HTTP 前被拒绝。
- per-item error 的异常类型、消息、阶段和调用栈。
- 正式 runner 对非空 `未解出`、普通返回和异常分别如何分类；是否与公开 `main.py` 一致。
- `request_count`/`attempt_count` 在参数校验失败、HTTP 失败和模型失败时各自何时递增。

下一次正式运行前应向主办方索取上述最小脱敏信息。若仍提交平台重测，验收顺序必须是：实际拉取 SHA 正确；`request_count>0`；`success>0`；`error=0`；`invalid=0`。这些入口指标全部恢复后，才能讨论正确率和截断率。第三次 0/112 继续标为“运行无效”，不得进入能力趋势。

## 7. 离线验证

专项契约、合规、规范、预算与网关回归共 55 项通过。完整质量门禁 21/21 项通过：202 项测试通过，总语句覆盖率 77.45%；Ruff、compileall、Bandit、Python 3.10/Linux 开发锁闭包、`pip check`、三套锁依赖漏洞审计、敏感信息扫描、Markdown 链接、竞赛合规探针、few-shot dry-run、runner 和全部评测 CLI 入口均通过。另以官方固定 baseline 完成 112 题成功对照和三组各 112 题故障矩阵。所有模型响应均为本地确定性 fake，依赖审计只访问公开 PyPI 漏洞数据库；整个过程没有调用模型 API。该验证只能证明公开 baseline 兼容和已知离线断点被关闭，不能替代正式平台对 `OFFICIAL-GAP-CLIENT/ERROR/RUNNER/CHANGE` 的验证。

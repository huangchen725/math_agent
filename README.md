# XH-202627 数学推理智能体

本仓库是“基于 Intern-S1 的数学智能体设计与推理创新”竞赛项目。当前实现采用 **领域路由 → 多候选生成 → 工具计算 → 验证 → 反思 → 聚合** 的单一流水线。

> **恢复状态（2026-09-06）**：R0 已在 `ba63ac0` 完成官方定锚：112 success、1069 次请求、24/112 correct（21.43%）。独立验收发现的 R1 缺口现已修复，Python 3.10/3.12 各通过 187 个离线测试。入口支持不透明附加构造参数，client 只走三参数公开调用；公开 trace 只保留白名单事件与数值预算；初始化至输出失败关闭；初始候选、反思与恢复统一校验完整答案；本地 usage/finish_reason 随请求返回；正式依赖从入口位置加载至独立命名空间。`--formal` 包含实际行为测试。阶段仍为 R1，第二次正式评测尚未执行；离线通过不代表官方兼容性或正确率提升。S1～S6 仍保存在 `archive/s1-s6-1fc98b7`。

> **当前离线进度**：R1 修复已提交为 `9126c04`。其上 Q0/Q1 离线工作流和实验实现已完成，两个 Python 版本各 371 项测试通过。真实模型基线、收益与官方验收仍分别待补。

> **最新正式结果（2026-09-06）**：新日志抓取较早的 `c009929`：112 success / 0 error，10 correct / 50 incorrect / 52 invalid（8.93%），607 次请求中 512 次截断（84.35%）。它未包含 `9126c04` 修复或 `6d42d2c` 的 Q0/Q1，以上“正式验收待补”指这些后续版本。当前输出预算仍需真实模型诊断，离线通过不能证明退化已修复。详见 [本次正式诊断](docs/evaluations/OFFICIAL_112_20260906.md)。

> **截断缺陷修复（本轮工作区）**：强制单次输出不超过用户确认的官方 8192 上限，修复生成预算耗尽丢弃已有合格答案、未知验证被判错及冲突元数据覆盖截断；明确 length 的空内容允许原预算内恢复。默认 unknown 不触发纠错，Q1 calibrated_verifier 仅进一步收紧标签格式。两个 Python 版本各 452 项完整门禁通过，详见 [修复与验证](docs/evaluations/TRUNCATION_REPAIR_20260906.md)。这些代码修复不代表真实截断率已降低；更新后的 18 次诊断计划全部在 8192 内，真实执行需单独额度授权。

最新 0 请求事故的本地根因已经闭环：judge 预载的同名 `llm_client` 被项目裸导入复用，随后 `isinstance` 误把官方 client 当成项目私有 client，并在第一次请求前访问不存在的 `chat_with_metadata`。永久防复发规则和重建顺序见 [工程底线与重建规范](docs/ENGINEERING_SPECIFICATION.md)，完整证据见 [2026-09-04 官方运行故障报告](docs/evaluations/OFFICIAL_112_20260904_RUNTIME_FAILURE.md)。该根因能解释提交 `1fc98b7`，不能被扩大为此前所有包结构 0 分的唯一原因。

## 核心接口

修复范围、失败反例与验证证据见 [R1 修复与复验](docs/evaluations/R1_REPAIR_VALIDATION_20260905.md)。

```python
ReasoningAgent(client).solve(problem, metadata)
# -> {"final_response": str, "trace": list[dict]}
```

- `client` 由调用方注入，代码中不保存 API key。
- `final_response` 保留选中候选的推理文本，并且最后只保留一行规范化的 `最终答案：...`；答案体不带解释性句子，常见记号统一为稳定形式。
- `trace` 记录求解阶段和数值预算；不包含题面、候选、答案、工具结果或异常原文。
- 构造形式兼容 `ReasoningAgent(client, config=None, *args, local_adapter=None, **kwargs)`；只有本模块的 `AgentConfig` 被用作配置，其它附加对象被忽略。本地适配器通过 `complete()` 返回绑定该请求的 response/metadata，不提供最近响应 getter。
- 完整组件边界、数据流、配置和安全约束只以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。
- 官方文件、消息、冲突口径和未公开契约见 [官方材料证据登记册](docs/OFFICIAL_MATERIALS_REGISTER.md)；赛事红线见 [竞赛合规清单](docs/COMPETITION_COMPLIANCE.md)。

## 环境与安装

要求 Python 3.10+。先创建虚拟环境：

```bash
python -m venv .venv
```

Linux/macOS：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

开发检查和 Gradio 演示分别使用：

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-demo.txt
```

## 配置

将 `.env.example` 复制为本地 `.env`，不要提交密钥：

```powershell
Copy-Item .env.example .env
```

| 变量 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `INTERN_API_KEY` | 是 | 无 | Intern API token |
| `INTERN_API_BASE` | 否 | 官方 Chat Completions 地址 | OpenAI 兼容端点 |
| `INTERN_MODEL` | 否 | `intern-s2-preview-397b` | 本地模型名；正式注入 client 由平台控制 |
| `LOCAL_MAX_CONCURRENCY` | 否 | `3` | 本地并发，必须为正整数 |

## 运行

批量处理 JSONL：

```bash
python main.py --input_file sample_data/dev.jsonl --output_dir outputs/run-001
```

输入每行至少包含非空 `problem`；可选 `idx` 只能使用字母、数字、下划线和连字符。每题结果原子写入独立 JSON 文件，只有有效的成功记录会在断点续跑时跳过。结束后会生成 `_run/run_summary.json`，只记录输入文件名及 SHA-256、模型、耗时和成功/失败/跳过计数，不保存题面。

启动本地演示：

```bash
python demo.py
```

演示默认监听 `127.0.0.1:7860`，会使用真实 API。

## 验证

Q0/Q1 离线开发已按 2026-09-06 用户决策并行推进，R1 官方验收仍单独等待。当前 Q0 冻结集为 U-MATH 的 144 道公开英文大学数学题（六领域，开发/留出各 72），仅在被忽略的 `outputs/q0-umath-v4/` 保存；许可原文和来源版本保存在 `outputs/q0-umath-source-v2/`。它不是赛事隐藏题集，不保证预训练独立，也未完成实际模型运行或双人盲审。详见 [Q0/Q1 离线诊断报告](docs/evaluations/Q0_Q1_OFFLINE_20260906.md)。

离线准备与比较命令（均不调用模型）：

```bash
python -m evaluation.q0_pipeline verify outputs/q0-umath-v4
python -m evaluation.q1_experiments outputs/q0-umath-v4 --output outputs/q1/dev-plan.json
python -m evaluation.q0_pipeline score outputs/q0-umath-v4 RUN_DIR PLAN_JSON --variant baseline --output SCORE_JSON
python -m evaluation.q0_pipeline compare BASE_SCORE CANDIDATE_SCORE --output COMPARISON_JSON
python -m evaluation.q0_pipeline review-packet outputs/q0-umath-v4 SCORE_JSON --salt REVIEW_SALT --output PACKET_JSON
python -m evaluation.q0_pipeline review-merge PACKET_JSON REVIEWER_A_JSON REVIEWER_B_JSON --output REVIEW_RESULT_JSON
```

从原始来源重建：`python -m evaluation.import_umath OUTPUT_SOURCE` 只下载公开数据；然后执行 `python -m evaluation.q0_pipeline freeze OUTPUT_SOURCE/records.jsonl NEW_BUNDLE`。冻结文件、题号、近重复、来源、代码/配置和运行输出指纹不一致时拒绝使用。旧 v1–v3 为被审核淘汰的中间产物。

Q1 开关通过 `ReasoningAgent(client, local_policy=Q1Policy(...))` 显式启用，默认不启用实验策略。十组计划覆盖基线、五项单变量、critic/reflection/tools 消融和组合候选；`run_plan()` 只接受调用方提供的 client，命令行不会创建真实客户端或自动花费额度。模拟运行必须标记 `fixture`，评分时显式指定 `--execution fixture`；不能据此晋升实验策略或声称正确率提升。正式工具能力与本地适配器实验分开记录。

默认检查不访问外部 API：

```bash
python .agents/policy_guard.py --changed
python -m pytest -q
python -m compileall -q .
python -m ruff check .
python .agents/policy_guard.py --formal
```

所有仓库任务在修改前还必须运行 `python .agents/policy_guard.py --paths <预计路径...>`；不改文件的真实 API、推送、提交、发布等动作使用 `--actions`。守卫会列出本次触发的规则 ID；出现 `[POLICY BLOCK]` 时，工作 agent 必须在执行前报告具体动作、风险和安全替代，并停止触线子动作。完整流程见 [.agents/policies/HARD_RULES.md](.agents/policies/HARD_RULES.md)。阶段已于 2026-09-05 进入 R1：改动版正式检查使用 `--formal`；`--anchor-canary` 仅用于核对历史锚点内容，不能为改动版背书。

对本地 JSONL 题集做题量、领域分布、来源字段、内部重复和 prompt/sample 重合审计，同样不会访问 API：

```bash
python evaluation/audit_dataset.py path/to/benchmark.jsonl
python evaluation/audit_dataset.py path/to/benchmark.jsonl --successes 36 --output outputs/benchmark/audit.json
python evaluation/rescore_report.py path/to/benchmark.jsonl path/to/old_report.json --output outputs/benchmark/rescored.json
python evaluation/generate_internal_benchmark.py --output outputs/private-eval/benchmark.jsonl --manifest outputs/private-eval/manifest.json
python evaluation/score_run.py outputs/private-eval/benchmark.jsonl outputs/private-eval/run --report outputs/private-eval/score.json --review outputs/private-eval/review.jsonl
```

审计和评分命令不访问模型 API。`generate_internal_benchmark.py` 生成18领域、396题的可复现内部合成基准，仅用于项目内压力测试，不能作为官方或与预训练语料独立的成绩。该基准的 35B 实测、资源用量和适用边界见 [内部大规模评测报告](docs/evaluations/INTERNAL_35B_V1.md)。正式题集记录格式见 `evaluation/benchmark.schema.json`。离线判分使用 `evaluation/judge.py` 的四态结果：`correct`、`wrong`、`unknown`、`no_answer`；文字语义或无法证明的等价关系进入 `unknown`，不能用字符串包含关系自动判对。

`verify_math.py` 默认只解析 21 个 few-shot，不访问 API：

```bash
python verify_math.py
```

在线验证必须显式启用并设置请求硬上限；失败项重试也共享这一上限：

```bash
python verify_math.py --execute --max-requests 21
python verify_math.py --execute --max-requests 40 --retry-failures
```

在线模式会产生真实调用、费用和限流影响。

## 目录

```text
.
├── user_agent.py              # 竞赛接口与推理编排
├── agent_types.py             # Candidate/Answer/Verification 内部类型
├── answer_equivalence.py      # 保守答案归一化与等价判断
├── budget.py                  # 单题请求、token、工具与时间预算
├── math_tools.py              # 11 个受限 SymPy 工具
├── tool_executor.py           # 可终止子进程与工具硬超时
├── deterministic_verifier.py # 确定性验证原语（尚未接入选择器）
├── domain_prompts.py          # 18 个数学领域提示
├── llm_client.py              # OpenAI 兼容 HTTP 客户端
├── local_support/             # 正式图外显式本地适配器（CLIENT-002）
├── main.py                    # JSONL 批处理与断点续跑
├── demo.py                    # Gradio 演示
├── verify_math.py             # 人工在线验证
├── evaluation/                # 题集审计与保守离线判分
├── sample_data/               # 可公开的小型输入样例
├── tests/                     # 无网络回归测试
├── .agents/skills/            # 仓库级 Codex skill
├── .agents/policies/          # 工作红线触发协议与机器规则清单
├── .agents/policy_guard.py    # 修改前后与正式候选规则守卫
├── docs/                      # 审计与优化路线
└── ARCHITECTURE.md            # 唯一架构文档
```

## 安全与协作

- 不提交 `.env`、token、私有题集或包含敏感题面的运行输出。
- 模型产生的工具参数始终按不可信输入处理，必须保留解析白名单和资源边界。
- 不根据单次随机结果修改候选数、温度或 token 预算；先固定数据集并保留实验记录。
- 评测集必须记录来源、许可、数据划分和难度；进入正式盲测前必须排除与 prompt few-shot、样例和开发集的重合。
- 协作规则见 [AGENTS.md](AGENTS.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 每个项目 Skill 都有 `PROJECT_POLICY.md`；使用第三方 Skill 也不能绕过全局红线和授权边界。
- 安全边界见 [SECURITY.md](SECURITY.md)，缺陷与路线见 [审计与优化方案](docs/AUDIT_AND_OPTIMIZATION.md)。
- 任何重新拆分必须保持根入口真实声明 `ReasoningAgent`，禁止用可碰撞的通用模块类身份开启私有 client 能力，并通过官方预加载顺序、严格三参数 client、隔离导入和模块污染矩阵。
- [技术报告](技术报告.md) 与 [创新点说明](创新点说明.md) 是比赛陈述材料，不作为架构规范；提交信息见 [SUBMISSION_INFO.md](SUBMISSION_INFO.md)。

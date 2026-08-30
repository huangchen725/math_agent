# XH-202627 数学推理智能体

本仓库是“基于 Intern-S1 的数学智能体设计与推理创新”竞赛项目。当前实现采用 **领域路由 → 多候选生成 → 工具计算 → 验证 → 反思 → 聚合** 的单一流水线。

## 核心接口

```python
ReasoningAgent(client).solve(problem, metadata)
# -> {"final_response": str, "trace": list[dict]}
```

- `client` 由调用方注入，代码中不保存 API key。
- `final_response` 保留选中候选的推理文本，并且最后只保留一行规范化的 `最终答案：...`；答案体不带解释性句子，常见记号统一为稳定形式。
- `trace` 记录领域判断、题型长度目标、候选生成、工具调用、验证、截断恢复、反思、最终答案来源和单题预算摘要；截断事件只保存阶段、token 与处理状态，不保存残缺回复。
- 完整组件边界、数据流、配置和安全约束只以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。

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
| `INTERN_MODEL` | 否 | `intern-s2-preview` | 模型名 |
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

默认检查不访问外部 API：

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

对本地 JSONL 题集做题量、领域分布、来源字段、内部重复和 prompt/sample 重合审计，同样不会访问 API：

```bash
python evaluation/audit_dataset.py path/to/benchmark.jsonl
python evaluation/audit_dataset.py path/to/benchmark.jsonl --successes 36 --output outputs/benchmark/audit.json
python evaluation/rescore_report.py path/to/benchmark.jsonl path/to/old_report.json --output outputs/benchmark/rescored.json
python evaluation/generate_internal_benchmark.py --output outputs/private-eval/benchmark.jsonl --manifest outputs/private-eval/manifest.json
python evaluation/score_run.py outputs/private-eval/benchmark.jsonl outputs/private-eval/run --report outputs/private-eval/score.json --review outputs/private-eval/review.jsonl
```

审计和评分命令不访问模型 API。`generate_internal_benchmark.py` 生成18领域、396题的可复现内部合成基准，仅用于项目内压力测试，不能作为官方或与预训练语料独立的成绩。该基准的 35B 实测、资源用量和适用边界见 [内部大规模评测报告](docs/evaluations/INTERNAL_35B_V1.md)；同模型在 112 题隐藏集上的低分与截断复盘见 [隐藏集评测复盘](docs/evaluations/OFFICIAL_112_20260829.md)。正式题集记录格式见 `evaluation/benchmark.schema.json`。离线判分使用 `evaluation/judge.py` 的四态结果：`correct`、`wrong`、`unknown`、`no_answer`；文字语义或无法证明的等价关系进入 `unknown`，不能用字符串包含关系自动判对。

下一版本的能力优化使用 P0 冻结与配对协议。公开大学竞赛对照来自固定版本的 PutnamBench，生成的第三方题面和盲审材料只放在被忽略的 `outputs/`；公开数据只能证明同题相对变化，不能声称预训练独立。完整条件见 [能力基线协议](docs/evaluations/ABILITY_BASELINE_PROTOCOL_V1.md)。主要离线入口为：

```bash
python evaluation/import_putnam_bench.py path/to/PutnamBench/informal/putnam.json --source-commit COMMIT --output outputs/ability/benchmark.jsonl --manifest outputs/ability/source.json --recent-count 36
python evaluation/freeze_experiment.py outputs/ability/benchmark.jsonl --output outputs/ability/baseline-manifest.json --experiment-id baseline-v1 --model intern-s2-preview --dataset-role public_test --repetitions 3 --concurrency 1
python evaluation/blind_review.py create outputs/ability/benchmark.jsonl outputs/ability/old-run outputs/ability/new-run --packet outputs/ability/review.jsonl --key outputs/ability/review-key.json
python evaluation/blind_review.py resolve outputs/ability/review-completed.jsonl outputs/ability/review-key.json --baseline-adjudications outputs/ability/old-adjudications.jsonl --candidate-adjudications outputs/ability/new-adjudications.jsonl
python evaluation/score_run.py outputs/ability/benchmark.jsonl outputs/ability/old-run --adjudications outputs/ability/old-adjudications.jsonl --report outputs/ability/old-score.json
```

`paired_compare.py` 只在三轮报告、两份干净提交生成的冻结 manifest 和新版截断门禁均存在时，才可能给出“能力提升已获得证据”的结论。冻结旧版真实基线已完成 120 题 × 3 次，共 3,173 个模型请求；可靠性门禁通过，数学正确率仍等待候选版本完成后的匿名 A/B 盲审。匿名汇总见 [P0 公开能力基线结果](docs/evaluations/ABILITY_BASELINE_RESULTS_V1.md)。候选版本运行前必须重新确认费用与额度，单版本硬上限仍为 7,200 次请求。

截断专项压力集固定在 `evaluation/truncation_stress.jsonl`，包含 18 领域各 2 题，只用于长输出与恢复可靠性，不用于声称实际正确率。正式在线压力测试应对同一提交连续运行 3 次，将各次 `score_run.py` 报告交给门禁：

```bash
python evaluation/truncation_gate.py outputs/truncation/run-1-score.json outputs/truncation/run-2-score.json outputs/truncation/run-3-score.json --output outputs/truncation/gate.json
```

门禁要求请求级截断点估计和单侧 95% Wilson 上界都低于 5%，候选生成自身截断率低于 5%，恢复覆盖率 100%，无截断残句进入最终答案，`invalid=0`，且保守正确率不明显低于 22% 基线。该命令本身不访问 API；生成三个在线运行目录仍会产生真实调用和费用。

当前 35B 三轮真实压力结果为 800 次请求、0 截断，单侧 95% Wilson 上界 0.3371%，详细冻结条件与边界见 [35B 截断专项压力测试](docs/evaluations/TRUNCATION_STRESS_35B_V1.md)。

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
├── agent_types.py             # 调用结果与 Candidate/Answer/Verification 内部类型
├── answer_equivalence.py      # 保守答案归一化与等价判断
├── budget.py                  # 单题请求、token、工具与时间预算
├── math_tools.py              # 11 个受限 SymPy 工具
├── tool_executor.py           # 可终止子进程与工具硬超时
├── deterministic_verifier.py # 确定性验证原语（尚未接入选择器）
├── domain_prompts.py          # 18 个数学领域提示
├── llm_client.py              # OpenAI 兼容 HTTP 客户端
├── main.py                    # JSONL 批处理与断点续跑
├── demo.py                    # Gradio 演示
├── verify_math.py             # 人工在线验证
├── evaluation/                # 题集、审计、保守判分与截断门禁
├── sample_data/               # 可公开的小型输入样例
├── tests/                     # 无网络回归测试
├── .agents/skills/            # 仓库级 Codex skill
├── docs/                      # 审计与优化路线
└── ARCHITECTURE.md            # 唯一架构文档
```

## 安全与协作

- 不提交 `.env`、token、私有题集或包含敏感题面的运行输出。
- 模型产生的工具参数始终按不可信输入处理，必须保留解析白名单和资源边界。
- 不根据单次随机结果修改候选数、温度或 token 预算；先固定数据集并保留实验记录。
- 评测集必须记录来源、许可、数据划分和难度；进入正式盲测前必须排除与 prompt few-shot、样例和开发集的重合。
- 协作规则见 [AGENTS.md](AGENTS.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 安全边界见 [SECURITY.md](SECURITY.md)，缺陷与路线见 [审计与优化方案](docs/AUDIT_AND_OPTIMIZATION.md)。
- [技术报告](技术报告.md) 与 [创新点说明](创新点说明.md) 是比赛陈述材料，不作为架构规范；提交信息见 [SUBMISSION_INFO.md](SUBMISSION_INFO.md)。

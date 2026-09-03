# XH-202627 数学推理智能体

本仓库是“基于 Intern-S1 的数学智能体设计与推理创新”竞赛项目。当前正式实现采用 **领域路由 → 三个纯文本候选 → 每候选一次模型验证 → 多数票/置信度选择 → 答案规范化** 的单一保守流水线。候选/验证数量及工具、确定性证据优先和 critic/reflection 的旧配置字段只兼容历史构造，不能改变固定 3×1 协议或重新启用第二条正式路径。

## 核心接口

```python
from user_agent import ReasoningAgent

ReasoningAgent(client).solve(problem, metadata)
# -> {"final_response": str, "trace": list[dict]}
```

- 构造器兼容平台公开的 `__init__(self, client, *args, **kwargs)`；只有真正的项目 `AgentConfig` 才会被采用，字典、字符串等不透明参数即使占用 `config` 名称也不会污染求解配置。
- `client` 由调用方注入。未知注入客户端只接收公开最小参数 `messages/temperature/max_tokens`；`thinking_mode/tools/tool_choice` 和原子 metadata 仅用于项目自有 `InternChatClient`。代码中不保存 API key。
- `final_response` 保留选中候选的推理文本，并且最后只保留一行规范化的 `最终答案：...`；答案体不带解释性句子，常见记号统一为稳定形式。
- 对外 `trace` 只保留步骤、状态、候选/请求编号、长度和预算等结构化元数据；题面、prompt、候选/工具/验证正文、最终答案与异常消息会在返回前删除。截断事件只保存阶段、token 与处理状态。
- 根 `user_agent.py` 可被平台从任意工作目录按绝对路径加载，并且只依赖同级根目录模块，不依赖 judge 当前目录、预置 `PYTHONPATH` 或 `math_agent/` 子目录。扁平部署用于隔离排查连续四次 `0 request`，线上关联仍待下一次正式评测确认。
- `solve()` 对输入预检到输出投影的完整生命周期失败关闭；最外层保护不会额外发请求或绕过预算，普通异常不得逃成 runner 级整题 error。
- 默认正常题固定发起 6 次公开调用：3 次候选生成和 3 次紧凑验证；另有最多 4 次仅用于截断/整题紧急处理的恢复预算。正式上层不发送工具、批评、反思或确定性验证请求。
- 完整组件边界、数据流、配置和安全约束只以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。
- P1、S1～S6 的不可回退工程规则、历史故障和验收矩阵见 [工程规范](docs/ENGINEERING_SPECIFICATION.md)；赛事红线和执行控制见 [竞赛合规清单](docs/COMPETITION_COMPLIANCE.md)；三份原件、新通知转录、动态官方页面、baseline 版本、冲突口径和未定义技术边界见 [官方材料证据登记册](docs/OFFICIAL_MATERIALS_REGISTER.md)。

## 环境与安装

核心 Agent 与开发工具要求 Python 3.10+；可选 Gradio Demo 要求 Python 3.12+，以使用已修复已知漏洞的界面依赖。先创建虚拟环境：

```bash
python -m venv .venv
```

Linux/macOS：

```bash
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
```

开发检查和 Gradio 演示分别使用各自的哈希锁；安装 Demo 锁时请确认解释器为 3.12+：

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m pip install --require-hashes -r requirements-demo.lock
```

`requirements*.txt` 是维护者调整直接依赖时使用的输入规格；日常安装、CI 和正式交付均使用精确版本与 SHA-256 齐全的 `requirements*.lock`。

## 配置

将 `.env.example` 复制为本地 `.env`，不要提交密钥：

```powershell
Copy-Item .env.example .env
```

| 变量 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `INTERN_API_KEY` | 是 | 无 | Intern API token |
| `INTERN_API_BASE` | 否 | 官方 Chat Completions 地址 | OpenAI 兼容端点 |
| `INTERN_MODEL` | 否 | `intern-s1` | formal 默认值；当前书面证据还允许 `intern-s1-pro`、`intern-s2-preview` |
| `COMPETITION_MODE` | 否 | `1` | 参赛合规模式；拒绝 formal allowlist 外的模型 ID |
| `LOCAL_MAX_CONCURRENCY` | 否 | `3` | 本地并发，必须为正整数 |

自有 HTTP 客户端只接受赛事官方 Intern API 地址。`COMPETITION_MODE=0` 仅用于明确标记的本地非提交实验，不能放宽端点限制，也不能让 allowlist 外模型进入 formal 交付包。当前 FAQ 已撤销 S1-only 推断，但“397/35B”简写、登录后提交页实际选项和版本漂移仍未解决；正式运行必须保存模型选择回执。运行阶段不依赖 GPU、通用外网或动态下载。赛事红线与操作清单见 [竞赛合规清单](docs/COMPETITION_COMPLIANCE.md)，证据冲突和缺口见 [官方材料证据登记册](docs/OFFICIAL_MATERIALS_REGISTER.md)。

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

完整质量门禁不会调用模型 API：

```bash
python -m scripts.run_quality_gates
```

该入口连续执行全量离线测试与 70% 语句覆盖率门槛、Ruff、compileall、Bandit、开发锁的 Python 3.10/Linux 条件依赖闭包检查、`pip check`、三套依赖锁漏洞审计、敏感信息扫描、Markdown 本地链接检查、竞赛合规门禁、few-shot dry-run，以及所有正式 CLI 的帮助入口，并将脱敏后的有界输出写入 `.quality/quality-report.json`。合规门禁验证正式模型和端点、运行时网络入口、隔离解释器中的根入口加载、仅复制根目录 `.py` 时的三参数 `solve()`、参考答案字段隔离、公开 trace 脱敏、JSON 输出契约与发布排除项，不调用模型 API。除 `pip-audit` 查询公开漏洞数据库外，其余检查不需要网络；完全断网时可使用 `--skip-dependency-audit`，但该报告不能授权正式发布包。

迭代时仍可单独运行：

```bash
python -m pytest -q
python -m compileall -q agent.py solver.py user_agent.py evaluation scripts tests main.py demo.py verify_math.py
python -m ruff check .
python -m scripts.check_secrets --include-untracked
python -m scripts.check_markdown_links
```

对本地 JSONL 题集做题量、领域分布、来源字段、内部重复和 prompt/sample 重合审计，同样不会访问 API：

```bash
python -m evaluation.data.audit_dataset path/to/benchmark.jsonl
python -m evaluation.data.audit_dataset path/to/benchmark.jsonl --successes 36 --output outputs/benchmark/audit.json
python -m evaluation.scoring.rescore_report path/to/benchmark.jsonl path/to/old_report.json --output outputs/benchmark/rescored.json
python -m evaluation.data.generate_internal_benchmark --output outputs/private-eval/benchmark.jsonl --manifest outputs/private-eval/manifest.json
python -m evaluation.scoring.score_run outputs/private-eval/benchmark.jsonl outputs/private-eval/run --report outputs/private-eval/score.json --review outputs/private-eval/review.jsonl
```

审计和评分命令不访问模型 API。`evaluation.data.generate_internal_benchmark` 生成18领域、396题的可复现内部合成基准，仅用于项目内压力测试，不能作为官方或与预训练语料独立的成绩。该基准的 35B 实测、资源用量和适用边界见 [内部大规模评测报告](docs/evaluations/INTERNAL_35B_V1.md)；同模型在 112 题隐藏集上的低分与截断复盘见 [2026-08-29 隐藏集评测复盘](docs/evaluations/OFFICIAL_112_20260829.md)，请求前失败的证据链见 [2026-09-01 运行时故障复盘](docs/evaluations/OFFICIAL_112_20260901_RUNTIME_FAILURE.md) 和 [2026-09-03 第四次运行时故障及扁平化决策](docs/evaluations/OFFICIAL_112_20260903_RUNTIME_FAILURE.md)。正式题集记录格式见 `evaluation/data/benchmark.schema.json`。离线判分使用 `evaluation.scoring.judge` 的四态结果：`correct`、`wrong`、`unknown`、`no_answer`；文字语义或无法证明的等价关系进入 `unknown`，不能用字符串包含关系自动判对。

下一版本的能力优化使用 P0 冻结与配对协议。公开大学竞赛对照来自固定版本的 PutnamBench，生成的第三方题面和盲审材料只放在被忽略的 `outputs/`；公开数据只能证明同题相对变化，不能声称预训练独立。完整条件见 [能力基线协议](docs/evaluations/ABILITY_BASELINE_PROTOCOL_V1.md)。下方冻结命令中的 `intern-s2-preview` 用于复现既有实验；它当前属于 formal allowlist，但历史实验记录本身不能替代本次 AtomGit 模型选择回执：

```bash
python -m evaluation.data.import_putnam_bench path/to/PutnamBench/informal/putnam.json --source-commit COMMIT --output outputs/ability/benchmark.jsonl --manifest outputs/ability/source.json --recent-count 36
python -m evaluation.experiments.freeze_experiment outputs/ability/benchmark.jsonl --output outputs/ability/baseline-manifest.json --experiment-id baseline-v1 --model intern-s2-preview --dataset-role public_test --repetitions 3 --concurrency 1
python -m evaluation.experiments.blind_review create outputs/ability/benchmark.jsonl outputs/ability/old-run outputs/ability/new-run --packet outputs/ability/review.jsonl --key outputs/ability/review-key.json
python -m evaluation.experiments.blind_review resolve outputs/ability/review-completed.jsonl outputs/ability/review-key.json --baseline-adjudications outputs/ability/old-adjudications.jsonl --candidate-adjudications outputs/ability/new-adjudications.jsonl
python -m evaluation.scoring.score_run outputs/ability/benchmark.jsonl outputs/ability/old-run --adjudications outputs/ability/old-adjudications.jsonl --report outputs/ability/old-score.json
```

`evaluation.experiments.paired_compare` 只在三轮报告、两份干净提交生成的冻结 manifest 和新版截断门禁均存在时，才可能给出“能力提升已获得证据”的结论。冻结旧版真实基线已完成 120 题 × 3 次，共 3,173 个模型请求；可靠性门禁通过，数学正确率仍等待候选版本完成后的匿名 A/B 盲审。匿名汇总见 [P0 公开能力基线结果](docs/evaluations/ABILITY_BASELINE_RESULTS_V1.md)。候选版本运行前必须重新确认费用与额度，单版本硬上限仍为 7,200 次请求。

P1 曾完成严格题型验证层：封闭数值表达式、明确数域的有限方程解集、导数、不定积分、极限、留数、数值矩阵行列式、模幂和组合数可在隔离子进程中生成 `pass/fail/unknown` 证据。该成果仍由离线测试覆盖，但为保持当前兼容性实验只有一个变量，正式 `solve()` 暂不调用题型分析或确定性验证，选择器也忽略旧确定性证据；`enable_deterministic_verification=True` 不会恢复该分支。以后若恢复 P1，须从 Git 历史单独提出并完成冻结 A/B，不能把既有工程实现直接写成正确率提升。

截断专项压力集固定在 `evaluation/data/truncation_stress.jsonl`，包含 18 领域各 2 题，只用于长输出与恢复可靠性，不用于声称实际正确率。正式在线压力测试应对同一提交连续运行 3 次，将各次 `evaluation.scoring.score_run` 报告交给门禁：

```bash
python -m evaluation.scoring.truncation_gate outputs/truncation/run-1-score.json outputs/truncation/run-2-score.json outputs/truncation/run-3-score.json --output outputs/truncation/gate.json
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

## AtomGit 正式提交

初赛自动判分不从本仓库当前的 GitHub `origin` 自动取码。官方规则要求把队伍 AtomGit 仓库添加为名为 `atomgit` 的远程并推送 `main`，再在作品页关联仓库、选择模型并点击“提交作品”；只推送代码不会进入评测队列。平台在北京时间 12:00/24:00 抓取当时最新 `main`，因此点击提交后到抓取完成前要冻结分支，随后以 AtomGit 远端 SHA 与本地冻结 SHA 对账。平台不要求填写 commit hash，但本地发布与审计仍使用精确 SHA。截止前还需把最终代码与规定材料打成 ZIP 发组委会邮箱；邮件归档不能替代 AtomGit 自动评测。当前 `atomgit` 地址尚未配置，两类提交回执也未生成，正式提交链路仍是阻断项；具体清单见 [竞赛合规清单](docs/COMPETITION_COMPLIANCE.md)。

## 可复现交付

正式交付包只能从干净 Git 提交生成，并要求同一提交已经通过含依赖审计的完整质量门禁：

```bash
python -m scripts.run_quality_gates
python -m scripts.build_release --output-dir dist
```

正式包直接读取当前提交中的 Git blob，固定 ZIP 条目顺序、时间戳和权限，并附带 `release-manifest.json`、精简质量报告、三份官方原件与新通知转录哈希、动态官方证据 URL/核验日、核验过的 baseline commit、formal 默认值/allowlist/匹配状态、全部文件 SHA-256 和压缩包 `.sha256`。formal 接受 `intern-s1`、`intern-s1-pro`、`intern-s2-preview`；其它模型只能生成明确标记的 draft 实验包。路径白名单、Git 忽略规则、单文件/总大小限制和二次敏感信息扫描会阻止本地密钥、运行输出、原始群截图、二进制伪装、无法完整扫描或意外过大的文件进入包；嵌入的质量报告也单独扫描。正式包成功不等于 AtomGit 已点击提交或完成批次抓取。

开发中的脏工作树只能显式生成标记为 `draft` 的预览包，不能冒充正式产物：

```bash
python -m scripts.build_release --allow-dirty --output-dir dist
```

项目代码当前采用保守的“保留所有权利”声明，不等同于开源授权；第三方依赖和数据仍服从各自许可，边界见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 目录

```text
.
├── user_agent.py              # 可按绝对路径加载的竞赛兼容门面
├── agent.py                   # 唯一 ReasoningAgent 类型源与生命周期边界
├── agent_config.py            # 固定策略与预算配置
├── agent_prompts.py           # 流水线提示词
├── agent_types.py             # 调用、候选、答案与验证类型
├── solver.py                  # 顶层求解编排
├── candidate_*.py             # 候选生成、评估与选择阶段
├── context.py                 # 单题显式 SolveContext
├── model_gateway.py           # 统一模型调用、元数据与预算记账
├── model_calls.py             # 显式模型消息适配
├── response_processing.py     # 答案抽取与最终格式校验
├── trace_sanitizer.py         # 对外 trace 元数据白名单投影
├── truncation.py              # 截断事件状态记账
├── domain_*.py                # 零调用领域路由与 18 领域提示
├── task_router.py             # 暂停于正式路径的题型分析库
├── answer_equivalence.py      # 保守答案归一化与等价判断
├── budget.py                  # 单题请求、token、工具与时间预算
├── math_*.py                  # 工具兼容门面与受限 SymPy 解析
├── tool_*.py                  # 工具实现、注册、循环与隔离执行
├── deterministic_verifier.py # 暂停于正式路径的隔离验证库
├── competition_policy.py      # 正式模型、官方端点与参赛模式校验
├── llm_client.py              # OpenAI 兼容 HTTP 客户端
├── main.py                    # JSONL 批处理与断点续跑
├── demo.py                    # Gradio 演示
├── verify_math.py             # 人工在线验证
├── evaluation/                # 离线评测包
│   ├── data/                  # 数据导入、生成、审计、schema 与压力集
│   ├── scoring/               # 保守判分、重算、汇总与截断门禁
│   ├── experiments/           # 冻结、盲审、配对比较与协议
│   └── io_utils.py            # 共享 JSON/JSONL、哈希与原子写入
├── sample_data/               # 可公开的小型输入样例
├── tests/                     # 无网络回归测试
├── scripts/                   # 质量/合规门禁、密钥/链接检查和确定性打包
├── .github/                   # SHA 固定的 CI 与依赖更新配置
├── .agents/skills/            # 仓库级 Codex skills
│   ├── math-agent-maintainer/ # 项目维护、合规与回归工作流
│   └── property-based-testing/ # 固定版本的第三方属性测试 Skill（仅开发期）
├── docs/                      # 工程/合规规范、审计路线与冻结评测证据
├── requirements*.lock         # 精确版本与制品哈希锁
├── LICENSE                    # 项目代码许可边界
├── THIRD_PARTY_NOTICES.md     # 第三方依赖与数据边界
└── ARCHITECTURE.md            # 唯一架构文档
```

## 安全与协作

- 不提交 `.env`、token、私有题集或包含敏感题面的运行输出。
- 提交前运行包含未跟踪且未忽略文件的敏感信息扫描；正式交付包会再次扫描自身白名单内容。
- 模型产生的工具参数始终按不可信输入处理，必须保留解析白名单和资源边界。
- 不根据单次随机结果修改候选数、温度或 token 预算；先固定数据集并保留实验记录。
- 评测集必须记录来源、许可、数据划分和难度；进入正式盲测前必须排除与 prompt few-shot、样例和开发集的重合。
- 第三方 `property-based-testing` Skill 只辅助开发期的解析、归一化和状态不变量测试，不属于运行时，也不会进入 formal 竞赛包；其固定来源、文件哈希和许可证保存在 Skill 目录内。
- 协作规则见 [AGENTS.md](AGENTS.md)、[工程规范](docs/ENGINEERING_SPECIFICATION.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 安全边界见 [SECURITY.md](SECURITY.md)，缺陷与路线见 [审计与优化方案](docs/AUDIT_AND_OPTIMIZATION.md)。
- [技术报告](技术报告.md) 与 [创新点说明](创新点说明.md) 是比赛陈述材料，不作为架构规范；提交信息见 [SUBMISSION_INFO.md](SUBMISSION_INFO.md)。

# XH-202627 数学推理智能体

> **2026-09-13 核心重构离线验收通过**：普通入口现使用具名 `solver_v2` 候选，覆盖公开检索、独立路线、有界计算、证据选答和按需派发；正式接口、六源加载、False及硬预算不变。旧默认策略显式保留为 `legacy_deployment_policy()`，显式 `Q1Policy()` 仍全关闭。Python3.10/3.12各1372项全量通过；8次线上请求后因传输/协议失败停止，0个完整配对，尚未证明提分。题答仍1054条，方法资料179条；详见 [本批实施与验收](docs/evaluations/SOLVER_V2_20260913.md)。

> **最新正式结果（2026-09-12）**：平台抓取 `1841685`，与已验收 `55f1799` 的代码和资源一致，1054条答案库及快答批次已经进入被测提交，七项部署开关默认开启。成绩27/112 correct（24.11%）、83 incorrect、2 invalid；794请求、93截断（11.71%），Agent约2小时29分。较昨天少对1道，invalid减少5道；墙钟缩短但请求与token增加，不能直接归功于查表。没有命中/核验接受次数，正确率提升仍未体现。详见 [本次报告](docs/evaluations/OFFICIAL_112_20260912.md)。

> **最新正式结果（2026-09-11）**：28/112 correct（25.00%）、77 incorrect、7 invalid，112 success / 0 error；689请求、73次截断（10.60%），Agent约3小时54分。平台抓取的是 `43a6a14`：四项联合策略已默认开启，但尚无昨晚 `dcbe4d0` / `55f1799` 的1054条答案库与快答批次。不能据此评价扩库效果，也不能把相对昨天多对3道当作稳定提分证明。当前本地 `55f1799` 的684个提交文件与昨晚验收包一致；远程是否同步本轮未查询。详见 [本次报告](docs/evaluations/OFFICIAL_112_20260911.md)。

> **2026-09-10提交前复核**：在本地提交 `dcbe4d0` 后补齐快答解析的冲突拒绝：CONDITIONS、CHECK和完整答案体统一拒绝嵌套标签、围栏与隐藏控制符，最终答案不再通过通用提取器选择后一个标记。修补及重新验收记录见 [提交前复核](docs/evaluations/PREPUSH_REVIEW_20260910.md)；下方1114项及首日报告属于修补前的已提交版本。用户负责随后提交推送，本次复核未调用模型API。

> **当前首日候选（2026-09-10晚间）**：普通注入入口已开启1054条公开题答的严格同题核对快答、受限单候选参考、完整正确答案交付修复，并保留简洁补答、有界数学核验、证据选答与先核算后裁决。两种Python完整门禁各1114项通过，四参数False、8192及原预算/依赖/六源加载保持。真实91请求未证明未命中题提分；快答和最终严格回放的适用边界见 [首日实施与验收](docs/evaluations/DAY1_IMPLEMENTATION_20260910.md)。显式Q1Policy仍全关闭，旧基线必须使用冻结源码。

> **最新正式结果（2026-09-10）**：平台已抓取合并后的 `b87e4b9`，本次 **25/112 correct（22.32%）、85 incorrect、2 invalid**；741 请求、76 次截断（10.26%），Agent 约 3 小时 4 分。此次已不是代码未同步，但被测源码中的 B1/B2/K/C 新开关仍全部默认关闭，不能算检索或计算增强的启用实验。工程合并完成，整体提分仍未证实；下一步应针对真实路由误判、完整候选/选答损失和可覆盖实际题型的数学核验推进。详见 [本次报告与建议](docs/evaluations/OFFICIAL_112_20260910.md)。下方按各日期保留历史观测。

> **最新正式结果（2026-09-09）**：同一提交 `9acff7e`、同一输入哈希，本次 **30/112 correct（26.79%）、82 incorrect、0 invalid**；804 请求、78 次截断（9.70%），Agent 约 2 小时 10 分。上一轮同版本为 25/112、8 invalid；结果差异不能归因于尚未进入被测提交的 B1/B2/K/C 工程，也不能证明 invalid 已永久消失。完整核验及比较见 [本次正式报告](docs/evaluations/OFFICIAL_112_20260909.md)。下方有日期记录保留为相应历史状态。

> **2026-09-08 第一批 K/C 已实施并验证**：公开教材检索 `corpus_retrieval`、完整受限任务核验 `bounded_math`、题意条件检查 `condition_checks` 已接入独立 Q1 开关，默认均关闭。Python 3.10/3.12 最终完整门禁各 773 项通过；36 次 397B/False 小批请求完成，0 截断、27,930 token。单阶段正确交付 B1 为 4→3/4、B2 为 2→3/8、C2a 为 5→4/6；最终检索英文/中文明确有用均 2/12，C1 现有公开开发题覆盖 0/72，因此没有启用正式新策略。六文件闭包需包含 `xh202627_corpus.py`，检索需携带 `resources/hefferon-v1/`。实现、回执、参考争议和限制见 [本批验收](docs/evaluations/FIRST_BATCH_20260908.md)。

> **最新正式结果（2026-09-08）**：平台抓取 `9acff7e`（正式求解代码等同 `5c2f7a0`），25/112 correct（22.32%）、79 incorrect、8 invalid；112 success / 0 error。731 请求中 50 次截断（6.84%），总 token 减少但墙钟升至约 3 小时 2 分。上一批为 26/112、0 invalid；提分收益未证实，新增 invalid 需逐题核对。B1/B2 不在被测提交中；后续本地小批结果另见上方验收，默认仍关闭。详见 [本批分析](docs/evaluations/OFFICIAL_112_20260908.md)。下方历史结果按日期理解。

本仓库是“基于 Intern-S1 的数学智能体设计与推理创新”竞赛项目。当前实现先尝试严格同题核对，未能快答时进入领域路由、多候选生成、验证、反思与聚合的单一流水线。

> **2026-09-07 第一批提分工程**：A3→A1→A2→A4→A5 已完成离线实施，Python 3.10/3.12 完整 formal 各 625 项通过。修复有界多行/粗体答案提取和符号补答传递；新增旧响应严格回放、本地小批限额与暂停控制、参考争议匿名复核材料。原实测维持暂停，本轮零 API；不改变模型、提示、候选数与预算，不承诺正式分数增幅。交付与复验见 [第一批工程报告](docs/evaluations/ACCURACY_ENGINEERING_IMPLEMENTATION_20260907.md)。下方有日期的测试数量属于相应历史版本。

> **恢复状态（2026-09-06）**：R0 已在 `ba63ac0` 完成官方定锚：112 success、1069 次请求、24/112 correct（21.43%）。独立验收发现的 R1 缺口现已修复，Python 3.10/3.12 各通过 187 个离线测试。入口支持不透明附加构造参数，client 只走三参数公开调用；公开 trace 只保留白名单事件与数值预算；初始化至输出失败关闭；初始候选、反思与恢复统一校验完整答案；本地 usage/finish_reason 随请求返回；正式依赖从入口位置加载至独立命名空间。`--formal` 包含实际行为测试。阶段仍为 R1，第二次正式评测尚未执行；离线通过不代表官方兼容性或正确率提升。S1～S6 仍保存在 `archive/s1-s6-1fc98b7`。

> **当前离线进度**：Q0/Q1 工程已完成，截断专项修复已提交为 `dfb5ce8`。Q2 已补充预登记、重复配对统计、候选锁定、留出集与交付核验工作流；验证结果见 [Q2 离线报告](docs/evaluations/Q2_OFFLINE_20260907.md)。真实模型基线、收益、人工盲审与官方验收仍分别待补。

> **最新正式结果（2026-09-07）**：平台抓取 `0641043`，26 correct / 86 incorrect / 0 invalid（23.21%），112 success / 0 error，803 请求中 77 次截断（9.59%）。2026-09-08 已核实它合并 `dfb5ce8` 与思考关闭修复，包含 Q0/Q1、尚无 Q2 和答案交付增量；跨批次改善仍不能归因于单一变量。下一目标为提升正确率。公开开发集配对此前因 120 秒读取超时停止：基线完成 6/72、紧凑提示 0/72，累计 38 次请求、已知 53,566 token，另一次失败用量未知。已修复离线判分误判，两版本各 522 项全量门禁通过。用户随后批准重开并允许最长 360 秒等待；v3 采用读取 300 秒、外层 350 秒，现因耗时过长按用户要求暂停：基线 72/72、紧凑提示 11/72，两个执行进程均已退出，不自动续跑。累计 532 次请求、已知 1,153,518 token，另保留历史一笔未知用量；完整配对结论仍缺失。详见 [正式报告](docs/evaluations/OFFICIAL_112_20260907.md)、[首轮实测与后续方案](docs/evaluations/ACCURACY_PILOT_20260907.md) 和 [提分计划](docs/evaluations/ACCURACY_NEXT_20260907.md)。

> **截断缺陷修复（`dfb5ce8`）**：强制单次输出不超过用户确认的官方 8192 上限，修复生成预算耗尽丢弃已有合格答案、未知验证被判错及冲突元数据覆盖截断；明确 length 的空内容允许原预算内恢复。默认 unknown 不触发纠错，Q1 calibrated_verifier 仅进一步收紧标签格式。两个 Python 版本各 452 项完整门禁通过，详见 [修复与验证](docs/evaluations/TRUNCATION_REPAIR_20260906.md)。这些代码修复不代表真实截断率已降低；更新后的 18 次诊断计划全部在 8192 内，真实执行需单独额度授权。

最新 0 请求事故的本地根因已经闭环：judge 预载的同名 `llm_client` 被项目裸导入复用，随后 `isinstance` 误把官方 client 当成项目私有 client，并在第一次请求前访问不存在的 `chat_with_metadata`。永久防复发规则和重建顺序见 [工程底线与重建规范](docs/ENGINEERING_SPECIFICATION.md)，完整证据见 [2026-09-04 官方运行故障报告](docs/evaluations/OFFICIAL_112_20260904_RUNTIME_FAILURE.md)。该根因能解释提交 `1fc98b7`，不能被扩大为此前所有包结构 0 分的唯一原因。

> **2026-09-08 核验与补修**：已取得 `0641043` 源码，确认其正式调用显式传 `thinking_mode=False`；本地快进至 `5c2f7a0` 后保留正式求解行为，修复离线中继丢参数和回放忽略参数差异。旧响应解析诊断与完整请求回放分别标记。历史有日期的三参数、测试数量和未知 SHA 描述只代表当时状态；最新证据见 [参数修复与验收](docs/evaluations/PROTOCOL_REPAIR_20260908.md)。Python 3.12/3.10 完整 formal 各 666 项通过；本轮不调用真实 API，不承诺提升正确率。

## 核心接口

> **2026-09-10 晚间首日候选（本地工程验收通过）**：在43a6a14工程起点上增加公开完整题答库、严格整题的一次核对快答、单候选方法参考及有证明的答案末行修复。库位于 `resources/answer_bank/`，由代码绑定清单摘要、惰性有界读取；丢失或损坏仅关闭检索。三个新开关默认开启，完整状态和真实验收结果见 [首日报告](docs/evaluations/DAY1_IMPLEMENTATION_20260910.md)；没有正式提分回执。

公开语料随上游许可分发，不适用项目代码的保留所有权利声明；单独打包资源时也必须携带 [第三方版权与许可声明](THIRD_PARTY_NOTICES.md)。其中 Notes on Diffy Qs：Copyright © 2008–2026 Jiří Lebl。

> **2026-09-08 B1/B2 实验候选**：`Q1Policy(tool_aware_prompts=True)` 让纯文本生成提示匹配其能力，保留领域数学内容及显式适配器的工具提示；`Q1Policy(concise_recovery=True)` 使用一致的简短补答系统提示，保持 512 上限。两项默认关闭、单独比较，默认请求保持 `9acff7e` 行为。原工程见 [B1/B2 离线报告](docs/evaluations/B1_B2_OFFLINE_20260908.md)，本地小批结果见 [第一批验收](docs/evaluations/FIRST_BATCH_20260908.md)，完整流程收益尚未验证。

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

Q1 开关通过 `ReasoningAgent(client, local_policy=Q1Policy(...))` 显式启用，默认不启用实验策略。计划包含基线、独立策略开关、critic/reflection/tools 消融和原五项组合；新增策略不自动加入 `combined`。`tool_aware_prompts` / `concise_recovery` 分别为 B1/B2 单变量候选。`run_plan()` 只接受调用方提供的 client，命令行不会创建真实客户端或自动花费额度。模拟运行必须标记 `fixture`，评分时显式指定 `--execution fixture`；不能据此晋升实验策略或声称正确率提升。正式工具能力与本地适配器实验分开记录。

Q2 离线入口（默认三次重复，冻结后不得减少候选、重复次数或修改阈值）：

```bash
python -m evaluation.q2_pipeline freeze outputs/q0-umath-v4 outputs/q2/NEW_STUDY
python -m evaluation.q2_pipeline reserve outputs/q2/NEW_STUDY baseline 0
python -m evaluation.q2_pipeline record outputs/q2/NEW_STUDY dev:baseline:0 RUN_DIR --receipt RECEIPT_JSON
python -m evaluation.q2_pipeline analyze outputs/q2/NEW_STUDY
python -m evaluation.q2_pipeline select outputs/q2/NEW_STUDY CANDIDATE
python -m evaluation.q2_pipeline reserve outputs/q2/NEW_STUDY baseline 0 --split test
python -m evaluation.q2_pipeline analyze outputs/q2/NEW_STUDY --split test
python -m evaluation.q2_pipeline accept outputs/q2/NEW_STUDY
python -m evaluation.q2_pipeline delivery outputs/q2/NEW_STUDY --expected-commit FULL_SHA --remote-commit FULL_SHA
```

这些命令只管理本地证据，没有模型执行命令。`record` 需要已经完成、绑定预登记凭证的运行；执行库接口 `run_reserved(study, slot, output, client, execution="fixture")` 由调用方提供 client，真实运行必须另获额度授权。仅对项目自有本地 client 使用 `ObservedTextClient` 收集逐请求元数据，再用 `receipt_from_observations` 生成回执；未知官方 client 不进入该适配器。模拟回执和缺失成本数据均不能晋级。

只有全部预登记开发运行入账且候选通过门槛，才能锁定唯一候选并登记留出运行。留出评估结束后关闭该研究，不能改选策略；失败运行不能静默重跑。已有公开题集准备文件位于 `outputs/q2-20260907/study/`，仅为未执行的工程方案。详情、统计边界及使用限制见 [Q2 离线报告](docs/evaluations/Q2_OFFLINE_20260907.md)。

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
- 任何重新拆分必须保持根入口真实声明 `ReasoningAgent`，禁止用可碰撞的通用模块类身份开启私有 client 能力，并通过官方预加载顺序、严格四参数 client（含 thinking_mode=False）、隔离导入和模块污染矩阵。
- [技术报告](技术报告.md) 与 [创新点说明](创新点说明.md) 是比赛陈述材料，不作为架构规范；提交信息见 [SUBMISSION_INFO.md](SUBMISSION_INFO.md)。

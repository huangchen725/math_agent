# 下一版本解题能力基线协议（P0 v1）

## 当前状态

P0 的离线基础设施已经建立，真实基线尚未调用模型。当前状态是 `prepared_not_executed`，不能提前声明当前版本在新题集上的正确率。

冻结的运行时基线为 commit `831b94f1f0e2e57a4cf93e5c4b3f588c89f0d5cb`。本轮只增加评测、盲审和配对统计工具，没有修改 `ReasoningAgent`、领域提示、候选数、温度、工具轮数或聚合规则。

## 数据分层

| 层 | 用途 | 是否允许按错题调参 | 能否证明实际能力 |
| --- | --- | --- | --- |
| 开发集 | 定位错误、单元测试和专项修复 | 允许 | 不能 |
| 固定回归集 | 防止已修复行为回退；包括 36 题截断压力集 | 只允许检查，不应反复针对题面改提示 | 不能 |
| 第三方公开基准 | 新旧版本同题配对比较 | 运行后只能降级为开发/回归证据 | 可证明该公开基准上的相对变化；不能证明预训练独立性 |
| 密封验收集 | 最终一次性确认陌生题泛化 | 禁止；揭封后退役 | 是下一版本正式能力声明的必要条件 |

密封验收集仍需独立命题者或私有第三方提供 100～200 题。题面不进入仓库、prompt、错误模式库或开发报告；仓库只保存数据哈希和匿名汇总。

## 第三方公开基准

公开基准使用 [PutnamBench](https://github.com/trishullab/PutnamBench) 的非正式题面。该项目将 Putnam 定位为本科数学竞赛基准，并说明非正式题面经 MAA 许可提供。固定信息如下：

| 项目 | 值 |
| --- | --- |
| 上游 commit | `34eba93650f2fa803ca6aae6dfd2c9f22d46c00d` |
| 上游 JSON SHA-256 | `54c89a29aa685e29e52ef802bba48007fb973753a0e3744be883b9e09e2b5403` |
| 选择种子 | `20260830` |
| 题量 | 120 |
| 有目标结论 / 证明题 | 72 / 48 |
| 2022～2025 题目 | 36，其中目标结论题 26、证明题 10 |
| 生成数据 SHA-256 | `f5f7666651b4a8b4214d6fae7a1a24e1caa4b816cb8b0d2f3a12b2a40c57f0d7` |
| prompt/sample/36题压力集/396题内部集重合 | exact 0、template 0、near 0 |

难度分布为 introductory 38、intermediate 44、challenge 38；主题分布为代数 17、分析 19、数论 18、线性代数 14、组合 14、几何 13、抽象代数 10、概率 9、集合论 6。

PutnamBench 是公开数据，模型预训练重复无法核验。它适合比较两个固定版本在同一批大学竞赛题上的表现，但不能被称为密封盲测或预训练独立正确率。

题面和原始响应只保存在被 Git 忽略的 `outputs/ability_baseline_v1/`。仓库提交可包含协议、上游版本、选择参数和哈希，不包含第三方题面。

## 固定运行条件

- 模型配置名：`intern-s2-preview`；运行后还必须记录接口实际返回的模型名。
- 每个版本运行 3 次，使用相同题序、模型、配置和请求规则。
- 本地并发固定为 1，避免已观察到的并发限流干扰数学能力。
- 旧版和新版分别预计约 3,240 次模型请求；按每题最多 20 次请求计算，单版本硬上限为 7,200 次。
- 正式运行前必须再次确认真实 API 费用和请求额度。本协议本身不调用 API。
- 答案字段不会传给 Agent；`main.py` 只传题面和 `idx`。

## 判分与配对

Putnam 题包含证明和开放表达，不能用字符串包含或同源模型 judge 自动判对。流程固定为：

1. 对旧版和新版输出按题随机交换 A/B 标签；
2. 评审者只看到题面、参考目标、rubric 和匿名 A/B 输出；
3. 完成 `correct/wrong/unknown/no_answer` 裁决后再解盲；
4. 每一题记录旧版和新版的配对转移；
5. 以逐题配对正确率差为主指标，报告 item-level paired bootstrap 95% 区间；
6. 三次运行按题多数结果执行单侧精确 McNemar 检验；
7. `unknown` 不进入正确分子，争议题应由第二名独立评审者处理，不能由开发者根据预期方向改判。

只有同时满足以下条件，工具才输出 `ability_improvement_demonstrated`：

- 数据哈希、模型、并发、重复次数和冻结 manifest 可比；
- 新版正确率更高，配对 bootstrap 95% 下界大于 0；
- 单侧精确 McNemar `p < 0.05`；
- 至少三分之二的重复运行方向为正；
- 新版 `invalid=0`、runner error/missing 为 0、截断残句为 0；
- 新版重新运行的截断门禁通过。

即便公开基准通过，正式对外的“陌生大学竞赛题能力提升”仍需密封验收集确认。

## 本地入口

从固定 PutnamBench checkout 生成公开基准：

```powershell
python evaluation/import_putnam_bench.py outputs/putnam_bench_source/informal/putnam.json `
  --source-commit 34eba93650f2fa803ca6aae6dfd2c9f22d46c00d `
  --output outputs/ability_baseline_v1/public_putnam_120.jsonl `
  --manifest outputs/ability_baseline_v1/public_putnam_120_source_manifest.json `
  --count 120 --answer-target-count 72 --recent-from-year 2022 --recent-count 36
```

实验前使用 `freeze_experiment.py` 生成旧版和新版各自的冻结 manifest。运行和评分后，使用 `blind_review.py create/resolve` 生成盲审裁决，再由 `paired_compare.py` 读取三份旧版报告、三份新版报告、两份冻结 manifest 和新版截断门禁报告。

协议的机器可读版本为 `evaluation/ability_protocol_v1.json`。

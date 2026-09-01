# 提交说明文件

## 队伍信息
- 参赛主体：广州大学
- 题目编号：XH-202627
- 题目名称：基于 Intern-S1 的数学智能体设计与推理创新
- 发榜单位：上海人工智能实验室
- 队伍名称：（待填，个人参赛可填个人名）
- 负责人姓名：（待填）
- 联系电话：（仅在提交平台私密填写，不写入公开仓库）

## 仓库信息
- 仓库平台：GitHub；AtomGit 地址待提交时确认
- GitHub 地址：https://github.com/huangchen725/math_agent
- AtomGit 地址：（导入后的 AtomGit 仓库地址，待填）
- 最终分支名称：main
- 最终 commit hash：（提交前运行 `git rev-parse HEAD` 后填写）

## 选用模型
- 正式模型：intern-s1
- 合规状态：赛事手册明确要求基于 Intern-S1；`intern-s2-preview` 仅保留为历史开发实验记录，不得用于正式提交，除非已取得并归档主办方书面许可

## 系统简介
本智能体基于官方 baseline（InternLM/Challenge-Cup-2026）增强，采用“领域路由-生成-验证-反思-聚合”流水线。完整且唯一的当前架构说明见 `ARCHITECTURE.md`：

1. **题型识别与领域路由**：本地关键词识别 18 个数学子领域，注入领域专属专家 prompt
2. **可选工具增强求解**：项目自有客户端可通过 OpenAI 兼容 tool_calling 调用 11 个受限 SymPy 工具；未知赛事注入 client 采用三参数兼容面并把工具槽降级为纯文本
3. **多候选生成**：保持三个候选槽；工具能力可用时混合工具增强与纯推理，否则全部使用纯文本候选
4. **验证判断**：严格直接题先生成确定性证据，其余由同模型 verifier 提供辅助判断；模型 verifier 不作为独立真值
5. **反思纠错**：验证不通过时反馈重试一轮
6. **Self-consistency 聚合**：答案级多数投票 + 数值比较（72==72.0==72/1）+ LaTeX 归一化

## 文件清单
| 文件 | 说明 |
|------|------|
| user_agent.py | 竞赛兼容入口，重新导出公开接口 |
| math_agent/ | 唯一运行时实现包，包含编排、路由、工具、验证、预算和客户端 |
| main.py | 本地 runner（断点续跑、3 并发） |
| pyproject.toml | 测试、覆盖率门槛与静态检查配置 |
| requirements*.txt | 直接依赖输入规格 |
| requirements*.lock | 精确版本和制品 SHA-256 锁 |
| scripts/ | 完整质量门禁、敏感信息/链接检查与确定性打包 |
| .github/ | Python 3.10/3.12 CI 与依赖更新配置 |
| LICENSE / THIRD_PARTY_NOTICES.md | 项目与第三方许可边界 |
| ARCHITECTURE.md | 唯一架构规范 |
| docs/ENGINEERING_SPECIFICATION.md | P1～S6 工程硬规则、历史故障和回归验收基线 |
| docs/COMPETITION_COMPLIANCE.md | 赛事红线、手册哈希、工程控制和提交操作清单 |

## 本地运行
```bash
pip install --require-hashes -r requirements.lock
export INTERN_API_KEY="你的token"
python main.py --input_file sample_data/dev.jsonl --output_dir outputs
```

## 交付生成

最终 commit hash、文件清单、默认模型/配置、赛事手册哈希、正式模型匹配状态、锁文件哈希和质量检查摘要由正式包内的 `release/release-manifest.json` 自动记录，不应把工作中的 HEAD 手工固化到本文。生成前确保工作树干净，并运行：

```bash
python -m scripts.run_quality_gates
python -m scripts.build_release --output-dir dist
```

输出 ZIP 旁的 `.sha256` 用于传输校验。脏工作树使用 `--allow-dirty` 时只会得到 `draft`，不得作为最终竞赛交付物。

formal 包只接受 `intern-s1`，并要求质量报告中的 `competition_compliance` 通过。提交日志与结果不得人工逐题修改或赛后补填；应保留平台原始文件并按 `docs/COMPETITION_COMPLIANCE.md` 生成 SHA-256 留证。

## 样例测试边界
- 3 道公开样例只用于接口和流程冒烟，不用于估计实际正确率。
- 正确率、截断和成本结论必须绑定数据集哈希、模型、配置和提交记录。

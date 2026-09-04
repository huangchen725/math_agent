# 提交说明文件

## 队伍信息
- 参赛主体：广州大学
- 题目编号：XH-202627
- 题目名称：基于 Intern-S1 的数学智能体设计与推理创新
- 发榜单位：上海人工智能实验室
- 队伍名称：（待填，个人参赛可填个人名）
- 负责人姓名：（待填）
- 联系电话：13826011382

## 仓库信息
- 仓库平台：GitHub + AtomGit（已同步）
- GitHub 地址：https://github.com/huangchen725/math-agent-xh202627
- AtomGit 地址：（导入后的 AtomGit 仓库地址，待填）
- 最终分支名称：main
- 最终 commit hash：（提交前运行 `git rev-parse HEAD` 后填写）

## 选用模型
- 模型名称：intern-s2-preview（书生 Intern-S2 预览版）
- 备选模型：intern-s1、intern-s1-pro

## 系统简介
本智能体基于官方 baseline（InternLM/Challenge-Cup-2026）增强，采用“领域路由-生成-验证-反思-聚合”流水线。完整且唯一的当前架构说明见 `ARCHITECTURE.md`：

1. **题型识别与领域路由**：本地关键词识别 18 个数学子领域，注入领域专属专家 prompt
2. **工具增强求解**：通过 OpenAI 兼容 tool_calling 调用 11 个受限 SymPy 工具，降低计算错误
3. **多候选生成**：工具增强候选 + 纯推理候选混合，温度采样增加多样性
4. **验证判断**：每个候选由独立 verifier 默认判断一次，VERDICT 机制评估候选正确性
5. **反思纠错**：验证不通过时反馈重试一轮
6. **Self-consistency 聚合**：答案级多数投票 + 数值比较（72==72.0==72/1）+ LaTeX 归一化

## 文件清单
| 文件 | 说明 |
|------|------|
| user_agent.py | 智能体入口（ReasoningAgent 类）—— 提交核心 |
| math_tools.py | SymPy 数学计算工具（11 个工具 + tool_calling 循环） |
| domain_prompts.py | 18 个数学子领域的专属专家 prompt |
| llm_client.py | InternChatClient（官方提供，本地调试用） |
| main.py | 本地 runner（断点续跑、3 并发） |
| requirements.txt | 依赖列表 |
| ARCHITECTURE.md | 唯一架构规范 |

## 本地运行
```bash
pip install -r requirements.txt
export INTERN_API_KEY="你的token"
python main.py --input_file sample_data/dev.jsonl --output_dir outputs
```

## 样例测试结果
- 样例 3 题（抽象代数/测度积分/复分析）正确率：100%
- 每题平均 trace 步数：14 步（含领域路由、工具调用、验证、聚合）

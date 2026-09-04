# 贡献指南

## 开发环境

使用 Python 3.10+ 创建虚拟环境，然后安装开发依赖：

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
```

先阅读 `AGENTS.md` 和 `docs/ENGINEERING_SPECIFICATION.md`；涉及组件边界、数据流或接口时，再阅读并更新唯一架构文档 `ARCHITECTURE.md`。当前恢复锚点和 `archive/s1-s6-1fc98b7` 工程线不得混为同一活动架构。

修改前必须读取 `.agents/policies/HARD_RULES.md`，并运行：

```bash
python .agents/policy_guard.py --paths <预计修改路径...>
```

工作说明要列出命中的规则 ID。若输出 `[POLICY BLOCK]`，必须先报告触发动作、后果和安全替代，停止该子动作，不能先改后说明。

真实 API、Git 提交/推送、正式提交、发布、依赖调整或 benchmark 等动作另加 `--actions <action...>`；即使不产生文件差异也必须触发规则。

## 修改原则

- 每次改动解决一个可说明、可验证的问题。
- 不把 API key、`.env`、私有数据集、运行输出或个人信息加入提交。
- 不在同一次实验中同时修改候选数、温度、token 预算与 prompt。
- 新增运行依赖时同步更新对应 requirements 文件和 README。
- 修复缺陷时优先在现有测试文件中补回归测试；只有没有自然归属时才新建测试文件。
- 不把真实 API 调用放进默认测试。
- 不使用通用裸模块类身份判断注入 client，也不调用其私有方法；任何入口或模块拆分必须通过官方预加载顺序、严格三参数 client、隔离导入和模块污染矩阵。
- 正式评测一次只改变一个变量；结构迁移不得同时修改 prompt、模型设置、候选数、工具或聚合。

## 提交前检查

```bash
python .agents/policy_guard.py --changed
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

正式候选另运行 `--anchor-canary` 或 `--formal`。前者只允许未改动的 R0 历史锚点，后者在工程规范进入 R1 前应当失败。任何守卫非零退出都阻断提交、推送和发布。

如果改动影响真实推理结果，还需记录：代码提交、配置、模型、输入数据标识、请求数、错误数、耗时和评分。随机模型的一次结果不能单独证明优化有效。

## 变更说明

提交或合并请求应简要说明：

1. 修改了什么；
2. 为什么需要修改；
3. 如何验证；
4. 是否影响竞赛接口、调用量、超时风险或输出格式；
5. 是否仍有未解决风险。

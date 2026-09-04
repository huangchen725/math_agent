# 贡献指南

## 开发环境

使用 Python 3.10+ 创建虚拟环境，然后安装开发依赖：

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
```

先阅读 `AGENTS.md`；涉及组件边界、数据流或接口时，再阅读并更新唯一架构文档 `ARCHITECTURE.md`。

## 修改原则

- 每次改动解决一个可说明、可验证的问题。
- 不把 API key、`.env`、私有数据集、运行输出或个人信息加入提交。
- 不在同一次实验中同时修改候选数、温度、token 预算与 prompt。
- 新增运行依赖时同步更新对应 requirements 文件和 README。
- 修复缺陷时优先在现有测试文件中补回归测试；只有没有自然归属时才新建测试文件。
- 不把真实 API 调用放进默认测试。

## 提交前检查

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

如果改动影响真实推理结果，还需记录：代码提交、配置、模型、输入数据标识、请求数、错误数、耗时和评分。随机模型的一次结果不能单独证明优化有效。

## 变更说明

提交或合并请求应简要说明：

1. 修改了什么；
2. 为什么需要修改；
3. 如何验证；
4. 是否影响竞赛接口、调用量、超时风险或输出格式；
5. 是否仍有未解决风险。

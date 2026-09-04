# 贡献指南

## 开发环境

使用 Python 3.10+ 创建虚拟环境，然后安装开发依赖：

```bash
python -m venv .venv
python -m pip install --require-hashes -r requirements-dev.lock
```

先阅读 `AGENTS.md`；涉及组件边界、数据流或接口时，再阅读并更新唯一架构文档 `ARCHITECTURE.md`。

## 修改原则

- 每次改动解决一个可说明、可验证的问题。
- 不把 API key、`.env`、私有数据集、运行输出或个人信息加入提交。
- 不在同一次实验中同时修改候选数、温度、token 预算与 prompt。
- 新增或升级依赖时先更新对应 `requirements*.txt`，再用 `pip-compile --generate-hashes --strip-extras` 重新生成受影响的 `.lock`，并在全新环境用 `--require-hashes` 验证安装；共享锁必须在最低支持 Python 上真实安装，不能只依赖另一解释器的 `--python-version` 干运行。不要手工编辑锁内版本或哈希。
- 修复缺陷时优先在现有测试文件中补回归测试；只有没有自然归属时才新建测试文件。
- 不把真实 API 调用放进默认测试。

## 提交前检查

```bash
python -m scripts.run_quality_gates
```

完整门禁不调用模型 API，但其中 `pip-audit` 会查询公开漏洞数据库。完全断网时可以临时添加 `--skip-dependency-audit` 做其余诊断；该结果不能用于正式发布。提交前还应确认 `git diff --check` 通过。

正式交付包只能在干净提交上、使用同一提交通过的完整质量报告生成：

```bash
python -m scripts.build_release --output-dir dist
```

工作中的预览只能使用 `--allow-dirty`，产物会标为 `draft`。不得放宽发布白名单、大小限制、敏感信息扫描或质量证据校验来绕过失败。

如果改动影响真实推理结果，还需记录：代码提交、配置、模型、输入数据标识、请求数、错误数、耗时和评分。随机模型的一次结果不能单独证明优化有效。

## 变更说明

提交或合并请求应简要说明：

1. 修改了什么；
2. 为什么需要修改；
3. 如何验证；
4. 是否影响竞赛接口、调用量、超时风险或输出格式；
5. 是否仍有未解决风险。

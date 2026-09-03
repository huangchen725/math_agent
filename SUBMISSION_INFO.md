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
- 正式评测仓库平台：AtomGit；GitHub 仅作为开发镜像，不能替代赛事提交
- GitHub 地址：https://github.com/huangchen725/math_agent
- AtomGit 地址：（队伍组织下的仓库地址，待填；当前本地尚未配置官方要求的 `atomgit` 远程，属于提交阻断项）
- 最终分支名称：main
- 本地冻结 commit hash：（提交前运行 `git rev-parse HEAD` 后填写）
- AtomGit 抓取后 `main` hash：（批次完成后读取远端并填写）
- 作品页点击时间/批次：（北京时间，待填；平台在 12:00/24:00 抓取）
- 作品页提交回执：（待填）
- 最终 ZIP 文件名与 SHA-256：（待填）
- 最终 ZIP 邮件发送时间/送达记录：（待填；与 AtomGit 自动评测均须留证）

## 选用模型
- formal 默认模型：`intern-s1`
- formal allowlist：`intern-s1`、`intern-s1-pro`、`intern-s2-preview`
- 本次作品页实际选择：（待填，必须使用页面展示的精确 ID 并保存回执）
- 合规状态：当前初赛技术规则直接列出以上三个 ID 并允许提交时选模，FAQ 另推荐 `intern-s2-preview`，因此 S1-only 门禁已撤销；“397/35B”简写与精确 API ID 的映射、提交页选项和实际运行版本仍未闭环。历史 S2 实验不能替代本次选择回执，allowlist 外模型不能生成 formal 包

## 系统简介
本智能体基于官方 baseline（InternLM/Challenge-Cup-2026）增强，当前正式版本采用“领域路由-三个纯文本候选-逐候选模型验证-多数票/置信度选择-答案规范化”保守流水线。完整且唯一的当前架构说明见 `ARCHITECTURE.md`：

1. **入口兼容**：根构造器兼容 `client,*args,**kwargs`，未知 client 只接收三参数 `chat` 调用
2. **领域路由**：本地关键词识别 18 个数学子领域，注入领域专属专家 prompt
3. **固定三候选**：所有候选使用同一个纯文本三参数协议；默认正常路径恰好 3 次生成请求
4. **紧凑验证**：每个合格候选由同模型 verifier 判断一次，默认再使用 3 次请求；无法解析时保持中性置信度
5. **Self-consistency 聚合**：答案级多数投票 + 数值比较（72==72.0==72/1）+ LaTeX 归一化
6. **截断保护**：最多 4 次恢复预算，截断残句不进入聚合或最终答案
7. **暂停能力**：11 个受限工具、题型/确定性验证和 critic/reflection 模块仍受离线测试保护，但当前正式 `solve()` 不调用，旧配置开关也不能恢复第二条协议

## 文件清单
| 文件 | 说明 |
|------|------|
| user_agent.py | 竞赛兼容入口，从同级 `agent.py` 重新导出公开接口 |
| 根目录运行模块 | 唯一分层实现，包含 `agent.py`、编排、路由、工具、验证、预算和客户端；不依赖运行包子目录 |
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
| docs/OFFICIAL_MATERIALS_REGISTER.md | 三份原件、新通知转录、动态官方页面与 baseline 指纹、逐项事实、冲突和未定义技术边界 |

## 本地运行
```bash
pip install --require-hashes -r requirements.lock
export INTERN_API_KEY="你的token"
python main.py --input_file sample_data/dev.jsonl --output_dir outputs
```

## 交付生成

最终 commit hash、文件清单、默认模型/配置、三份官方原件与新通知转录哈希、动态官方证据 URL/核验日、核验 baseline commit、formal allowlist/匹配状态、锁文件哈希和质量检查摘要由正式包内的 `release/release-manifest.json` 自动记录，不应把工作中的 HEAD 手工固化到本文。生成前确保工作树干净，并运行：

```bash
python -m scripts.run_quality_gates
python -m scripts.build_release --output-dir dist
```

输出 ZIP 旁的 `.sha256` 用于传输校验。脏工作树使用 `--allow-dirty` 时只会得到 `draft`，不得作为最终竞赛交付物。

formal 包只接受当前三个精确模型 ID，并要求质量报告中的 `competition_compliance` 通过；这不表示 `OFFICIAL-GAP-MODEL` 已关闭。提交日志与结果不得人工逐题修改或赛后补填；应保留平台原始文件并按 `docs/COMPETITION_COMPLIANCE.md` 生成 SHA-256 留证。模型、client、Judger 或容器信息更新时，先追加 `docs/OFFICIAL_MATERIALS_REGISTER.md`，不得只改环境变量。

## AtomGit 操作收口

1. 取得队伍 AtomGit 仓库 URL，以官方指定名称 `atomgit` 配置远程并把冻结提交同步到 `main`。
2. 在赛事作品页关联正确仓库、选择上方记录的模型并点击“提交作品”；只推送代码不会入队。
3. 点击后冻结 `main`，直到北京时间 12:00/24:00 对应批次完成抓取。
4. 抓取后记录 AtomGit 远端 `main` SHA，并与本地冻结 SHA、formal manifest 对账。
5. 保存页面回执、时间、模型和批次；单日最多 2 次、单周最多 10 次。
6. 初赛截止前把最终代码和其它规定材料打成 ZIP 发组委会邮箱，说明文件写明队伍、题目、AtomGit URL、`main` 和所选模型；记录 ZIP SHA-256、发送时间和送达证据。邮件不能替代作品页提交。

## 样例测试边界
- 3 道公开样例只用于接口和流程冒烟，不用于估计实际正确率。
- 正确率、截断和成本结论必须绑定数据集哈希、模型、配置和提交记录。

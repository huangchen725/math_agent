# XH-202627 基于 Intern-S 的数学智能体

基于官方 baseline (InternLM/Challenge-Cup-2026) 增强的数学推理智能体。

## 架构
- **接口**：`ReasoningAgent(client).solve(problem, metadata) -> {"final_response": str, "trace": [...]}`
- **核心流程**：题型识别+规划 → 多候选生成 → 验证投票 → 最优选 + 答案抽取
- **增强点**（相对官方 baseline）：
  1. 推理规划层：解题前先识别题型+生成求解策略
  2. 领域路由：12 个数学子领域的专家提示注入
  3. 答案鲁棒抽取：从模型输出中多策略抽取最终答案
  4. 候选多样性：温度采样 + 规划信息注入

## 快速开始

### 1. 配置 API Key
```bash
# 编辑 .env，填入你的 key
INTERN_API_KEY=你的token
```
获取地址：https://internlm.intern-ai.org.cn/api-token

### 2. 安装依赖
```bash
pip install -r requirements.txt
# lagent 必须从源码装（requirements.txt 已指定 git+url）
```

### 3. 本地运行（样例数据）
```bash
python main.py --input_file sample_data/dev.jsonl --output_dir outputs
```
结果保存到 `outputs/{idx}.json`，已完成的题会跳过（断点续跑）。

### 4. 提交到判分平台
1. 在 AtomGit 注册：https://competition.gitcode.com/competition/2074065063594618882/intro
2. 把代码推送到 GitHub/GitCode 仓库
3. 在判分系统提交仓库地址 + commit SHA
4. 限制：每天 2 次，每周 10 次

## 关键约束
- **不能硬编码 API key**：平台注入 client，key 由官方管理
- **每题独立进程**：1200 秒/题，6 小时总量，3 并发
- **输出**：`final_response` 是纯答案字符串（如 "72"），不是 LaTeX
- **stream=True 和 n!=1 被拒**

## 文件结构
```
├── user_agent.py      # 智能体入口（ReasoningAgent）—— 提交核心
├── llm_client.py      # InternChatClient（官方提供，本地调试用）
├── main.py            # 本地 runner
├── requirements.txt   # 依赖
├── sample_data/       # 样例数据
│   └── dev.jsonl
└── .env               # API key 配置（不提交）
```

## 时间节点
- 报名：5/30 - 6/30（www.tiaozhanbei.net）
- AtomGit 注册截止：9/15
- 作品提交截止：**9/15**（已从 9/5 顺延）
- 邮箱：changshuai@pjlab.org.cn

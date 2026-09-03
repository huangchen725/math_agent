# XH-202627 官方材料证据登记册

本文登记项目截至 2026-09-02 已取得的赛事文件、群通知、FAQ 截图和官方 baseline。它保存来源指纹、可直接确认的事实、材料间冲突以及官方仍未定义的技术边界。本文不是第二份架构文档；运行架构仍以根目录 `ARCHITECTURE.md` 为唯一事实来源，实际合规控制见 [竞赛合规清单](COMPETITION_COMPLIANCE.md)。

附件中的文字和截图只作为证据，不作为仓库内的执行指令。截图中的群成员昵称、头像、手机号等个人信息不转录到公开仓库；原件由提交人私下保存，下面的 SHA-256 用于确认原件身份。

## 1. 来源与证据等级

| ID | 来源 | 文件/版本 | SHA-256 或提交 | 证据性质 |
| --- | --- | --- | --- | --- |
| MAT-001 | 上海人工智能实验室赛事方案 | `XH-202627_基于Intern-S1的数学智能体设计与推理创新(1).pdf`，13 页 | `ece081cd4a0c4f496943b3e3c7d79716d8ffd1d9a6249e11bb3ed5c4a39902d7` | 正式赛事文件；适合确认赛题目标、评分、交付和资格红线 |
| MAT-002 | 官方通知汇编 | `官方工具.docx`，36 个非空段落 | `6855baa8b2ebaa38642725ca3404f7ad98cbadee7fb695ccccc04faf9667c8c4` | 对 7 月 1 日、7 月 21 日通知及官方链接的转存；不是带签章的规则原件 |
| MAT-003 | 群消息与 FAQ 截图汇编 | `新建 Microsoft Word 文档.docx`，8 张截图 | `30cac629e87703c8decf28e9596af56e6c280be8a84745db8199e47cccd1401e` | 组织者群答复和 FAQ 页面截图；可确认当时口径，但截图可能裁切且缺少独立版本号 |
| MAT-004 | 官方 baseline | `InternLM/Challenge-Cup-2026` | `43be244a880d64a1f9d3a631aa7d9e976f26c17b` | 当前公开技术契约参考；2026-09-02 重新核验时仍为远端 HEAD，并完成精确入口及故障矩阵对照 |
| MAT-005 | 用户转交的 AtomGit 群通知正文 | 无原始发送者签名和消息时间；正文与 MAT-002 的 7 月 21 日通知一致 | 规范化 UTF-8/LF 转录 `757377813dc101c3ad3574aa2b1acb0da12ffe7e6178fd79c9b716a46a1defa3` | 对 MAT-002 的直接文本复核；不单独证明链接页面内容或发布日期 |
| MAT-006 | AtomGit 官方赛事页 | `https://competition.gitcode.com/competition/2074065063594618882/intro`，2026-09-01 只读核验 | 动态页面，无不可变版本 ID | 当前运营、提交流程、批次、异常与平台托管边界；页面会变化，必须记录核验日期 |
| MAT-007 | 官方初赛赛题介绍与提交要求 | `https://aicarrier.feishu.cn/wiki/L90FwD9gJiqdg0k33RCcHTdcnrb`，页面显示 07 月 21 日修改，2026-09-02 逐节复核 | 动态页面，无不可变版本 ID | 当前入口、构造器、client 最小示例、模型列表、`solve`、返回值、AtomGit 评测与邮件归档规范 |
| MAT-008 | 官方更新日志 | `https://aicarrier.feishu.cn/wiki/C3dBwzdyFiDxEIkYq7ucOZ59neh`，页面显示 07 月 20 日修改，2026-09-01 核验 | 动态页面，无不可变版本 ID | 记录 07 月 14/16 日规则变化及适用动作；页面明确自称变更日志 |
| MAT-009 | 官方 FAQ 与答疑沉淀 | `https://aicarrier.feishu.cn/wiki/BHoMw601Xiy5i3keTLDcg3M3n5x`，页面显示 07 月 24 日修改，2026-09-01 核验 | 动态页面，无不可变版本 ID | 模型、题集、工具、依赖、环境和 Judger 的书面答复；页面提示部分内容可能由 AI 生成，因此低于签章文件但高于口头转述 |

证据使用顺序如下：

1. 先执行明确的资格红线和安全限制，不用其它材料放宽。
2. 对当前平台入口、提交批次和 runner 调用方式，使用 MAT-006～MAT-009 的后续公开页面；对客户端实现和 trace 安全边界，仍优先使用绑定提交的 MAT-004 baseline。
3. 后续书面通知可以更新较早的日期、入口和运营口径，但必须保留原文、页面修改时间、核验日期和来源指纹；动态网页不得伪装成不可变版本。
4. 两个来源冲突、截图不完整或术语没有精确定义时，不自行选择对项目最有利的解释；登记为未决项并采用可回退的保守实现。
5. “材料没有禁止”不等于允许；“本地 fake 可运行”也不等于正式平台承诺兼容。

## 2. 正式赛事方案确认的事实

MAT-001 明确写出：

- 赛题编号为 XH-202627，目标是基于 Intern-S1 API 构建数学智能体。
- 学生赛道面向 2026 年 6 月 1 日前正式注册的国内全日制普通高校专科、本科、硕士、博士及全日制职业教育学生，不含在职研究生；指导学生的高校青年教师不得同时以参赛人员身份参加同一选题，发榜单位及隶属单位青年不得参加本单位选题。
- 可个人或组队参赛，团队不超过 10 人、指导教师不超过 3 人；允许跨专业、学校、单位和地域组队，但每件作品只能由 1 所高校或科研院所作为参赛主体申报。
- 初赛为单智能体，需理解自然语言数学题、自主规划与求解、解释推理过程，并返回结构化 JSON。
- 初赛题集为 112 题、18 个子领域；组委会可能根据整体通过率追加更实时、更高难度的问题。
- 方案评分表为：答案正确性 60%、推理策略与系统设计 10%、展示质量 20%、创新性与可扩展性 10%；同分时先比较答案正确性。
- 接口异常、格式错误或结构化结果无法解析会导致题目未通过；系统必须返回必要日志信息以供解析和复核。
- 鼓励任务拆解、推理规划、过程校验、多模块协同、多智能体、题型路由、长程推理和本地/外部工具结合；不鼓励只堆叠 prompt 或固定模板的单轮调用。
- 严禁人工逐题干预、赛后补填结果、伪造日志或使用未经允许的外部闭源服务代答。
- 初赛/决赛材料包括技术方案 PDF、日志和结果 JSON；决赛另有不超过 10 分钟的视频及 PPT，源码或 Notebook 为建议项。
- 原方案列出的报名期为 5 月 30 日至 6 月 30 日，原作品提交节点为 9 月 5 日；这些日期后来受到 MAT-002 通知更新。
- 原方案要求在挑战杯官网报名、下载并加盖学校公章后上传报名表；作品材料发到 `changshuai@pjlab.org.cn`，同时提交审核通过的报名表，压缩包按“申报人所在单位-申报人姓名-作品名称-联系电话”命名。
- 报名账户可在书生 API 控制台生成 token，主办方会调整报名账户的 Intern-S1 流控策略；同队成员可共用该账户生成的 API key。
- 赛事保障包括至少两场线上培训、答疑社群、专家指导和书生社区交流。方案列出擂主 1 名、特等奖/一/二/三等奖各 5 名，奖金依次为 10 万、2 万、1 万、0.5 万、0.2 万元；获奖比例原则上不超过参赛作品总数的 30%。
- 方案包含比赛专班的个人姓名、手机号和工作日 9:00–17:00 联系时间，以及上海人工智能实验室介绍和 Intern-S1 在 2025 CMO 的宣传性成绩说明。为避免在公开仓库复制个人信息，本登记册只保留原件哈希和内容类别；需要联系时从私下保存的原件核对。

方案未给出 Python 客户端签名、支持的请求关键字参数、响应对象形状、工具调用协议、单题模型调用数、token 上限、容器镜像、Python 版本、内存、磁盘或运行时网络规则。

## 3. 官方通知汇编确认的事实

MAT-002 保存了下列通知和入口：

- 2026-07-01 通知发布初赛赛题文档、官方 baseline、问题收集问卷、持续更新 FAQ 和 6 月 11 日专场直播回放。
- 初赛赛题链接：`https://aicarrier.feishu.cn/wiki/L90FwD9gJiqdg0k33RCcHTdcnrb`。
- 官方 baseline：`https://github.com/InternLM/Challenge-Cup-2026`。
- 问题收集表：`https://aicarrier.feishu.cn/share/base/form/shrcnl4dufqp6D1uGoZnTF4Pmwg`。
- FAQ：`https://aicarrier.feishu.cn/wiki/BHoMw601Xiy5i3keTLDcg3M3n5x`。
- 2026-07-21 通知说明 AtomGit/赛事专属判分页面承担初赛自动判分；AtomGit 注册报名和作品提交截止时间调整到 9 月 15 日。
- 自动判分系统因活动排期从原定 7 月 21 日延后，预计 7 月 28 日开放。
- 赛事页面：`https://competition.gitcode.com/competition/2074065063594618882/intro`。
- 6 月 11 日专场回放：`https://weixin.qq.com/sph/AlHizQTEUj`；挑战杯报名入口：`2026.tiaozhanbei.net`。
- 书生官网：`https://internlm.intern-ai.org.cn/`；Web 应用：`https://chat.intern-ai.org.cn/`；InternStudio：`https://studio.intern-ai.org.cn/console/dashboard`；昇腾集群：`https://internstudio-ascend.intern-ai.org.cn/console/instance/`；API 文档：`https://internlm.intern-ai.org.cn/api/document?lang=zh`。
- InternLM GitHub：`https://github.com/InternLM`；Intern-S1：`https://github.com/InternLM/Intern-S1`；书生实战营课程：`https://aicarrier.feishu.cn/wiki/Ud8QwcbnSi5hunkOWaychZQ2nuc`。
- AtomGit 注册/使用步骤：`https://aicarrier.feishu.cn/wiki/VTSdwzVoPi0AdVkZhkWcnFQznAd`；初赛规则更新日志：`https://aicarrier.feishu.cn/wiki/C3dBwzdyFiDxEIkYq7ucOZ59neh`。
- 7 月 21 日通知原文把作品截止从“原 9 月 4 日”改到 9 月 15 日，而 MAT-001 写的是 9 月 5 日；9 月 15 日是后续口径，但两个“原日期”不一致，不能静默改写历史。

日期与提交入口属于会继续变化的运营信息。正式提交前必须重新读取平台当日公告，不能仅依赖本登记册中的历史通知。

## 4. 群消息与 FAQ 截图确认的事实

MAT-003 的八张截图包含以下与项目直接相关的信息：

### 4.1 判分上线、模型与提交

- 判分系统于 7 月 28 日宣布上线；即日起至 8 月 4 日为试运行期，期间可能评测过慢、分数波动或不稳定。
- 通知推荐使用“Intern-S2-Preview-397B”开发和提交；另一次针对“正式评测默认 397B 还是 35B”的群内答复为“397”。截图没有给出可直接传给 API 的精确模型 ID，也没有解释是否所有提交都被锁定到该模型。
- 作品必须从赛事页面“赛题发布”板块下的“提交作品”通道上传，不能选错入口。
- API 调试额度不足时，可以在 API 平台申请更高流控并备注“挑战杯”。

### 4.2 答案、Judger 与 trace

- 题目可能存在多个解，但群答复称没有统一的多解连接符格式要求；“无解”题理论上不会出现。
- FAQ 称 LaTeX 表达可接受，Judger 基于 Intern-S 系列模型结合参考答案和参考解题过程进行语义判断，不只是字符串精确匹配；示例 `-1/8` 与 `-\frac{1}{8}` 通常会判为一致。
- FAQ 称 `final_response` 和选手返回的 `trace`（如有）会作为 Judger 输入的一部分。
- FAQ 要求 `final_response` 本身清晰且可独立判分：选择题给选项，填空题给最终结果，证明题提供必要且完整的证明，其它推导题保留支撑结论的关键步骤；其余中间过程可放入 `trace`。

上述旧 FAQ 截图与 MAT-004 当前 baseline 的安全规则冲突：当前 baseline 明确要求 `trace` 只保存非敏感结构化元数据，不能放题面、完整 prompt、模型输入输出、候选解答或最终答案，并说明主要按 `final_response` 判分。项目按当前绑定版本执行：完整、可独立判分的必要推理放入 `final_response`，公开 `trace` 只保留元数据。

### 4.3 时间、调用预算与资源

- FAQ 称正式评测单题总超时为 20 分钟；baseline 的 120 秒只是本地样例客户端单次请求超时，不是正式单题总时限。
- FAQ 称平台当时没有额外规定单题输入/输出 token 数量，但选手必须控制模型上下文和总运行时间，不得超过模型上下文窗口。
- 群答复称单题 API 调用次数“理论上没有上限”，同时提到显示的流控策略为 2000 RPM。该答复没有定义 Judger 侧计数、TPM、总 token、并发或平台后来新增的调用预算。
- 内存、磁盘和基础 Docker 镜像在截图时仍待后续公告；大型依赖可邮件联系组委会并说明队伍、学校和仓库。
- 当时优先通过 `requirements.txt` 声明 Python 依赖，平台在评测前安装；是否支持交付 Dockerfile/镜像需等待后续公告。

MAT-004 后来进一步写明平台可能限制 `max_tokens` 和模型调用次数，因此“理论上无上限”不能视为长期、可机器依赖的保证。本项目继续保留自身请求、token 和时间预算。

### 4.4 网络、依赖与进程模型

- 正式运行只能依赖官方 API；不提供 GPU，运行时不能访问外网，不得调用需要联网的外部计算服务、在线 API 或工具。
- 评测环境会先联网安装 `requirements.txt` 中声明的依赖，再限制运行时外网访问；运行时不能动态下载模型、数据或其它资源。
- 平台会遍历测试集 tasks，并可能设置若干并发进程 slots；每个进程初始化选手的 `ReasoningAgent` 并调用 `solve` 解一个 `problem`，完成后释放资源。截图要求具体并发数和频率以评测系统公告为准。
- 群答复允许先创建空仓库再设为私有。MAT-004 同样建议不希望公开方案的队伍使用 private repository，并要求提交精确 commit SHA 而不是浮动分支。

MAT-004 当前固定口径进一步明确：每题独立进程重新加载模块、构造 Agent 且只调用一次 `solve`；最多同时运行 3 个题目进程；单题进程组硬时限 1200 秒，Agent 阶段总硬时限 6 小时；超时后不保证执行 `finally` 或退出钩子。

## 5. 新消息与当前公开页面确认的事实

### 5.1 MAT-005 群通知正文

MAT-005 没有附带原始发送时间或发送者身份，因此不能单独提升为带版本的技术契约。其正文与 MAT-002 中标记为 7 月 21 日的通知一致，新增作用是复核转录没有遗漏。SHA-256 按“移除 Markdown 链接外壳、保留 URL，统一 LF，UTF-8 编码并保留末尾换行”的下列规范化文本计算：

```text
@所有人 各位同学大家好！
为保障大家顺利参赛，我们依托 AtomGit 平台搭建了赛事专属页面，平台将承担初赛自动判分核心功能，所有参赛选手务必完成 AtomGit 注册报名，注册报名截止 9 月 15 日。
赛事地址：https://competition.gitcode.com/competition/2074065063594618882/intro
一、AtomGit平台操作 & 赛题更新文档
1.AtomGit 注册和使用步骤：https://aicarrier.feishu.cn/wiki/VTSdwzVoPi0AdVkZhkWcnFQznAd
2.初赛赛题部分规则更新
1）更新日志：https://aicarrier.feishu.cn/wiki/C3dBwzdyFiDxEIkYq7ucOZ59neh
2）初赛赛题：https://aicarrier.feishu.cn/wiki/L90FwD9gJiqdg0k33RCcHTdcnrb
二、赛程时间调整说明
1.原定于 7 月 21 日上线的自动判分系统，因与世界人工智能大会排期冲突，上线时间延后一周，预计7 月 28 日开放；
2.同步顺延作品提交截止时间：由原 9 月 4 日调整至9 月 15 日，给大家预留充足调试、打榜时间。
```

消息正文只改变报名/作品截止和判分上线计划，没有定义 client 签名、返回对象、模型 ID、token/resource 上限或 Judger 版本。

通知中的 AtomGit 注册教程链接在 2026-09-01 无登录访问时跳转到飞书登录页，正文没有独立读取。登记册只能确认该链接由通知提供，不能据此声称教程步骤、权限或页面版本已核验；需要执行注册操作时应由已登录参赛账户查看并另存当日回执。

### 5.2 MAT-006 AtomGit 当前赛事页

2026-09-01 无登录只读核验确认：

- 只有 6 月 30 日前在挑战杯官网成功报名书生赛道的选手可继续参加；AtomGit 平台注册和作品提交截止为 9 月 15 日，作品提交区间显示为 7 月 28 日至 9 月 15 日。
- 初赛代码必须在 AtomGit 完成报名/组队、关联队伍组织下仓库并推送 `main`；作品页还要选择模型并点击“提交作品”。只推送代码不会进入评测队列。
- 平台在北京时间 12:00 和 24:00 两个固定批次读取当时 `main` 的最新源码，不接收选手填写的 commit hash；点击提交后到系统拉取前继续修改 `main` 会造成版本错乱。单日最多 2 次、单周最多 10 次。
- 流程为：隔离环境安装依赖，平台官方 Client 初始化 Agent，批量调用 `solve` 处理私有题集，采集答案、trace、耗时、异常和资源占用，再由官方 Judger 打分。
- 平台统一控制接口超时、并发、token 预算和硬件资源上限，但页面没有公布具体数值；不会下发题目、标准答案、校验规则或逐题详细反馈。
- 明列异常包括：仓库权限/组织错误、没有 `main`、仅 GitHub 未同步 AtomGit、缺失 `user_agent.py`、构造器或 `solve` 签名不符、返回非字典、`final_response` 为空、JSON 失败、依赖冲突、超时/资源超限、读取绝对路径或本地私有文件、硬编码密钥、恶意逻辑和绕过资源控制。
- 当前页面把初赛榜单定义为纯客观自动打分并按截止时榜单排名，晋级不足 30 队；这仍与 MAT-001 的作品综合评分表分属不同口径。

### 5.3 MAT-007 当前接口与提交规范

- 仓库根目录必须有 `user_agent.py`；其它模块和依赖必须使用相对路径，不能依赖开发机绝对路径。
- 平台按 `from user_agent import ReasoningAgent` 导入，并以 `ReasoningAgent(client=official_client)` 构造。页面要求至少兼容 `def __init__(self, client, *args, **kwargs)`。
- 必须提供 `solve(self, problem: str, metadata: dict) -> dict`。`problem` 为题面字符串；`metadata` 至少可能包含 `idx`，其它字段以 runner 为准，不能依赖 `answer`、标准答案或隐藏数据。
- 返回值必须是字典且包含非空字符串 `final_response`；`trace` 被写为推荐字段。当前项目继续保留列表 trace，以兼容 baseline 和既有 runner。
- 页面把平台 client 描述为与 baseline `InternChatClient` 结构一致，并只给出 `chat(messages, temperature, max_tokens)` 三参数调用示例。它没有承诺扩展 kwargs、返回元数据或工具调用，因此三参数投影从项目推断升级为当前公开的最小调用契约。
- 页面示例使用 `max_tokens=4096`，但它只是示例值，不是平台上限；模型访问、限流、token 统计与超时由官方 client/runner 管理，具体正式预算仍未公布。
- 页面本身列出 `intern-s1`、`intern-s1-pro`、`intern-s2-preview` 三个可用示例，并说明提交时可选择实际模型。普通 API 控制台流控写为 RPM 30、TPM 150000，通常可申请 200 RPM 以内；这些是本地账户口径，不等于正式 runner 的预算。
- `INTERN_API_BASE` 应以书生 API 控制台当时文档为准；页面没有冻结端点版本或完整 URL 集合。项目当前硬编码的官方地址属于保守本地控制，端点变更仍须先归档证据。
- Agent 可新增内部模块、工具和状态，但不得依赖题目固定顺序、同一进程、开发机绝对路径、隐藏测试集/标准答案/Judger 信息，也不得硬编码 key、执行破坏性行为或规避资源限制。
- 赛事报名、组队、仓库管理和评测提交已统一到 AtomGit。已有 GitHub 仓库应新增名为 `atomgit` 的远程并推送 `main`；系统在固定批次拉取绑定仓库的最新 `main`，旧 commit-hash 填写流程已取消。
- 点击“提交作品”前必须先推送并确认根 `user_agent.py` 可见；从最终推送到平台抓取完成应冻结 `main`。其它开发分支可以存在，但不会作为默认评测分支。
- 自动判分收集 `final_response`、trace、耗时、异常和资源用量，官方 Judger 结合标准答案评分；页面只回传最终分数和异常状态，不公开逐题题目、答案、Judger 细节或逐题反馈。
- AtomGit 是自动评测入口，但不是全部交付：初赛截止前还要求把最终代码和其它材料打成 ZIP，通过页面列出的组委会邮箱发送。说明文件应写队伍、题目、AtomGit 地址、`main` 和所选模型，不再填写 commit hash。本地 SHA 仍用于项目自身审计。
- 每队每天最多 2 次、每周最多 10 次；12:00/24:00 前须完成推送和页面点击。仅推送、只推 GitHub、错误组织/仓库/权限、缺 `main`、入口或返回契约错误、依赖冲突、超时/资源超限、本地路径/未声明资源、密钥或绕限逻辑都可能造成异常。

### 5.4 MAT-008/MAT-009 更新与 FAQ

- 7 月 16 日记录明确把报名、组队、参赛 Git 组织、仓库托管和作品提交切换到 AtomGit，取消 commit hash 填写并改为 12:00/24:00 拉取最新 `main`。
- FAQ 明确允许 Intern-S 系列模型，不限于 S1；允许组合多个 Intern-S 模型，推荐精确 ID `intern-s2-preview`，并允许思考模式。结合 baseline 已列出的 ID，项目 formal allowlist 目前为 `intern-s1`、`intern-s1-pro`、`intern-s2-preview`；未来模型必须先追加证据再进入门禁。
- 正式运行不能调用其它在线 AI 或外部 API，即使用于生成 prompt 也不行；离线设计并固化 prompt 可以。
- 正式题集 112 题不公开；题面为中文 `str`，不直接上传图片，每个 `problem` 是一道独立题而非多小问。正式 metadata 只含少量与解题基本无关的信息，不提供参考答案或题型标签。
- 初赛可以使用 multi-agent/sub-agent。允许本地离线 MCP、离线 RAG、SymPy 和可在 Docker 中运行的本地 sandbox；所有资源必须随仓库提交或在依赖阶段可复现构建，不能联网。
- 正式环境为 Linux Docker，只安装根 `requirements.txt` 声明的 Python 包；不会预装 Lean 4、elan、lake 或 mathlib，运行时也不能下载这些非 Python 工具链。
- FAQ 仍称单题 20 分钟、平台不额外限制单题输入/输出 token，并称 `final_response` 与 trace 都可进入 Judger；MAT-006 后续页面只说平台统一管控 token 预算，MAT-004 又限制公开 trace 为元数据。因此具体 token 数字与 trace/Judger 口径继续保持未决。

MAT-007～MAT-009 页面均显示“部分内容可能由 AI 生成”。本项目把页面内明确、可交叉验证的接口和运营字段作为当前公开口径，但不会用该提示放宽资格红线，也不会把动态页面写成具有不可变版本的契约。

## 6. 材料间冲突与当前处理

| ID | 冲突 | 当前处理 |
| --- | --- | --- |
| INFO-CONFLICT-001 | MAT-001 题名和资源说明使用 Intern-S1；MAT-003 推荐/称正式评测使用 397B；MAT-007 逐项列出 `intern-s1`、`intern-s1-pro`、`intern-s2-preview` 并允许提交时选模；MAT-009 允许 Intern-S 系列并推荐 `intern-s2-preview` | S1-only 门禁撤销；formal 仅允许三个已书面出现的精确 ID，实际提交仍须记录页面选择。“397”与 API ID 的映射保持未决 |
| INFO-CONFLICT-002 | MAT-003/MAT-007 说 trace 可记录关键推理、候选和验证并可作为设计参考；MAT-004 当前版本要求公开 trace 只含非敏感元数据 | 以当前绑定 baseline 的安全要求为准；必要证明和关键推导放 `final_response`，`trace` 继续失败关闭地脱敏 |
| INFO-CONFLICT-003 | MAT-003/MAT-009 称单题调用和 token 没有额外上限；MAT-004/MAT-007 又确认平台统一控制模型调用预算与资源 | 不依赖“无限”；MAT-007 的 `max_tokens=4096` 只是示例，保留项目本地请求、token 和 600 秒软期限 |
| INFO-CONFLICT-004 | MAT-001 给出 60% 客观正确率加 40% 主观材料评分；MAT-004/MAT-007 称初赛榜单完全按客观判分排名 | 将二者分别理解为赛事作品综合评审口径和在线初赛榜单口径，未经书面确认不把它们合并成一个分数公式 |
| INFO-CONFLICT-005 | MAT-001 原作品提交节点为 9 月 5 日；MAT-002/MAT-005 后续通知改为 9 月 15 日，且 MAT-006 当前页面也显示 9 月 15 日 | 当前操作截止按 9 月 15 日；保留历史差异并在提交当天再核对页面 |
| INFO-CONFLICT-006 | 群消息出现 2000 RPM；MAT-004/MAT-007 写普通账户 RPM 30、TPM 150000，通常申请 200 RPM 以内 | 额度按账户控制台的实际状态冻结；这些是本地 API 账户口径，不是正式 runner 预算，也不把群聊数字写成保证 |
| INFO-CONFLICT-007 | MAT-001 要求作品和报名表通过邮箱提交；后续材料把自动评测代码统一到 AtomGit，曾不清楚是否替代邮件 | MAT-007 已解析当前操作：AtomGit 绑定仓库/点击提交进入自动评测；截止前最终代码和其它材料仍打 ZIP 发组委会邮箱。双通道均需完成，历史差异保留 |
| INFO-CONFLICT-008 | MAT-004 建议用精确 commit SHA 留证；MAT-006～MAT-008 明确平台不接收 commit hash，而在批次时抓最新 `main` | 本地仍冻结并记录 SHA；平台侧必须在提交后停止改 `main`，批次完成后用远端 `main` SHA 对账，不能假定页面绑定了提交时 SHA |
| INFO-CONFLICT-009 | MAT-001 把初赛表述为单智能体；MAT-009 明确初赛可使用 multi-agent/sub-agent | 多 Agent 被允许但不是要求；当前单 Agent 仍合规，若升级必须另做能力、资源和稳定性验证 |

## 7. 官方仍未定义的技术边界

这些缺失与多次 0 分直接相关，缺失本身必须作为风险保存：

| ID | 未定义或不完整的边界 | 失败风险 | 项目防御 |
| --- | --- | --- | --- |
| OFFICIAL-GAP-CLIENT | MAT-007/官方 README 已明确 Agent 构造器兼容 `client,*args,**kwargs` 和三参数 `chat` 示例，但公开 `main.py` 只传 `client=`，同提交 baseline Agent 自身仍只有 `client, config=None`；正式 runner 实际构造参数、client 包/类版本、返回类型、扩展参数兼容矩阵、固定 endpoint 版本及变更机制仍未给出。固定 baseline + `eb5d8d4` 的 112 题对照已全部进入公开 client，不能复现正式 0 请求 | 不透明构造值污染项目配置，或在 HTTP 前 `TypeError`，整场 0 请求 | 只有真正的项目 `AgentConfig` 可成为配置；未知 client 只发送 `messages/temperature/max_tokens`，不读私有字段，不失败后盲目重试 |
| OFFICIAL-GAP-RESPONSE | 普通文本、工具调用、`finish_reason`、usage、错误响应的完整返回类型和字段保证 | 解析失败、无法识别截断、工具循环失效 | 外部返回按最小文本契约处理；工具仅在项目自有客户端启用；缺元数据时不伪造 |
| OFFICIAL-GAP-ERROR | 构造、参数校验、初始化、请求和返回处理错误如何进入 runner，哪些异常会被聚合日志保留；连续四次日志都没有逐题异常 | 112/112 error 但无法区分构造、预检、client 校验或 runner 拒绝 | `solve` 完整生命周期最外层失败关闭且不额外请求；离线逐路径 fake；保留平台原始汇总日志和提交 SHA |
| OFFICIAL-GAP-BUDGET | MAT-006/MAT-007 只确认平台管控 token/并发/超时/资源；FAQ 又称无额外单题输入输出 token 限制。普通 API 的 RPM 30/TPM 150000 和示例 `max_tokens=4096` 都不能推出正式每题调用数、总 token、`max_tokens` 或上下文窗口 | 超时、限流、截断或尾部题缺失 | 当前保守兼容内核 6 次正常请求、最多 4 次恢复、200000 token 和 600 秒本地软预算；这只是项目自限，不代表官方额度 |
| OFFICIAL-GAP-MODEL | 已确认三个精确 ID 可进入 formal allowlist，但“397/35B”映射、登录后提交页实际选项、队伍锁模和版本漂移仍未定义 | 本地与正式模型不一致，能力基线失效 | manifest 冻结实际模型字符串和允许集合；提交时另存选择回执，未留回执不宣称环境可复现 |
| OFFICIAL-GAP-RESOURCE | 已确认 Linux Docker、Python `requirements.txt`、无 GPU/外网/Lean 工具链，但基础镜像、Python/系统库版本、CPU、内存、磁盘及进程/子进程数值仍缺失 | 安装失败、OOM、SymPy 工具失效 | Python 3.10/3.12 离线门禁、锁文件、受限子进程；具体资源上限保持未解决 |
| OFFICIAL-GAP-JUDGE | `final_response` 长度、答案标记、证明题细则、`trace` 的实际权重和 Judge 版本 | 数学正确但无法判分或因冗长受损 | `final_response` 自包含且末行唯一答案；不依赖 `trace` 才能得到结论 |
| OFFICIAL-GAP-RUNNER | 已知平台先克隆完整仓库并记录根 `user_agent.py` 路径、构造/solve 形式、相对路径和批次抓取 `main`；公开 `main.py` 复用一个 Agent，并将任何非空字符串（含 `未解出`）记为 success，README 则说明正式环境逐题独立进程。`eb5d8d4` 在公开入口 112/112 success、正式入口却 112/112 error，证实两者存在影响结果的差异；worker 是否另行复制文件、实际 `args/kwargs`、工作目录、`sys.path`、精确模块加载 API、进程启动参数、状态分类和 stderr 捕获仍缺失 | import/构造失败、不透明配置污染、诊断丢失，或本地 success 在正式环境被分类为 error | 运行实现兼容根目录扁平部署；入口按 `__file__` 引导同级模块；隔离解释器、根文件副本与不透明参数回归；不依赖 cwd、包子目录、跨题状态或 stdout；正式结果不得用公开 `main.py` 的状态语义替代 |
| OFFICIAL-GAP-TOOLS | 已明确允许离线 MCP/RAG/SymPy/Docker 内本地 sandbox，禁止联网工具和 Lean 运行依赖；子进程、文件写入、包体积及工具消息协议的具体上限仍缺失 | 安全策略触发或能力静默降级 | 当前正式路径暂停模型工具调用；受限本地工具库仅保留离线测试，未来恢复仍须无网络、白名单、限时、限长并重新验证平台协议 |
| OFFICIAL-GAP-CHANGE | 平台 client、runner、镜像、模型、Judger 和限制的冻结日期、版本号与变更公告 SLA；公开 baseline 当前固定提交 `43be244` 无法复现正式平台对 `eb5d8d4` 的 0 请求/112 error | 同 commit 历史成绩无法复现，公开 baseline 通过而正式平台全灭 | 每次正式运行重新保存页面、来源哈希、commit、模型、日志和环境可见信息；旧成绩只作历史观测；记录 baseline 固定 SHA 与正式平台可见版本 |

## 8. 向主办方请求的最小书面契约

下一次正式提交前，优先请求主办方用可留存文字回答：

1. 正式 runner 构造 `ReasoningAgent` 的完整调用形式和实际 `args/kwargs`；注入 client 的包/类版本和完整签名；除已公开三参数外，`thinking_mode`、`tools`、`tool_choice`、`top_p` 是否保证接受。
2. 普通回复和工具调用的返回类型；是否公开 `finish_reason`、usage、request id。
3. 登录后提交页当前可选的精确 API ID、397/35B 映射，以及页面选择与实际调用模型如何对应。
4. 每题模型请求数、输入/输出/总 token、`max_tokens`、RPM/TPM 和重试计数规则。
5. Python、基础镜像、CPU、内存、磁盘、子进程、文件写入和依赖安装阶段的限制。
6. `final_response` 和 `trace` 的 Judge 输入方式、大小限制、证明题要求和隐私规则。
7. client 或 runner 参数错误是否会留下逐题错误类型；`request_count` 的统计起点是什么。
8. 平台组件发生不兼容变更时，是否提供版本号、冻结期和公告渠道。

答复归档时必须记录原文、答复者/官方页面、日期、附件 SHA-256 和适用批次。口头转述不能直接放宽自动门禁。

## 9. 更新规则

- 新增官方文件或截图时，先计算 SHA-256，再逐页/逐图读取并登记来源 ID。
- 不覆盖旧口径；使用冲突行或时间线追加更新。
- 只有直接原文可以写成“官方明确”；推断必须标注为推断。
- 变更模型、客户端、输出或运行边界时，同步更新 `COMPETITION_COMPLIANCE.md`、`ENGINEERING_SPECIFICATION.md`、项目 Skill、离线回归和发布 manifest。
- 原始附件不得直接加入公开仓库，除非完成隐私审查并确认有权公开分发。

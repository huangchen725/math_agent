# 2026-09-04 官方 112 题请求前故障与同名模块碰撞复现

> 性质：正式日志事实与本地确定性 A/B 记录
>
> 正式评测提交：`1fc98b7509b2e07bd229f668cee32e2702cf2cfa`
>
> 原始日志 SHA-256：`68551643cfe8d6defdb356e51a74c31db0bddc169654356d1123cc13450bde68`
> 当前结论：`1fc98b7` 请求前缺陷已本地闭环；正式平台因果待恢复评测确认

## 1. 正式日志事实

| 指标 | 值 |
| --- | ---: |
| 总题数 / graded | 112 / 112 |
| correct / incorrect / invalid | 0 / 0 / 112 |
| success / error / skipped | 0 / 112 / 0 |
| request / attempt / retry | 0 / 0 / 0 |
| prompt / completion / total tokens | 0 / 0 / 0 |
| Agent 阶段 | 约 15.16 秒 |
| infra errors | 0 |

日志明确记录依赖安装成功、正确提交被拉取、runner 正常完成和 client usage 统计完整。因此这不是 112 道数学题全部答错，也不是模型截断、限流或答案格式问题；每道题都在可计数的模型请求之前失败。

## 2. 精确复现

官方 baseline 的加载顺序先导入其顶层 `llm_client`，再导入选手的 `user_agent`。按该顺序复现时，Python 已有：

```python
sys.modules["llm_client"] = official_llm_client
```

提交 `1fc98b7` 的 `model_gateway.py` 又执行：

```python
from llm_client import InternChatClient
```

该语句不会重新读取仓库同名文件，而是取得已缓存的官方类。注入对象本来就是该官方类的实例，所以：

```python
isinstance(client, InternChatClient) is True
```

代码随后进入原本只为项目私有客户端准备的分支，访问 `client.chat_with_metadata`。官方类没有该方法，因而在第一次 HTTP 请求前抛出 `AttributeError`。

| 对照 | 进入 `chat()` | 结果 |
| --- | ---: | --- |
| `1fc98b7` + 官方先加载 `llm_client` | 0 | `AttributeError`，回退为未解出 |
| 同一代码与输入，仅禁止 nominal-type 私有分支 | 6 | 正常完成并产生规范答案 |
| 包结构 `eb5d8d4` + 同一碰撞场景 | 6 | 正常完成 |
| 恢复候选 `319710f` + 同一碰撞场景 | 6 | 正常完成 |

## 3. 根因与范围

`1fc98b7` 的直接根因是三个条件组合：

1. 官方 runner 预载通用顶层名 `llm_client`；
2. 项目扁平化后使用同一裸模块名；
3. 代码用该类身份提高外部 client 权限，并调用私有方法。

这足以解释该提交的 0 请求，并要求永久禁止同类设计。它不能统一解释此前包结构版本的全部 0 请求；尤其 `eb5d8d4` 在同一实验中不受该碰撞影响。正式 runner、构造、client 版本和错误分类仍不完整，相关 `OFFICIAL-GAP-*` 不得关闭。

## 4. 永久门禁

- 不信任 `sys.modules`、`sys.path`、judge 当前目录或预加载状态。
- 不使用通用裸模块名承载正式 client、Agent、context、solver 或 budget 边界。
- 不以外部 client 的 nominal type、同名方法、marker、字段或签名探测开启扩展能力。
- 改动后的正式入口只调用三参数公开 `chat`。
- 回归必须先加载外部同名 `llm_client`，再加载 `user_agent`；并覆盖严格三参数 fake、私有属性陷阱、隔离导入和完整模块污染矩阵。
- 平台兼容性与数学能力分开统计；0 请求轮次不得进入能力比较。

规则编号和重建顺序见 `docs/ENGINEERING_SPECIFICATION.md`。

## 5. 恢复决策

仓库以普通前向提交恢复到唯一取得官方正分的 `350a267f` 内容树，当前工程化实现保存在 `archive/s1-s6-1fc98b7`。下一次正式评测先确认请求链；只有恢复后，才以一次一变量方式加固 client 并重新引入截断和架构能力。

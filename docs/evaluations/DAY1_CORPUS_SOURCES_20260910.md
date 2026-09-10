# 2026-09-10 首日公开题答库来源与清洗

状态：首版数据完成、可复现构建与全库索引往返通过；不是逐题独立数学验收，也不是正式提分结果。数据净化前已确定来源筛选与Q0排除规则。固定公开命中探针的独立数学审查发现一条源答案缺参数条件，按确定反例整条隔离；保留原探针、不换成有利案例。数据侧没有依据模型线上答对/答错来选择库内容。

## 1. 最终规模与许可

| 来源 | 原始输入 | 剔除/隔离 | 收录 |
| --- | ---: | --- | ---: |
| U-MATH公开MIT文本题 | 900 | Q0全部144与近重复共290；原始控制字符破坏公式3；源答案缺参数符号条件1 | 606 |
| Lebl Notes on Diffy Qs，公开题目紧邻公开解答 | 246对 | 图像/交叉引用/未知宏或上下文依赖24 | 222 |
| Levin DMOI第三版，直接statement+solution对 | 280对 | 图像/引用/未支持宏52；解答说明矛盾1；空题面1 | 226 |
| 合计 | — | 无同题异答冲突、无重复计数 | **1054** |

MIT 606条、CC BY-SA 4.0 448条。没有以混合大数据集的顶层license替代上游许可审核。Hefferon原有争议条目及其他题答未加入本次新库；现有教材卡片保持独立。Numina/OpenMath等混合或生成大集合未临时混入。

固定来源：

- [U-MATH数据卡](https://huggingface.co/datasets/toloka/u-math/blob/7210f97b3f21122c3a90126935e966ca7d8951b6/README.md)，明确全部数据MIT，作者题库带专家验证声明。本次复用并重新校验2026-09-06已取得的固定900条文本快照，不把现有下载当成新的900条。原始记录SHA `3c8afc194fdde029bd5275ea487353262485fcdb9e23c5239b959e3d3cc59af5`。
- [Notes on Diffy Qs固定源码](https://github.com/jirilebl/diffyqs/tree/658bcae9fb710f3fae2c9da4ca4524ce157453af)，作者Jiří Lebl；该版本LICENSE提供NC-SA及BY-SA双许可，本库选择BY-SA 4.0。
- [DMOI第三版固定源码](https://github.com/oscarlevin/discrete-book/tree/1e2e26b0be8f47c9862b756ba5d7265b60c47854)，作者Oscar Levin，BY-SA 4.0。本次没有使用许可不同的第四版，也没有读取教师专用分支。

完整来源与每个源文件SHA保存在 `resources/answer_bank/SOURCE_PROVENANCE.json`，许可声明、MIT全文和署名在同目录README及licenses内。CC BY-SA衍生数据保持原许可，不被仓库代码许可覆盖。

## 2. 清洗与事故预防

适配器只访问Q0 `dev.input.jsonl`、`test.input.jsonl`，拒绝任何labels文件或带answer字段的排除输入。按题面先排除，再访问允许入库的公开原始答案。隔离键是仅用于排除的激进数字模板键，双向SequenceMatcher阈值0.88；它绝不用于运行时接受答案，不能声称识别了全部语义等价题。

保留完整小问。Diffy Qs只有当前exercise结束后紧邻的`exsol`可配对，不能把前一道没有解答的题拼到下一道答案上。DMOI只接受同一节点直接拥有statement与单一solution/answer的题；图像、未解析引用、动态WeBWorK及表格依赖整条排除。预处理只按已固定源码定义扩展有限宏；`\\R`不能误改`\\Rightarrow`，省略号、对齐行、否定、全部列表项必须保留。

人工抽查发现一条DMOI饼干题说明将“超过4”与“至少4”混写，整条隔离，不擅自改标准答案。U-MATH三条原始`\\frac`被控制字符破坏，整条隔离。固定探针`umath-00d40e3ce13ab1756fe05034`问参数曲线沙漏面积，未声明a,b符号而源答案为8ab/3；a=1,b=-1导致负面积，是确定反例。复核原题后整条隔离，保留已冻结8个命中探针中的该位置，预期该题不能走库存快答。其他未被发现的原源错误仍可能存在，因此所有条目是`source_verified`，不是`math_verified`。

没有截断题面/源解答来凑记录长度；最终1054条的题面加参考解答均未超过5800字符。所有源答案保留为参考文本，不能直接拿来当规范末行答案。

## 3. 实际构建与验证

数据输入：`outputs/day1-20260910/data/clean-v6/records.jsonl`；SHA `d8a1e550f0bc7fa774fae3b33620612dcc731dd33b44f31f62fffe0879a27c40`。

正式资源：`resources/answer_bank/`；root manifest SHA `4ed168f2a36c48d314ddc33c37b64aa7c71eafc5a1489598553154d8adaa93b1`。第二次独立目录重建得到相同root，0同题异答冲突、0重复计数。

最终全库1054题按原完整题面逐一lookup，1054次全部恢复相同完整record。该次本地观测P95 10.69ms、最慢80.55ms；这是索引往返耗时，不是模型作答或比赛耗时。附带许可与来源资料后当次共521文件、3,334,022字节，随后说明文档编辑可使体积略增。初始1055资源与其8.53ms P95观测完整保留于本地证据，不能替代最终1054验证。

来源适配器34项固定回归已通过，包含：跨习题答案错配、原始hash被改、图像/引用、宏前缀、分页、嵌套花括号、XML小问/省略号/数学行闭合、输入标签拒绝、数字变式仅用于排除、同题异答全隔离、JSON完整往返、原始控制字符损坏、沙漏源答案缺符号条件隔离。全库数学环境与教材显示定界符闭合审计0异常。父任务会把此测试文件纳入全量门禁。

## 4. 复现

先按固定revision取得来源文件（已有公开快照与每文件哈希在来源清单中），然后运行：

```text
python -m evaluation.xh_answer_sources --umath outputs/q0-umath-source-v2 --textbooks outputs/day1-20260910/data --exclude-input outputs/q0-umath-v4/dev.input.jsonl --exclude-input outputs/q0-umath-v4/test.input.jsonl --output NEW_CLEAN_DIR
python -m evaluation.xh_answer_bank --input NEW_CLEAN_DIR/records.jsonl --output NEW_BANK_DIR --exclude outputs/q0-umath-v4/dev.input.jsonl --exclude outputs/q0-umath-v4/test.input.jsonl
```

公开下载脚本和原始文件在 `outputs/day1-20260910/data/`；下载无模型请求、无凭据读取。资源是可发布输入，outputs是本地证据，不应整目录提交。尚未据本库完成任何正式评测；回忆题命中率也不能混入未入库正确率。

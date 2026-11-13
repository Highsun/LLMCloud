# 中文云计算基础语料草稿交接（B）

> 远端阅读：[公开主题/来源索引](cloud-basics-draft-sources-2026-11-12-b.md)和[交付总览](../testing/laptop-3060-handoff-2026-11-13.md)。下表E盘链接用于本机定位；完整语料私下交接，Git中仅公开说明、来源与摘要。2026-11-13已获得本次材料提交/推送授权。

日期：2026-11-12，Asia/Shanghai。交付状态：**120条候选问答已编写并通过工程校验，人工审核尚未完成，未启动正式训练。** 数据和审核正文全部保存在E盘；本文仅为D盘说明与结果摘要。

用户要求先在本地执行验收、回传证据，随后编写语料。本批在本轮200步人工补测结果核对后整理，沿用 [既有数据规则](README.md)，不修改共享Schema/扫描器/依赖/冻结评测规范。云部署留待上线前另行验证。

## 文件位置

| 内容 | E盘实际文件 |
| --- | --- |
| 全部120条JSONL | [cloud-basics-zh-draft.jsonl](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/cloud-basics-zh-draft.jsonl) |
| 逐条可读问答、来源和双人审核勾选 | [review-guide.md](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/review-guide.md) |
| 来源目录 | [sources.json](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/sources.json) |
| record_id/问答族/来源/审核状态侧车 | [curation.json](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/curation.json) |
| 只读复核与原函数构建入口 | [build_draft.py](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/build_draft.py) |
| 训练草稿96条 | [train.jsonl](E:/LLMCloud/data/prepared/cloud-basics-zh-draft-20261112-v1/train.jsonl) |
| 验证草稿12条 | [validation.jsonl](E:/LLMCloud/data/prepared/cloud-basics-zh-draft-20261112-v1/validation.jsonl) |
| 测试草稿12条 | [test.jsonl](E:/LLMCloud/data/prepared/cloud-basics-zh-draft-20261112-v1/test.jsonl) |
| 划分清单 | [manifest.json](E:/LLMCloud/data/prepared/cloud-basics-zh-draft-20261112-v1/manifest.json) |
| 原数据检查/tokenizer检查及哈希结果 | [validation-summary.json](E:/LLMCloud/data/curated/cloud-basics-zh-draft-20261112-v1/validation/validation-summary.json) |

原编写分组输入为同目录authoring-01/02/03.json；它们保留主题和手写问答，用于复核生成结果。不是额外的360条数据。所有原始/划分/验证目录各有SHA256SUMS，不覆盖已有版本。

## 内容与来源

| 范围 | 问答族数 | 条数 | 主题示例 |
| --- | --- | --- | --- |
| Docker基础 | 12 | 48 | 卷、绑定挂载、tmpfs、多阶段构建、缓存、上下文、摘要、资源、端口、网络、重启、日志 |
| HTTP基础 | 5 | 20 | ETag、字节范围、缓存策略、内容编码、认证与权限 |
| DNS基础 | 2 | 8 | 记录类型、TTL与缓存 |
| SQLite基础 | 5 | 20 | 事务、连接隔离、一致性备份、NULL约束、索引计划 |
| 对象存储与负载均衡 | 6 | 24 | S3对象键、版本、分段、校验和、生命周期及负载均衡监听器/目标 |
| 合计 | 30 | 120 | 每族4条概念/情境/误区问答 |

使用30个分别打开核对的Docker、Mozilla MDN、SQLite和AWS官方文档页面，实际URL与2026-11-12查阅记录见E盘sources.json。答案为原创中文表述，不抓取整段文档；涉及S3/Docker/SQLite特性的题目明确限定产品语境，不推广成所有云产品共同承诺。事实来源核对不替代团队对事实、措辞和来源使用方式的人工审核。

E盘独立来源目录另外保留共享目录的5个来源ID，仅用于原冻结协议的来源引用校验；它们不是本次30个新增训练来源，也未被本批记录引用。原项目docs/data/sources.json不改动。原准备CLI固定使用共享来源目录，本批因此通过其公开Python函数 `plan_dataset(..., sources_path=本批目录, allow_unreviewed=True)` 与原 `write_bundle` 生成，使用方式在独立build_draft.py中可审阅；没有复制一套宽松扫描器或改全局常量。

本批侧重云计算部署运维基础扩展，不把原12道冻结题及其问答族改写混入训练/验证/测试。按族隔离避免同族4条分散到不同集合，但跨族语义近重复、题目独立性仍须人工复核，不能把ID/哈希检查通过表述成已证明没有语义泄漏。

## 实际校验结果

- 原数据34533字节、120条，SHA-256：`d8a00d7bd16354a0577b6aeef88437c30a633c37e02a958d59d649e83d227f1e`。
- 原DatasetScanner/InstructionRecord校验通过；规范化instruction/input去重、冻结prompt精确匹配/保留族检查通过。完整output字符串重复0条，不等于已完成语义去重。
- 固定seed42、30族各4条，按原SHA-256族排序策略划分24/3/3族，即96/12/12条；三组族集合互不相交。两次内存重建逐字节相同，build_id=`54acf9229ff98c04`。
- train哈希=`5033df310c2c3a804f0ab35ca35cf7c9ee56261e23819ad1ddd8055a14b7817f`；validation=`4e3ef8d20966b87b416b15b93224e23aab0a8b5f6567fe8fed6378d4272068b7`；test=`ccab4294784c7073e747f912d59faf44d10fa8b0419f4ea2767e0438b4716280`。
- 原始与划分文件哈希均验证通过。120个curation.reviewed均为false，manifest/provenance保持draft_unreviewed。
- 调用原scripts/check_training_data.py，固定Qwen revision `7ae557604adf67be50417f59c2c2f167def9a775`、原chat template，在CPU离线诊断96条train和12条validation；max_seq_length=256，两组截断数均0，回答监督有效，样本EOS监督正常，批次padding检查通过。
- tokenizer诊断没有读取test正文，没有加载基础模型、使用GPU、更新参数、给模型效果评分，亦未使用本批调参。原prepared metadata核对通过，不把草稿状态升级成reviewed。

复核环境为E盘Ubuntu的clean `9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca`，与本轮测试同一项目代码。完整诊断/错误流在E盘validation子目录，D盘仅保留对应 [小型结果摘要](../../data/acceptance/b-review/laptop-3060/20261112T131702Z-manual-po1lbqv7/corpus-draft-validation-summary.json)。tokenizer-only工具设置USE_TORCH=0时可能打印PyTorch不可用提示，这是本次诊断隔离，不代表原训练环境缺少torch。

## 下一步人工审核与使用

1. 用户/B逐条核对review-guide.md，队友/A交叉检查事实、来源、边界措辞、问答族和与冻结题的语义独立性，记录审核人/日期/结论。不能批量自动勾选。
2. 发现相近题时调整族或删除/改写，所有变化保存在新版本；原草稿及其哈希保留。审核通过后再产生新的reviewed侧车与正式划分，不能只改旧manifest中的状态字符串。
3. 正式效果实验只把train用于训练、validation用于模型选择；test及冻结题留到方案确定后评测。当前96/12/12是候选划分，不代表已形成最终冻结实验数据。
4. 本批短回答在256长度下已验证无截断；这只是输入工程检查，不是训练超参数或效果最优的结论。审核完成后再另行确定正式实验的训练规模、参数与对照。

原冻结规范C12含有早期项目状态相关的critical_errors表述，而当前本地真实异步链路已经实测；正式评分前应由双方复核其适用性。本次不修改v1、不据旧状态给模型评分；如需变更，按现有规则新建协议版本并记录原因。

本次只新增本批E盘数据及D盘自有说明/结果，未修改队友业务实现、共享契约/依赖/旧数据样例或冻结协议，未提交/推送。远端fetch仍受本机127.0.0.1代理不可达影响，最新远端变化尚未确认；数据与正式审核状态需随交接单独核对。

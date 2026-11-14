# 候选语料v2：B侧授权采纳与交接

日期：2026-11-14（Asia/Shanghai）。用户明确委托助手完成本侧确认并提交。B侧决定为：采纳[联网资料核查](cloud-basics-web-review-2026-11-14-b.md)的结论，将14条建议应用到独立候选版本，保留106条原回答，交A继续交叉复核。

确认方式为用户聊天中的明确授权，由Codex执行资料核查与修订；没有把该委托写成用户已逐条亲自查证，也没有代填队友签字。原始核查报告仍标AI核查，B侧采纳另存独立记录。

## 新版本与实际结果

| 项目 | 结果 |
| --- | --- |
| 版本 | cloud-basics-zh-candidate-20261114-v2 |
| 总量/原问答族 | 120条/30族；本次不自动调整族边界 |
| B侧采纳范围 | 120条核查结论；应用14条修订，106条保持原样 |
| 资料来源 | 原30个引用来源+10个补充来源；45项目录含5个冻结协议继承来源 |
| 数据格式/引用 | 原DatasetScanner和准备函数的纯内存草稿检查通过 |
| 正式审核状态 | A交叉复核、族边界与协议适用性待完成；curation.reviewed全为false |
| 运行产物 | 未生成新train/validation/test划分，未启动正式训练或效果评分 |
| 原件 | 原草稿10项文件、原核查报告7项清单及共享冻结协议哈希均不变 |

新JSONL为35,755字节，SHA256：

```text
f5a7d697c82f59680b251c5a330cc33fd34e3b3ef5ad9b6deb073dbba7d7c8c2
```

完整文件留在本机E盘，不随Git发布：

```text
E:\LLMCloud\data\curated\cloud-basics-zh-candidate-20261114-v2\
  cloud-basics-zh-candidate.jsonl  新候选语料
  curation.json                   原逐行映射/族ID，reviewed仍false
  sources.json                    含补充来源的新目录
  b-adoption.json                 用户授权方式及120条采纳记录
  applied-revisions.json          14条修改前后对照
  review-guide-b.md               可读候选及采纳说明、A待复核栏
  source-checks.json              官方资料与核查章节
  semantic-review.json            7项语义/评测边界
  validation-summary.json         原工具校验及原件保留结果
  SHA256SUMS                     完整性清单
```

## 给队友的私下交接包

已在E盘生成ZIP与同名.sha256，并核对12个条目无重复、CRC正常、解压内容与源文件逐字节一致。尚未向队友发送；本机路径不是GitHub附件。

```text
E:\LLMCloud\data\handoffs\cloud-basics-zh-candidate-20261114-v2-b-adoption.zip
```

- 大小：58,289字节。
- SHA256：333dbf643e33598f5eef2833d697170019d8f4760479a6f4fb8b74565b822b65。
- 包含候选问答、逐条采纳、修订对照、来源、语义边界、校验结果及构建记录，不含模型、DB、Adapter或HAR。

接收后先核验ZIP摘要，解压到全新的私有目录，按SHA256SUMS核对文件；先看README、review-guide-b.md及applied-revisions.json，再复核来源、语义族与冻结协议。不要覆盖原v1，也不要仅把reviewed批量设true后训练。

## A侧仍需确认

1. 交叉复核修订候选及来源依据，记录实际审核人、日期与结论，明确数据使用方式。
2. 处理5组跨族语义线索及C06独立性；相同主题不自动等于泄漏。需要合族时在正式实验前统一建立新版本，不为评分结果移动留出题。
3. 共同核对既有C12过时关键错误条款是否需要新协议版本；本轮不改受保护的v1。
4. 双方实际审核完成后，再用原准备工具产生正式划分与清单，开展正式实验。

本次仅提交公开摘要和B自有日志到既有B分支，完整语料及交接包保持私有。B侧授权采纳已记录，A/B联合审核尚未宣称完成。

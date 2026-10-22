# M1-06 领域数据与评测规范

版本：1.0.0。日期：2026-10-22。交付范围：候选领域和数据来源、人工整理流程、可复现划分工具、首批冻结测试题。正式实验语料尚未完成收集与双人审核，本次没有声称已经拥有 100–300 条高质量领域数据。

## 领域选择

| 候选 | 优点 | 限制 | 本轮决定 |
| --- | --- | --- | --- |
| 中文云计算基础问答 | 对应课程，官方事实来源可查，适合 0.5B 短回答 | 避免仅背术语，需情境题与条件边界 | 选定，标识 cloud-basics-zh |
| LLMCloud 使用问答 | 项目自身资料可追溯 | 当前功能仍演进，不能把计划写成已实现 | 作为少量边界/运维题，记录代码版本 |
| 通用聊天/代码生成 | 大型公开语料较多 | 范围大、授权/质量核对成本高，难以用小数据验收 | 暂不引入 |

目标任务是用中文直接回答概念、职责与简短情境问题。回答通常 2–5 句，有条件时说明条件，不承诺无限资源、绝对不丢数据或尚未实现的项目能力。先覆盖服务/部署模型、容器与虚拟机、持久化和异步任务；不扩展为 Kubernetes 实践、大模型知识库或自动抓取平台。

## 来源与原创要求

[sources.json](sources.json) 记录来源 ID、URL、适用内容和查阅版本：

- [NIST SP 800-145](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-145.pdf)：云的特征、服务和部署模型。
- [Docker 容器说明](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/)：容器/虚拟机与隔离。
- [Redis 持久化](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)：恢复策略及取舍。
- [Celery 任务队列简介](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)：客户端、Broker、Worker 的职责。
- 仓库 requirements/architecture/datasets：仅作为第一方项目事实来源，关联实际 Git commit。

以上是参考事实来源，不是已获授权可直接批量导入的训练数据包。成员用原创表述整理问答，记录依据和来源版本；不整篇抓取、复制正文，不导入凭据、个人信息、用户上传内容或许可证不明的数据。若后续直接采用外部数据集，先单独核对其许可、署名/再分发要求和语言质量，更新来源清单再处理。

建议先收集 100–300 条、至少约 30 个独立问答族。成员 B 编写，成员 A 交叉复核事实、措辞、来源使用及题目独立性；AI 草稿必须标为未审核，不自动批量标 reviewed。记录审核依据于私有数据目录，不把正式语料或模型回答提交 Git。

## 输入、审核与划分

输入仍为已有严格 instruction/input/output JSONL，上传与训练共用 DatasetScanner。来源/审核信息放独立 curation.json，不增加上传字段或放入训练记录。侧车示例见 [curation.example.json](../examples/datasets/curation.example.json)。

每条侧车记录包含 row、record_id、group_id、source_ids、reviewed。row 从 1 起，指有效非空白记录的顺序，不是物理行号；必须逐条完整映射。record_id 唯一；group_id 为独立问答族，同一事实的复述、改写与衍生题都使用相同 group_id；source_ids 引用来源清单，reviewed 必须是布尔值。ID 使用小写字母、数字、下划线或连字符，最长 64。

划分采用固定 seed=42 对问答族 ID 做 SHA-256 排序，约按族数 80/10/10 分 train/validation/test。每个留出集分配 max(1, floor(族数/10)) 个族，剩余族用于训练，至少需要三个族。组内样本不跨集，因此实际行数比例可能不同；manifest 记录真实数量。小样本三族只能各一族，不能称为正式实验划分。

这是离线实验语料质量规则，API 仍允许同内容重复上传并返回新 ID。工具拒绝规范化后重复的 instruction/input，规范化只用于比较，训练文本保留原有空白。冻结题的 prompt 与 group_id 都不能进入这三个开发子集。这个检查不能识别所有语义相似题：成员仍需人工检查问答族、改写和近重复；不能因哈希不相等就断言无泄漏。

```bash
# 格式冒烟：仅检查，不写数据；三条样例和未审核侧车仅演示流程
uv run --locked python scripts/prepare_dataset.py \
  --source docs/examples/train.jsonl \
  --curation docs/examples/datasets/curation.example.json \
  --allow-unreviewed --check-only

# 将格式样例写成草稿包；输出目录必须不存在，所有产物位于忽略的 data/
uv run --locked python scripts/prepare_dataset.py \
  --source docs/examples/train.jsonl \
  --curation docs/examples/datasets/curation.example.json \
  --allow-unreviewed --output data/prepared/format-smoke-v1

# 正式人工审核后再运行，不带 allow-unreviewed
uv run --locked python scripts/prepare_dataset.py \
  --source data/curated/cloud-basics-v1.jsonl \
  --curation data/curated/cloud-basics-v1.curation.json \
  --seed 42 --output data/prepared/cloud-basics-v1
```

默认拒绝未审核数据；显式允许时 manifest 永久标注 draft_unreviewed。已存在的输出目录一律拒绝，不使用 --force；检查模式不写文件。CLI 输出必须位于配置的 DATA_DIR，拒绝越界路径。来源文件不改写。

输出包含 train.jsonl、validation.jsonl、test.jsonl、provenance.json、manifest.json。manifest 最后写入，记录原始输入/侧车/来源清单/评测协议哈希、seed、工具版本、build_id、每集行数/字节数/哈希/族 ID、审核状态；不记录本机绝对路径。已确认写入失败只清理本次拥有的文件；强杀或清理失败时可能保留无 manifest 的目录，不能将其当成完整包。复现实验还要记录代码 commit、环境锁和模型 revision。

## 两层留出与首批固定题

[cloud-basics-eval-v1.json](cloud-basics-eval-v1.json) 固定 **12 道公开评测题**、族 ID、参考要点、关键错误和来源 ID。它是版本化评测规范，不是训练 JSONL 或模型生成记录。修改题目/评分须新增 v2，不覆盖 v1。

- validation：训练中做模型选择与早停；不与训练族重叠。
- test：开发语料中的一次性留出，在超参数确定后评估；不用于反复调参。
- 冻结 12 题：独立于上述三个子集，用于基础模型与 Adapter 的固定对照，也不得用于训练或调参。

固定题包括弹性场景、服务责任、混合云、虚拟化与云的区分、容器内核、部署兼容性、Redis 恢复条件、持久化选择、提交与完成、任务组件、上传重试、API/GPU 职责边界。它们不构成专业能力认证，只是本项目的小规模对照。

基础模型与微调模型使用同一 chat template、prompt 和解码参数；初始 do_sample=false、max_new_tokens=192，记录基础模型 revision、Adapter 哈希及完整生成配置。每题准确性 0–2、清晰度 0–1、边界意识 0–1，共 4 分；总分 48。两人盲评，保留各自评分和分歧，不只展示提升案例。原始输出和评分存于被忽略的 data/experiments/，汇总到 experiment.md，当前没有任何模型输出或成绩。

## 下一阶段入口

M1-06 的数据说明、工具与冻结题已具备；正式语料仍需人工收集/审阅。M2 先用极小数据验证 Qwen2.5-0.5B 真实加载、LoRA、产物重载，再用审核后的数据包做正式实验。三个格式样例只用于工程冒烟，不能作为有意义的效果实验。

具体任务按 [M2 开发计划](../m2-development-plan.md) 执行：B 负责数据转换、训练与重载，A 负责契约、缓存及产物规范，并交叉审核正式语料。工程闭环与正式效果实验分开验收；数据清单中的 reviewed/draft 状态继续保留，原始上传文件缺少审核依据时明确记录未知，不能自动升为已审核。

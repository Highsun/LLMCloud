# 项目状态与协作记忆

梳理日期：2026-10-24。这是成员及 AI 助手的当前状态摘要；详细契约以 datasets.md 和 Pydantic Schema 为准，历史过程见工作日志。开始任务时仍须核对最新 Git、日志和实际代码。

## 项目目标与边界

LLMCloud 将 Qwen2.5-0.5B-Instruct 的 LoRA 微调封装成异步云服务。交付链路：上传数据 → 配置微调 → Celery 排队 → 单 GPU 真实训练 → Loss/日志 → Adapter 下载 → 测试推理。团队两人、每人每周 6–8 小时、八周完成，先实现单用户与单 GPU 闭环。

开发环境为 WSL2 Ubuntu、Python 3.12/uv、Node/Vue3/Vite；RTX 5070 12GB 用于本地训练验证。API 使用 FastAPI，SQLite 管元数据、本地文件管数据和产物，Redis/Celery 执行异步任务。当前不引入更大模型、量化、Kubernetes、多 GPU 或新的存储服务。

## 已确认的实现

| 范围 | 当前事实 |
| --- | --- |
| M0 | 工程、uv、健康检查、模型白名单、Redis/Celery ping、GPU 环境验证已完成 |
| M1-01/02/03 | 严格 JSONL 扫描、不可变数据集存储、迁移/审计、上传/分页/详情 API、统一错误与 request_id 已完成 |
| 成员 B 前端 | `5665ef2` 交付 Vue 工作台、数据集页面及后续阶段界面；`5114741` 合并 M1-03；`65fb120` 补交文档与日志 |
| M1-04 接续 | 在成员 B 页面基础上修复列表刷新竞态与窄屏溢出，22 项前端、8 项真实浏览器、61 项后端及生产构建通过；见 [接续日志](worklogs/2026-10-22-m1-04-integration.md) |
| M1-05/06 | 故障验收与 GitHub CPU CI 已通过；来源方案、按族划分与审核工具、12 道冻结题、格式草稿包已交付，72 项 CPU 检查通过 |
| M2-01 | [内部训练契约 1.0.0](contracts/training.md)、CPU 校验类型、Schema/格式样例、导出漂移和错误结构已交付 |
| M2-02 | [模型缓存与离线检查](model-cache.md) 已交付，真实 Qwen BF16 GPU 前向通过；固定 revision 为 7ae557604adf67be50417f59c2c2f167def9a775，9 文件/999,602,607 字节 |
| M2-03 | [数据转换、标签、截断、padding 与清单核对](training-data.md) 已交付；真实 tokenizer 和 CPU 张量验证通过 |
| M2-04 | [真实训练](training.md)、CLI、同源指标/回调、基础保存已完成；本机真实 Qwen LoRA 更新及冻结权重哈希验证通过 |
| M2-05 | [共享 CPU 产物审计](training-artifacts.md)、排他原子提交与保存故障验收已完成；已校验 M2-04 真实产物和新训练结果 |
| M2-06 | [新进程重载](adapter-reload.md) 已实际加载并生成，M2 工程闭环完成 |
| M3 | [协作计划](m3-development-plan.md)/[API 草案](api/tasks.md)/[交接](m3-handoff.md) 已整理；01～07 实现均待开始 |
| M4–M5 | 页面观测/下载和在线推理待完成 |

`trainer.train` 已执行真实 Qwen LoRA，`worker.train` 仍是业务占位。已有产物的新进程重载已通过；未来各任务仍须分别验收，不表示正式效果提升。

## 必须延续的接口与实现决定

- 数据集 API 固定 `/api/v1/datasets`；上传只接收 file 和可选 name，成功 201，列表分页直接返回 DatasetPage，详情只读元数据。
- 文件上限 50 MiB、单物理行上限 1 MiB、multipart 总体上限 50 MiB + 64 KiB。UTF-8 JSONL，instruction/output 必填，input 可省略。上传与 Trainer 共用扫描器，前端不另写内容解析器。
- 原始字节、大小、行数和 SHA-256 由服务端产生；存储键为 `datasets/{UUID}/train.jsonl`，文件名不能决定路径；上传后不可变。
- 错误保留真实 HTTP 状态，用稳定 code 判断条件；request_id 由服务端生成。浏览器网络失败或取消后，上传可能已保存，不自动重传。
- 上传成功重新读取第一页；并发查询仅允许最新请求更新数据、错误与加载状态。
- 新库启动建表，旧库显式 `--check`/`--apply` 迁移，不删库。OpenAPI 从真实应用生成，不能恢复成手工维护的另一套设计稿。
- API 不加载 GPU 模型或直接训练；Trainer 不依赖 HTTP/Celery/SQL。后续单 Worker 串行执行，训练与推理互斥。
- M2 沿用 TrainRequest → train → TrainResult，类型在 trainer/contracts.py；原 trainer.train 导入位置保留，已从占位 dataclass 迁移为 Pydantic 关键字构造。Request 新增必填 model_revision/cache_dir/log_path，进度新增 learning_rate/epoch/recorded_at，结果新增 tokenizer/config/manifest 路径，详见契约迁移说明。
- step 表示优化器更新步数，kind 区分 train/eval，时间归一 UTC。Trainer 通过 MetricWriter 单独写入并 flush metrics.jsonl，再回调同源事件，Worker 更新数据库不重复写入。公开 TrainingConfig 保持不变，内部 RuntimeOptions 管理 precision/max_steps/local_files_only。
- 模型/tokenizer 固定 revision，使用同一 chat template，检查助手回答监督与截断。成功前校验 Adapter/配置/清单，工程验收须在新进程重载；不能将格式草稿训练或文本变化当作效果提升证据。
- 模型缓存由 trainer.model_cache 统一解析、下载与校验，CLI 为 scripts/prepare_model.py。cache_dir 默认 HF_HOME/hub，环境/.env 与显式参数按文档优先级解析；verify_model_cache 不导入 HF/torch、不联网、不写文件，检查每个文件的大小/摘要与 revision，返回已验证的 snapshot_dir。缓存清单不是训练成功 manifest。
- 训练数据由 trainer.preprocessing.prepare_training_data 处理，继续使用 DatasetScanner；固定模板无 generation 区块，完整文本偏移决定回答标签，不重复特殊 token，不手动 shift。InstructionCollator 保留 labels 并右 padding；部分回答截断不强行补 EOS，仅 prompt/EOS 的样本必须失败。
- 可选数据清单与实际 train/validation 的哈希/统计、provenance/族/审核状态核对，不读取 test 正文；无清单 review_status=unknown，草稿不升级 reviewed。check_training_data.py 默认只读统计，显式 --show-sample 才显示样本。

## 协作与下一步

成员 A 主负责后端/存储/调度，成员 B 主负责 frontend，并在 M2 承担训练。M2 中 A 主改契约、缓存和产物校验辅助模块，B 主改 trainer/train.py、数据转换和重载入口；共享类型先核对，不并行改同一训练入口。保留成员 B 的组件、样式和页面结构；必要修复以最小变更配合回归验证，并在新日志说明原因。不要覆写历史交付记录。

每次开发前、每个独立部分完成后及最终提交/推送前 fetch、检查工作区、阅读新增工作日志与相关代码；落后时优先 ff-only，分叉时保存自身提交后正常 merge，冲突后重跑相关检查；提交仅包含本次任务文件。测试使用独立临时库，不能把自动化上传留在实际业务数据中。

M1-01 至 M1-06 的计划范围已完成；数据方案见 docs/data/README.md，格式草稿不等于正式语料，冻结题/族不得进入训练或调参。正式语料继续由团队编写/审核。M2 独立 Trainer 工程闭环已完成，下一步 M3 接入 Celery 业务调度。

M2-01 已交付类型和格式约定，生成 Schema/样例使用 scripts/export_training_contract.py，--check 检查漂移。M2-02 已执行真实缓存与 GPU 前向；M2-01 的格式占位仍不是实验数据。M2-04 已进行真实 LoRA 反向/优化器更新和基础保存；M2-05 独立产物审计/保存故障验收已完成，新进程重载已完成，正式效果评测未完成。

下一步 M3 异步调度；M2-06 已完成真实生成验收，接续见 [日志](worklogs/2026-10-23-m2-06.md)。复用 trainer.artifacts.verify_training_artifacts 获取已校验的路径和清单，不能将 artifacts_verified 当成加载/生成成功。M2-05 见 [日志](worklogs/2026-10-23-m2-05.md)。M2-04 由本次用户指定当前侧交付，入口见 training.md，实测见 [M2-04 日志](worklogs/2026-10-23-m2-04.md)。Trainer 复用 load_training_tokenizer / prepare_training_data / InstructionCollator，不另写标签逻辑；M2-03 按本次用户要求由当前侧交付，B 后续接续时核对调用方式。工程闭环预算约 14 团队人时；正式语料审核与效果实验继续独立记录；交接见 [M2-03 日志](worklogs/2026-10-22-m2-03.md)。

入口：[项目规划](project-plan.md)、[M2 执行计划](m2-development-plan.md)、[数据集契约](api/datasets.md)、[成员 B 日志](worklogs/2026-10-21-m1-04-frontend.md)、[日志索引](worklogs/README.md)。

## M3 接续决定（规划，未实现）

A 负责 SQL 仓储/条件状态更新、显式迁移、HTTP/派发与离线对账；B 负责 Worker/单实例保护及现有前端接通。先共同提交 Task Schema/Protocol/样例，两边随后用独立替身检查，不互相等待完整实现；真实 Redis/GPU/浏览器验收仍须合作。预算约 20 人时加 4 缓冲，不能沿用一周必然完成的假设。

派发 not_sent 与 unknown 分开；unknown 可留 PENDING 或已被领取状态，返回可查询 task_id。计划支持可选 Idempotency-Key，同键不重发；消息领取仍需 claim_token CAS。早确认不承诺崩溃自动恢复；最低限度对账离线应用，先停 API/Worker，不擅自重训。上述均须在 M3-01～07 实现并验收，当前任务路由和 worker.train 仍未实现。

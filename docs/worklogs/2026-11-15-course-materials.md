# M5 课程材料准备

日期为 2026-11-15。用户要求继续完成 M5 稳定性、部署与课程交付，并明确将 M3/M4 追加异步复核留到开发完成后统一进行。本项基于已有正式 E01 结果准备可直接使用和继续编辑的课程材料，没有重新训练、重新生成或重做留出评估。

## 交付

材料入口为 [docs/course/README.md](../course/README.md)。包含课程报告 Markdown 正文、11 页可编辑 PPT、PPT 逐页内容源、约 6 分 40 秒演示脚本、视频素材索引与机器可读实验事实。报告覆盖系统设计、数据划分、冻结参数、训练与重载、留出指标、评分分歧、稳定性验证方法和单机部署与持久化验收。

PPT 使用原生可编辑柱状图，Loss 图从零起算，评分轴显示满分 48，避免放大差异。首版两张插图来自 2026-11-12 活训练和 2026-11-14 GPU_BUSY 的真实历史截图，图注明日期与环境，不将其写成本轮新跑；更新后第 9 页改为本轮故障注入实测结果，GPU_BUSY 截图继续保留在历史素材 MP4 中。每页备注保留来源与口播。原始语料、完整回答、评分原表与身份映射未复制到课程材料。

结论保留 E01 的全部关键限制：8 条留出集、259 监督 token 的 Loss 从 4.395694571 降至 4.024454654，用户人工评分 25→33，A 侧文件声明的 AI 代评 27→21。混合总分 52→54 只作描述，不能称双人人工盲评或稳定质量提升。训练实际 dirty 基线和后续补丁冻结提交分别记录，未改写历史身份。

## 验证

通过第一方 Artifact Session 创建文稿、导出 PPTX，并逐页渲染检查全部 11 页。修正活训练页换行与实验图表默认数轴后，重新渲染相关页。PPTX 包完整性检查为 0 findings，16:9、11 页、标题与项目符号几何检查为 0 findings、0 warnings；含 2 个原生图表和 11 份备注。没有声称在 PowerPoint 原生客户端打开过。

首版逐页预览与布局 JSON 位于 `E:\LLMCloud\data\course-build-20261115\slides`。Live 文稿 artifactRef 为 `artifact_wevLNuk7fCqagYvSDwGG3EyA64WOEyua`，本地最终文件在 `docs/course/LLMCloud-course.pptx`。后续依据本轮真实 GPU 故障结果更新第 9 页并重渲染，更新版预览另存 `slides-v2`，未覆盖视频原始输入。11月16日最终部署与恢复结论更新第1/9/10/11页后再次渲染检查，最终预览位于 `slides-final-20261116`，PPT SHA-256 为 `98d984cd0f8334595b0ff697b6cf862531618aae92badc071e3800ddea7b7685`。后续若更新文稿，应重新渲染和记录摘要。

本轮新增结果准确说明首 CUDA token 后受控暂停 95 秒，90.063 秒返回 504 / INFERENCE_TIMEOUT，清理期 GPU_BUSY，后续 compare 成功；另含 Worker 异常退出、缓存缺失、实际 Redis 确认丢失与迟到/重复消息恢复。运行 auth=false、工程测试 Adapter，不写成自然慢生成、用户系统 GPU 联合验收或 E01 新实验。

## 剩余范围

当前 Windows 打包运行时不含 LibreOffice，未交付未经逐页渲染验证的 Word 文件，报告采用可直接编辑的 Markdown。已有 8 张真实截图，未找到可直接交付的连续实录视频。本项另完成 46 秒无配音历史证据与 E01 图表 MP4，永久文字说明非在线实录，不称完整演示成片完成。视频与 manifest 留 E 盘，生成脚本纳入课程目录，详见素材索引。

部署章节引用 `docs/deployment.md` 与 `docs/testing/m5-deployment-2026-11-15.md`。账号、M5故障、浏览器120秒、完整四服务容器和11月16日恢复结果已按实际独立记录更新；主机重启、云端业务、HTTPS与标准云端NVIDIA runtime未因此通过。未提交或推送 Git。

## 2026年11月16日收尾

本次只在课程目录和本日志收尾，原11月15日实验/录像日期不改。报告补齐账号与归属、最终448项CPU（447通过、1原可选跳过，已含auth12与来源清单5项）、五契约、19项推理CPU、10项Edge fixture浏览器及120488毫秒计时的准确范围。

保留首次全GPU容器无.git导致 MODEL_LOAD_FAILED 的实际失败和来源清单修复；修复后本机四服务全部容器的新账号真实闭环通过，task18c617b2-c024-4911-85f7-cd2f35dd97d1、2步19.016450秒、末Loss3.8488，下载原审计12文件/96张量/2指标与源一致、compare各64token及390px通过。11月16日独立daemon与四服务重启后SQL四表各3行、上传3文件、outputs28、cache28摘要一致，SQLite完整性/FK、唯一Worker锁和Redis AOF保持；这一轮未新增GPU运行。

新生成两份不剪辑、不变速、不缩放的H.264 MP4，运行材料全留E盘：

| 素材 | 实际身份与长度 | SHA-256 |
| --- | --- | --- |
| `20261115-live-demo/LLMCloud-live-demo.mp4` | 容器API/前端/Redis加原生GPU Worker，40.000秒 | `3d009b47af175b8dc092227b2d209a3d76bdbebb0457d5f92362b4a44acb7e77` |
| `20261115-container-demo/LLMCloud-container-demo.mp4` | 完整四服务容器真实流程，39.520秒 | `05cf4fb4ff9aeb0493277461c4329adda67b8f7d643915282967dc63ddb86030` |

两者均在 `E:\LLMCloud\data\course-video`，另保留46秒历史图表素材。CPU转码脚本为 `docs/course/transcode-live-demo.py`，原始WebM、manifest、精确命令和关键帧独立保留。源与输出时长、尺寸1440×1000、25fps相同，全解码通过，分别检查9个起点/过程/尾部关键帧；未声称播放器连续观看。灰色留白为原Playwright视口切换行为，不裁切伪装，注册步骤很短。带口播5–8分钟完整成片仍需后续展开。

最终PPT结构与几何再次检查均0 findings、0 warnings。报告 `docs/course/report.md` SHA-256 为 `43f14d01ee3ad70e0ef6ada20412f34b2706dde3980bc89c9cf9988a417603c8`。材料仅证明已验证B分支；队友 feature/user-system 的 a935316 与本侧schema不兼容，分支独立保留未合并，不声称A+B合并验收。M3/M4追加异步复核按最新安排留待开发完成后统一记录，云端与目标旧库仍待实际验证。

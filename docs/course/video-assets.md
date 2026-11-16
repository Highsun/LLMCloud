# 课程演示视频素材索引

当前已提供 39.520 秒完整四服务容器真实浏览器 MP4、40 秒首轮混合部署 MP4 和 46 秒无配音历史证据素材。尚未完成带口播的 5–8 分钟课程演示成片。历史截图仍按原日期与环境使用，不能冒充本轮新验收。视频与原截图留 E 盘和被忽略的本机证据目录，默认不复制入 Git。

## 完整四服务容器真实录像

优先使用 `E:\LLMCloud\data\course-video\20261115-container-demo\LLMCloud-container-demo.mp4`。时长 39.520 秒，1440×1000、25fps、H.264/yuv420p，无音轨，8361490 字节，SHA-256 为 `05cf4fb4ff9aeb0493277461c4329adda67b8f7d643915282967dc63ddb86030`。2026-11-15 实际录制，2026-11-16 仅转码整理，不改原测试日期。

此次 API、前端、Redis 与唯一 GPU Worker 全在本机 E 盘 WSL ext4 容器中运行，私有 CDI 提供 RTX3060，账户模式开启。新账号通过真实 UI 注册并完成上传、2 步训练、Loss/日志、下载、compare 与 390px，无 mock。task_id 为 18c617b2-c024-4911-85f7-cd2f35dd97d1，训练 19.016450 秒；独立 ZIP 审计 12 文件、96 张量、2 指标，源字节完全一致。范围是本机全容器，不能称为云端上线，也不能外推到尚未合入的队友用户系统分支。

源 WebM 为 `E:\LLMCloud\data\local-validation\m5-completion-20261115\container-demo-02\page@05da2fa9e26aeb877c9b1dd9309e2bc4.webm`。使用 [transcode-live-demo.py](transcode-live-demo.py) 的 output-name 和 deployment-scope 参数 CPU 转码，未剪辑、变速或缩放。源与输出时长、尺寸、帧率一致，全流解码通过；0、1、5、15、20、23、30、38、39.48 秒关键帧已检查，尚未播放器连续观看。初始注册帧和末尾窄屏的固定画布灰色留白属于原录制行为，不是转码拉伸；操作较快，不作为教学式逐项讲解。精确命令、源与输出摘要、流信息和检查帧均留输出目录。

## 本轮真实浏览器录像

可用 MP4 为 `E:\LLMCloud\data\course-video\20261115-live-demo\LLMCloud-live-demo.mp4`。时长 40.000 秒，1440×1000、25fps、H.264/yuv420p，无音轨，8682975 字节，SHA-256 为 `3d009b47af175b8dc092227b2d209a3d76bdbebb0457d5f92362b4a44acb7e77`。

该次在新账号下完成真实浏览器流程，注册由 UI 点击、填写用户名密码并提交执行，之后包含上传、3 步训练、Loss/日志、下载、compare 与 390px 窄屏，无 mock。注册表单展示很短，不是教学式逐项讲解，不能承诺观众能清晰读完全部注册操作。部署范围是容器 API、前端和 Redis，以及同机临时原生 GPU Worker，不是全 GPU 容器或云端验收。task_id 为 21774371-36a6-4b51-b9a1-ef33a0a7bec0；下载 ZIP 已独立原 CPU 审计 12 文件、96 张量、3 条指标，且与源文件一致。原结果见 docs/testing/m5-demo-results-2026-11-15.json，UI 操作脚本为 scripts/check_demo_browser.mjs。

源 WebM 为 `E:\LLMCloud\data\local-validation\m5-completion-20261115\live-demo-02\page@da82010b27f9685cd646b4e5a6b076e4.webm`。使用 [transcode-live-demo.py](transcode-live-demo.py) CPU 转码，不剪辑、不变速、不缩放，源与输出时长、尺寸、帧率一致，全流解码通过。0、5、10、15、20、25、30、35、39.96 秒关键帧已检查，尚未在播放器连续观看。末尾窄屏切换的固定画布灰色留白属于原录制行为，正式成片建议补录固定窄屏片段。manifest、原始流信息、精确命令和关键帧均留输出目录。

## 已生成的无配音素材片段

可用片段为 `E:\LLMCloud\data\course-video\20261115-historical-material-v1\LLMCloud-historical-evidence-silent.mp4`。时长 46.000 秒，1280×720、24fps、H.264/yuv420p，无音轨，SHA-256 为 `d713e7a88fc785066a36a6ed91de3d203effa32e4e9a9ff323d9cf36eb922f93`。

片段按 10 秒活训练历史截图、12 秒 E01 留出 Loss、14 秒评分分歧、10 秒 GPU_BUSY 历史截图排列。全程文字明确标注“历史证据与实验图表素材 非在线实录 无配音”，并标各段日期，可作为正式视频插入素材。不是 5–8 分钟完整课程演示，不包含本轮 90 秒超时实录或用户系统验收录像。

复现脚本为 [render-video-material.py](render-video-material.py)。输入是当时逐页渲染的 PPT PNG 快照，留在 `E:\LLMCloud\data\course-build-20261115\slides`，保留原输入哈希。PPT 后续更新的新结果另存 `slides-v2`，不覆盖本片源图。脚本通过参数接收 ffmpeg、ffprobe、字体、源图和新输出目录；manifest、精确时间线、编码命令及逐场景和切点检查帧均在输出目录。

本片使用本机已安装剪映附带的 FFmpeg，CPU MediaFoundation H.264 编码，不与训练争用 NVIDIA 编码器。ffprobe 时长与 46 秒时间线一致，全流解码通过，4 个场景及 8 个起点、切点、尾帧已检查。尚未在播放器连续播放核验，不将逐帧和解码检查描述为完整人工观看。

| 来源相对目录 | 文件 | 内容与使用边界 |
| --- | --- | --- |
| data/acceptance/b-review/laptop-3060/20261112T105827Z-manual-pr6cllqq | user-loss-view-1.png、user-loss-view-2.png | 2026-11-12 本地真实任务的 Loss 页面，搭配原任务记录引用 |
| 同上 | user-runtime-log.png | 同轮真实日志页面，说明已测显示行为 |
| data/acceptance/b-review/laptop-3060/20261112T131702Z-manual-po1lbqv7 | user-live-step56.png | 200 步任务活训练期间截图，不能据一帧推断完整时间线 |
| 同上 | user-narrow-screen.png | 390px 设备模拟，不能称为实机手机测试 |
| data/acceptance/b-review/laptop-3060/20261114T074641Z-m5-wklgq0uf | user-first-compare.png | 既有基础模型与 Adapter 对比页面 |
| 同上 | user-gpu-busy.png | 既有 GPU_BUSY 反馈，不能作为 504 超时证据 |
| 同上 | user-final-task-compare.png | 既有切任务后的推理对比结果 |

## 仍需录制的片段

按 [演示脚本](demo-script.md) 在冻结版本补齐慢速口播与完整课程成片，优先复用 39.520 秒完整四服务容器主录像；40 秒首轮录像保留其混合部署身份。账号数据归属、迁移、90 秒服务端超时清理及 120 秒浏览器超时的专门录像须以本轮实际通过结果为依据，未通过或未执行时在成片中保留范围说明。两份主录像均不覆盖这些独立故障场景。

建议工作目录为 `E:\LLMCloud\data\course-video\<录制日期与唯一编号>\`，分为 raw、edits、exports 与 evidence。录制工具、字幕工程和成片允许按用户现有软件选择，不要求安装新服务或上传媒体。素材路径中不得放入会话 Cookie、口令、匿名身份映射或评分原表。

## 交付核验

成片应为 5–8 分钟 MP4，包含可读字幕和原始录制来源。播放检查整段音画、文本遮挡和隐私信息，确认任务身份连续。记录文件大小、时长、编解码格式、SHA-256 与实际播放结果后再写视频已完成；脚本与截图准备完毕不等于视频已录制或导出。

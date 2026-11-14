# RTX 3060 网页推理会话（M5，B 独立入口）

日期：2026-11-14。入口 [laptop-3060-inference.py](laptop-3060-inference.py) 调用现有生产 API/Worker/前端和 M4 服务生命周期，不替换推理实现，不添加测试 HTTP 控制。先用 `--check`，需要时 `--smoke-services`，最后 `--start`。运行 checkout 必须 clean；不安装依赖、不下载模型。

## 存储与隔离

- 指定一份已有 M4 本地会话 data 目录作为源。源内必须只有终态训练任务且无未结束推理；使用原 CPU 产物审计，至少有一个固定 revision 的已完成 Adapter。
- 以只读 SQLite 连接备份到 E 盘新的 UUID 会话目录；复制源 datasets/outputs，每个文件比对 SHA256，复制前后确认源 DB/manifest 哈希不变。不复制模型缓存、Redis、旧临时下载或旧运行日志。
- 历史任务保留原 ID、训练代码提交与参数，不假装是本次训练，不新增伪造完成状态。新建空 inference_jobs 表由现有应用启动逻辑完成，不手工改原 DB。
- 使用现有共享 Worker 锁、新 Redis Unix socket、新队列和随机 localhost 端口；不启动多个 GPU Worker。
- 新模型生成、DB、Adapter 临时快照和完整浏览器证据在 E；D 只存 ready/report、启动器副本和不超过 1 MiB 的小型日志。

## 启动

在本机 Ubuntu 中使用以下源目录（其他机器替换为自己已审计的本地数据），报告路径应为 D 盘项目：

```bash
cd ~/LLMCloud
export LLMCLOUD_TEST_REPO="$HOME/LLMCloud"
export LLMCLOUD_REPORT_REPO="/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud"
source_data="$HOME/LLMCloud/data/acceptance/m4-07/5421dcac-74c0-4af9-b5a4-d555384a5381/data"
.venv/bin/python docs/testing/laptop-3060-inference.py --check --source-data "$source_data"
.venv/bin/python docs/testing/laptop-3060-inference.py --start --source-data "$source_data"
```

也可由助手在本机运行并保留 exec session。服务运行期间保留终端/进程；使用本轮输出的 browser_url，不复用旧测试地址。ready 中的 real_generation=false 只表示启动时尚未提交生成，不表示使用 mock。

本轮可选真实历史任务：8e5c706b-332e-4922-97bb-54e8d0cf2e68、8da5af9b-56ab-4bb3-afd7-fc8d1d56489c，均为原 200 步工程样例，训练代码 9b1165e。模型和 tokenizer revision 固定 7ae557604adf67be50417f59c2c2f167def9a775。两任务均来源清楚且已独立审计，不作为正式效果提升证据。

## 分步人工检查

1. 打开 ready.browser_url，确认 API 在线，两个已完成任务可选。浏览器 DevTools Network 勾选 Preserve log，不启用限速。
2. 选择第一任务、基础模型与 Adapter 对照、每份最大输出 64 token，使用开发提示词“请给出一个整理书桌的小建议。”生成一次。回传两份回答是否出现、是否报错、任务 ID 和截图。先不提交训练、不重复点击。
3. 导出带响应内容的 HAR 到 E 盘新文件；助手核对该 POST 的真实 task_id/mode/base/adapter/token 数、HTTP 状态、请求 ID 和时序。正常相同回答也可接受，不要求输出变化。
4. 再单独检查 adapter 模式，以及切换任务、切模式、取消和离开页面后迟到结果不会覆盖。取消浏览器等待不等于 GPU 已释放；完成后的手动重试需要独立成功证据。
5. 在助手确认时序后，通过正式训练页面提交一个新 200 步小数据任务，再对历史已完成 Adapter 发推理，检查 GPU_BUSY；训练结束后手动重试成功。无须修改公开契约或后台造状态。ARTIFACT_NOT_READY 用受控 API 对未完成任务单独核对，因为生产下拉只列完成任务。
6. 完成后停止使用页面，在另一个 Ubuntu 终端执行本轮 ready.stop_command。入口会等待训练终态及推理实际清理，再关闭拥有的 Worker/API/前端/Redis。结束时 report 保持 pending_review，助手另行审核用户证据，不自动声称人工或联合验收通过。

会话最长 2 小时。意外退出保留 failed/interrupted 状态及全部运行目录供诊断，不删除原始证据、不自动重投任务。不使用 Ctrl+C 作为正常结束方式。

## 入口本身的验证

测试修复基线 280532a（test_task_contract.py 20 项及全量 CPU 411 通过/1 可选跳过、五项契约全通过；具体回归在前一未提交修复树运行并保留原证据）。新入口 AST 检查及 --check 通过。--smoke-services 运行了新 DB/文件副本、真实 API/Redis/Vite、OpenAPI/422/404 与两份历史产物核对，未启动 Worker、未加载 GPU、未真实生成。

服务冒烟 runtime=/home/l7/LLMCloud/data/acceptance/m5-inference/0ff5d1b7-7206-49e2-bb5a-4af2fb4e1a09；D 盘证据=data/acceptance/b-review/laptop-3060/20261114T074302Z-m5-vqaa0ehy。status=isolated_services_smoke_passed，source_unchanged=true，cleanup_errors=[]。这不是 GPU 网页验收，正式会话使用新的运行目录和 URL。

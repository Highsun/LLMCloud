# M5 稳定性、账户与演示交付（2026-11-15）

本轮用户要求继续队友任务，并授权登录、注册、用户数据持久化与迁移一起完成。M3/M4追加异步复核改为开发完成后统一处理，不代替队友填写复核结论。当前分支为 `feature/m4-observability-ui`，实施起点 `3e2e5c3`；运行时为该提交加本轮工作区改动，不能将实际测试基线写成提交后 clean。

## 推理故障验收

[原运行结果摘要](m5-fault-results-2026-11-15.json)来自真实 FastAPI/TCP、SQLite、私有 Redis 与单 solo GPU Worker。GPU 为 RTX 3060 Laptop 6GB，模型与 tokenizer 固定 revision `7ae557604adf67be50417f59c2c2f167def9a775`。运行 `auth=false` 以隔离推理故障；账户隔离另有真实 API/浏览器回归，不混称本轮故障运行启用了账户。

复用历史工程 Adapter `8e5c706b-332e-4922-97bb-54e8d0cf2e68`，原训练提交仍为 `9b1165e`；只读备份源数据库、复制并审计数据与 Adapter 到 E 盘 WSL ext4 新目录，没有复制基础模型。原资产哈希在结束时重核一致。未重跑 E01 或改写其回答、评分、原清单。

| 场景 | 实际结果 |
| --- | --- |
| 服务端90秒 | 确认真实首个CUDA token后注入一次95秒暂停；生产90秒预算不变，90.063153秒返回504/INFERENCE_TIMEOUT |
| 超时后清理与复用 | 清理未完成时下一请求409/GPU_BUSY；运行预留实际释放后compare成功，12.701296秒 |
| Worker异常退出 | 同样确认首CUDA token后仅SIGKILL本轮Worker；后继取得公共锁并恢复孤儿请求，原API返回500/INFERENCE_FAILED；新compare成功 |
| 模型缓存缺失 | Worker指向本轮独立空缓存，返回503/MODEL_NOT_CACHED；没有删除/更改真实缓存，恢复配置后compare成功 |
| 派发确认丢失、未领取 | 真Redis已收到消息，测试Publisher显式返回UNKNOWN；API原子终止待领取请求并返回503；随后真实迟到消息不执行模型，新请求成功 |
| 派发确认丢失、已领取及重复消息 | 真Redis发送后等SQLite确认已领取，再返回UNKNOWN并发一个同ID重复消息；原请求成功，无自动重投新ID；重复消息按终态退出 |
| 故障后的健康请求 | 最后一次独立compare成功，11.654691秒；唯一Worker/API/私有Redis正常结束，公共实例锁可重新取得 |

这是可复现的受控故障注入，**不是自然生成恰好耗时90秒的性能测试**。首token、真实GPU、HTTP预算、清理占用与下一次生成均有独立事实；暂停仅在 `scripts/m5_fault_worker.py`，生产Worker不导入该文件，不改变输出上限或推理默认值。原始数据和日志留 `/home/l7/LLMCloud/data/acceptance/m5-faults/run-03/`（E盘承载的WSL磁盘）。

前两次准备失败保留在E盘：run-01为Unix socket路径超长，run-02为Windows挂载盘不满足已有Linux产物安全要求。修正为短socket路径与WSL ext4工作区后run-03完整通过，没有削弱生产文件校验或将失败报告改写为成功。

## 独立CPU与前端范围

`tests/test_inference.py` 的19项独立回归覆盖真实SQLite预留/领取竞争、训练优先、迟到/重复领取、取消占用直到清理、超时不提前释放、遗留请求恢复、保留期清理、畸形请求、确认丢失及错误状态。GPU与产物在该CPU套件内明确使用替身，不充作真实生成。

本轮最终全量CPU回归448项，447通过、1原可选浏览器跳过（58.663秒）；包括账户12项、推理19项、镜像来源校验5项。前端135项与生产构建通过，新增credentials断言后的推理19项专项也通过。五份正式契约检查全部通过。[最终摘要](m5-regression-results-2026-11-15.json)保留原日志哈希。早期441项是实施中快照，不将交叠专项另加成一个虚构总数。

推理浏览器回归10项全部通过，使用真实Edge浏览器，接口由明确的fixture拦截；覆盖两模式、两类409、取消/切任务/切模式、离开缓存页面、390px布局。真实120秒计时实测120488毫秒显示客户端超时，输入保留、没有自动重发，用户手动重试后成功。详见[浏览器摘要](m5-browser-results-2026-11-15.json)。与生产GPU端到端录像分开保存，不把fixture回答作为模型生成。

## 复现命令

Linux/WSL先使用已锁定依赖环境。所有TMPDIR/运行输出必须位于E盘承载的Linux文件系统或目标云机，不能用D盘运行产物，也不为兼容DrvFS放宽安全规则。

```bash
python -m unittest discover -s tests -p test_inference.py -v
python scripts/check_m5_faults.py --real-gpu \
  --source /absolute/path/to/terminal-real-task-data \
  --cache-dir /absolute/path/to/huggingface/hub \
  --output /absolute/new/run-directory
```

`--source`必须全为终态任务并有可审计Adapter；`--output`必须不存在。工具只操作新目录与其私有服务，模型缓存只读复用。当前源任务是工程样例，不作为正式效果实验。

```bash
cd frontend
npm run build
PLAYWRIGHT_CHANNEL=msedge npx playwright test --config playwright.inference.config.mjs
```

Windows PowerShell按 `$env:PLAYWRIGHT_CHANNEL='msedge'` 设置。`LLMCLOUD_INFERENCE_TEST_OUTPUT`指定E盘证据目录。使用生产preview，避免并行开发热重载重置120秒等待；首轮热重载干扰的失败记录保留，不误诊为GPU预算问题。

真实演示录像入口为 `scripts/check_demo_browser.mjs --url http://127.0.0.1:8080 --output <E盘新目录>`。它要求已启用账户的真实受限服务和可用Worker；创建随机临时账户，密码只存在进程内存、不记日志或报告。真实上传、提交训练、读指标/日志、下载和compare；视频、截图、ZIP和回答均留E盘。该入口本身不代表已执行，实际执行结果另记。

本轮已实际执行该入口：初轮采用容器CPU服务+同机原生GPU Worker；修复Git-free镜像来源采集后，最终[完整四服务容器复测](m5-container-demo-results-2026-11-15.json)通过，新账号、实际2步、Loss/日志、独立审计ZIP和compare均有真实结果与录像。完整GPU容器结果不再依赖初轮的原生Worker结论；云上目标环境仍待实测。

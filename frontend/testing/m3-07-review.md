# M3-07 B 侧独立复核

2026-11-04：已同步 main=c088a2d，用户提供的 ZIP/.sha256 与本次 A 纳入 Git 的两个固定证据文件一致。B 已完成异步真实材料/截图复核和 CPU 真实快照页面复查，修复手机失败码窄列换行问题；结果见 [B 独立日志](../../docs/worklogs/2026-11-04-m3-07-b.md)。A 的真实 GPU 验收来源见 [交接](../../docs/m3-acceptance.md) 和 [工作日志](../../docs/worklogs/2026-11-04-m3-07-a.md)。阶段共同收口由双方核对，不把既有页面复查记作新 GPU 运行。

## 只读复核命令

从仓库根目录运行，服务/CPU 依赖沿用 uv.lock，无需 training extra、模型缓存或 GPU：

```bash
uv run --locked python frontend/testing/review_m3_evidence.py \
  data/acceptance/imported/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review

# 同时收到四份完整成功 bundle 时，复用原共享 CPU 审计器
uv run --locked python frontend/testing/review_m3_evidence.py \
  <收到完整原始成功bundle的运行目录> --audit-artifacts

uv run --locked python -m unittest discover -s frontend/testing -p test_m3_evidence.py -v
```

本机 Windows 使用已有 CPU 环境时，将 `uv run --locked python` 换成 `.venv-worker-tests/Scripts/python.exe`，无需调整原项目依赖。该脚本仅输出 JSON，不写回 report，不启动 API/Redis/Worker/GPU，不执行对账或训练。退出 0 表示材料结构与交叉记录一致，退出 2 表示文件缺失，退出 1 表示材料无法通过检查。

检查覆盖：正式 TaskDetail/版本/revision；九个不同任务、四成功/五预期失败；实际 UTC 训练区间不重叠、第二项提前提交；同键/重复消息结论；完成前回滚恢复同一任务和参数；中断进度/排队未执行；原页面请求正文与快照、RUNNING 观测；五组补字体浏览器结果、截图宽度和 trace 无测试控制路径。可选完整产物审计核对实际清单摘要及配置，不复制 Trainer/SQL/审计算法。

输出始终保留 `milestone_complete=false`、`gpu_rerun=false` 和 `visual_review=still_required`。截图检查仅验证 PNG 头/宽度，不判断文字、遮挡或交互；trace 标志与报告声明不能独立证明真实 GPU 执行。默认模式下报告中的产物审计属于 A 的记录；只有 `--audit-artifacts` 成功才记 B 独立 CPU 产物审计通过。

## 需由 A 提供的最小材料

`m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip`（6,672,377 字节）及 .sha256 已收到；A 又按用户授权在 c088a2d 将 data/acceptance/handoffs 中这两个固定文件纳入 Git，其余运行目录仍忽略。可信 ZIP SHA-256 为 `dba657710cbc2f0d92207c6ce8cb2593efe0474815146bd5d51b2de0e6bae62a`。Windows 可先用 `Get-FileHash -Algorithm SHA256 <收到的ZIP路径>` 比对，再按交接校验包内 SHA256SUMS。本轮 ZIP/62 项文件校验均通过。包不含 Adapter/tokenizer 权重，不能对本包使用 --audit-artifacts 宣称完整权重审计通过。

保留原目录结构放在 Git 忽略的 data/acceptance 下，不提交数据库、数据、权重、截图或 trace：

- report.json 和 browser-success/result.json。
- browser-success-cjk、browser-recovered-cjk、browser-saving-failed-cjk、browser-interrupted-cjk、browser-invalid-dataset-cjk 五个目录，各含 result.json、desktop.png、mobile.png、trace.zip。
- 如需 B 独立复审产物：四份原始 data/outputs/{task_id} 完整成功 bundle；不需要额外拷贝基础模型或训练数据。完整成功任务 ID 由 report.json 读取。
- 如需实际页面操作：可访问的原验收服务地址，或由 A 按原交接的 `--review-run` 重开既有实际隔离库；不要用测试替身生成同 ID 的任务替代。

包内有实际 SQLite 快照，可按下一节在 Windows/Linux 重开生产页面读取既有记录，无需安装训练栈、Redis 或下载模型。新上传至 GPU 完成的同步人工联调另记，不由本页面复查替代。

## 本机真实快照页面复查

在新工作目录复制数据库，使用原 create_app/仓储/公开响应；没有模拟状态、Publisher 或测试控制接口。仅复查进程增加只读请求保护，防止意外 POST；原证据目录不修改。

```bash
# 终端 1，仓库根目录；工作目录必须不存在且位于 data/acceptance 下
uv run --locked python frontend/testing/serve_m3_review.py \
  --source-run <解压目录> --work-dir data/acceptance/b-review/<新目录> --port 18007

# 终端 2，frontend 目录（Linux/WSL）
VITE_BACKEND_URL=http://127.0.0.1:18007 npm run dev -- --port 15107

# 终端 3，仓库根目录；使用已安装的 Playwright Chromium
node frontend/testing/review_m3_browser.mjs --url http://127.0.0.1:15107 \
  --run <解压目录> --output data/acceptance/b-review/<新目录>/browser
```

Windows 使用现有 CPU Python 时按上文替换 uv 命令；Vite 可在 PowerShell 设置 `$env:VITE_BACKEND_URL='http://127.0.0.1:18007'` 后运行 `npm.cmd run dev -- --port 15107`。已有 Chrome 时给浏览器命令加 `--channel chrome`。

脚本核对六种状态筛选、九项原记录/配置/错误、刷新、终态轮询及桌面/390px；在手机上实际切换侧栏、横向滚动表格并点击详情；保存 18 张截图、trace 和 result.json。它不创建训练任务。结果须另做视觉检查，脚本不能代替个人签字或双方阶段确认。完成后 Ctrl+C 停止自己启动的 Vite/API，保留新结果和原证据；再次运行使用新输出目录，禁止覆盖。

## 人工与视觉检查记录

收到材料后逐项记录实际 task_id、截图位置、操作和结果，再更新 B 独立日志：

1. 真实上传与配置、连续两任务，确认原任务 ID/参数快照，与原提交响应和实际 UTC 起止一致。
2. 原任务查询、刷新、ALL/五状态全量筛选及分页，确认刷新不重复 POST、终态详情停止自动查询。
3. 正常完成/恢复完成、保存失败、中断、非法数据的详情，核对失败码、实际步数/空进度，100% RUNNING 不误报完成。
4. 桌面与 390px：中文可读、任务编号不遮挡、侧栏关闭后内容可操作、表格可横向滚动且页面无溢出。
5. Loss/日志/下载和推理未发布时仍禁用。界面问题只在 frontend 修复，并附真实复现证据及必要回归；共同阶段状态由 A 按独立日志汇总。

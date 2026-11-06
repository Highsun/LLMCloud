# Windows 中转、macOS 导入与 Ubuntu 云端完整恢复

更新：2026-11-06。用户确认云服务器暂未准备，先保存 Windows“下载”，之后自行传到 Mac。本文会同时以 `RESTORE.md` 放入私有迁移目录，离线也能阅读。**迁移包不是开发仓库；先恢复代码，再在仓库根目录读 continue.md。**

## 1. 现在拿走什么

Windows 实际已知文件夹（经当前用户注册表查询，未猜用户名）：

```text
C:\Users\PC\Downloads\LLMCloud-migration-2026-11-06\
```

整个文件夹一同复制到 Mac，推荐放：

```text
~/Downloads/LLMCloud-migration-2026-11-06/
```

必须保留这 10 个文件：`runtime.tar.gz`、`models.tar.gz`、`manifest.json`、`code.bundle`、`host-inventory.json`、`restore-verification.json`、`handoff.json`、`continue.md`、`RESTORE.md`、`SHA256SUMS`。约 906 MB；包含原 `.env` 私有参考与数据/证据，不提交 Git、不公开分享。两个 tar.gz 保持原样，不在 Windows 解压/重压，避免模型链接丢失。

Windows 副本已经位于 WSL 之外，删除原项目/WSL 不会删除这个 NTFS 目录；但它仍与 Windows 主机共存，清空主机/磁盘前必须再复制到 Mac 或独立存储。原 WSL 仓库外还保留一份同内容备份。当前未上传云端。

## 2. Windows 或 Mac 收到后先验包

Windows PowerShell，在该文件夹中执行（不启动训练或服务）：

```powershell
Set-Location -LiteralPath 'C:\Users\PC\Downloads\LLMCloud-migration-2026-11-06'
Get-Content -LiteralPath '.\SHA256SUMS' | ForEach-Object {
    $expected, $name = $_ -split '  ', 2
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path (Get-Location) $name)).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Checksum mismatch: $name" }
    Write-Output "OK $name"
}
```

Mac 终端（路径不同则只改第一行）：

```bash
cd "$HOME/Downloads/LLMCloud-migration-2026-11-06"
shasum -a 256 -c SHA256SUMS
```

清单不包含自身，其他每项都应输出 OK；缺文件/摘要不同就停下，从尚完好的副本重新复制，不能改 SHA256SUMS 掩盖问题。两个数据归档还可与根 continue.md 中固定摘要交叉核对。

## 3. 在 Mac 恢复代码并交给新 Codex

正常联网方式：

```bash
mkdir -p "$HOME/code"
cd "$HOME/code"
git clone https://github.com/Highsun/LLMCloud.git
cd LLMCloud
git status --short --branch
```

如果仓库已存在，先检查其修改和远端，不重复 clone 或覆盖。需要 GitHub 认证时使用 Mac 自己的身份，不搬旧 SSH agent/私钥或 `.git/config`。

GitHub 不可达时，先在临时空仓库上下文验证离线包，再 clone。下面目录必须不存在；若已存在换新名字，别删旧开发目录：

```bash
BUNDLE="$HOME/Downloads/LLMCloud-migration-2026-11-06"
VERIFY_REPO="$(mktemp -d)"
git -C "$VERIFY_REPO" init --quiet
git -C "$VERIFY_REPO" bundle verify "$BUNDLE/code.bundle"
mkdir -p "$HOME/code"
git clone -b main "$BUNDLE/code.bundle" "$HOME/code/LLMCloud-offline"
cd "$HOME/code/LLMCloud-offline"
git remote set-url origin https://github.com/Highsun/LLMCloud.git
git status --short --branch
```

核对 `git rev-parse HEAD` 与包内 `handoff.json` 的 code_commit；联网 clone 可能已有更新，以审查后的新 main 为准。离线包只兜底到本次导出时刻，不会自动包含队友后续提交。

把下段直接交给 Mac 上的新 Codex：

> 请完整阅读仓库根 continue.md、AGENTS.md 和 docs/migration-restore.md，按其中接续 LLMCloud。私有包在 ~/Downloads/LLMCloud-migration-2026-11-06（如我另放位置，以实际路径为准），云服务器还未准备。先校验包、核对 Git 并建立 macOS CPU 开发环境；只静态检查和小范围测试，不在 Mac 运行训练/全栈，不恢复 GitHub Actions。等我提供云服务器资料，再指导我执行 Ubuntu/CUDA 部署检查，我返回日志后你再改代码。

Mac 只需要按 continue.md 安装 Python 3.12/uv 的基础依赖和 Node 开发依赖。**不加 training extra，不展开模型来运行，不启动 Redis/Docker/GPU/端到端服务。** 包可原样暂存；代码正常编辑提交。

## 4. 云机准备好后，把私有包传过去

先向接续 Codex 提供：Ubuntu/CPU 架构、GPU 型号/显存/驱动、持久盘/挂载点、SSH alias 或地址/用户名/端口、代码与数据目录、访问方式。不要发送密码/私钥。尚无这些信息时不购买机器、不执行本节、不把占位路径当真实地址。

下面仅是 Mac → 已确认云机的模板，`cloud-alias` 必须替换为用户配置的真实 SSH 目标。接收位置应位于已确认持久盘；示例 home 目录只有在云平台保证持久时才使用：

```bash
ssh cloud-alias 'mkdir -p "$HOME/private-migrations" && chmod 700 "$HOME/private-migrations"'
scp -r "$HOME/Downloads/LLMCloud-migration-2026-11-06" cloud-alias:~/private-migrations/
```

已在 SSH config 配端口则命令不变；否则 ssh 用 `-p`、scp 用大写 `-P`，由接续助手按实际连接参数生成。不要公开 Redis/API 或把包上传 GitHub。云端接收后进入该文件夹执行 `sha256sum -c SHA256SUMS`，全部 OK 才继续。

## 5. Ubuntu 只恢复到全新的暂存目录

以下为 **Ubuntu 云端命令**，不是 Mac 命令。先 clone 最新代码/离线代码，进入仓库；准备 Python 3.12，不需要先下载 torch 才能校验/解压。设置真实的绝对路径：

```bash
# 示例须改成该云机实际的持久接收位置。
BUNDLE="$HOME/private-migrations/LLMCloud-migration-2026-11-06"
STAGED="$HOME/llmcloud-restored-2026-11-06"
python3 scripts/migration_bundle.py verify --bundle "$BUNDLE"
python3 scripts/migration_bundle.py restore --bundle "$BUNDLE" --target "$STAGED"
```

verify 应显示 migration_verified、580 entries、7 databases。`remote_transfer=not_assessed` 表示脚本只验证字节，不判断网络传输；不表示当前云端没有接收到文件。restore 拒绝已存在目录；再次操作时仅 verify 或使用新的暂存目录，不能为了重跑而删库。

恢复布局：

```text
<STAGED>/
├── data/
│   ├── llmcloud.db              # 原业务空库，已有所需 schema
│   ├── models/huggingface/      # 完整固定模型缓存和内部链接
│   ├── outputs/                # 原 6 成功/4 失败目录
│   ├── prepared/               # 工程格式草稿及来源/划分记录
│   ├── experiments/            # M2-06 等证据
│   ├── acceptance/             # M3/M4 等历史证据/隔离 DB
│   ├── backups/                # 迁移前旧数据库备份
│   └── redis/                  # 仅取证，不能接入新 broker
├── logs/                       # 历史日志，不含旧 worker.lock
└── private-config/             # 原 WSL .env / frontend.env / Redis unit，仅参考
```

## 6. 将运行数据放入已确认的云端持久目录

先停止目标端 API/Worker；只对**全新的目标数据目录**执行。路径由用户确认，例如：

```bash
DATA_DIR="/ACTUAL/PERSISTENT/PATH/LLMCloud/data"
LOG_DIR="/ACTUAL/PERSISTENT/PATH/LLMCloud/logs"
test ! -e "$DATA_DIR/llmcloud.db" || { printf 'Target database already exists; stop and inspect.\n' >&2; exit 1; }
mkdir -p "$DATA_DIR" "$LOG_DIR"
rsync -a --exclude '/redis/' "$STAGED/data/" "$DATA_DIR/"
rsync -a --exclude '/worker.lock' "$STAGED/logs/" "$LOG_DIR/"
```

没有 rsync 时先由用户安装或使用保留符号链接的等效复制，不用会跟随/展开所有链接的复制。**不要把原 Redis AOF/RDB 回放为新任务队列，不合并历史验收库到根业务库，不补造训练任务。** 根业务库本来 users/datasets/tasks 都为 0；历史验收 9 任务（4 完成/5 失败）在自己的隔离库里，这是正确恢复结果。

`.env` 从当前 `.env.example` 创建，前端从 `frontend/.env.example` 创建；已有文件先检查，不能覆盖秘密配置。编辑以下实际路径，其他字段保留当前契约：

```dotenv
DATA_DIR=/ACTUAL/PERSISTENT/PATH/LLMCloud/data
LOG_DIR=/ACTUAL/PERSISTENT/PATH/LLMCloud/logs
DATABASE_URL=
HF_HOME=/ACTUAL/PERSISTENT/PATH/LLMCloud/data/models/huggingface
HF_HUB_CACHE=/ACTUAL/PERSISTENT/PATH/LLMCloud/data/models/huggingface/hub
DEFAULT_MODEL_REVISION=7ae557604adf67be50417f59c2c2f167def9a775
```

DATABASE_URL 留空会自动使用 DATA_DIR 下的 SQLite，避免抄错旧绝对 URL。Redis 用云端新的受控服务；重建队列/CORS/前端代理。不能直接启用 private-config 内原 `.env`/systemd unit，不带入 WSL 的 home、172.24.224.1 代理、旧端口/socket/SSH agent。云机新建自己的 worker.lock，不删除/覆盖任何活锁。

## 7. Ubuntu 依赖与恢复结果核对

从代码仓库根目录运行；训练依赖只装在云机：

```bash
uv sync --locked --extra training
uv run --locked --extra training python scripts/prepare_model.py check \
  --hf-home "$DATA_DIR/models/huggingface" \
  --cache-dir "$DATA_DIR/models/huggingface/hub" \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775
```

应为 cache_verified、9 required files、999602607 字节，revision 固定。此步骤不加载 GPU；HF_HOME 与 Hub cache 两层不能混传。模型包没取到时才明确联网 `prepare --revision <同一revision>` 重建，不能静默用 main。

只读检查数据库（不自动 apply，不删除）：

```bash
DATA_DIR="$DATA_DIR" DATABASE_URL= uv run --locked --extra training python scripts/migrate_datasets.py --check
DATA_DIR="$DATA_DIR" DATABASE_URL= uv run --locked --extra training python scripts/migrate_tasks.py --check
```

注意 datasets 迁移脚本没有 --data-dir 参数，所以用进程环境指定；若报告需迁移，交给 Codex核对后，停写、保留备份，再显式 apply。不要针对 data/backups 中故意保留的旧库做批量迁移。

核对全部 7 份已还原数据库与 10 份原成功产物（仍只读/CPU，使用包内清单定位）：

```bash
STAGED="$STAGED" BUNDLE="$BUNDLE" uv run --locked --extra training python - <<'PY'
import json, os, sqlite3
from pathlib import Path
from trainer.artifacts import verify_training_artifacts
root = Path(os.environ['STAGED'])
manifest = json.loads((Path(os.environ['BUNDLE']) / 'manifest.json').read_text())
for relative in manifest['databases']:
    path = root / relative
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    print('DB OK', relative)
count = 0
for parent in [root / 'data/outputs', root / 'data/acceptance/m3-07/dbdffce3-e453-46bf-b962-d66a424d7199/data/outputs']:
    for output in sorted(parent.iterdir()):
        if output.is_dir() and (output / 'manifest.json').exists():
            print(verify_training_artifacts(output).summary())
            count += 1
assert count == 10, count
print('RESTORE AUDIT OK: 7 databases, 10 successful artifact bundles')
PY
```

4 个原失败目录不能被当成功目录审计，也不能删除后宣称全成功。原 summary 的 reload_verified=false 仅表示本次是 CPU 审计，不推翻 M2 历史单独进程重载记录。历史日志/地址保持原样，不能拿旧 localhost URL 当云端服务。

最后，由接续 Codex 根据新云机实际驱动/GPU/网络指导用户检查 CUDA、Node/npm、重建 Redis、前端构建、进程守护和受控访问，再组织 CPU/HTTP/真实 GPU/人工验收。现有 compose 仅 Redis，完整生产部署和推理仍未完成；这些恢复命令本身不启动训练，也不把 M3/M4/M5 标为完成。

## 8. 什么情况下才可删除旧副本

Windows 下载副本和 Mac 接收副本至少有一份已实际校验，代码可 clone，continue.md/RESTORE.md/清单均在；云机就绪后再复制并做以上恢复检查。云端校验前建议保留 Mac 原始包。收到错误时返回：code_commit、实际命令/目录/退出码、未打码的必要报错（密码/令牌打码）、包摘要结果；不要用重新打包、重训或清空库掩盖错误。

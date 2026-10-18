# 运行与配置指南

[返回项目首页](../README.md)

## 环境与配置

推荐 Docker Compose 运行应用与 Qdrant。原生开发需要 Python 3.12+、Node.js 22 和 npm。命令示例为 PowerShell，均从项目根目录开始，不依赖开发者电脑盘符。

### 网页配置（推荐）

Windows 用户先[下载并安装 Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)，打开并等待 Linux 引擎就绪；要求 Compose 2.24+。快捷启动不安装软件、不改 Docker context。非 Windows 用户仍可使用标准 Compose 命令。

首次在根目录执行 `& '.\Evidence Studio.cmd' -Build`；以后双击 `Evidence Studio.cmd`。更新代码后显式重新构建。常用选项：

```powershell
& '.\Evidence Studio.cmd' -NoBrowser
# 非标准安装位置：换成你电脑上 docker.exe 的实际路径
& '.\Evidence Studio.cmd' -DockerPath 'D:\Apps\Docker\resources\bin\docker.exe'
```

引擎未就绪时脚本会退出并提示打开 Docker Desktop；不会自动切换 context 或使用远程引擎。日常启动不构建或拉取，首次缺镜像会提示 `-Build`。路径不可访问时可将仓库放在有读写权限的目录。

优先使用 `docker compose` 插件；未注册插件时检查所选 `docker.exe` 同目录的 `docker-compose.exe`，同样要求 2.24+。非标准安装还需保证你自己的 Docker context / DOCKER_HOST 已能连接本机引擎；启动器不会覆盖这些配置。

启动后在“设置 → 生成模型 · 自备 API”填写自己的配置。DeepSeek 示例为 `https://api.deepseek.com`、`deepseek-flash`，密钥从[自己的开放平台账户](https://platform.deepseek.com/api_keys)获取。[官方模型名和接口说明](https://api-docs.deepseek.com/)可能变化，请以服务商文档为准。

保存只校验、落盘，不产生模型请求；下一次请求使用新配置，正在进行的请求保留原快照。“测试连接”会发送固定简短文本，可能计费，且不会自动保存或重试。问答会发送问题及选中资料片段。API 额度与网页订阅、其他 Coding Plan 并非同一概念。

网页配置在 `runtime-config/model.json`，Compose 以目录挂载持久化。文件存在时优先使用它；没有文件时回退环境配置。损坏文件会报错，不会静默换成另一账户。留空密钥可沿用已配置密钥，但更换地址必须重填。保存成功清空密码框，不回显密钥或写浏览器存储。

这是本机明文文件，权限保护不等于加密；电脑管理员可能读取。不要分享 `runtime-config/`、`.env`、运行备份或包含密钥的截图。项目仅面向单用户本机，不要直接暴露到公网。

### 环境配置（兼容旧用法，可选）

新安装无需先创建 `.env`。需要环境配置时，只复制缺失文件，不覆盖已有内容：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地 `.env` 填写：

- `EVIDENCE_RAG_LLM_BASE_URL`：OpenAI-compatible API 的基础地址，应用会追加 `/chat/completions`，不要填写完整补全接口路径。
- `EVIDENCE_RAG_LLM_MODEL`：服务商实际提供且账号有权调用的模型名；样例值不保证适用于你的账号。
- `EVIDENCE_RAG_LLM_API_KEY`：后端读取的密钥，不放入截图、源码或 Git。
- `EVIDENCE_RAG_MODEL_CONFIG_PATH`：网页配置文件路径，原生默认 `runtime-config/model.json`；Compose 显式设置为 `/app/runtime-config/model.json`。

配置完整不代表服务商连接成功。实际生成会发送问题和选中片段，可能产生费用；健康接口不校验完整模型能力。

其他常用配置：

- 单文件默认上限 20 MiB，单知识库默认 100 MiB，可通过 `.env.example` 中的容量项调整。
- 本地 Embedding 为 multilingual-e5-small、384 维，默认 CPU、批量大小 16。首次索引从 ModelScope 下载，原生模式保存到 `models/`。
- `EVIDENCE_RAG_RETRIEVAL_MIN_VECTOR_SCORE` 默认 0.55，控制纯向量候选可独立作为证据的最低余弦相似度；不是概率或经过校准的答案置信度。BM25 词项命中仍可参与候选融合。
- 生成模型、向量模型、路径等完整变量以 [配置模板](../.env.example) 为准。更换 Embedding 模型或维度后，应重建对应知识库索引，不能混用向量空间。

## Docker Compose

确保 Docker 引擎已启动，在项目根目录执行：

```powershell
docker compose up -d --build
docker compose ps
```

浏览器访问 <http://127.0.0.1:8000>，健康检查为 <http://127.0.0.1:8000/api/health>。应用默认只绑定本机；Qdrant 由应用通过 Compose 内部服务名访问，不需要从浏览器连接。

基础镜像使用 DaoCloud Docker Hub 加速地址，CPU-only PyTorch 使用官方 wheel 源。首次构建和下载模型需要网络；来源不可访问时检查网络与源配置，不随意使用未知镜像。

### 数据与维护

- `app_data`：SQLite 业务数据和上传副本。
- `qdrant_storage`：向量与来源元数据。
- `model_cache`：Embedding 模型缓存。
- `./runtime-config/`：宿主机目录挂载，保存网页模型配置；并非命名数据卷，备份需要单独保护且包含明文密钥。

```powershell
# 停止和恢复已有容器，不清空命名卷
docker compose stop
docker compose start

# 查看状态与最近日志
docker compose ps
docker compose logs --tail 100 api
```

重建容器不等于删除卷。`docker compose down` 删除容器和网络但保留命名卷，追加 `-v` 会删除命名卷数据，不能当作普通重启命令。备份或清理前先确认业务库、上传资料和向量对应关系；日志、数据库与备份可能包含隐私。

仓库包含通用 CMD/PowerShell 入口，个人 `.lnk`、图标与视频不随仓库发布，不是运行依赖。不要改目录名后误以为旧命名卷被清空：Compose 项目名会影响命名卷选择，迁移前先确认名称与备份。

## 原生开发

后端（终端一）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\uvicorn.exe evidence_rag.app:app --reload
```

前端（终端二，从项目根目录开始）：

```powershell
Set-Location frontend
npm ci --registry=https://registry.npmmirror.com
npm run dev
```

以上使用清华 PyPI 镜像与 npmmirror。前端 `/api` 请求由 Vite 转发到 `http://127.0.0.1:8000`；设置接口允许本机 Vite 的 5173 来源，使用默认端口并打开终端显示的本机地址。原生后端默认使用嵌入式 Qdrant，Compose 模式使用独立 Qdrant 服务，两种模式的实际存储位置不同。

若容器已经占用 8000，不要再直接启动同端口开发服务；选择一种运行方式，或明确修改端口及代理配置，避免把请求发到错误实例。

## 常见问题

- **网页无法访问**：先检查 Docker/开发服务是否运行、端口是否被占用；不要仅因有镜像就认为服务已启动。
- **文件显示等待索引**：上传只保存副本并建立任务，需要手动开始索引。批量上传后可点击“全部开始索引”。
- **首次索引慢**：可能正在下载或加载 E5 模型，CPU 索引也需要时间；先看任务状态与错误，不连续重复请求。
- **PDF 索引失败**：确认文字可复制。扫描件没有 OCR 支持，不能只把后缀改成 PDF。
- **模型不可用**：核对 Base URL、模型权限、额度和网络。网页保存后下一次问答生效；修改 `.env` 需要重新加载运行配置，且不会覆盖已存在的网页配置。不要为重试而删除数据卷。
- **回答拒答**：确认当前知识库、索引状态和原文是否真的支持问题。不要把“多给一些候选”当作一定能回答的保证。
- **历史引用仍能展开**：系统保留原文快照用于追溯，删除原文不等于立即抹除所有历史内容。

删除文档仅操作应用保存的副本与对应向量，不修改上传来源文件。与隐私删除相关的操作还需考虑历史快照和备份。

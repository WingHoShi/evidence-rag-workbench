# 通用快捷启动与网页模型配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows 用户自行安装 Docker Desktop 后可快捷启动，在网页安全配置自己的 DeepSeek API。

**Architecture:** 独立文件配置存储提供每请求快照，现有 `.env` 作为回退。配置路由与前端表单独立于知识库流程，通用脚本保留现有 Compose 数据卷和 Docker 上下文。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、httpx、React、TypeScript、Vitest、PowerShell 5.1、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-18-portable-launch-and-model-settings-design.md`

## Global Constraints

- 仅修改项目一，保留已有 README 改版、`.env` 和业务数据卷。
- 不启停当前服务，不调用真实模型；所有自动化网络测试使用模拟响应。
- 不增加依赖；保持现有代码风格，不顺手重构检索等模块。
- 密钥不写浏览器存储、不回显、不进入 Git、Docker 构建上下文或测试输出。
- 保存不产生模型费用；测试连接只能主动发起且不自动保存。
- 不自动提交；完成后展示暂存清单和中文提交信息，用户确认后才提交推送。以下各任务的提交步骤统一延后。
- 使用现有工作目录，不创建分支或工作树。执行方式待用户选择；推荐主代理在当前会话逐项实施。

## Review Focus

1. 换 Base URL 而不输入新密钥：拒绝而不是将旧密钥发送至新地址（任务一、三）。
2. 配置 JSON 损坏或替换失败：不切换账户、不损坏旧文件（任务一）。
3. Pydantic 错误与上游异常：不包含提交的密钥或上游响应正文（任务二）。
4. 开发代理的 Origin 与后端 Host 不同：允许明确的本机开发来源，仍拒绝外部站点（任务二）。
5. Docker 安装在带空格目录且环境有自定义 context：正确调用，不覆写环境，不自动改用远程引擎（任务四）。

## 文件职责

- 新增 `backend/src/evidence_rag/model_config.py`：配置校验、原子保存、优先级与快照。
- 新增 `backend/src/evidence_rag/model_config_routes.py`：状态、保存、主动测试及本机请求边界。
- 修改 `settings.py`、`answering.py`、`app.py`：配置路径与最小接线，保留测试注入能力。
- 新增 `frontend/src/ModelSettings.tsx` 与测试；修改 `App.tsx`、`api.ts`、`styles.css` 接入现有设置页。
- 修改 `Evidence Studio.cmd`、`scripts/start-project.ps1`、`compose.yaml`、`.gitignore`：公开可移植入口、可选环境文件与配置挂载。
- 新增后端配置与路由测试、启动脚本测试；同步容器静态测试及文档。

### Task 1: 配置存储与每请求读取

**Files:** 新增 `model_config.py`、`backend/tests/test_model_config.py`；修改 `settings.py`、`answering.py`。

**Interfaces:** `ModelConfig(base_url: str, model: str, api_key: SecretStr)`；`ModelConfigStore(settings: Settings)` 提供 `resolve() -> ModelConfig`、`status() -> dict`、`save(base_url: str, model: str, api_key: str | None) -> dict`。`Settings.model_config_path` 默认 `Path('runtime-config/model.json')`。模型客户端保留原 Settings 构造参数，允许注入 store。

- [x] 写失败测试：无文件回退原 Settings；保存再读取地址与模型一致；状态 JSON 不含测试密钥；换地址且空密钥报错；同地址空密钥沿用；损坏文件报配置错误；模拟 `os.replace` 失败后旧文件字节不变。
- [x] 运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_model_config.py`，确认因缺实现失败。
- [x] 实现 URL/字段约束、SecretStr、不跟随符号链接覆盖的文件检查、同目录临时文件原子替换与权限限制；文件配置优先于环境配置，缺文件才能回退。用锁防止同进程并发保存竞争，单进程部署不扩展为分布式配置服务。
- [x] 每次 `stream()` 开始调用 store.resolve，固定本次快照；新增 MockTransport 测试：连续两次请求之间保存配置，第二次请求使用新模型和新密钥，进行中的请求保持旧值；上游重定向不携带授权继续请求。
- [x] 重跑新测试和 `test_settings.py`、`test_grounded_qa.py`，预期全部通过；记录待提交文件，不提交。

### Task 2: 脱敏配置接口

**Files:** 新增 `model_config_routes.py`、`backend/tests/test_model_config_routes.py`；修改 `app.py`。

**Interfaces:** `create_model_config_router(store: ModelConfigStore) -> APIRouter`；GET/PUT `/api/model-config`，POST `/api/model-config/test`。请求字段 `base_url`、`model`、可选 `api_key`；状态字段 `configured`、`base_url`、`model`、`source`（file/environment/none）。

- [x] 写失败测试：GET 无密钥；PUT 保存不发任何网络请求；跨站 Origin、非法 Host 拒绝；本机同源与 Vite 本机开发来源可用；恶意 extra 字段或类型错误响应不含密钥；损坏配置返回脱敏错误。
- [x] 运行该文件确认失败，再实现路由。Host 仅接受 localhost/127.0.0.1/[::1]/测试客户端 testserver；有 Origin 时仅接受与 Host 同源或明确本机 Vite 5173 来源，拒绝 null；无 Origin 的 CLI 请求须符合可信 Host 且不带跨站 Fetch Metadata。
- [x] 使用原始请求加局部 Pydantic 验证并返回固定校验错误，避免全局改变既有业务错误格式；响应加 `Cache-Control: no-store`。保存失败返回安全错误，不返回异常对象。
- [x] 写主动测试的 MockTransport 测试：固定短 messages、有限输出 token、超时、401、429、5xx、非 JSON/空 choices、仅 reasoning 无回答均不报成功，不暴露上游正文；不保存配置、不自动重试。测试失败不影响原配置。
- [x] 实现固定短 Chat Completions 非流式测试调用和可注入 HTTP 传输，接线共享 store；运行两组新增测试及原后端回归，预期全部通过。

### Task 3: 网页模型设置

**Files:** 新增 `ModelSettings.tsx`、`ModelSettings.test.tsx`；修改 `App.tsx`、`api.ts`、`styles.css`、`App.test.tsx`。

**Interfaces:** `ModelConfigStatus` 对应任务二状态；API 方法 `getModelConfig()`、`saveModelConfig(payload)`、`testModelConfig(payload)`；组件 `ModelSettings({onConfigured}: {onConfigured?: () => void})`。

- [x] 写失败测试：未配置显示 DeepSeek 默认地址/模型、费用提示；保存仅 PUT；测试仅 POST；密码输入 type=password；保存成功清空；响应未包含 key 也可显示已配置；留空沿用及换地址重新输入提醒；错误不显示提交密钥。
- [x] `npm --prefix frontend test -- --reporter=dot` 确认新测试失败后实现组件和类型。默认 `https://api.deepseek.com`、`deepseek-flash`，不覆盖已有安全状态字段；并发操作期间禁用保存/测试，失败不清空用户输入。
- [x] 在现有设置页接入组件、工作台未配置时提示前往设置；保持无模型情况下可管理文档，维持原来源数量设置。更新 App 测试的状态请求 mock。
- [x] 验证密钥未写入 localStorage/sessionStorage，无 key 回填，无自动连接测试。执行全部前端测试和 `npm --prefix frontend run build`，预期通过。

### Task 4: 可移植快捷启动与持久化

**Files:** 修改 `Evidence Studio.cmd`、`scripts/start-project.ps1`、`compose.yaml`、`.gitignore`；新增 `scripts/tests/start-project.Tests.ps1`，修改 `backend/tests/test_container_files.py`。

**Interfaces:** 脚本参数 `-NoBrowser`、`-Build`、`-DockerPath <path>`；无 Build 时不构建/拉取；CMD 传递显式参数，失败暂停。

- [x] 将旧 CMD/脚本备份至确切的仓库外本地备份目录。写模拟 Docker 脚本与 PowerShell 自包含断言测试，不安装 Pester。
- [x] 先运行脚本测试确认失败：模拟 PATH/显式含空格路径、Docker 缺失/引擎未就绪/Compose 缺失、启动非零退出、不覆盖 DOCKER_*、非本机引擎拒绝、NoBrowser 不打开页面。
- [x] 实现函数化依赖发现与启动主入口，测试可导入函数而不自动启动；保留 Windows PowerShell 5.1 兼容。仅接受本机命名管道引擎，拒绝 ssh/tcp 远程 context，避免将本机配置误用于远程部署。
- [x] Compose `.env` 使用 `required: false`（声明 Compose >=2.24），挂载 `./runtime-config:/app/runtime-config`，配置路径设为 `/app/runtime-config/model.json`；原卷名不动。启动时创建缺失目录但不写真实密钥或覆盖 `.env`。
- [x] 通过模拟进程调用断言日常 `up -d --no-build --pull never`、显式构建分支和超时诊断；健康检查用模拟函数，不启停现有 Docker。运行静态容器回归及 PowerShell 测试。

### Task 5: README 与发布验收

**Files:** 修改 `README.md`、`docs/setup.md`、`docs/api.md`、`docs/evaluation.md`、`.env.example`；必要时同步 `evaluation/README.md`；更新本计划完成状态。

- [x] README 按“安装 Docker Desktop → 首次构建 → 快捷启动 → 网页填自己的 DeepSeek API → 使用功能”编排；附官方 Docker Windows 安装页、DeepSeek API 文档/申请入口；明确用户自行安装，不自动下载软件。
- [x] 说明 Compose 最低版本、非标准安装参数、配置优先级、本机明文文件/备份注意事项、收费按钮、API 额度不等同网页订阅、资料出网边界。不宣称所有 Coding Plan 均兼容。
- [x] `.env.example` 更新模型示例但不含真实密钥；API 文档列新增接口和脱敏错误；评测文档记录本轮实际结果，历史指标不改写为新结果。
- [x] 全量运行 `.venv/Scripts/python.exe -m pytest`、`npm --prefix frontend test`、`npm --prefix frontend run build`、PowerShell 模拟启动测试、Markdown 本地链接检查、`git diff --check`。分清语法/模拟测试与尚未运行的真实 Docker/DeepSeek 验收。
- [x] 检查变更与 Git 忽略规则，使用不输出密钥的扫描检查候选发布文件；列出真实配置仍排除的证据。独立审查密钥暴露、跨站请求、配置切换和卷保护；如委派审查需用户明确选择相应执行方式。
- [ ] 向用户展示最终改动、测试、剩余风险、拟暂存清单和提交信息，例如 `feat: 支持快捷启动与网页模型配置`。未确认前不暂存、提交、推送；确认后仅提交已暂存文件，推送并核对远程 SHA。

## 自审结果

设计每个部分已映射至任务一至五；Review Focus 五项均有所属测试。接口字段统一使用 `model`，不混用 `model_name`。启动测试不依赖现有服务；真实模型调用仍未授权用于本轮。新规格和计划与业务修改一并候选提交，不单独抢先发布。

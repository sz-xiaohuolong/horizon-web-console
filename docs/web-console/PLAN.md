# Horizon 本地 Web 控制台实施计划

交付一个可本机运行和验收的控制台，先建立事实与技术基线，再形成观测、控制、配置及微信闭环，最后统一验证。以下记录预期任务和依赖；实际状态与证据由 [PROGRESS.md](PROGRESS.md) 和 [VERIFICATION.md](VERIFICATION.md) 维护。

依据：[PRD.md](PRD.md)、[技术方案](DESIGN.md)、[AGENTS.md](../../AGENTS.md)、[视觉系统](../../DESIGN.md)。Release 为 `web-console-local-v1`，已获完整本地开发授权，停止于用户验收。

## 1. 前置环境与共同约束

- 复用 Python >=3.11、uv、Pydantic 2、pytest 和现有文件存储；增加 FastAPI/Uvicorn。
- 前端在 `web/` 使用 React、TypeScript、Vite 与 Tailwind 4，npm 锁定依赖；后端托管 `web/dist`。
- 自动验证使用临时配置、工件及伪服务；不运行真实付费 AI、不发送消息、不执行含 Git 推送的 `scripts/daily-run.sh`。
- 保留接手时用户已有改动，详见根规则；配置测试不能修改真实 `data/config.json` 或覆盖已有备份。
- 本地入口目标为 `uv run horizon-web --host 127.0.0.1 --port 8765`。构建、测试和启动成功均需实际结果，不能凭命令存在认定通过。

| 用途 | 计划命令或操作 | 预期判据 |
|---|---|---|
| 后端相关测试 | `uv run --extra dev pytest tests/test_web_*.py` | API、安全、配置、锁和任务生命周期通过 |
| 原功能回归 | `uv run --extra dev pytest`，按变更及失败定位范围执行 | 适用回归通过或明确记录已有失败 |
| 前端构建 | `npm --prefix web ci`、`npm --prefix web run build` | 类型与生产构建通过 |
| 视觉和真实操作 | Hallmark 检查、内置浏览器桌面/窄屏 | 无阻断视觉问题，主要流程可操作 |

## 2. 文件级变更映射

| 操作 | 文件或目录 | 职责 | 任务 |
|---|---|---|---|
| 新增 | `AGENTS.md`、`DOCUMENT_MAP.md`、`PRODUCT.md`、根 `DESIGN.md` | 项目规则、入口、产品与视觉事实 | TASK-001 |
| 新增 | `docs/web-console/` | 需求、方案、计划、接口、进度与验证 | TASK-001、TASK-006 |
| 新增 | `src/web/api.py`、`src/web/server.py`、`src/web/__init__.py` | API、本地启动、静态托管与入口 | TASK-002 |
| 新增 | `src/web/runtime.py`、`src/web/config.py` | 后台任务、SSE日志、指标和安全配置修改 | TASK-004 |
| 新增 | `src/web/wechat.py` | 二维码、验证码、上下文与会话状态 | TASK-005 |
| 新增 | `src/run_lock.py` | CLI 与 Web 的共同运行锁 | TASK-004 |
| 修改 | `src/main.py` | 完整 CLI 运行接入共享锁 | TASK-004 |
| 修改 | `pyproject.toml`、`uv.lock` | Web 依赖与 `horizon-web` 命令 | TASK-002 |
| 新增 | `web/src/App.tsx`、`Overview.tsx`、`Runs.tsx`、`Reading.tsx`、`Settings.tsx` | 中文导航、概览、运行、速递、配置和微信界面 | TASK-003–TASK-005 |
| 新增 | `web/src/components.tsx`、`lib.ts`、`hooks.ts`、`types.ts`、`main.tsx` | 公共控件、请求、状态与前端入口 | TASK-003–TASK-005 |
| 新增 | `web/src/app.css`、`base.css`、`tokens.css`，`web/package*.json`、`vite.config.ts`、`tsconfig.json`、`index.html` | 视觉系统、锁定依赖与构建 | TASK-003 |
| 新增 | `tests/test_web_api.py`、`tests/test_web_runtime.py`、`tests/test_web_wechat.py`、`web/tests/lib.test.ts` | 真实行为接缝与安全回归 | TASK-002–TASK-005 |
| 修改 | `README_zh.md`、`.gitignore` | 本地启动说明及构建/运行产物边界 | TASK-006 |

上表源码文件已根据当前工作树核对；实施及验证状态仍由进度记录维护。现有 `src/mcp/` 服务优先复用；安全修复影响共享存储时，应同步相应现有测试，记录实际改动，不扩大为无关重构。

## 3. 任务、依赖与就绪前沿

| 任务 | 可验证交付 | 需求 | 依赖 |
|---|---|---|---|
| TASK-001 | 已冻结验收、技术基线与设计规范 | 全部 | 用户现有授权、项目事实核验 |
| TASK-002 | 只读 API 和单端口静态托管 | REQ-001–REQ-003 | TASK-001 |
| TASK-003 | 概览、阶段检索及 Markdown 阅读界面 | REQ-001–REQ-003 | TASK-001；联调依赖 TASK-002 |
| TASK-004 | 后台运行、取消、共享锁、SSE 与安全配置修改 | REQ-004、REQ-005 | TASK-002；界面联调依赖 TASK-003 |
| TASK-005 | 微信扫码和上下文管理 | REQ-006 | TASK-002、TASK-003 |
| TASK-006 | 聚焦审查、回归、浏览器验收与交付文档 | 全部 | TASK-002–TASK-005 |

计划启动时就绪任务是 TASK-001。基线通过后后端读接口与前端框架可在明确接口契约下并行；运行、配置和微信在各自边界内实现，由同一 owner 整合。执行时就绪判断以进度事实为准。

### TASK-001：基线与设计

核验仓库入口、旧 CLI 与 MCP 工件差异、依赖及官方文档，建立根规则和唯一地图。冻结 PRD 的 REQ/AC；Hallmark 选择操作台主题，Impeccable 沉淀 token、布局和状态要求。检查文档链接和范围，不能把方案写成实现。恢复时只移除本次创建的规则与文档，不影响现有草案。

### TASK-002：真实读取闭环

在 `src/web/` 建立 FastAPI 入口、依赖和请求来源保护，复用运行服务读取阶段、元信息和摘要。配置和会话只输出脱敏摘要。建立无工件、旧工件、非法标识和摘要渲染输入的测试，再接入 `web/dist`。通过相关 pytest 和启动健康检查验收；失败不写真实数据。

### TASK-003：操作界面

在 `web/` 实现应用导航、概览、运行列表和阶段条目检索、详情及历史 Markdown 阅读下载。请求层统一加载、错误、空状态和重试反馈；遵循根视觉规范与键盘操作。运行生产构建，并用临时工件进行浏览器验收。恢复可独立撤回前端构建和页面，不变更业务文件。

### TASK-004：运行与配置控制

先用伪服务建立启动/重复提交/取消/阶段异常/锁释放测试，再实现后台任务和 SSE 日志。共享锁接入 CLI，Web 运行不用 CLI 自动通知路径。配置从原始 JSON 白名单合并，测试 revision 冲突、凭据保留、独立备份和原子写失败，再实现编辑界面。测试期间所有文件位于临时目录；恢复时终止任务并核验锁、原配置和已生成工件。

### TASK-005：微信状态闭环

以伪 ILink 客户端覆盖二维码、等待、确认、过期、取消、失败及首条消息上下文，再实现本地登录 API 与界面。任何状态响应都不得携带令牌，刷新不可调用发送接口。真实账户行为保留用户验收边界。恢复取消当前登录任务并保留已合法保存的会话；不因页面取消自动删除原会话。

### TASK-006：验证与交付

核对 diff、规格、安全与兼容风险；执行适用后端回归、前端构建、Hallmark 检查及内置浏览器操作。桌面和窄屏在一次批量检查中收集问题，集中修复后只做必要确认。同步 API、已实现架构、进度与验证矩阵，保留本地启动入口供验收；不提交远程、不创建 PR 或部署。

复杂委派使用本文件的任务/AC、根规则、技术方案与 API 契约作为交接上下文，明确各 Agent 文件归属、禁止操作、必要测试及应交回证据。用户原有脏文件是共同保护边界。

## 4. 需求追溯与计划验证

| 验收编号 | 场景 | 计划检查入口 | 任务 |
|---|---|---|---|
| AC-001–AC-003 | 真数据、缺指标、未接管调度 | `tests/test_web_api.py`、概览浏览器 | TASK-002、TASK-003 |
| AC-004–AC-006 | 阶段筛选、推断说明、路径拒绝 | `tests/test_web_api.py`、详情浏览器 | TASK-002、TASK-003 |
| AC-007–AC-008 | 摘要选择下载与安全渲染 | `tests/test_web_api.py`、临时 Markdown 浏览器 | TASK-002、TASK-003 |
| AC-009–AC-012 | 运行、并发、取消失败、日志重连 | `tests/test_web_runtime.py`、SSE、浏览器 | TASK-004 |
| AC-013–AC-015 | 来源编辑、凭据保留、配置冲突 | `tests/test_web_api.py`、配置界面 | TASK-004 |
| AC-016–AC-018 | 微信状态机、上下文和脱敏 | `tests/test_web_wechat.py`、微信界面 | TASK-005 |

实际结果统一见 [VERIFICATION.md](VERIFICATION.md)，本表不另维护通过状态。

## 5. 本地交付与恢复

交付前应确认相关测试及构建证据、浏览器操作、配置与会话保护、用户原有改动和文档契约一致。未覆盖的真实外部模型/微信行为直接记录限制。

交付顺序为安装锁定依赖、构建前端、以本机地址启动、执行浏览器验收并保留验收入口。任一核心 AC 失败、配置损坏、令牌泄露或并发保护失效时停止宣称可验收，先定位并修复受影响路径。

恢复顺序：停止 Web 任务与服务，确认锁释放；必要时从本次独立备份恢复配置并校验；回退本次明确修改，保留用户原有脏文件和已有摘要。代码恢复不能代替数据恢复检查，不使用全工作树重置。

## 6. 里程碑与偏差入口

| 里程碑 | 达成条件 | 依赖 |
|---|---|---|
| 可观测 | 概览、阶段和速递形成真实数据闭环 | TASK-001–TASK-003 |
| 可控制 | 运行、配置及微信状态可安全操作 | TASK-004、TASK-005 |
| 可验收 | 聚焦审查、测试、构建、浏览器证据及文档一致 | TASK-006 |

实际进度、偏差和阻塞在 [PROGRESS.md](PROGRESS.md) 留一份记录；需求变化更新 PRD，技术变化更新方案，验证结果更新 VERIFICATION。没有可靠排期，不承诺虚构完成时长。

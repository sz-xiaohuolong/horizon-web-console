# Horizon 本地控制台 API 接入

本接口服务同仓 React 控制台，默认地址为 `http://127.0.0.1:8765`，适用 `web-console-local-v1`。接口已在 `src/web/api.py` 实现；字段校验以该模块的 `RunRequest`、`ConfigPatch`、`VerificationRequest`、`DeliveryRequest` 及运行时 `/api/openapi.json` 为准。`/api/docs` 是无需 CDN 的离线接口目录。

## 1. 接入与安全边界

前端使用同源相对路径 `/api/...`。服务仅接受 `127.0.0.1`、`localhost` 和 `::1` 的 Host；存在 Origin 时必须与请求 Host 严格同源。所有写操作同时要求 `Origin` 和 `X-Horizon-Request: 1`，JSON 正文使用 `Content-Type: application/json`。例如通过 `127.0.0.1:8765` 请求时，不能将 Origin 写成 `localhost:8765` 或省略端口。

服务没有多用户账号或公网访问承诺，来源检查不代替公开网络鉴权。配置、工件和会话根目录由服务端决定，调用方只传合法记录标识。运行目录及元信息、阶段、摘要、日志工件若为符号链接则拒绝读取。配置、会话、日志和错误均脱敏，不能把响应中的脱敏占位值当成新凭据写入。

## 2. 接口目录

除启动运行为 `202` 外，下表成功响应为 `200` JSON；SSE 返回事件流。无结果列表返回空 `items`。非法输入、缺失文件与冲突按第 6 节处理。

| 方法与路径 | 输入与约束 | 成功结果及副作用 |
|---|---|---|
| `GET /api/health` | 无 | `{ "status": "ok" }` |
| `GET /api/overview` | 无 | `active_run`、`latest_run`、运行/摘要数量、`sources`、`ai`、`wechat`、`scheduler`、`warnings`、`busy` |
| `GET /api/runs` | `limit` 默认 100，范围 1–1000 | `{items, count}`，按更新时间倒序；count 为本次返回数量 |
| `POST /api/runs` | `RunRequest`，见第 3 节 | 取得共享锁后创建后台任务，返回运行对象；不发送外部通知 |
| `GET /api/runs/{run_id}` | 合法运行标识 | 运行对象、阶段可用性、计数和元信息 |
| `POST /api/runs/{run_id}/cancel` | 无正文 | 返回取消后的运行对象；只能取消本进程活跃任务，保留已写工件 |
| `GET /api/runs/{run_id}/stages/{stage}` | 阶段及过滤参数，见第 4 节 | `{items, total, offset, limit, score_distribution, source_counts}` |
| `GET /api/runs/{run_id}/summary` | `language` 默认 `zh`，1–20 位字母、数字、下划线或短横线 | `{run_id, language, markdown}` |
| `GET /api/runs/{run_id}/logs` | 无 | `{items}`，日志项为 `{id, time, level, message}` |
| `GET /api/runs/{run_id}/logs/stream` | 可选 `Last-Event-ID` 非负整数 | `text/event-stream`，`log`/`done` 事件，见第 3 节 |
| `GET /api/summaries` | 无 | `{items, count}`，条目含 `id/date/language/title/size/revision/updated_at`；size 单位为字节，按更新时间倒序 |
| `GET /api/summaries/{summary_id}` | `horizon-YYYY-MM-DD-语言.md` 文件名 | `{id, date, language, markdown, size, revision, updated_at}`；revision 为正文 SHA-256，不返回任意路径文件 |
| `GET /api/summaries/{summary_id}/wechat` | 已归档文件名 | 只读推送预览，不联网、不发送；字段见第 5 节 |
| `POST /api/summaries/{summary_id}/wechat` | `{revision, confirmation}`，均为预览返回的 64 位十六进制值 | 确认后分段发送完整报告，返回 `{status, chunks_sent, message}` |
| `GET /api/config` | 无 | `{revision, config, profiles}`，原始环境变量引用保留，凭据脱敏 |
| `PATCH /api/config` | `{revision, patch}` | 返回更新后的配置视图，独立备份后原子写入；其他任务占锁时拒绝 |
| `GET /api/wechat` | 无 | 本地会话、上下文及估算额度，见第 5 节 |
| `POST /api/wechat/login` | 无正文 | 获取二维码并创建登录任务；已有本进程登录任务时返回该任务 |
| `GET /api/wechat/login/{login_id}` | 服务端返回的登录标识 | 登录状态和前端所需二维码数据 |
| `POST /api/wechat/login/{login_id}/verify` | `{code}`，非空、最长 32 字符 | 将验证码交给当前等待验证码的登录任务，否则冲突 |
| `POST /api/wechat/login/{login_id}/cancel` | 无正文 | 取消本进程登录任务，保留原有合法会话 |
| `POST /api/wechat/refresh` | 无正文 | 读取新消息上下文后返回微信状态；不发送消息 |

历史速递接口返回 JSON 中的 Markdown。网页下载由前端以原文生成文件，不依赖另一个下载端点。

## 3. 运行、状态与日志

`POST /api/runs` 正文的 `hours` 默认为 24，范围 1–168；`enrich` 默认为 `true`；`languages` 可省略以使用配置语言，提供时为 1–10 个语言标识，每个最长 20 字符，只允许字母、数字、下划线或短横线，重复值去重。界面提供 12/24/48/72 小时和 7 天选项。未知正文字段会被拒绝。

运行对象包含 `run_id/status/current_stage/created_at/updated_at/duration_seconds/tokens/counts/stage_durations/error/meta/stages`。状态为 `running`、`completed`、`failed`、`cancelled`、`interrupted` 或 `unknown`。`tokens` 为 `{input, output, total}` 或 `null`；缺失历史耗时和计数也允许 `null`。`stages` 是四阶段是否存在的布尔映射，不能仅凭任务状态推定工件齐全。

后台顺序执行现有阶段服务并在 `data/mcp-runs/{run_id}` 保存工件。没有抓取结果时仍可生成空结果速递；深度补充整体失败会记录警告并用筛选结果生成速递。每种语言的本地历史摘要会写入 `data/summaries/horizon-日期-语言.md`，同日同语言沿用现有覆盖行为；运行目录仍保存该次摘要。

重复启动不保证幂等，忙时返回 `409`，调用方应读取当前任务。取消只停止后续处理，不能撤销已经发生的外部请求或费用；已完成或其他进程任务不可由本进程取消。服务正常退出会取消本进程活跃任务；强制中断后，下次无其他进程持锁时将遗留 Web 运行标记为 `interrupted`。

SSE 以 `event: log` 发送日志项，事件 `id` 为递增序号；请求携带 `Last-Event-ID` 后只重放较新的保留项。任务结束发送 `event: done`，空闲等待每 10 秒发送注释心跳。断开日志连接不影响运行，重连不会新建任务。内存最多保留 2000 项，每条正文最多 8000 字符；每运行的 `web-logs.jsonl` 约束为约 1 MB 尾部日志，超出部分不能保证重放。正文只作为文本显示。

## 4. 阶段过滤与配置更新

阶段 `stage` 只允许 `raw`、`scored`、`filtered`、`enriched`。查询参数如下：

| 参数 | 默认与约束 | 口径 |
|---|---|---|
| `offset` | 默认 0，非负整数 | 过滤结果的起始位置 |
| `limit` | 默认 50，范围 1–200 | 本页条数 |
| `q` | 默认空，最长 200 字符 | 对条目序列化内容做不区分大小写搜索 |
| `source` | 默认空 | 非空时精确匹配 `source_type` |
| `disposition` | 默认 `all`，可选 `kept/removed` | 依据条目是否存在于 filtered 工件判断 |
| `min_score` | 可省略，范围 0–10 | 只保留已评分且不低于该值的条目 |

响应的 `total` 和 `score_distribution` 按过滤结果计算，`source_counts` 始终统计完整当前阶段。条目增加 `retained` 和 `exclusion_reason`；缺少 filtered 工件时 retained 为 `null`。未保留原因仅由工件差集推断，响应明确标注“推断”，不代表精确评分/去重/配额决策日志。

配置 revision 是读取原文件字节的 SHA-256，用于检测外部编辑和过期保存。`patch` 非空，顶层只允许 `collection`、`processing`、`digest`、`sources`、`wechat`；`processing` 只允许 `default_profile/profile_settings`。`sources` 类型必须在既有注册表中。字段由现有 Config 和 ProfileRegistry 校验；采集时间窗为 1–168 小时，评分阈值为 0–10，配额遵循正数约束。

`digest.profile_min_items` 为处理配置 ID 到非负整数的映射，例如 `{"tech-blog": 2}`；ID 必须已加载，最低条数合计不能超过 `max_items`。先在评分和去重之后预留条目，再按评分补齐，分类上限始终有效。完成筛选后，运行元信息的 `balanced_digest_profile_shortfalls` 记录未满足的数量，Web 运行日志同时给出警告。此字段不代表自动降低评分门槛或跨运行补选。

`sources.rss[]` 支持 `time_window_hours`（1–168 或 null）和 `max_items`（1–100 或 null）。前者以当前时间为基准覆盖运行级时间窗，后者优先采集该时间窗内最新的有效条目；两者省略时保持既有行为。

普通对象递归合并；提供的每个 `sources` 类型整体替换该类型，其他类型保留。`digest.category_groups`、`digest.profile_min_items` 和 `processing.profile_settings` 整体替换，空对象用于清空对应映射，因此调用方应提交该映射的完整目标内容。列表和映射替换仍会恢复匹配到的原有隐藏凭据与环境变量引用；新增无法匹配的脱敏占位符或将其移动到另一主机不被接受。

若多条私密订阅同名且脱敏后的 URL 完全相同，服务无法唯一关联原有凭据。删除、重排或编辑这组条目时返回 `422`，原配置和独立备份均不写入；须先在本地配置中为这些订阅设置不同名称，再重新读取并编辑。

从 `GET /api/config` 取得 revision 后只提交实际修改的允许字段，不提交整份配置响应。服务保留未编辑的原始字段、环境变量引用及隐藏凭据，不接受新增或更改网页凭据。视图保留现有 Schema 未识别的用户扩展字段，替换来源块时也保留同一可识别条目的原有扩展字段。保存先写入 `config.json.web-UTC时间-随机后缀.bak`，再原子替换配置文件，不覆盖用户的 `config.json.bak`。发生 revision 冲突后应保留草稿并重新加载，不能盲目重试覆盖。

## 5. 微信连接与共享锁

微信状态含 `enabled/connected/ready/remaining_budget/budget_limit/estimated/message`，可能带 `logged_in_at/context_updated_at`。`connected` 只表示已保存会话，`ready` 表示本地会话具备机器人令牌、用户和消息上下文；两者都不构成实时外部连接探测。`estimated` 为 `true`，额度按本地会话计数估算。

登录响应含 `login_id/status/qr_data_url/expires_at/message/verify_code`。二维码通过本地 SVG data URL 展示，过期时间约为创建后 8 分钟。状态包含 `waiting/scanned/confirmed/waiting_message/ready/expired/failed/cancelled`。`verify_code: true` 表示需要用户输入手机验证码；确认扫码后还可能等待首条微信消息上下文。登录任务状态留在服务进程内，重启或旧任务被清理后可能返回 `404`，此时重新获取二维码。

登录与刷新会持有同一数据目录的共享锁，阻止并发流水线和配置写入；取消和结束后释放。登录、刷新不调用发送接口、不消耗回复额度。会话保存于服务端 `wechat_session.json`，令牌和用户标识不返回浏览器。原 CLI 共享该锁；既有 MCP 直接调用路径及外部工具没有自动获得此互斥保证，不能与 Web 同时修改相同数据。

### 手动报告推送

历史页每 5 秒检查索引 revision；同日同语言正文更新时重新读取，“刷新归档”同时刷新列表与正文。`updated_at` 为文件修改时间，浏览器按本地时区显示。运行仍不会自动推送。

预览返回 `revision/confirmation/chunk_count/remaining_budget/estimated/can_send/reason/delivery`。`delivery` 为已有发送结果或 null。预览只读本地配置、会话、报告与发送记录。正文为空、开关关闭、语言不符、会话未就绪、估算额度不足或已有发送记录时，`can_send` 为 false，并给出中文恢复说明。

POST 只接收版本和确认指纹，不接受正文或收件人。服务在共享锁内重读报告，校验正文版本、收件会话、上下文、分段与额度均未变化，冲突返回 409。仅使用预览时的上下文；需要补充额度时先到微信连接页主动刷新，再重新预览。

发送前将 pending 记录原子写入 `data/wechat-deliveries/`，按报告内容及收件会话哈希去重；发送结束记录结果，重启后仍防重复。成功时 status 为 success；失败或部分发送返回对应失败类别及已确认段数，HTTP 200 不代表投递成功，调用方必须检查 status。连接中断或 pending 结果不明时先检查微信与 GET 预览，不能盲目重试。同一版本在失败后也不会再次投递；当前不提供强制重发或续发按钮。

## 6. 错误与调用示例

失败响应至少包含中文 `detail`，部分 Horizon 业务错误另带 `code`。前端不能把错误当作空列表。

| HTTP 状态 | 含义 | 调用方处理 |
|---|---|---|
| `400` | Host 不是允许的本机地址 | 使用本机地址访问 |
| `403` | Origin 非同源，或写操作缺少必要来源头 | 检查完整来源和请求头，不重试业务操作 |
| `404` | 运行、阶段、摘要或登录会话不存在 | 刷新索引；微信会话失效可重新登录 |
| `409` | 运行锁、配置 revision、任务取消或验证码状态冲突 | 读取当前状态，保留草稿后再操作 |
| `422` | 输入、配置或工件内容无效 | 修正字段或检查本地文件 |
| `502` | 微信二维码获取或上下文刷新失败 | 检查网络或重新扫码 |
| `503` | 前端尚未构建 | 执行前端安装和构建；API 可单独检查 |

只读检查：

```sh
curl http://127.0.0.1:8765/api/health
# {"status":"ok"}
curl 'http://127.0.0.1:8765/api/runs?limit=10'
# 无工件时：{"items":[],"count":0}
curl http://127.0.0.1:8765/api/openapi.json
```

用户主动运行的正常调用如下，会访问配置中的真实信息源和 AI 服务；自动测试采用伪服务替换它们：

```sh
curl -i http://127.0.0.1:8765/api/runs \
  -H 'Origin: http://127.0.0.1:8765' \
  -H 'X-Horizon-Request: 1' \
  -H 'Content-Type: application/json' \
  --data '{"hours":24,"enrich":true,"languages":["zh"]}'
```

空闲且配置有效时返回 `202` 和状态为 `running` 的运行对象，其中 run_id 由服务器生成。后续用该标识查询 `/api/runs/{run_id}`，不能依赖固定示例标识。

安全的失败示例不会启动运行：

```sh
# 缺少来源头：403，{"detail":"写操作需要同源控制台请求。"}
curl -i http://127.0.0.1:8765/api/runs \
  -H 'Content-Type: application/json' --data '{"hours":24}'

# 时间窗非法：422，返回请求参数无效提示
curl -i http://127.0.0.1:8765/api/runs \
  -H 'Origin: http://127.0.0.1:8765' \
  -H 'X-Horizon-Request: 1' \
  -H 'Content-Type: application/json' --data '{"hours":0}'
```

## 7. 示例核验入口

`tests/test_web_api.py` 覆盖来源保护、字段校验、配置保留与冲突、阶段筛选和安全文件读取；`tests/test_web_runtime.py` 覆盖伪服务运行、取消、共享锁、指标及日志重放；`tests/test_web_wechat.py` 覆盖微信伪服务状态机。实际执行与浏览器证据见 [VERIFICATION.md](VERIFICATION.md)，未连接真实模型或微信账户不能据此声称外部服务验收成功。

# QGIS Copilot 技术事实与发现

## 文档用途

记录已经查实的事实、当前判断、风险和待验证事项。旧结论被纠正时，直接更新为当前正确内容，并保留必要的来源说明。

## 当前已知

### Goal 1 环境证据（2026-08-30）

- 实际安装：QGIS 4.2.1-Belém do Pará，安装根目录 `D:\app\QGIS`；
- QGIS 自带 Python：3.12.13；Qt / PyQt：6.11.0；
- `D:\app\QGIS\bin\python-qgis.bat` 能导入 `qgis` 及 Qt Widgets；
- 用户实际插件目录存在：`C:\Users\czk\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins`；
- 该 Windows 会话没有创建符号链接特权；已用 Windows Junction 把插件目录的 `qgis_copilot` 映射到唯一权威源码 `D:\wenjian\Hermes\QGIS Copilot\qgis_copilot`，并验证映射下存在 `metadata.txt`。

### Goal 1 代码验证（2026-08-30）

- `python-qgis.bat -m compileall -q qgis_copilot tests` 通过；
- `QT_QPA_PLATFORM=offscreen python-qgis.bat -m unittest discover -s tests -v` 通过，4 项：空白消息拒绝、发送后可取消、设置入口不保存/发送凭据、插件动作与 Dock 生命周期清理；
- Goal 1 的发送操作只演示 UI 状态循环；没有模型请求、项目读取、PyQGIS GIS 操作或凭据持久化。后续 Goal 必须替换该占位失败状态，不能误当真实聊天。

### Goal 1 真实桌面验收（2026-08-30）

- QGIS 4.2.1 重启后，工具栏出现“打开 QGIS Copilot”，证明插件已被发现、启用并完成初始化；
- 点击该入口后，Dock 正常打开，实测画面显示：标题 “QGIS Copilot”、设置按钮、消息输入框、发送按钮、欢迎文案以及“准备就绪：输入一个 GIS 问题开始。”状态；
- 没有可见 ImportError、traceback 或资源加载错误；空 QGIS 项目仍保持正常可用；
- QGIS 对新插件需要一次启动发现和一次显式 profile 启用：`QGIS4.ini` 的 `[PythonPlugins]` 内设置 `qgis_copilot=true` 后重启生效。
- 为启动探测产生了根目录一个字面名为 `NUL`、0 字节的 Windows 文件。它是明确的调试残留；普通 Python、cmd 和 Win32 删除尝试均被 Windows 设备名语义或权限拒绝。未删除或移动任何其他路径，后续需用经验证的 Windows 管理员/恢复路径定向清理。

### Goal 2 实现与自动化证据（2026-08-30）

- 新增 `models/`、`security/`、`tasks/`、`agent/` 的最小职责模块；未引入 pip、Node.js、TypeScript、React、WebEngine 或独立后端。
- `models/openai_compatible.py` 用 Python 标准库 `urllib` 请求 OpenAI-compatible `/chat/completions`；适配层不导入 UI 或 PyQGIS 对象。
- `tasks/network.py` 用 `QThread` 执行网络请求；线程只接收纯 Python 消息与模型适配器，不携带 QGIS 对象；取消后丢弃已到达的响应。
- `security/credentials.py` 使用 `QgsApplication.authManager()` / `QgsAuthMethodConfig` 的 Basic 认证配置保存 Key；普通 `QSettings` 只保存 endpoint、模型名、超时和 auth config ID。
- `security/redaction.py` 会掩盖 Authorization、Bearer token 和常见密钥字段，避免将密钥带入 UI 或错误文案。
- 已修复真实桌面暴露的认证存储缺陷：首次存储使用 `storeAuthenticationConfig`，已有 auth config ID 时改用 QGIS 的 `updateAuthenticationConfig`，不再把同一 ID 当作新配置重复插入。
- `agent/core.py` 目前严格限制一次请求最多一步；Goal 3 才会接入工具多轮循环。
- `QT_QPA_PLATFORM=offscreen D:/app/QGIS/bin/python-qgis.bat -m compileall -q qgis_copilot tests` 通过；随后 `-m unittest discover -s tests -v` 共 9/9 通过。
- Goal 2 测试启动了仅监听 `127.0.0.1` 的临时 HTTP 端点并完成真实 POST `/v1/chat/completions`，同时覆盖 settings、脱敏、认证存储 seam、最大步数和 QThread 取消；它证明网络协议与非阻塞任务链，不代表一个真实外部模型已验收。
- 本轮 secret scan 没发现硬编码 Key 或长 Bearer token；命中的 `api_key`、`secret-value` 是变量名和测试夹具文本，不是实际凭据；未发现 `eval` 或 `exec`。

### Goal 2 真实桌面验收状态（2026-08-30）

- QGIS 4.2.1 进程能够启动，且工具栏已经可见“打开 QGIS Copilot”，证明本轮模块没有阻止插件被发现和加载。
- 受当前桌面自动化窗口路由限制，无法可靠地把后台 QGIS 窗口前置并点击工具栏来获取 Goal 2 设置对话框的可观察证据；没有重复误点或更改 QGIS 配置。
- 更重要的验收阻塞是：没有可安全使用的真实外部测试模型端点，且 API Key 属于敏感信息。必须由哥哥在 QGIS 设置窗口亲自输入可用 endpoint、model 与 Key；小鱼不接收、不记录、不输入密钥。完成后可验证连通性、真实聊天、认证失败、超时/断网和取消 UI 路径。

### Goal 5 实现、测试与交付证据（2026-08-30）

- API Key 仍只通过 `QgsApplication.authManager()` 的认证配置保存：普通 `QSettings` 只保存 endpoint、model、timeout 和 auth config ID；重开设置窗口不会回填既有 Key。已有认证配置用 `updateAuthenticationConfig` 更新，Key 留空保存会保留现有 auth config ID。
- `SettingsDialog` 新增 API Key 右侧“显示/隐藏”切换：默认 Password 回显，点击仅切换本次手动输入的文本；不读取、显示或导出认证存储内既有 Key。QGIS bundled runtime 专项测试已覆盖切换与恢复掩码。
- 新增 `diagnostics/logging.py`：通过 Python logging 记录聊天、工具和 Processing 的状态、耗时与受限摘要；摘要会经过 Authorization、Bearer token、api_key 和 password 脱敏且截断为最多 500 字符。专项测试确认日志不包含测试秘密。
- 新增 `.gitignore` 排除 Python 缓存、测试/本地 GIS 数据、构建产物、常见密钥文件与调试残留；新增 `scripts/package_plugin.py`，用标准库生成并校验单顶层 `qgis_copilot/` ZIP。实际生成 `dist/qgis_copilot.zip`，成员数 33，大小 32,488 bytes，包含 `metadata.txt`、`__init__.py` 与 `LICENSE`，不含 tests/references/.git/缓存/密钥成员。
- README 已更新为实际可用的 ZIP 安装、模型配置与隐私、权限边界、已知限制、QGIS bundled Python 验证命令和 GPL-3.0-only 说明；不再声称未验证平台兼容或“仍处 Goal 1”。
- `python-qgis.bat -m compileall -q qgis_copilot tests scripts` 通过。Goal 1–3、Goal 5 的组合运行 25/25 通过（exit 0）；Goal 4 的独立 Processing 回归 9/9 通过（exit 0）。一次把所有测试放在同一 QGIS Python 进程的历史组合运行，正文全部通过后曾在退出阶段触发 Windows native segmentation fault（139）；因此不将该组合进程称为完整绿色，而以两组独立、exit 0 的结果作为当前自动化证据。
- 通过 Git 内容扫描排查常见真实 API Key、长 Bearer token、私钥头和 `eval`/`exec`（排除只读 reference）；本轮无命中。注意 `git grep` 仅覆盖已跟踪文件；本轮新增文件另由插件 ZIP 内容校验与 Goal 5 专项测试覆盖。
- QGIS 4.2.1 已由 `D:\app\QGIS\bin\qgis.bat` 在真实桌面启动。哥哥补充的真实验收结果与截图确认：干净 QGIS 已从 ZIP 安装，已配置真实模型并完成项目查询；截图可见先生成待确认计划，随后 700 米缓冲 Processing 成功，生成并加入 `气象站点_700米_测试2`（70 个要素），且原始图层未被覆盖；哥哥同时确认重启 QGIS 后已复用已保存凭据，无需再次输入 Key。截图本身不展示敏感 Key，故不记录具体凭据值。Goal 5 最终用户路径通过。


- 面向普通用户时，QGIS 内置聊天入口比要求连接外部 Agent 更低门槛；
- QGIS 插件直接承担 MCP Host 和核心 Agent 能力，可以减少额外进程、端口和配置问题；
- QGIS 原生操作不必强制经过 MCP 网络链路，MCP 更适合作为扩展和互操作边界；
- 模型服务需要独立适配层，以同时支持云端 API 和可选本地模型。

### 安全风险

- 能够修改 QGIS 项目或执行 PyQGIS 的 Agent 具有真实副作用；
- 任意代码执行不能作为普通用户模式的默认能力；
- 本地网络服务若监听非 localhost，可能扩大未授权访问面；
- API Key、图层属性和项目路径都可能属于敏感信息，不能进入公开仓库或普通日志。

### 工程风险

- QGIS Python 环境与用户系统 Python 环境不能假设一致；
- 网络请求和模型响应不能阻塞 QGIS 主线程；
- QGIS 3.x、QGIS 4.x 以及不同操作系统的 Qt/PyQt 能力需要分别验证；
- 聊天界面如果依赖 Qt WebEngine，必须先验证目标 QGIS 发行版是否提供兼容的 Python bindings，不能只看运行时 DLL 是否存在。

### v2.0 产品与计划基线（2026-08-30）

- 产品方向已由已完成的 MVP 扩展为“可信 GIS 工作台”：优先补足数据检查与分析，并以受控空间处理承接诊断结论；任务链为“看懂数据 → 发现问题 → 明确目标 → 形成方案 → 确认执行 → 验证结果 → 继续迭代”。
- `产品需求文档.md` 已确定本轮体验要求：真实会话信息条、模型能力档案与受控模型行为模式、快捷任务、工具/计划/结果卡、本轮审计记录、结果后的 QGIS 原生操作。模型不支持时显示服务默认，不伪造“思考强度”、原始思维链或 Processing 百分比。
- 已确定的只读增量工具为：项目诊断、CRS 一致性、图层质量、字段统计、表达式预览、空间关系预览和选择集摘要；必须保持有界返回，预览不改变选择集、项目、源图层或源数据。
- 已确定的写入增量工具为：重投影、裁剪、筛选导出、相交和融合；均必须复用计划 → 明确确认 → QGIS Processing → 输出重开验证 → 加入项目闭环，默认创建新 GeoPackage 且拒绝覆盖。
- `开发短计划.md` 已升级为 v2.0，按 Goal 6（工作台）、Goal 7（诊断与重投影）、Goal 8（预览、裁剪、导出）、Goal 9（相交、融合、交付回归）执行；当前只可进入 Goal 6。
- 已同步 `架构说明.md`、`README.md`、`task_plan.md`。这些文件中的 v2.0 内容是已确认计划，不是已实现/已发布声明；实际能力与证据必须在相应 Goal 完成后更新。



- Dock 关闭并重开、插件禁用/卸载后的动作与窗口清理；
- 目标 QGIS 版本及长期支持策略；
- QGIS 插件市场对依赖、许可证和打包的具体要求；
- OpenAI-compatible API 在目标模型上的工具调用和流式响应一致性；
- QGIS 主线程下 Processing 任务的异步调度方式；
- 插件更新、崩溃恢复和日志导出机制。

## 证据边界

Goal 1 的真实 QGIS 插件发现、启用和 Dock 打开已得到桌面证据；Dock 关闭/重开与插件卸载清理仍作为 Goal 1 的补充回归项。


### Goal 3 实现与自动化证据（2026-08-30）

- 新增 `context/project_context.py`：生成有界、JSON-safe 的项目摘要，包含项目文件、标题、项目 CRS、图层数量，以及图层 ID、名称、provider、source、类型、geometry type、CRS、要素数、范围和选择集数量；默认最多 100 个图层。
- 新增 `tools/contracts.py`、`tools/registry.py`、`tools/permissions.py` 和 `tools/qgis_tools.py`：注册并暴露 `get_project_state`、`list_layers`、`inspect_layer`、`query_features` 四个只读工具，所有工具结果为结构化成功/失败对象。
- `query_features` 强制限制 `limit` 为 1–100，只返回前 N 条属性和字段名；不存在图层、重名图层、无效参数和未知工具不会让调用方崩溃。
- `models/base.py` 与 OpenAI-compatible 适配器支持解析 `tool_calls` 及 JSON arguments；Agent 增加工具调用预算、工具事件接缝和工具结果写回会话能力。
- Application Controller 已把当前项目摘要注入模型请求，并创建内置只读工具注册表。
- 使用 QGIS 4.2.1 bundled Python 3.12.13、Qt/PyQt 6.11.0 执行 compileall 和 unittest：13/13 通过。

### Goal 3-1 实现与验证证据（2026-08-30）

- 完善 OpenAI-compatible 工具协议：`ToolRegistry` 公开四个 `type=function` JSON schema，模型请求携带 `tools` 与 `tool_choice=auto`；适配器接受空 `content` + `tool_calls`，解析 JSON 字符串参数并拒绝非对象参数。
- `Conversation` 现在保存 assistant `tool_calls` 与带 `tool_call_id` 的 tool result。`AgentCore` 对每个用户请求限制最多 3 次模型调用；Controller 在接收网络线程的 completion 后、在 QGIS 主线程执行工具，再用普通 Python tool result 发起下一轮请求。
- `inspect_layer` 现返回字段 schema（名称、类型、类型名、长度、精度、别名）；`query_features` 严格限制 1–100，返回 `returned_count` 与 `has_more`，不返回无界要素。
- 聊天 Dock 在 Controller 中会显示“正在生成回答”、工具名、工具完成摘要；无效工具/参数、工具失败、取消与最大步数均进入错误或取消状态，不附加伪造 assistant 成功回答。
- 使用 `D:/app/QGIS/bin/python-qgis.bat` 运行 `compileall` 和完整 `unittest discover -s tests -v`：17/17 通过。测试覆盖四工具 schema/权限、字段 schema、查询边界/has_more、未知/重名/无效参数、tool_calls、assistant/tool 会话格式、127.0.0.1 两轮 HTTP、最大步数、失败不伪造成功、网络线程仅承载普通 Python 数据。
- 真实 QGIS 4.2.1 / PyQGIS 内核回归：创建本地内存项目，包含“九段线”（字段 `segment`）与“70个气象站点”（70 条 `station`/`temp` 记录）；经本机 `127.0.0.1` 两轮模型协议依次调用 `list_layers`、`inspect_layer`、`query_features(limit=5)`。结果分别包含两个图层、`segment` 字段和气象站点 S0–S4；每次都确认图层 ID 列表与要素数未改变。
- 该本地 HTTP 端点只是无密钥协议测试，监听 `127.0.0.1`，不接收真实 API Key 或离开本机的数据；不是外部模型验收。

### Goal 3-2 实现与自动化证据（2026-08-30）

- 已记录真实桌面触发条件：同一 17 图层项目中，`list_layers` 和 `inspect_layer` 成功，`query_features` 的模型请求超时；问题发生在模型网络阶段，不是 QGIS 图层读取或只读工具失败。
- 新增 `build_model_project_context()`，仅发送项目标题、项目 CRS、图层总数，以及每层 ID、名称、类型、provider、CRS、要素数和截断标记；不发送字段、数据源路径、范围、选择集或属性。完整字段/范围/选择集仍仅由 `inspect_layer` 返回，前 N 属性仍仅由 `query_features` 返回。
- 第二轮模型请求收敛为系统提示、当前用户问题、当前 assistant `tool_calls` 和匹配的 tool result；不再重复发送初始项目上下文。工具协议、主线程执行和 1–100 属性上限不变。
- 默认超时由 45 秒调整为 120 秒，设置范围仍为 1–300 秒。超时错误会显示当前秒数、设置入口和“重试”路径，并明确不会自动重复请求。
- 使用 QGIS 4.2.1 bundled Python 执行 `compileall` 与完整 `unittest discover -s tests -v`：21/21 通过。新增覆盖轻量上下文、第二轮消息收敛、120 秒默认值与超时恢复文案；既有 127.0.0.1 两轮协议、栅格图层和只读工具回归继续通过。

### Goal 4 实现与 QGIS Processing 自动化证据（2026-08-30）

- 启动独立 QGIS Python 时，Processing provider 默认尚未注册；在测试中显式加入 QGIS 内置 `D:\app\QGIS\apps\qgis\python\plugins` 并运行 `Processing.initialize()` 后，`native:buffer` 可用。真实 QGIS Desktop 已加载“数据处理”环境，插件运行依赖该 QGIS 内置组件，不引入第三方依赖。
- 新增 `buffer_vector`：它是 WRITE 权限的计划工具，只校验有效矢量输入、正数距离、分段、CRS 语义、未保存项目/输出路径与 `.gpkg` 文件冲突，生成包含输入、参数、输出、影响和风险的计划；计划阶段不创建目录或文件、不添加图层，也不修改原图层。
- 聊天 Dock 新增可见计划卡片和“确认执行”“取消计划”动作。取消时清除待执行计划并明确显示没有写入或添加图层。
- 确认后 `BufferProcessingTask` 通过 `QgsProcessingAlgRunnerTask` 提交 QGIS Task Manager，运行 `native:buffer`，检查输出 `.gpkg` 存在、用 OGR 重新打开、验证图层有效后才加入当前项目；失败或取消不会显示成功。
- 截图暴露了两个真实问题并已定向修复：（1）写入计划出现后，Controller 暂停确认流程却没有先写入与 assistant `tool_call_id` 匹配的 tool result；此外，输出路径冲突等工具失败分支也直接中断而未写回失败 tool result。任一情况都会使同一会话的下一条用户消息带着孤立 function call 回到严格模型服务，触发 HTTP 400 `No tool output found for function call`。现已在显示计划或显示工具失败前，统一持久化匹配 ID 的结构化 tool result，并新增成功计划和失败计划两条配对回归。（2）原计划把 500 直接按输入 CRS 的单位交给 Processing；对截图所示 EPSG:4326 站点层会成为 500 度而非 500 米。现已将地理 CRS 路径改为临时 EPSG:3857 米制缓冲、再投回源 CRS；计划卡片会明确展示“米”与转换风险。
- 修复后以 QGIS 4.2.1 bundled Python 执行 `compileall` 和 Goal 4 回归：9/9 通过，包含成功/失败工具调用配对、EPSG:4326 的 500 米处理链、输出 CRS 回归、真实异步 Processing 输出重开与项目插入。
- 组合运行历史全部测试时，各项测试正文均报告通过，但 QGIS 退出阶段出现 Windows native segmentation fault（退出码 139）。因此有效证据为单独的 Goal 4 9/9 通过和此前 Goal 1–3 的独立结果；不把该组合进程的退出码称作完整绿色回归。
- 真实 QGIS Desktop 已确认 Dock 与 Processing Toolbox 都在运行，但此轮桌面自动化无法安全地把新代码重载并通过模型产生写入计划；不能据此冒充计划/取消/确认/失败的桌面证据。Goal 4 仍处于桌面验收待完成状态。



- 哥哥提供的 QGIS Copilot 截图记录同一真实项目的三条请求均完成，状态为“准备就绪”，没有可见 traceback、超时或错误提示。
- `当前项目有哪些图层？` 成功返回 17 个图层；截图没有保留第一条工具进度行，因此不能从该截图单独确认工具名，但其结果与真实项目图层数量一致。
- `告诉我九段线的字段和 CRS` 显示 `inspect_layer`：目标为“金沙江区位分析图—九段线”，CRS 为 `EPSG:4326 — WGS 84`，字段为 `fid`（Integer64）和 `name`（String，长度 9）。
- `查询70个气象站点图层前5条属性数据` 显示 `query_features`：返回 5 条记录，字段包括省份、站名、纬度、经度，且 `has_more=True`；未出现此前的模型服务超时。
- 截图中的工具均为只读查询，未显示编辑、保存、写入、删除或图层变更；这是项目未被本次请求修改的可见证据，但不是项目文件哈希级别的证明。
- 因此 Goal 3-2 的真实 Desktop 验收通过；不自动进入 Goal 4。

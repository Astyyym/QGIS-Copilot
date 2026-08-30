# QGIS Copilot 任务状态

## 当前阶段

- 阶段：增量版本 v2.0，准备进入 Goal 6——可信会话工作台与模型能力档案
- 状态：原 Goal 1–5 MVP 已完成并具备真实用户路径证据；新产品需求、架构和 Goal 6–9 开发短计划已确认，尚未开始实现新能力
- 负责人：哥哥与小鱼共同确认
- 当前进入条件：以 `开发短计划.md` 的 Goal 6 为唯一第一轮实现范围；不得把已写入 PRD 的规划功能当作已交付能力

## 已确认

- [x] 产品名称暂定为 QGIS Copilot
- [x] 产品入口放在 QGIS 插件内
- [x] QGIS 插件承担聊天、Agent Host 和核心 QGIS 工具调度
- [x] 普通用户不应强制安装 Hermes、uv、外部 Agent 或手动配置 MCP
- [x] QGIS 原生工具优先直接调用 PyQGIS
- [x] MCP 作为可选扩展能力
- [x] 模型采用提供商抽象，不绑定单一厂商
- [x] 默认采用先计划、后执行的安全交互
- [x] 首发采用全 Python 单体插件
- [x] 聊天界面采用 qgis.PyQt Qt Widgets
- [x] 首发模型接口采用 OpenAI-compatible HTTP API
- [x] MCP 作为后续扩展，不作为内置 QGIS 工具必经链路
- [x] 首发不引入 TypeScript、Node.js、React 或独立后端

## Goal 阶段状态

- [x] Goal 1：建立可加载的 QGIS 插件与聊天工作台
  - [x] 环境与运行时检查：QGIS 4.2.1，Python 3.12.13，Qt/PyQt 6.11.0
  - [x] 插件骨架、元数据、生命周期与 Qt Dock Widget
  - [x] 消息列表、输入框、发送、停止、重试、设置入口和基础状态
  - [x] QGIS 自带 Python 自动化测试 4/4 通过
  - [x] 开发插件目录 Junction 指向权威源码
  - [x] 真实 QGIS 界面发现、启用并打开 Dock 验收
- [x] Goal 2：接入模型并建立 Agent 基础循环
  - [x] OpenAI-compatible 适配器、设置校验与最长 300 秒超时
  - [x] QGIS 认证存储 API Key，普通 QSettings 仅保存地址、模型、超时和 auth config ID
  - [x] Authorization/API Key 脱敏、认证失败/超时/断网/无效响应/取消路径
  - [x] QThread 非阻塞网络请求和单步受限 Agent 基础循环
  - [x] 设置对话框、连通性测试入口与未配置时自动打开设置
  - [x] QGIS 自带 Python 自动化测试 9/9 通过，含本机 HTTP 测试端点的真实 HTTP 请求与取消
  - [x] 真实外部模型已在 QGIS Desktop 的后续三条只读聊天请求中实际完成工具调用；密钥由哥哥自行输入，未被记录或回显
- [x] Goal 3：接入只读 QGIS 上下文和工具
  - [x] 有界项目摘要、图层元数据、字段/CRS/范围/选择集
  - [x] 工具契约、只读权限判定与注册/发现/结构化调用结果
  - [x] get_project_state、list_layers、inspect_layer、query_features
  - [x] 前 N 属性限制（1–100）与无效图层/参数结构化错误
  - [x] 模型响应支持 OpenAI-compatible tool_calls 解析；Agent 工具预算与 tool 事件基础接缝
  - [x] QGIS 自带 Python 自动化测试 13/13 通过
  - [ ] 真实 QGIS 项目三条聊天请求的工具调用可见性与结果核对：由 Goal 3-1 接管
- [x] Goal 3-1：修复只读工具 Agent 闭环
  - [x] OpenAI-compatible tools schema、`tool_choice=auto`、空 content + `tool_calls`、JSON arguments 解析
  - [x] assistant `tool_calls` 与 tool result / `tool_call_id` 会话格式
  - [x] Controller 在主线程执行只读工具，网络线程仅接收普通 Python messages/tools 数据
  - [x] 有界两轮模型请求，默认每个用户请求最多 3 次模型调用；失败、取消和到达上限不伪造成功
  - [x] 聊天面板显示生成中、工具名、工具完成摘要和工具失败/取消/步数错误状态
  - [x] QGIS 自带 Python 自动化测试 17/17 通过；含 `127.0.0.1` 两轮 HTTP 和真实内存 QGIS 项目三条指定请求
  - [x] 真实 QGIS Desktop 中加载实际项目、通过聊天 Dock 使用外部模型端点完成三条请求：截图证据显示 17 图层列表、`inspect_layer` 和 `query_features` 均正常完成
- [x] Goal 3-2：收敛只读请求上下文并提升模型超时可恢复性
  - [x] 初始模型上下文仅保留项目标题/CRS/图层总数及图层 ID、名称、类型、provider、CRS、要素数；不含字段、路径、范围、选择集和属性
  - [x] 第二轮仅发送系统提示、当前用户问题、assistant tool_calls 与匹配 tool result，不重复项目上下文
  - [x] 默认超时改为 120 秒，仍允许 1–300 秒；超时文案展示当前秒数、设置和手动重试路径，不自动重复请求
  - [x] QGIS 自带 Python 自动化 21/21 通过，含轻量上下文、二轮消息收敛、超时恢复文案、栅格回归与既有工具闭环
  - [x] 真实 QGIS Desktop：同一 17 图层项目执行三条指定请求；列表返回 17 图层，`inspect_layer` 返回九段线 EPSG:4326 与字段，`query_features` 返回气象站点前 5 条且 `has_more=True`，无超时/报错可见

- [x] Goal 4：完成安全的 GIS 执行闭环
  - [x] `buffer_vector` 写入工具只生成经过输入图层、距离、CRS 与新 `.gpkg` 路径校验的执行计划；计划阶段不创建目录/文件、不添加图层、不修改原图层
  - [x] 聊天 Dock 显示输入、参数、输出、影响与风险，并提供“确认执行”“取消计划”按钮
  - [x] 取消计划会清空待执行状态，不创建输出文件或结果图层
  - [x] 确认后用 `QgsProcessingAlgRunnerTask` 调度 `native:buffer`；完成后验证输出文件、重新打开并加入当前项目
  - [x] 输出文件已存在、未保存项目且未指定路径、非 `.gpkg` 路径、无效距离均被拒绝；不允许覆盖
  - [x] 无论计划生成成功还是因冲突等参数问题失败，都会写回匹配 assistant `tool_call_id` 的结构化 tool result，避免下一条用户消息夹带孤立 function call，导致严格模型服务返回 `No tool output found for function call`（HTTP 400）
  - [x] 对地理坐标图层（如 EPSG:4326）明确按米执行：临时投影至 EPSG:3857 缓冲后转换回输入 CRS；自动化已验证输出图层恢复 EPSG:4326
  - [x] QGIS 自带 Python Processing 回归 9/9 通过，含真实异步 `native:buffer` 新建 GeoPackage、重开并入项目、原图层要素数不变
  - [x] 真实 QGIS Desktop 的计划、取消、确认生成结果图层和失败状态验收已完成（哥哥确认）
- [x] Goal 5：完成安全、测试、打包和真实用户路径验收
  - [x] API Key 继续使用 QGIS Authentication Manager：地址、模型、超时和 auth config ID 存在普通设置；既有 Key 不回填 UI，留空保存保留旧凭据，替换使用原 ID 更新
  - [x] API Key 输入框新增默认掩码的“显示/隐藏”；只作用于本次手动输入，自动化验证 1 次显示与恢复掩码
  - [x] 新增脱敏且长度有界的结构化诊断：记录工具/Processing/聊天的状态、耗时和摘要，不记录明文 Authorization、Bearer、API Key 或 password
  - [x] 新增 `.gitignore` 和 `scripts/package_plugin.py`；生成 `dist/qgis_copilot.zip`，只含 `qgis_copilot/` 顶层、插件必需文件和 LICENSE
  - [x] README 已补齐 ZIP 安装、配置/隐私、权限边界、已知限制和真实支持矩阵
  - [x] QGIS 自带 Python 编译通过；Goal 1–3、Goal 5 组合 25/25 通过，Goal 4 独立 9/9 通过；敏感字串与 `eval`/`exec` 扫描无命中
  - [x] 真实用户路径已完成：干净 QGIS 从 ZIP 安装，配置真实模型，查询当前项目，生成并确认 700 米缓冲区计划，Processing 成功生成并加入 `气象站点_700米_测试2`（70 个要素），确认原始图层未被覆盖；重启 QGIS 后已复用已保存凭据，无需再次输入 Key

## v2.0 增量 Goal 状态（尚未实现）

- [ ] Goal 6：可信会话工作台与模型能力档案
  - [ ] 会话信息条、快捷任务、统一工具/计划/结果卡、本轮审计记录
  - [ ] 模型能力档案与真实模型行为模式；不伪造“思考强度”或原始思维链
  - [ ] 真实结果后的 QGIS 原生操作与状态回归
- [ ] Goal 7：数据诊断与安全重投影闭环
  - [ ] 项目诊断、CRS 一致性、图层质量、字段统计、表达式预览与选择集摘要
  - [ ] 从诊断建议到确认式 `reproject_layer` 的输出验证闭环
- [ ] Goal 8：空间关系预览、裁剪与筛选导出闭环
  - [ ] 空间关系预览及其只读/不改变选择集保证
  - [ ] 确认式 `clip_vector` 与 `export_filtered_features`
- [ ] Goal 9：高频矢量叠加分析、统一交付与回归
  - [ ] 确认式 `intersection` 与 `dissolve`
  - [ ] 文档、打包、敏感信息扫描、干净 QGIS 及各写入工具的真实 Desktop 验收

所有 v2.0 Goal 的准确范围、阶段验收、停止条件、风险与第一轮范围以 `开发短计划.md` 为准；产品目标和用户体验边界以 `产品需求文档.md` 为准。

## 阶段门

Goal 1 全部验收通过：QGIS 4.2.1 已加载插件，工具栏出现“打开 QGIS Copilot”，点击后 Dock 正常显示欢迎文案、设置、输入框、发送按钮和“准备就绪”状态。Goal 2 的模型连接已在真实 QGIS Desktop 的三条聊天请求中得到实际使用证据。Goal 3-1 与 Goal 3-2 均通过：截图记录同一 17 图层项目中，列表结果为 17 图层；`inspect_layer` 成功返回九段线的 EPSG:4326 与字段；`query_features` 成功返回气象站点前 5 条属性且 `has_more=True`，没有可见超时或错误。Goal 4 已通过：代码、QGIS 自带 Python Processing 回归与真实 Desktop 计划/取消/确认/失败验收均完成（Desktop 结论以哥哥确认记录）。Goal 5 已通过：代码、安全与打包回归通过；干净 QGIS 从 ZIP 安装、真实模型配置、项目查询、确认写入及重启后凭据复用的端到端路径已由哥哥实测成功。

## 已解除阻塞

- 真实 QGIS 窗口已可操作；重新启动后，插件被发现并按 profile 配置自动加载。
- 根目录仍有一个字面名为 `NUL` 的 0 字节调试残留；它不影响 Goal 1 验收，但需在后续用经验证的 Windows 定向清理方式处理。

## 当前不在范围

- 不修改已有 QGIS MCP 仓库；
- 不引入 Node.js、TypeScript、React、WebEngine、独立后端或强制 MCP；
- 不开放任意 PyQGIS 代码执行、自动执行模式、原地批量编辑、删除、自动保存或默认覆盖输出；
- 不在 v2.0 阶段提前实现栅格/DEM、制图布局、报告、云端同步或在线账户；
- 不创建或推送远程仓库；
- 不发布新版本 ZIP，直到 v2.0 Goal 的真实 Desktop 与干净安装验收完成。

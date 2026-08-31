# QGIS Copilot 技术事实与发现

## 文档用途

记录已经查实的事实、当前判断、风险和待验证事项。旧结论被纠正时，直接更新为当前正确内容，并保留必要的来源说明。

## 当前运行时基线

- 实际安装：QGIS 4.2.1-Belém do Pará，安装根目录 `D:\app\QGIS`；QGIS 自带 Python 3.12.13，Qt / PyQt 6.11.0；
- `D:\app\QGIS\bin\python-qgis.bat` 能导入 `qgis` 及 Qt Widgets；实际 profile 插件目录是 `C:\Users\czk\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins`；
- 插件目录的 `qgis_copilot` Junction 指向唯一权威源码 `D:\wenjian\Hermes\QGIS Copilot\qgis_copilot`，映射下存在 `metadata.txt`；
- QGIS bundled Python 组合测试在所有测试正文结束后可能发生 Windows native segmentation fault（exit 139）。它不能算绿色；本项目以独立 QGIS 进程的 exit 0 作为有效自动化证据。

## 已完成基线（Goal 1–6）

- Goal 1–5 的插件生命周期、OpenAI-compatible 网络线程、QGIS Authentication Manager 凭据、受限只读工具、`buffer_vector` 计划→确认→Processing→输出验证、ZIP 打包和安全日志均已有历史证据；API Key 不写入普通设置、日志、聊天记录、测试或 ZIP。
- Goal 6 已由哥哥在真实 QGIS Desktop 验收：会话信息条、快捷任务、工具详情、审计记录、`list_layers` / `inspect_layer` / `query_features` 和结果卡“打开属性表”均可用；属性表真实打开，未观察到数据、选择集或项目写入。
- 初始模型上下文保持轻量：只包含项目身份和受限图层发现信息。字段、来源、范围、选择集、属性和空间细节只经显式只读工具按需返回。

## Goal 7 实现与自动化证据（2026-08-30）

- 新增 `qgis_copilot/tools/diagnostics_tools.py`，并将工具注册保持在内部 `ToolRegistry`：`get_project_diagnostics`、`check_crs_consistency`、`validate_layer`、`get_layer_statistics`、`validate_expression`、`select_by_expression_preview` 和 `selection_summary` 均为 `READ_ONLY`，具备稳定 schema、参数上限与结构化 `ToolResult` 错误。
- 项目诊断返回未保存/未保存修改、失效图层、空图层、活动编辑、缺失 CRS 与 CRS 不一致风险；诊断不创建文件、不修改项目、图层、源数据或选择集。
- 图层验证区分矢量与栅格：矢量扫描最多 10,000 个要素，报告字段、空几何与无效几何；栅格返回有效性、CRS 和尺寸，并明确字段/空几何/无效几何不适用。字段统计只返回指定字段的空值数量、最多 20 个唯一值样本与有限数值统计；表达式与选择集返回最多 20 条属性样本，表达式预览使用 `QgsFeatureRequest(QgsExpression)`，不调用选择操作。
- 新增 `qgis_copilot/tools/processing_tools.py` 的 `reproject_layer` WRITE 计划工具。它要求有效矢量输入、明确且有效的目标 CRS、明确的新 `.gpkg` 路径和输出名；默认拒绝已有输出。计划阶段不会创建目录/文件、加图层、修改源图层或保存项目，且明确承诺不猜测目标 CRS。
- `tasks/processing.py` 新增 `ReprojectProcessingTask`，复用 QGIS `QgsProcessingAlgRunnerTask` / Task Manager。确认后运行 `native:reprojectlayer`，只有输出文件存在、可重新以 OGR 打开、图层有效且实际 CRS 等于计划目标 CRS 才加入项目；取消、失败或 CRS 验证失败不显示成功，失败/取消会尝试清理本次新路径的部分输出。
- Controller 已根据计划的真实工具名选择 Buffer 或 Reproject Task；写入计划继续在 UI 明确确认前先写入匹配 `tool_call_id` 的 plan-only tool result，避免下一回合产生孤立 function call。Goal 7 未添加裁剪、导出、相交、融合或任何原地编辑。
- `tests/test_goal7_diagnostics_reproject.py` 在 QGIS bundled runtime 独立进程中 4/4 exit 0：覆盖诊断/统计/表达式/选择集不变、栅格边界、重投影计划零副作用与非法 CRS/路径冲突拒绝、已确认重投影真实生成 GeoPackage、可重开、CRS 为 EPSG:3857、输出进项目且源图层要素数不变。
- 回归采用独立进程：Goal 4 安全 Processing 9/9 exit 0；Goal 5 安全/打包与 Goal 6 工作台 9/9 exit 0；Goal 3 只读协议 9/9 与真实 QGIS 证据 2/2 已单独通过。本轮尝试将多个套件放入同一 QGIS 进程时，在 Goal 4 启动处发生 native segmentation fault（139），因此没有将该组合运行称为绿色。

## Goal 7 未完成的 Desktop 证据

- 仍必须在真实 QGIS Desktop 使用一个已保存的、包含矢量/栅格图层的测试项目执行：项目诊断、字段统计、表达式预览（核对选择集不变）、明确目标 CRS 的重投影计划；分别记录取消、已有输出冲突拒绝、确认成功和 Processing 失败。
- 成功路径必须可见核对结果图层 CRS、要素数、输出路径与源图层不变。当前自动化不是 Desktop 用户路径的替代证据。

## 持续安全与范围边界

- 本轮不引入 Node.js、TypeScript、React、WebEngine、独立后端或 MCP；不修改 `references/QGIS-4.0-MCP-public/`。
- 不上传完整项目、完整属性表、数据源路径、API Key 或无界要素；不开放任意代码、自动执行、原地编辑、删除、自动保存或覆盖已有输出。
- 根目录仍有一个字面名为 `NUL` 的 0 字节 Windows 调试残留，未处理，避免误删任何其他路径。

## 会话历史体验修复（2026-08-30）

- 哥哥的真实 Desktop 测试确认：重投影计划的取消、确认成功和真实输出冲突拒绝均已通过；冲突拒绝截图显示 `reproject_layer` 因输出文件已存在而结构化失败，未进入 Processing。
- 修复计划按钮遗留禁用状态：每次新 WRITE 计划显示时重新启用“确认执行”和“取消计划”。
- 新增“新建会话”与本次 QGIS 运行内的会话切换下拉框。会话 1、会话 2 等各自保留消息、工具卡、审计记录、Agent 上下文和待确认计划；运行中禁止切换/新建以避免状态混淆。
- 会话历史仅保存在内存，不写入 QSettings、项目文件、日志或其他聊天持久化文件；关闭 QGIS 后随进程清除。
- QGIS bundled runtime 工作台回归 7/7 exit 0，新增覆盖新建会话清理、按钮重新启用、会话历史切换隔离。哥哥重新安装后已完成真实 Desktop 验收：会话 1/会话 2 可切换查看，关闭 QGIS 后历史清除。

## Goal 8 实现与自动化证据（2026-08-31）

- 新增 `tools/query_tools.py`，注册 `spatial_query_preview` 为 `READ_ONLY`；当前明确支持 `intersects`、`contains`、`within`、`nearby`。预览限制输入/关系图层各 10,000 要素、返回样本最多 20 条；要求有效且一致的 CRS，nearby 不接受地理 CRS，不调用选择 API。
- 扩展 `tools/processing_tools.py`：`clip_vector` 校验有效矢量输入、面掩膜、CRS、输出冲突并生成 `WRITE` 计划；`export_filtered_features` 仅接受计划阶段重新验证的表达式、选择集 ID 或空间预览 ID，空匹配、表达式失效和选择集变化拒绝执行。
- `tasks/processing.py` 新增共享 `VectorProcessingTask`：确认后使用 `native:clip`、`native:extractbyexpression` 或 `native:saveselectedfeatures`，验证输出可重开后才加入项目；失败/取消删除本次新输出，源图层与选择集不作为写入目标。
- `application/controller.py` 已把两类新 WRITE 工具接入统一计划确认与 Processing 分派；系统边界文案已覆盖裁剪和筛选导出。
- `tests/test_goal8_spatial_preview_export.py` 在 QGIS bundled runtime 独立进程 exit 0，3/3：相交预览匹配 2 个要素且项目/选择集不变；裁剪确认输出 2 个要素并可加入项目；表达式导出确认输出 2 个要素；输出冲突与空匹配被拒绝。
- Goal 8 旧能力隔离回归：Goal 4 9/9、Goal 6 7/7、Goal 7 4/4 exit 0。尚未把这些自动化证据当作真实 Desktop 验收。
- Goal 8 Desktop 证据（哥哥提供截图）：`spatial_query_preview` 对同一行政区图层返回 34 个相交关系和前 20 条样本，界面明确显示选择集、图层、项目和源文件未修改；`export_filtered_features` 先经 `validate_expression` 校验 `"省份" = '四川'`，确认后生成 `D:\Temp\qgis_copilot_filtered.gpkg` 并加入“四川气象站点”（35 个要素），审计记录显示源图层未覆盖。
- 同一组 Desktop 截图中的 `clip_vector` **未成功执行**：它在计划阶段以“裁剪要求输入图层 CRS 一致”被结构化拒绝，未出现确认按钮、输出文件或结果图层。这是有效的 CRS 风险拒绝证据，不是无重叠语义，也不是裁剪成功证据。Goal 8 仍需补一条 CRS 一致图层的裁剪成功路径，之后才可确认完整通过。
- 验收决定：哥哥已明确确认 Goal 8 通过。阶段状态以该最终验收决定为准；证据边界保持透明——当前会话留存的 Desktop 截图覆盖空间预览、CRS 不一致裁剪拒绝、筛选导出成功，未单独留存 CRS 一致的裁剪成功截图。

## Goal 9 实现与自动化证据（2026-08-31）

- `tools/processing_tools.py` 新增 `intersection` 与 `dissolve` 两个 `WRITE` 计划工具，均要求有效矢量图层、有效且一致的 CRS、新 `.gpkg` 输出路径和明确输出名称；计划阶段不创建文件、不添加图层、不修改源数据。
- `intersection` 支持明确输入/叠加字段保留列表；同名字段冲突必须使用明确的非空 `overlay_prefix`，默认前缀为 `overlay_`，不会静默覆盖字段语义。计划携带 `native:intersection` 与实际字段参数。
- `dissolve` 只接受明确的 `dissolve_field` 或 `dissolve_all=true` 二选一；不允许模型或插件猜测分类字段，计划携带 `native:dissolve` 参数。
- `tasks/processing.py` 的共享 `VectorProcessingTask` 已按真实工具选择 `native:intersection` / `native:dissolve`，确认后执行；输出文件存在且可由 OGR 重新打开为有效图层后才加入项目，失败/取消清理新输出。
- `tests/test_goal9_overlay_delivery.py` 在 QGIS bundled runtime 独立进程 exit 0，3/3：覆盖注册权限、计划零副作用、字段冲突、融合规则拒绝、相交成功可重开、融合按字段/全量成功、输出冲突和源图层不变。
- Goal 9 的代码、自动化、打包和 Desktop 验收已由哥哥确认通过；本轮实际验证了相交计划/确认执行/输出加入项目/源图层未覆盖，以及融合成功和取消路径。
- Controller 确认分派已补齐 `intersection` 与 `dissolve`，两者均进入共享 `VectorProcessingTask`；专项回归扩展为 4/4 exit 0。
- `<QGIS安装目录>/bin/python-qgis.bat -m compileall -q qgis_copilot tests scripts` exit 0；Goal 4/6/7/8 隔离回归分别为 9/9、7/7、4/4、3/3 exit 0。
- `scripts/package_plugin.py` 实际生成 `dist/qgis_copilot.zip`，38 个成员；ZIP 只有 `qgis_copilot/` 顶层目录，不含 tests、references、`__pycache__`、`.pyc`、`.key` 或 `.pem`。敏感模式扫描命中 5 处既有测试脱敏夹具，未发现实际凭据。
- 已启动独立临时 QGIS profile 并验证 QGIS 4.2.1 Desktop 可启动；哥哥随后完成新版 ZIP 安装、真实模型配置和相交/融合用户路径测试，并确认 Goal 9 通过。自动化、Desktop 和哥哥的最终验收决定分别记录，不互相冒充。
- 2026-08-31 认证故障复现：`qgis-auth.db` 文件存在但 `auth_configs` 表为空，而普通 QGIS 设置仍保存旧 `auth_config_id=o645z3u`；插件因此在聊天请求加载 API Key 时失败。`QgisCredentialStore.save_api_key` 已修复为：更新旧 ID 失败时创建新认证配置，并由调用方写回新 ID；不清除数据库、不影响其他凭据。新增回归覆盖该失效 ID 场景。
- 2026-08-31 Desktop 复现 `intersection` 计划崩溃：双输入计划的 `inputs` 使用 `input_layer_name/input_feature_count` 与 `overlay_layer_name/overlay_feature_count`，旧 `ChatDockWidget.show_execution_plan` 却硬编码读取单输入 `layer_name/feature_count`，触发 `KeyError: 'layer_name'`。现已按单/双输入兼容显示，并补充 UI 回归；Goal 6 隔离回归 8/8、Goal 9 隔离回归 4/4 exit 0。
- 组合运行两套 Qt 测试在全部正文通过后发生 native shutdown segmentation fault（139）；按既有项目规则不称为组合绿色，仅采用两个独立 exit 0 进程作为有效证据。

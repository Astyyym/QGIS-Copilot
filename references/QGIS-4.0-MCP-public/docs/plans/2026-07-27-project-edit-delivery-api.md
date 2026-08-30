# 工程、编辑与交付 API 扩展

**目标：** 为 QGIS 4.2 / Qt6 的 Astyyym QGIS MCP 增加工程理解、受控数据编辑和交付诊断能力，不实现制图表达。

**边界：** 所有 QGIS API 调用保留在插件进程与主线程；不新增布局/样式工具，不开放任意几何写入，不做跨 MCP 进程的持久编辑会话。写入 API 使用单次短事务：预检、可选备份、执行、提交或回滚、返回影响摘要。

### 任务 1：工程理解
- 文件：`astyyym_qgis_mcp/qgis_mcp_plugin.py`、`src/qgis_mcp/qgis_mcp_server.py`
- 新增：`inspect_project_state`、`get_layer_tree`、`inspect_layer`、`get_project_diagnostics`。
- 验证：Python AST/编译；启动 QGIS 后在测试工程确认项目、树、图层、诊断 JSON。

### 任务 2：只读编辑辅助
- 文件：同上。
- 新增：`query_features`、`get_layer_statistics`、`validate_expression`、`manage_selection`（仅读取/设置选择集，不写数据源）。
- 验证：表达式命中数、字段投影、统计结果、选择集计数与 QGIS UI 一致。

### 任务 3：受控字段编辑
- 文件：同上。
- 新增：`calculate_field`、`update_feature_attributes`、`delete_features`。
- 规则：必须先计算影响数；默认 `dry_run=True`；实际执行使用图层短事务、编辑命令、备份尝试、失败回滚；不提供任意几何重写。
- 验证：使用复制测试图层确认 dry-run 不改数据、提交后字段/要素数正确、失败时回滚。

### 任务 4：交付诊断
- 文件：同上。
- 新增：`validate_project_for_delivery`、`validate_processing_result`、`verify_output_file`、`get_operation_log`、`capture_project_state`。
- 验证：检查真实 QGZ、矢量/栅格输出、缺失路径与错误表达式的结构化失败结果。

### 任务 5：公开接口与文档
- 文件：`README.md`、`README.en.md`。
- 更新：MCP 工具包装器、工具表、工具数量与安全行为说明。
- 验证：包装器/handler 名称一一对应、README 无旧工具数、`git diff --check`（在正式 Git 工作树阶段）。

**暂停点：** 本轮只修改本地权威源码并做静态检查；不重启 QGIS、不部署插件、不发起 socket/MCP 调用。哥哥启动完整 QGIS 与 Astyyym QGIS MCP 服务后再进行真实测试。

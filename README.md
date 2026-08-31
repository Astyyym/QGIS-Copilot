# QGIS Copilot

QGIS Copilot 是运行在 QGIS 内的原生 Qt AI GIS 工作台。它用自然语言帮助你理解当前项目、检查数据问题、预览分析条件，并把高风险 GIS 操作拆成：

> **诊断/预览 → 计划 → 人工确认 → QGIS Processing → 输出验证 → 加入项目**

它不要求安装 Hermes、Node.js、uv、MCP 客户端或独立服务。

> **当前支持基线：** v0.3.0 已在 Windows / QGIS 4.2.1（Python 3.12.13，Qt/PyQt 6.11.0）完成 Goal 1–12 开发、独立 QGIS 自动化回归、ZIP 打包和真实 QGIS Desktop 用户路径验收。其他 QGIS 版本和操作系统尚未验证，不能视为兼容承诺。

## 当前已可用能力

- 读取当前项目、列出图层、检查字段与 CRS、查询指定图层前 N 条属性（严格限制 1–100 条）；
- 通过 OpenAI-compatible `/chat/completions` 接入用户自选模型；
- 显示模型工具调用状态和结果摘要；
- 为矢量图层生成以**米**为单位的缓冲区计划；仅在用户点击“确认执行”后，创建新的 `.gpkg` 结果并验证、添加回项目；
- 对已有输出文件默认拒绝覆盖；对地理 CRS 输入，先临时投影至米制 CRS 后再转回源 CRS；
- 通过统一计划—确认—Processing—验证闭环生成新的重投影、裁剪、筛选导出、相交和融合 GeoPackage；相交支持明确的字段保留/前缀规则，融合必须明确分类字段或全量融合；
- 只读检查栅格 provider、CRS、范围、尺寸、像元大小、波段、NoData 与有限统计；当前 Goal 10 代码已通过 QGIS bundled runtime，真实 Desktop 调用验收待完成；
- 栅格整理已增加确认式裁剪、重投影和分区统计：分别生成新的栅格或 GeoPackage 结果，不原地修改输入；Goal 12 已通过 QGIS bundled runtime 和哥哥在真实 QGIS Desktop 中的成功、取消及覆盖保护验收；
- 使用 QGIS Authentication Manager 安全保存 API Key，并支持重启 QGIS 后复用凭据。

## 当前工作台能力

当前工作台围绕以下真实工作链运行：

```text
看懂数据 → 发现问题 → 明确目标 → 形成方案 → 确认执行 → 验证结果 → 继续迭代
```

已完成的能力包括：

1. **会话透明度与工作台体验**：当前项目、模型、接口类型、模型行为模式、执行模式、快捷任务、工具卡、计划卡、审计记录和真实结果操作；
2. **数据检查与分析**：项目健康检查、CRS 一致性、图层质量、字段统计、表达式筛选预览、空间关系预览和选择集摘要；
3. **受控空间处理**：缓冲、重投影、裁剪、筛选导出、相交、融合统一纳入计划—确认—验证闭环。

### 模型行为模式

“思考强度”不会被做成无效装饰。QGIS Copilot 将使用模型能力档案：所有模型可使用“服务默认”；只有模型接口被确认支持时，才会开放并实际发送快速、平衡或深度等行为参数。不支持时会明确显示由模型服务控制，且不会显示模型原始思维链。

## 安装（ZIP）

1. 从交付物取得 `qgis_copilot.zip`；
2. 在 QGIS 中打开 **插件 → 管理并安装插件 → 从 ZIP 安装**；
3. 选择 ZIP 并安装，随后在插件管理器启用 **QGIS Copilot**；
4. 在菜单 **QGIS Copilot → 打开 QGIS Copilot**，或工具栏点击同名按钮；
5. 若刚安装后未显示，重启一次 QGIS 再检查插件管理器。

开发者打包：在仓库根目录使用 QGIS 自带 Python：

```text
<QGIS安装目录>/bin/python-qgis.bat scripts/package_plugin.py
```

输出为 `dist/qgis_copilot.zip`。ZIP 仅含一个顶层目录 `qgis_copilot/`，以及插件必需的 `metadata.txt`、`__init__.py` 和 `LICENSE`；不含测试、参考仓库、Git、缓存、数据库或密钥文件。

## 模型配置与隐私

打开聊天 Dock 的**设置**，填写：

- API 地址：完整的 `http://` 或 `https://` OpenAI-compatible 基础 URL，例如 `https://provider.example/v1`；
- 模型名；
- 超时：1–300 秒，默认 120 秒；
- API Key：首次保存必填；之后可留空以保留已有凭据。

API Key 通过 QGIS Authentication Manager 保存；普通 QSettings 只保存地址、模型名、超时与认证配置 ID。重开 Copilot 或 QGIS 后插件会复用该认证配置，**不会将既有 Key 回填到界面**。输入框默认掩码；“显示/隐藏”只作用于本次手动输入。

请自行选择并信任模型服务。发送聊天请求时，插件会将当前请求、必要的轻量项目摘要和按需工具结果发送至你配置的模型端点；不要对不可信服务发送敏感项目数据。插件不内置云端账号或对话同步。

## 权限与安全边界

- 当前 `get_project_state`、`list_layers`、`inspect_layer`、`query_features`、`inspect_raster`、`probe_raster_processing` 是只读工具，不应修改项目、图层、选择集或源数据；
- `buffer_vector`、`reproject_layer`、`clip_vector`、`export_filtered_features`、`intersection`、`dissolve`、`clip_raster_by_mask`、`reproject_raster`、`zonal_statistics` 是写入计划工具：计划阶段不创建目录/文件、不加图层、不改源数据；
- 写入必须在原生计划卡片中由用户明确确认；取消计划不会写入；
- 默认拒绝覆盖已有 `.gpkg` 输出；不会执行任意 PyQGIS 代码；
- 网络请求在 Qt 工作线程运行；QGIS 读取与 Processing 回到 QGIS 主线程；
- 日志只记录工具名、状态、耗时与经过脱敏/长度限制的摘要；Authorization、Bearer token、API Key、password 等敏感字段会被遮蔽。

## 已知限制

- 当前发行基线只支持 OpenAI-compatible HTTP 非流式聊天接口；
- 写入工具仅生成新的 GeoPackage，不原地编辑、不删除、不覆盖已有输出；相交要求 CRS 一致并对同名字段使用明确前缀，融合不允许默默猜测分类字段；
- 栅格整理要求栅格与面图层 CRS 一致；重投影必须明确目标 CRS 与重采样；分区统计生成新的面图层并复制统计字段，不直接改写原分区图层；
- 模型可能选择错误工具或生成无效参数；插件会安全失败，但请在确认执行前核对图层、距离、输出路径和 CRS 风险；
- 取消运行中的 Processing 后，插件不会显示成功；请检查输出目录是否留有残留文件；
- 目前只在 Windows + QGIS 4.2.1 验证，其他平台/版本需要独立测试。

## 开发与验证

请在仓库根目录使用 QGIS 自带 Python，而非系统 Python：

```text
<QGIS安装目录>/bin/python-qgis.bat -m compileall -q qgis_copilot tests scripts
QT_QPA_PLATFORM=offscreen <QGIS安装目录>/bin/python-qgis.bat -m unittest discover -s tests -v
<QGIS安装目录>/bin/python-qgis.bat scripts/package_plugin.py
```

版本与发布说明：

- [QGIS Copilot v0.2.0](release-notes-v0.2.0.md)：可信 GIS 工作台与 Goal 1–9 完整交付
- [QGIS Copilot v0.3.0](release-notes-v0.3.0.md)：栅格基础、DEM 分析、栅格整理与分区统计

> **后续兼容承诺：** Goal 1–9 和 v0.2.0 是 v3.0 的不可破坏基线。新能力按独立模块和逻辑任务单开代码文件、增量接入；未经单独批准不重写、重命名、搬迁或删除已验证实现。每个新 Goal 必须通过 Goal 1–9 固定回归和真实 QGIS Desktop 旧代表路径。

产品需求、架构、开发计划、当前阶段状态与技术证据分别见：

- `产品需求文档.md`
- `架构说明.md`
- `开发短计划.md`：v2.0 Goal 6-9 历史执行计划
- `开发短计划-v3.0.md`：当前功能扩展路线、Goal 10-14 与高风险能力边界
- `task_plan.md`
- `findings.md`

## 许可证

本项目采用 [GPL-3.0-only](LICENSE)。

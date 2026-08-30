# QGIS Copilot

QGIS Copilot 是运行在 QGIS 内的原生 Qt AI GIS 助手。它用自然语言读取当前项目，并把高风险 GIS 操作拆成**计划 → 人工确认 → Processing 执行 → 输出验证**；不要求安装 Hermes、Node.js、uv、MCP 客户端或独立服务。

> **当前 MVP：** 已在 Windows / QGIS 4.2.1（Python 3.12.13，Qt/PyQt 6.11.0）完成开发与自动化回归。其他 QGIS 版本和操作系统尚未验证，不能视为兼容承诺。

## 能做什么

- 读取当前项目、列出图层、检查字段与 CRS、查询指定图层前 N 条属性（严格限制 1–100 条）；
- 通过 OpenAI-compatible `/chat/completions` 接入用户自选模型；
- 展示模型工具调用的状态与结果摘要；
- 为矢量图层生成以**米**为单位的缓冲区计划；仅在用户点击“确认执行”后，创建新的 `.gpkg` 结果并验证、添加回项目；
- 对已有输出文件默认拒绝覆盖；对地理 CRS 输入，先临时投影至米制 CRS 后再转回源 CRS。

## 安装（ZIP）

1. 从交付物取得 `qgis_copilot.zip`；
2. 在 QGIS 中打开 **插件 → 管理并安装插件 → 从 ZIP 安装**；
3. 选择 ZIP 并安装，随后在插件管理器启用 **QGIS Copilot**；
4. 在菜单 **QGIS Copilot → 打开 QGIS Copilot**，或工具栏点击同名按钮；
5. 若刚安装后未显示，重启一次 QGIS 再检查插件管理器。

开发者打包：在仓库根目录使用 QGIS 自带 Python 运行：

```text
D:/app/QGIS/bin/python-qgis.bat scripts/package_plugin.py
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

- `get_project_state`、`list_layers`、`inspect_layer`、`query_features` 是只读工具，不应修改项目、图层或源数据；
- `buffer_vector` 是写入计划工具：计划阶段不创建目录/文件、不加图层、不改源数据；
- 写入必须在原生计划卡片中由用户明确确认；取消计划不会写入；
- 默认拒绝覆盖已有 `.gpkg` 输出；不会执行任意 PyQGIS 代码；
- 网络请求在 Qt 工作线程运行；QGIS 读取与 Processing 回到 QGIS 主线程；
- 日志只记录工具名、状态、耗时与经过脱敏/长度限制的摘要；Authorization、Bearer token、API Key、password 等敏感字段会被遮蔽。

## 已知限制

- 首发只支持 OpenAI-compatible HTTP 非流式聊天接口；
- MVP 只实现了一个受确认的写入工具：新的 GeoPackage 矢量缓冲区；
- 模型可能选择错误工具或生成无效参数；插件会安全失败，但请在确认执行前核对图层、距离、输出路径和 CRS 风险；
- 取消运行中的 Processing 后，插件不会显示成功；请检查输出目录是否留有残留文件；
- 目前只在 Windows + QGIS 4.2.1 验证，其他平台/版本需要独立测试。

## 开发与验证

权威源码目录：`D:\wenjian\Hermes\QGIS Copilot`。请使用 QGIS 自带 Python，而非系统 Python：

```text
D:/app/QGIS/bin/python-qgis.bat -m compileall -q qgis_copilot tests scripts
QT_QPA_PLATFORM=offscreen D:/app/QGIS/bin/python-qgis.bat -m unittest discover -s tests -v
D:/app/QGIS/bin/python-qgis.bat scripts/package_plugin.py
```

开发规则、产品边界和阶段证据分别见 `AGENTS.md`、`产品需求文档.md`、`开发短计划.md`、`task_plan.md` 与 `findings.md`。

## 许可证

本项目采用 [GPL-3.0-only](LICENSE)。

# QGIS Copilot v0.1.0

首个可安装的 MVP 版本：在 QGIS 内提供原生 Qt 聊天工作台，让用户用 OpenAI-compatible 模型读取当前项目，并以**计划 → 明确确认 → QGIS Processing → 输出验证**的方式安全创建新的矢量缓冲区结果。

## 已包含

- QGIS 原生 Dock 聊天界面：发送、停止、重试、模型设置；
- OpenAI-compatible `/chat/completions` 模型连接；API Key 使用 QGIS Authentication Manager 保存，不回显到设置界面；
- 当前项目的受限只读能力：项目状态、图层列表、图层字段/CRS/范围、前 N 条属性（1–100 条）；
- 有界工具调用循环、网络超时、取消与真实错误反馈；
- 受确认的 `buffer_vector`：新 GeoPackage 输出、默认拒绝覆盖、地理坐标图层按米处理、输出重新打开验证并添加回项目；
- ZIP 安装包和 Windows + QGIS 4.2.1 的真实用户路径验证。

## 安装

1. 下载本页的 `qgis_copilot.zip`；
2. QGIS → **插件 → 管理并安装插件 → 从 ZIP 安装**；
3. 启用 **QGIS Copilot**；
4. 在 **QGIS Copilot → 打开 QGIS Copilot** 中打开工作台；
5. 在设置中填写你自己的 OpenAI-compatible API 地址、模型名和 API Key。

完整安装、隐私、权限和已知限制见仓库 [README](https://github.com/Astyyym/QGIS-Copilot#readme)。

## 安全与限制

- 只读工具不会修改项目、图层或源数据；
- 写入只会在用户明确确认后进行，并优先创建新 `.gpkg`，不会默认覆盖已有文件；
- 本版本只在 **Windows + QGIS 4.2.1** 验证；
- 当前只支持 OpenAI-compatible **非流式**聊天接口，且受确认的写入工具仅为矢量缓冲区；
- 当前不包含任意 PyQGIS 代码执行、自动执行、MCP 依赖、栅格/DEM 分析或批量原地编辑。

## 验证摘要

- QGIS 自带 Python：Goal 1–3 测试 21/21 通过；Goal 4 Processing 测试 9/9 通过（分开运行，避免 QGIS 原生退出阶段的不稳定性）；
- 重新打包后 ZIP 共 33 个成员、大小 32,511 bytes；结构与敏感信息扫描通过。

## 下一步

仓库已包含已确认但**尚未发布**的 v2.0 路线：可信会话工作台、模型能力档案、项目诊断、CRS/质量/统计检查，以及重投影、裁剪、筛选导出、相交和融合等确认式空间处理。具体范围和阶段验收见 `产品需求文档.md` 与 `开发短计划.md`。

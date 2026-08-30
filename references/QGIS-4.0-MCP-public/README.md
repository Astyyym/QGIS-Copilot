<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/Lang-English-blue?style=for-the-badge" alt="English"></a>
</p>

# QGIS 4 MCP 插件

<p align="center">
  <img src="https://img.shields.io/badge/QGIS-4.x-589632?style=flat-square&logo=qgis" alt="QGIS 4.x">
  <img src="https://img.shields.io/badge/Python-≥3.12-3776AB?style=flat-square&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-GPL--2.0-blue?style=flat-square" alt="License GPL-2.0">
  <img src="https://img.shields.io/badge/MCP-1.3.0+-purple?style=flat-square" alt="MCP 1.3.0+">
</p>

**QGIS 4 MCP 插件** 通过 [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) 将 AI 助手（Claude、Cursor、Codex 等）与 QGIS 4.x 连接起来。它将 PyQGIS 的核心能力封装为 MCP 工具，让你可以用自然语言驱动 GIS 工作流。

本项目是 [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp)（⭐984）的 **QGIS 4.x 兼容分支**。上游项目只支持 QGIS 3.x，灵感来源于 [BlenderMCP](https://github.com/ahujasid/blender-mcp)。

---

## 架构

```
┌─────────────────────┐     stdio (MCP)      ┌─────────────────────┐
│   AI 客户端          │ ◄─────────────────► │   MCP Server         │
│   (Claude/Cursor/   │     JSON-RPC 2.0     │   (Python / FastMCP) │
│    Codex 等)         │                      │   src/qgis_mcp/      │
└─────────────────────┘                      └─────────┬───────────┘
                                                        │ TCP Socket
                                                        │ port 9877
                                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     QGIS (4.x)                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Astyyym QGIS MCP 插件 (astyyym_qgis_mcp/)                         │  │
│  │  ┌─────────────────┐    ┌──────────────────────────────┐  │  │
│  │  │ 控制面板         │    │ 命令分发器                    │  │  │
│  │  │ (启动/停止)      │───►│ → 51 个工具处理器             │  │  │
│  │  └─────────────────┘    │ → JSON-RPC over TCP           │  │  │
│  │                         └──────────────┬───────────────┘  │  │
│  │                                        ▼                  │  │
│  │                         ┌──────────────────────────────┐  │  │
│  │                         │  PyQGIS API                   │  │  │
│  │                         │  (QgsProject, QgsVectorLayer, │  │  │
│  │                         │   processing, 地图画布...)    │  │  │
│  │                         └──────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 工作流程

1. **Astyyym QGIS MCP 插件** 在 QGIS 内部开启一个 TCP Socket 服务（默认端口 **9877**），监听 JSON-RPC 命令。
2. **MCP Server**（独立的 Python 进程）通过 TCP 连接到 QGIS，通过 `FastMCP` 将每个命令暴露为 MCP 工具。
3. **AI 客户端**（Claude Desktop、Cursor 等）通过 stdio 使用标准 MCP 协议与 MCP Server 通信，自动发现并调用工具。

---

## 与上游的区别

本分支为兼容 QGIS 4.x 做了以下改动（同时保持与 QGIS 3.x 的向后兼容）：

| 改动项 | 说明 |
|--------|------|
| **QGIS 版本检测** | 添加 `_qgis_major_version()` 工具函数，运行时自动检测 QGIS 版本是 3 还是 4 |
| **图层类型检测** | QGIS 4.x 使用 `Qgis.LayerType.Vector`/`Raster`，3.x 使用 `QgsMapLayer.VectorLayer`/`RasterLayer` |
| **几何类型辅助** | `_geometry_type_str()` 和 `_geometry_type_str_from_layer()` 处理 QGIS 4 的枚举类型变化 |
| **消息级别辅助** | `_msg_level()` 统一 `Qgis.MessageLevel`（QGIS 4）与 `Qgis` 属性（QGIS 3）的差异 |
| **插件元数据** | `metadata.txt` 添加 `qgisMaximumVersion=4.99`，允许在 QGIS 4.x 中安装 |
| **Python 版本** | `pyproject.toml` 要求 `>=3.12`，匹配 QGIS 4 的 Python 版本 |
| **Canvas API** | `zoom_to_layer` 改用 `canvas.setExtent()` + `canvas.refresh()`，因为 `zoomToActiveLayer()` 在 QGIS 4 已移除 |
| **Processing 上下文** | `execute_processing` 增加 `QgsProcessingContext` 和 `QgsProcessingFeedback` |
| **属性安全序列化** | `get_layer_features` 处理 QVariant/NULL 值的 JSON 安全序列化 |
| **图层树安全** | `get_layers` 增加 null-safe 树查找和分组路径信息 |

以上改动均依据 [QGIS 4.0 官方 PyQGIS 文档](https://qgis.org/pyqgis/4.0/) 验证，并在 QGIS 4.0.0-Norrköping 上实测通过。

---

## 环境要求

- **[QGIS 4.x](https://qgis.org/)**（Windows 桌面版，实测 4.0.0-Norrköping）
- **[Hermes Agent](https://hermes-agent.nousresearch.com/)**（WSL 侧，作为 MCP 客户端）
- **[uv](https://docs.astral.sh/uv/)**（Python 包管理器，MCP Bridge 依赖）
- **WSL2**（QGIS 跑在 Windows，Hermes 跑在 WSL，两者通过 TCP 通信）

---

## 安装

### 1. 安装 QGIS 插件

将 `astyyym_qgis_mcp/` 复制到 QGIS 插件目录：

```bash
# Windows via WSL — replace `<WindowsUser>` with your Windows account name
cp -r astyyym_qgis_mcp /mnt/c/Users/<WindowsUser>/AppData/Roaming/QGIS/QGIS4/profiles/default/python/plugins/
```

然后在 QGIS 中：**插件 → 管理并安装插件** → 找到 **Astyyym QGIS MCP** → 勾选启用。工具栏会出现 Astyyym QGIS MCP 图标。

> **修改插件代码后**，必须完整退出 QGIS 再重新打开（`Stop Server` → `Start Server` 不会重新加载 Python 类定义）。

### 2. 配置 Hermes MCP Bridge

WSL 侧 clone 本仓库，`uv sync` 安装依赖：

```bash
cd /path/to/qgis-4.0-mcp-public
uv sync
```

然后在 `~/.hermes/config.yaml` 的 `mcp_servers` 下添加：

```yaml
mcp_servers:
  qgis:
    command: uv
    args:
      - --directory
      - /path/to/qgis-4.0-mcp-public
      - run
      - python
      - -m
      - qgis_mcp.qgis_mcp_server
    env:
      PYTHONPATH: src
      QGIS_MCP_HOST: 127.0.0.1
      QGIS_MCP_PORT: "9877"
    timeout: 120
    connect_timeout: 30
```

> Bridge 代码修改后删 `__pycache__`，然后重启 Hermes 加载新代码。

---

## 使用

### 启动顺序（必须严格遵守）

1. **QGIS** → 点击工具栏 Astyyym QGIS MCP 图标 → **Start Server**（确认状态 *"Server: Running on port 9877"*）
2. **Hermes** → 启动 Hermes Desktop（或 `hermes` 命令）
3. Hermes 启动时自动发现 MCP 工具，之后在 TUI 中直接用自然语言操作

> ⚠️ **QGIS Server 必须先于 Hermes 启动。** 如果顺序反了，Bridge 重试耗尽后不会自动恢复，只能重启 Hermes。

### 实际使用示例

在 Hermes TUI 中直接说：

> "加载 D:/项目/规划方案.qgz，告诉我有哪些图层"

> "把广东省界裁剪人口数据，输出到 D:/项目/广东人口.gpkg"

> "对 DEM 做坡度分析，结果存到 D:/项目/slope.tif"

> "甲方给的 CAD 地形图转成 GPKG"

所有操作结果自动加入 QGIS 图层面板，输出路径用 `D:/...` 格式（不要用 `/mnt/d/...`，QGIS 不识别）。

---

## 可用工具

### 基础功能

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `ping` | 连通性测试 | 无 |
| `get_qgis_info` | 获取 QGIS 版本信息 | 无 |
| `load_project` | 加载 QGS/QGZ 项目 | `path` |
| `create_new_project` | 新建项目并保存 | `path` |
| `get_project_info` | 获取当前项目信息 | 无 |
| `add_vector_layer` | 添加矢量图层 | `path`, `name?`, `provider?` |
| `add_raster_layer` | 添加栅格图层 | `path`, `name?`, `provider?` |
| `get_layers` | 列出所有图层 | 无 |
| `remove_layer` | 按 ID 删除图层 | `layer_id` |
| `zoom_to_layer` | 缩放到图层范围 | `layer_id` |
| `get_layer_features` | 查询图层要素 | `layer_id`, `limit?` |
| `execute_processing` | 执行 Processing 算法 | `algorithm`, `parameters` |
| `execute_code` | 执行任意 PyQGIS 代码 | `code` |
| `save_project` | 保存项目 | `path?` |
| `render_map` | 渲染地图为图片 | `path`, `width?`, `height?` |

### 自定义扩展

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `get_fields` | 获取矢量图层字段名和类型 | `layer_id` |
| `reorder_layers` | 重排图层顺序（首项最上层） | `layer_ids: [有序ID列表]` |
| `rename_layer` | 重命名图层 | `layer_id`, `name` |
| `export_layer` | 导出图层到文件 | `layer_id`, `output_path` |
| `zoom_to_feature` | 缩放到满足表达式的要素 | `layer_id`, `expression` |
| `create_buffer` | 创建缓冲区（自动CRS转换） | `layer_id`, `distance(米)`, `output_path`, `dissolve?` |
| `add_field` | 添加字段并赋值（表达式/排序） | `layer_id`, `field_name`, `field_type`, `expression?`, `rank_by?` |
| `delete_fields` | 批量删除字段 | `layer_id`, `field_names: [列表]` |
| `reorder_fields` | 安全重排序字段（创建新文件，不动原始数据） | `layer_id`, `field_order: [有序名称列表]`, `output_path?` |

### 工程理解、受控编辑与交付诊断

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `inspect_project_state` | 返回工程、图层树、工程变量、布局列表和未保存状态 | 无 |
| `get_layer_tree` | 返回真实分组、层级、顺序与可见性 | 无 |
| `inspect_layer` | 检查数据源、CRS、范围、字段、选择集和编辑状态 | `layer_id` |
| `get_project_diagnostics` | 汇总失效图层、空矢量图层、活动编辑和 CRS 风险 | 无 |
| `query_features` | 按表达式或当前选择集读取属性，不写源数据 | `layer_id`, `expression?`, `fields?`, `limit?`, `selected_only?` |
| `get_layer_statistics` | 计算空值、唯一值和数值统计 | `layer_id`, `fields?`, `expression?` |
| `validate_expression` | 校验 QGIS 表达式并返回预计命中数 | `layer_id`, `expression` |
| `manage_selection` | 获取或修改 QGIS 内存选择集，不写数据源 | `layer_id`, `operation?`, `expression?`, `feature_ids?` |
| `calculate_field` | 预览或计算已有字段；默认仅 dry run | `layer_id`, `field_name`, `expression`, `filter_expression?`, `dry_run?` |
| `update_feature_attributes` | 预览或批量更新属性，不支持几何改写；默认仅 dry run | `layer_id`, `changes`, `expression?`, `feature_ids?`, `dry_run?` |
| `delete_features` | 预览或删除明确匹配的要素；默认仅 dry run | `layer_id`, `expression?`, `feature_ids?`, `dry_run?` |
| `validate_project_for_delivery` | 交付前检查工程路径、未保存改动、失效源、编辑状态和 CRS | 无 |
| `validate_processing_result` | 校验图层或输出文件的类型、CRS、要素数预期 | `layer_id?`, `output_path?`, `expectations?` |
| `verify_output_file` | 检查输出存在且可被 QGIS 重开 | `path`, `expected_type?` |
| `get_operation_log` | 返回本次插件实例已处理操作的审计记录 | `limit?` |
| `capture_project_state` | 生成带时间戳的工程与诊断快照 | 无 |

> 写入型工具默认 `dry_run=true`，只返回将受影响的要素数。实际写入必须显式传入 `dry_run=false`；属性更新与删除还必须提供 `expression` 或 `feature_ids`，避免无筛选批量修改。

### 数据质检与叠合分析

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `validate_layer` | 图层数据体检：CRS、字段、空几何、无效几何、栅格元数据 | `layer_id`, `check_geometry?`, `sample_invalid?` |
| `check_crs_consistency` | 检查工程或指定图层 CRS 是否一致 | `layer_ids?` |
| `reproject_layer` | 矢量图层重投影并自动加入工程 | `layer_id`, `target_crs`, `output_path` |
| `clip_vector` | 矢量裁剪 | `input_layer_id`, `overlay_layer_id`, `output_path` |
| `intersection` | 矢量相交叠加 | `input_layer_id`, `overlay_layer_id`, `output_path`, `input_fields?`, `overlay_fields?` |
| `difference` | 矢量差集/擦除 | `input_layer_id`, `overlay_layer_id`, `output_path` |
| `join_attributes_by_location` | 按空间关系连接属性 | `input_layer_id`, `join_layer_id`, `output_path`, `predicate?`, `join_fields?` |
| `calculate_area_fields` | 计算面积字段（平方米/公顷，原地更新前自动备份） | `layer_id`, `area_field?`, `hectare_field?`, `precision?` |
| `summarize_area_by_zone` | 按字段汇总面积和占比 | `layer_id`, `group_field`, `area_field?` |
| `select_by_expression` | 按 QGIS 表达式选择要素 | `layer_id`, `expression`, `method?` |
| `export_selected_features` | 导出当前选择集 | `layer_id`, `output_path` |

### 栅格与DEM分析

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `clip_raster_by_mask` | 用矢量掩膜裁剪栅格 | `raster_layer_id`, `mask_layer_id`, `output_path`, `crop_to_cutline?`, `alpha_band?` |
| `zonal_statistics` | 分区统计栅格值到面图层 | `raster_layer_id`, `zone_layer_id`, `output_path`, `prefix?`, `statistics?` |
| `slope` | 从 DEM 计算坡度（度） | `raster_layer_id`, `output_path` |
| `aspect` | 从 DEM 计算坡向 | `raster_layer_id`, `output_path` |
| `contour` | 从 DEM 生成等高线 | `raster_layer_id`, `output_path`, `interval?` |
| `cut_fill` | 填挖方计算（DEM − 设计面） | `dem_layer_id`, `design_surface_layer_id`, `output_path` |

### 数据转换与插值

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `cad_to_gpkg` | CAD（DXF/DWG）转 GeoPackage | `cad_path`, `output_path` |
| `create_grid` | 创建矩形渔网（fishnet） | `output_path`, `extent_layer_id`, `spacing?` |
| `idw_interpolation` | IDW 反距离加权插值（点→栅格） | `point_layer_id`, `value_field`, `output_path`, `pixel_size?` |

---

## 安全说明

> **此插件允许任意 PyQGIS 代码通过 TCP socket 远程执行。** 服务绑定 `0.0.0.0:9877`（默认端口），局域网内任何能连到该端口的主机都可以发送命令。

- **不要暴露到公网。** 9877 端口不做鉴权，也没有加密。
- **建议使用场景：** AI agent（Hermes/Claude）在本地或 WSL 中通过 `172.x.x.x` 内网 IP 连接，不跨机器开放。
- **`execute_code` 命令是双刃剑：** 它可以做任何事情——包括读写文件、删除图层、多次提交编辑。只在可信环境中使用。
- **端口可在插件 UI 中更改**（默认 9877），当前连接的 WSL IP 可用 `ipconfig` 查看。

## 致谢

- **上游项目：** [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp)（⭐984）
- **灵感来源：** [BlenderMCP](https://github.com/ahujasid/blender-mcp) by Siddharth Ahuja
- **协议：** [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- **QGIS 4 兼容参考：** [evenzur/qgis_3and4_MCP_Plugin](https://github.com/evenzur/qgis_3and4_MCP_Plugin)

## 许可证

[GPL-2.0](LICENSE)

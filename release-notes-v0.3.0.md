# QGIS Copilot v0.3.0

栅格与 DEM 能力增量版本，完成 Goal 10–12，并保持 Goal 1–9 兼容基线。

## 新增能力

- 栅格只读诊断：provider、CRS、范围、尺寸、像元大小、波段、NoData 和有限统计；
- Processing provider 与算法运行时探测；
- DEM 坡度分析，支持地理 CRS 的临时米制重投影；
- 栅格按面掩膜裁剪，生成新的 `.tif/.tiff`；
- 栅格重投影，明确目标 CRS、重采样方法和可选分辨率；
- 栅格分区统计，生成新的 GeoPackage 面图层，不原地修改分区图层。

## 安全边界

- 所有新增写入能力都遵循计划、人工确认、Processing、输出验证和加入项目闭环；
- 计划阶段拒绝已有输出，不覆盖文件；
- CRS、波段、统计项、字段前缀和掩膜类型不满足要求时结构化拒绝；
- 不开放自由栅格计算器表达式、删除、原地批量编辑、自动执行或任意代码。

## 验证

- Goal 12 专项：4/4；
- Goal 10：5/5；Goal 11：4/4；
- 受影响回归：Goal 4 9/9、Goal 6 8/8、Goal 7 4/4、Goal 8 3/3、Goal 9 4/4；
- QGIS bundled Python `compileall` 通过；
- 真实 QGIS Desktop 已验收正常栅格裁剪、正常分区统计、重投影取消和已有输出文件拒绝覆盖路径。

## 安装

下载本 Release 的 `qgis_copilot.zip`，在 QGIS 中使用“插件 → 管理并安装插件 → 从 ZIP 安装”。

当前验证环境为 Windows + QGIS 4.2.1；其他版本和平台需要独立测试。
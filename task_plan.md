# QGIS Copilot 任务状态

## 当前阶段

- 阶段：Goal 1——建立可加载的 QGIS 插件与聊天工作台
- 状态：架构已确定，等待执行 Goal 1
- 负责人：哥哥与小鱼共同确认

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

- [ ] Goal 1：建立可加载的 QGIS 插件与聊天工作台
- [ ] Goal 2：接入模型并建立 Agent 基础循环
- [ ] Goal 3：接入只读 QGIS 上下文和工具
- [ ] Goal 4：完成安全的 GIS 执行闭环
- [ ] Goal 5：完成安全、测试、打包和真实用户路径验收

## 阶段门

架构方向已经确定。严格按 `开发短计划.md` 的 Goal 1 → Goal 5 顺序执行。每个 Goal 验收通过后再进入下一个。

## 当前不在范围

- 不修改已有 QGIS MCP 仓库；
- 不开始编写产品代码；
- 不安装外部依赖；
- 不创建或推送远程仓库；
- 不发布 QGIS 插件。

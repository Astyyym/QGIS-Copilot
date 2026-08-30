# QGIS Copilot 任务状态

## 当前阶段

- 阶段：阶段 0——产品与环境基线
- 状态：架构已确定，等待进入插件骨架实现
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

## 实现阶段需要验证

- [ ] 首发支持的 QGIS 版本范围
- [ ] 首发支持的操作系统范围
- [ ] 目标 QGIS 版本中的插件加载和 Qt Widgets 行为
- [ ] OpenAI-compatible API 的工具调用和流式响应
- [ ] QGIS 主线程与网络任务调度
- [ ] 首批正式工具清单
- [ ] 许可证
- [ ] 任意 PyQGIS 代码执行的高级模式边界
- [ ] 备份、撤销和回滚范围

## 阶段门

架构方向已经确定。阶段 0 完成 QGIS 运行环境、插件骨架和技术约束验证后，进入阶段 1 的聊天壳实现。

## 当前不在范围

- 不修改已有 QGIS MCP 仓库；
- 不开始编写产品代码；
- 不安装外部依赖；
- 不创建或推送远程仓库；
- 不发布 QGIS 插件。

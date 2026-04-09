# DeerFlow Harness MCP 接入、Skills 装载与扩展机制

> 目标：说明 DeerFlow 当前实现里，MCP、skills 和反射式扩展是如何共同构成“可插拔能力面”的，以及这些能力为什么没有直接耦合进核心 agent 代码。
>
> 代码范围：以 `backend/packages/harness/deerflow/mcp/`、`skills/`、`reflection/` 和 `config/` 为主。

补充专题：

- `../04-工具系统/01-工具加载、内置工具与Deferred Tool Search.md`：工具系统主链路
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：prompt 装配和 runtime 条件注入

---

## 1. 扩展不是单一机制

DeerFlow 当前至少有三种扩展面：

1. 反射式 Python 扩展
2. MCP server 扩展
3. Skills 文本能力扩展

它们的定位不同：

- 反射式扩展：把配置字符串解析成真实代码对象
- MCP：把外部能力系统接入成工具
- Skills：把工作流知识和领域约束注入到 prompt

因此“扩展”在 DeerFlow 里并不等于“新增一个工具”。

---

## 2. 反射层是最基础的扩展底座

`deerflow/reflection/resolvers.py` 提供了：

- `resolve_variable("pkg.module:name")`
- `resolve_class("pkg.module:Class")`

许多模块都依赖这层机制，包括：

- 普通工具加载
- guardrail provider 加载
- sandbox provider 配置
- 其他 provider 或实现类的动态绑定

这层机制的价值在于：

- harness 内核不需要 import 所有可选实现
- 外部实现可以只通过配置接入

所以反射层是 DeerFlow 实现“配置驱动可插拔”的真正基础设施。

---

## 3. MCP 接入的基本流程

MCP 工具主入口在 `deerflow/mcp/tools.py::get_mcp_tools()`。

它的加载流程大致是：

1. 读取最新 `ExtensionsConfig`
2. 根据配置构造 server config
3. 准备 OAuth 初始头
4. 构造 `MultiServerMCPClient`
5. 从所有启用的 server 拉取工具
6. 对 async-only 工具补 sync wrapper
7. 返回标准 `BaseTool` 列表

这条链路说明 DeerFlow 把 MCP 当作“外部工具总线”，而不是某个单点插件。

---

## 4. 为什么要补同步 wrapper

MCP server 返回的工具可能只有异步接口。

但 DeerFlow 某些调用面，例如 client 侧同步流式消费，仍然需要同步可调用函数。

因此 `_make_sync_tool_wrapper(...)` 会：

- 检测当前是否已有运行中的 event loop
- 必要时把 coroutine 投递到全局线程池中执行
- 避免嵌套 event loop 问题

这一步的意义很实际：

- 让 MCP 工具最终都收敛成 DeerFlow 可统一调用的工具形态
- 上层不必为不同 MCP tool 的同步/异步差异写分支逻辑

---

## 5. 为什么 MCP 配置总是重新读磁盘

无论 `get_available_tools()` 还是 `get_mcp_tools()`，都刻意使用：

- `ExtensionsConfig.from_file()`

而不是依赖某个常驻内存对象。

原因在于当前部署模型里：

- Gateway API 进程和 LangGraph server/worker 进程可能不是同一个进程
- 配置更新可能由另一个进程写回磁盘

因此 DeerFlow 为了保证配置变更能及时生效，优先选择：

- 读取最新磁盘配置

而不是只信任进程内缓存。

这属于典型的多进程集成场景补偿策略。

---

## 6. Skills 不是工具，而是 Prompt 资源

`deerflow/skills/loader.py::load_skills(...)` 会扫描：

- `skills/public`
- `skills/custom`

发现 `SKILL.md` 并解析成结构化 `Skill` 对象。

这些 skills 的主用途不是自动注册成工具，而是：

- 作为 prompt 注入素材
- 为模型提供领域工作流、规范和专用说明

所以 DeerFlow 的 skill 更接近“能力文档模块”，而不是 LangChain Tool。

---

## 7. Skills 装载为什么分 public / custom

当前 loader 明确扫描两个分类目录：

- `public`
- `custom`

这表示 DeerFlow 从设计上就区分：

- 平台自带、可共享的技能
- 项目或用户侧自定义技能

并且最终是否启用，并不是靠文件是否存在，而是要再结合 `ExtensionsConfig` 中的 enabled 状态。

这带来两个好处：

1. 技能文件可以长期存在，但按需启停
2. 平台能力和业务定制能力可以共用同一套装载机制

---

## 8. Skills 为什么适合通过 Prompt 暴露

很多 skill 内容本质上是：

- 某个领域流程说明
- 某类工具的使用规范
- 某种任务的处理步骤

这类信息如果做成工具，往往并不合适，因为它不是“调用一下得到结果”，而是“指导模型如何组织工作”。

因此 DeerFlow 把它们放进 prompt section，而不是强行工具化，是合理的职责划分。

可以粗略理解为：

- Tool：执行能力
- Skill：策略知识

---

## 9. MCP 与 Skills 的关系

这两者都属于扩展能力，但作用面不同。

### 9.1 MCP

解决“系统可以调用哪些外部能力”。

### 9.2 Skills

解决“模型该如何使用这些能力，或按什么流程处理任务”。

因此一个常见组合是：

- 用 MCP 提供外部系统接口
- 用 Skill 教模型什么时候该调用它、按什么步骤调用它

这也是 DeerFlow 扩展体系比较完整的地方：

- 不只扩动作
- 也扩方法

---

## 10. 扩展配置为什么归到 `ExtensionsConfig`

从代码看，skills 和 MCP 的启停都倾向于通过 `ExtensionsConfig` 管理。

这样做的好处是：

- 把“是否启用某种可选扩展”从主配置里拆出来
- 更适合 Gateway 提供扩展开关管理接口
- 避免核心 `AppConfig` 过度膨胀

所以 `ExtensionsConfig` 更像一层扩展控制平面，而不是普通静态配置对象。

---

## 11. 当前扩展体系的设计原则

结合实现，可以把 DeerFlow 的扩展机制总结成 4 条原则。

### 11.1 核心运行时保持瘦身

具体能力尽量通过配置、反射和扩展模块接入，不强行耦合进 lead agent 内部。

### 11.2 工具扩展与知识扩展分离

MCP 解决工具接入，skills 解决方法论注入。

### 11.3 多进程场景优先以磁盘配置为准

这是当前 Gateway 与 worker 进程解耦下的现实选择。

### 11.4 扩展最终都要收敛成运行时可消费形态

例如：

- MCP 最终变成 `BaseTool`
- Skill 最终变成 prompt section

这使得上层 agent 装配保持统一。

---

## 12. 总结

DeerFlow 当前的扩展体系不是“在核心里加更多 if/else”，而是：

> 用反射层加载代码扩展，用 MCP 接入外部执行能力，用 skills 注入工作流知识，再由 agent 装配层把它们统一编译进一次具体运行。

如果只记一个核心判断，应该是：

- DeerFlow 的可扩展性不只在工具层
- 它同时扩展执行能力、配置控制面和 prompt 知识面

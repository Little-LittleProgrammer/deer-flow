# DeerFlow Harness 工具加载、内置工具与 Deferred Tool Search

> 目标：说明 DeerFlow 当前实现中，工具集合是如何从配置、内置能力、MCP 和 ACP 多路汇总出来的，以及大规模工具场景下为什么要引入 Deferred Tool Search。
>
> 代码范围：以 `backend/packages/harness/deerflow/tools/` 为主，必要时补充 `mcp/`、`sandbox/` 与 `config/`。

补充专题：

- `../02-安全与沙箱/01-Bash安全措施与执行链.md`：`bash` 和文件工具的安全边界
- `../07-MCP与扩展/01-MCP接入、Skills装载与扩展机制.md`：MCP 与 skills 的扩展机制

---

## 1. 工具系统不是单一注册表

DeerFlow 的工具入口在 `deerflow/tools/tools.py::get_available_tools(...)`。

它不是从一个全局 registry 里一次性取全量工具，而是按来源拼接：

1. `config.yaml` 声明的普通工具
2. harness built-in 工具
3. MCP 工具
4. ACP agent 工具
5. 运行时条件工具，例如 `task`、`view_image`

最终返回给 `create_agent(...)` 的，是这一批工具的合并结果。

---

## 2. 普通工具：配置 + 反射加载

普通工具来自 `config.tools`。

每个工具配置最关键的是：

- `group`
- `use`

其中 `use` 通过 `resolve_variable(...)` 解析成真实 Python 对象，例如某个 `BaseTool` 实例。

这带来两个直接效果：

- harness 核心层不需要硬编码所有业务工具
- 新工具接入主要靠配置，而不是改核心装配逻辑

因此 DeerFlow 的工具系统是“配置驱动 + 反射装配”的，而不是“注册器手工挂载”的。

---

## 3. Built-in 工具：框架治理能力

当前 `BUILTIN_TOOLS` 默认包括：

- `present_file_tool`
- `ask_clarification_tool`

运行时按条件还会追加：

- `task_tool`
- `view_image_tool`
- `tool_search`

这些 built-in 工具和业务工具的区别很明显：

- 业务工具解决外部任务
- built-in 工具解决 agent runtime 自身治理

例如：

- `present_file`：把线程产物以受控方式暴露给前端
- `ask_clarification`：把“中断并向用户提问”变成显式控制流
- `task`：把子代理委派变成标准工具调用
- `view_image`：在 vision 模型场景下把图像内容显式注入状态

所以 built-in 工具更像 runtime primitive，而不是普通扩展插件。

---

## 4. Host Bash 为什么会在工具层被剔除

`get_available_tools()` 在真正返回工具前，会调用 `is_host_bash_allowed(config)`。

如果当前不允许宿主机 `bash`：

- `group == "bash"` 的工具会被移除
- `use == "deerflow.sandbox.tools:bash_tool"` 的工具也会被移除

这一步的意义很大，因为它不是“等模型调用后再拒绝”，而是：

- 先从 schema 层把危险执行面收起来

也就是说，DeerFlow 的安全策略之一是：

- 优先缩小模型可见能力面
- 再在执行期做二次拦截和审计

---

## 5. `view_image` 和 `task` 为什么是条件暴露

这两个 built-in 工具都不是默认总是暴露。

### 5.1 `view_image`

只有当当前模型配置 `supports_vision=True` 时，`view_image_tool` 才会加入工具集。

原因很直接：

- 非视觉模型拿到该工具没有意义
- 还会额外增大工具 schema 和决策噪音

### 5.2 `task`

只有 runtime 参数 `subagent_enabled=True` 时，才会追加 `task_tool`。

这说明 DeerFlow 把子代理当成显式运行模式，而不是默认所有 agent 都能递归开子任务。

这也方便在不同入口里按需控制：

- 普通 lead agent 可启用 subagent
- 子代理内部再装配工具时，会显式关闭递归 subagent

---

## 6. ACP 工具：把外部 agent 能力收敛成单工具入口

如果配置里存在 ACP agents，`get_available_tools()` 会构造 `invoke_acp_agent` 工具。

它的设计不是“每个 ACP agent 单独暴露一个 schema”，而是：

- 汇总成一个可路由的统一调用入口

这种做法的工程意义是：

- 避免工具数量膨胀
- 保持主 agent 的工具面稳定
- 把具体路由细节下沉到工具内部

---

## 7. MCP 工具：外部能力总线

MCP 工具默认也会被 `get_available_tools()` 纳入。

其来源不是直接现场初始化，而是：

- 先从缓存获取 `get_cached_mcp_tools()`
- 再与普通工具、built-in 工具一起汇总

这样做的原因是：

- MCP server 初始化可能较重
- Gateway 进程与 LangGraph server 进程可能分离
- 配置变更后需要重新读取最新 `ExtensionsConfig`

所以 DeerFlow 对 MCP 的策略不是“即时发现、即时绑定”，而是：

- 启动或更新时初始化
- agent 装配时读取缓存结果

---

## 8. Deferred Tool Search 解决什么问题

当 MCP server 较多、工具 schema 很大时，把所有工具一次性暴露给模型会出现两个问题：

1. prompt 体积膨胀
2. 模型在大工具集合里选错工具的概率上升

为此当前实现引入了 `tool_search` 模式。

开启后流程变成：

1. MCP 工具先进入 `DeferredToolRegistry`
2. 不直接把它们全部绑定给模型
3. 只额外暴露一个 `tool_search` built-in 工具
4. 模型需要时先检索，再决定真正要用的工具

这本质上是在做两层拆分：

- discovery 层：`tool_search`
- execution 层：真正的 MCP tool

---

## 9. `DeferredToolFilterMiddleware` 的作用

只有 registry 还不够，因为模型绑定阶段仍可能看到不该直接暴露的 schema。

因此当 `tool_search` 启用时，还会追加 `DeferredToolFilterMiddleware`。

它的职责可以理解为：

- prompt 和工具列表层面说“这些工具是延迟暴露的”
- middleware 层真正把 deferred tools 从当前绑定视图中过滤掉

这又是 DeerFlow 的典型做法：

- Prompt 负责告诉模型怎么做
- Middleware 负责确保系统真按这个规则运行

---

## 10. `present_file` 为什么重要

`present_file_tool` 表面上只是“呈现文件”，但它体现了 DeerFlow 文件交付模型的一条核心原则：

- 结果交付走状态与产物登记
- 不让前端直接自由浏览工作目录

当前约束是：

- 只能呈现当前线程 `outputs/` 下的文件
- 最终通过状态里的 `artifacts` 对外暴露

所以 DeerFlow 的文件交付不是“写完文件就算完成”，而是：

1. 写到受控输出目录
2. 用 `present_file` 显式登记
3. UI 再按状态展示

---

## 11. 工具系统的实际设计原则

结合当前实现，可以把 DeerFlow 工具系统概括成 5 条原则。

### 11.1 工具来源多路汇总

普通工具、built-in、MCP、ACP 并行装配，不强制走单一来源。

### 11.2 先缩小能力面，再执行期兜底

例如 host bash 默认直接从工具列表移除，而不是只在运行时报错。

### 11.3 Built-in 工具优先服务 runtime 治理

例如 clarification、task、present_file 都是框架控制能力。

### 11.4 大规模工具集合需要 discovery 机制

`tool_search` 的目的不是增加一个工具，而是治理 MCP 规模。

### 11.5 工具系统和运行模式联动

vision、subagent、MCP、sandbox 都会影响最终暴露给模型的工具集合。

---

## 12. 总结

DeerFlow 当前的工具系统核心不是“有哪些工具”，而是：

> 它如何根据 runtime 条件，把多来源能力组合成一组既可用、又可控、还能扩展的模型可见工具面。

如果只记一个重点，应该是：

- 工具列表不是固定资产
- 它是一次 run 装配结果的一部分
- 并且会被安全策略、模型能力和扩展配置持续裁剪

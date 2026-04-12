# DeerFlow Harness 工具加载、内置工具与 Deferred Tool Search

> 目标：说明 DeerFlow 当前实现中，工具集合是如何从配置、内置能力、MCP 和 ACP 多路汇总出来的，以及大规模工具场景下 Deferred Tool Search 的工作原理。
>
> 代码范围：以 `backend/packages/harness/deerflow/tools/` 为主。

补充专题：

- `../02-安全与沙箱/01-Bash安全措施与执行链.md`：`bash` 和文件工具的安全边界
- `../07-MCP与扩展/01-MCP接入、Skills装载与扩展机制.md`：MCP 与 skills 的扩展机制

---

## 1. 工具系统是配置驱动的多路合并

DeerFlow 的工具入口在 `deerflow/tools/tools.py::get_available_tools(...)`。

它不是从单一注册表取工具，而是按来源拼接：

| 来源 | 加载方式 | 说明 |
|------|----------|------|
| 普通工具 | 配置 + 反射 | `config.yaml` 中声明 |
| Built-in 工具 | 硬编码 + 条件追加 | harness 治理能力 |
| MCP 工具 | 缓存读取 | 外部能力总线 |
| ACP 工具 | 汇总成单工具 | 外部 agent 路由 |
| 条件工具 | 运行时决定 | `task`、`view_image`、`tool_search` |

---

## 2. 普通工具：配置声明 + 反射装载

### 2.1 配置结构

```yaml
tools:
  - group: web_search
    use: "deerflow.community.tavily.tools:tavily_search"
  - group: code_execution
    use: "deerflow.sandbox.tools:bash_tool"
```

每个工具配置最关键的是：

- `group`：工具分组标签，用于批量启用/禁用
- `use`：通过 `resolve_variable()` 解析成真实 Python 对象

### 2.2 反射装载流程

```python
# tools.py 中
for tool_config in config.tools:
    tool_obj = resolve_variable(tool_config.use)
    tools.append(tool_obj)
```

这带来两个直接效果：

- harness 核心层不需要硬编码所有业务工具
- 新工具接入主要靠配置，而不是改核心装配逻辑

### 2.3 社区工具

`deerflow/community/` 下的工具也通过配置接入：

| 工具 | 文件 | 用途 |
|------|------|------|
| Tavily Search | `community/tavily/tools.py` | Web 搜索 |
| Jina AI | `community/jina_ai/tools.py` | 网页内容抓取 |
| Firecrawl | `community/firecrawl/tools.py` | 网页爬取 |
| DuckDuckGo | `community/ddg_search/tools.py` | 搜索引擎 |
| Exa | `community/exa/tools.py` | 语义搜索 |
| InfoQuest | `community/infoquest/tools.py` | 信息检索 |

---

## 3. Built-in 工具：框架治理能力

### 3.1 默认 Built-in 工具

| 工具 | 文件 | 用途 |
|------|------|------|
| `present_file_tool` | `builtins/present_file_tool.py` | 把线程产物暴露给前端 |
| `ask_clarification_tool` | `builtins/clarification_tool.py` | 显式中断并向用户提问 |
| `setup_agent_tool` | `builtins/setup_agent_tool.py` | Agent 初始化工具 |

### 3.2 条件追加的 Built-in 工具

| 工具 | 条件 | 用途 |
|------|------|------|
| `task_tool` | `subagent_enabled=True` | 子代理委派 |
| `view_image_tool` | `supports_vision=True` | 图像内容注入 |
| `tool_search` | `tool_search.enabled=True` | 延迟工具检索 |
| `invoke_acp_agent_tool` | ACP agents 配置存在 | 调用外部 agent |

### 3.3 Built-in 工具 vs 业务工具的区别

| 维度 | 业务工具 | Built-in 工具 |
|------|----------|---------------|
| 目的 | 解决外部任务 | 解决 agent runtime 自身治理 |
| 来源 | 配置声明 | 硬编码 |
| 示例 | Web 搜索、代码执行 | 澄清、子代理、产物呈现 |

Built-in 工具更像 **runtime primitive**，而不是普通扩展插件。

---

## 4. Host Bash 在工具层被剔除

`get_available_tools()` 返回工具前调用 `is_host_bash_allowed(config)`。

如果当前不允许宿主机 bash：

- `group == "bash"` 的工具会被移除
- `use == "deerflow.sandbox.tools:bash_tool"` 的工具也会被移除

**这不是"等模型调用后再拒绝"，而是先从 schema 层把危险执行面收起来**。

DeerFlow 的安全策略：

1. 优先缩小模型可见能力面（工具层）
2. 再在执行期做二次拦截和审计（中间件层）

---

## 5. 条件暴露的设计原理

### 5.1 `view_image`：为什么非视觉模型不暴露

- 非视觉模型拿到该工具没有意义
- 还会额外增大工具 schema 和决策噪音

### 5.2 `task`：为什么子代理是显式模式

只有 runtime 参数 `subagent_enabled=True` 时才追加。

这使得：

- 普通 lead agent 可启用 subagent
- 子代理内部再装配工具时，会显式关闭递归 subagent（`subagent_enabled=False`）
- 不同入口可以按需控制子代理能力

---

## 6. ACP 工具：外部 agent 的单工具入口

如果配置里存在 ACP agents，`get_available_tools()` 构造 `invoke_acp_agent` 工具。

设计不是"每个 ACP agent 单独暴露一个 schema"，而是：

- **汇总成一个可路由的统一调用入口**

工程意义：

- 避免工具数量膨胀
- 保持主 agent 的工具面稳定
- 把具体路由细节下沉到工具内部

---

## 7. MCP 工具：外部能力总线

MCP 工具通过 `get_cached_mcp_tools()` 从缓存读取，然后与普通工具、built-in 工具一起汇总。

### 7.1 为什么从缓存读取

- MCP server 初始化可能较重（网络请求、OAuth 等）
- Gateway 进程与 LangGraph server 进程可能分离
- 配置变更后需要重新读取最新 `ExtensionsConfig`

### 7.2 MCP 工具的生命周期

```text
启动/更新时
  → initialize_mcp_tools()
    → 读取 ExtensionsConfig
    → 构造 MultiServerMCPClient
    → 拉取所有 server 的工具
    → 补同步 wrapper
    → 缓存结果

Agent 装配时
  → get_cached_mcp_tools()
    → 返回缓存的工具列表
```

---

## 8. Deferred Tool Search 解决什么问题

### 8.1 问题

当 MCP server 较多、工具 schema 很大时，把所有工具一次性暴露给模型会：

1. **Prompt 体积膨胀**：工具 schema 占用大量 token
2. **选错概率上升**：模型在大工具集合里选择质量下降

### 8.2 解决方案

开启 `tool_search` 后流程变成：

```text
1. MCP 工具先进入 DeferredToolRegistry
2. 不直接把它们全部绑定给模型
3. 只额外暴露一个 tool_search built-in 工具
4. 模型需要时先调用 tool_search 检索
5. 检索到合适工具后再调用
```

本质上是两层拆分：

- **Discovery 层**：`tool_search` 工具负责检索
- **Execution 层**：真正的 MCP tool 负责执行

### 8.3 `DeferredToolRegistry`

`tools/builtins/tool_search.py` 中的注册表：

```python
class DeferredToolRegistry:
    def register(self, tools: list[BaseTool]):
        """注册延迟暴露的工具"""

    def search(self, query: str) -> list[BaseTool]:
        """根据查询检索匹配的工具"""

    def get_tool(self, name: str) -> BaseTool | None:
        """按名称获取工具"""
```

---

## 9. `DeferredToolFilterMiddleware` 的作用

只有 registry 还不够，因为模型绑定阶段仍可能看到不该直接暴露的 schema。

当 `tool_search` 启用时，还会追加 `DeferredToolFilterMiddleware`：

| 职责 | 说明 |
|------|------|
| Prompt 注入 | 告诉模型"有工具需要先搜索再使用" |
| 工具过滤 | 从当前绑定视图中移除 deferred tools |

DeerFlow 的典型做法：

- **Prompt** 负责告诉模型怎么做
- **Middleware** 负责确保系统真按这个规则运行

---

## 10. `present_file` 为什么重要

`present_file_tool` 体现了 DeerFlow 文件交付模型的核心原则：

- 结果交付走状态与产物登记
- 不让前端直接自由浏览工作目录

当前约束：

- 只能呈现当前线程 `outputs/` 下的文件
- 通过 `Command(update=...)` 更新状态里的 `artifacts`
- UI 按状态展示，不是直接读文件系统

文件交付流程：

1. 写到受控输出目录（`/mnt/user-data/outputs/`）
2. 用 `present_file` 显式登记
3. 状态中的 `artifacts` 被 reducer 合并
4. UI 按状态展示

---

## 11. `ask_clarification`：显式中断流

`ask_clarification_tool` 把"中断并向用户提问"变成显式控制流：

1. 模型判断信息不足
2. 调用 `ask_clarification(question=..., options=[...])`
3. `ClarificationMiddleware` 拦截
4. 事件通过 SSE 推送给前端
5. 用户回答后重新提交
6. 模型带着答案继续执行

这比"模型在 prompt 里自己决定何时提问"更可控。

---

## 12. 工具系统的设计原则

| 原则 | 说明 |
|------|------|
| 多路汇总 | 普通工具、built-in、MCP、ACP 并行装配 |
| 先缩小能力面 | Host bash 默认从工具列表移除 |
| Built-in 服务 runtime 治理 | 澄清、task、present_file 都是框架控制能力 |
| 大规模工具需 discovery | `tool_search` 治理 MCP 规模 |
| 工具面与运行模式联动 | vision、subagent、MCP、sandbox 都影响暴露结果 |

---

## 13. 工具加载完整流程图

```text
get_available_tools(config, subagent_enabled, ...)
  |
  +-- 1. 普通工具
  |      for tool_config in config.tools:
  |          tool = resolve_variable(tool_config.use)
  |          tools.append(tool)
  |
  +-- 2. Host Bash 过滤
  |      if not is_host_bash_allowed(config):
  |          tools = [t for t in tools if not is_bash(t)]
  |
  +-- 3. Built-in 工具
  |      tools.append(present_file_tool)
  |      tools.append(ask_clarification_tool)
  |
  +-- 4. 条件工具
  |      if subagent_enabled: tools.append(task_tool)
  |      if supports_vision: tools.append(view_image_tool)
  |
  +-- 5. MCP 工具
  |      mcp_tools = get_cached_mcp_tools()
  |      tools.extend(mcp_tools)
  |
  +-- 6. ACP 工具
  |      if acp_agents: tools.append(invoke_acp_agent_tool)
  |
  +-- 7. Deferred Tool Search
  |      if tool_search.enabled:
  |          registry.register(mcp_tools)
  |          tools.append(tool_search_tool)
  |          middlewares.append(DeferredToolFilterMiddleware)
  |
  +-- 8. 返回合并后的工具列表
```

---

## 14. 总结

DeerFlow 工具系统的核心不是"有哪些工具"，而是：

> 它如何根据 runtime 条件，把多来源能力组合成一组既可用、又可控、还能扩展的模型可见工具面。

如果只记一个重点：

- 工具列表不是固定资产
- 它是一次 run 装配结果的一部分
- 并且会被安全策略、模型能力和扩展配置持续裁剪

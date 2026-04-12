# DeerFlow Harness 实现架构原理

> 目标：从当前仓库实现出发，解释 DeerFlow Harness 如何把配置、Agent、工具、沙箱、子代理、持久化和流式运行时装配成一套可复用框架。
>
> 代码范围：以 `backend/packages/harness/deerflow/` 为主，必要时补充 `backend/app/gateway/` 的接入层实现。

补充专题：

- `../02-安全与沙箱/01-Bash安全措施与执行链.md`：模型输出 `bash` 命令的安全措施与执行链
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：lead agent 装配细节
- `../04-工具系统/01-工具加载、内置工具与Deferred Tool Search.md`：工具系统
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时
- `../06-子代理/01-task工具与Subagent执行模型.md`：子代理
- `../07-MCP与扩展/01-MCP接入、Skills装载与扩展机制.md`：MCP 与扩展

---

## 1. 定位

DeerFlow Harness 不是一个简单的"LLM + 工具列表"，而是一层 Agent 运行时内核。

它负责：

- 读取和拆分配置
- 动态装配模型、工具、Prompt 和中间件
- 维护线程级状态 `ThreadState`
- 提供文件系统隔离与沙箱执行
- 提供子代理委派能力
- 提供 checkpoint/store/stream bridge/run manager 等运行时基础设施
- 供 Gateway 和嵌入式 Python Client 复用

因此更准确的理解是：

- `backend/packages/harness` 是核心运行时
- `backend/app/gateway` 是这套运行时的 HTTP/SSE 适配层
- `backend/app/channels` 是 IM 平台（飞书、Slack、Telegram）适配层

---

## 2. 总体分层

从职责看，Harness 大致可以拆成 8 层：

| 层 | 目录 | 作用 |
|---|---|---|
| 配置层 | `config/` | 解析 `config.yaml`、扩展配置和专项配置 |
| 反射层 | `reflection/` | 把配置里的字符串路径解析成 Python 对象 |
| Agent 装配层 | `agents/` | lead agent、状态模型、中间件链、prompt |
| 模型层 | `models/` | 多模型提供商适配、thinking 模式、凭证加载 |
| 能力层 | `tools/`、`mcp/`、`community/` | 普通工具、MCP 工具、社区能力 |
| 执行环境层 | `sandbox/`、`subagents/` | 沙箱、文件系统隔离、子代理执行 |
| 运行时层 | `runtime/`、`agents/checkpointer/` | run 生命周期、持久化、流式桥接 |
| 接入层 | `client.py` | 进程内嵌入式调用 |

### 2.1 Harness / App 边界

`deerflow.*` 绝不导入 `app.*`。这是一个硬约束，由 `tests/test_harness_boundary.py` 在 CI 中强制执行。

- Harness（`packages/harness/deerflow/`）：可发布的 agent 框架，import 前缀 `deerflow.*`
- App（`app/`）：未发布的应用代码，import 前缀 `app.*`

App 可以导入 deerflow，但 deerflow 不能反向导入 app。

---

## 3. 启动与配置装载

### 3.1 `AppConfig` 是总入口

主入口在 `deerflow/config/app_config.py` 的 `AppConfig.from_file()`。

它不只是读 YAML，而是做一次总装配：

1. 定位 `config.yaml`（通过 `DEER_FLOW_CONFIG_PATH` 环境变量或默认路径）
2. 读取 YAML
3. 解析 `$ENV_VAR` 形式的环境变量引用（`_resolve_env_vars()` 递归替换）
4. 把 memory、summarization、guardrails、subagents、checkpointer、stream_bridge、tool_search 等配置分发到对应模块
5. 额外读取 `ExtensionsConfig`（`extensions_config.json`）
6. 最终生成 `AppConfig` 单例

这意味着 DeerFlow 的配置体系不是"一个大对象"，而是：

- `AppConfig` 负责总入口
- 多个专项配置模块负责各自的运行时开关和参数

### 3.2 配置热更新

`AppConfig` 支持基于文件 mtime 的热更新。当 `config.yaml` 被修改后，下次 `get_app_config()` 会自动重新加载。

### 3.3 版本检查

`config.yaml` 中有 `config_version` 字段。启动时如果用户版本落后于 `config.example.yaml`，会输出警告。运行 `make config-upgrade` 可以自动合并缺失的字段。

### 3.4 反射层让能力可插拔

`deerflow/reflection/resolvers.py` 提供：

- `resolve_variable("pkg.module:name")` — 解析任意 Python 对象
- `resolve_class("pkg.module:Class", BaseClass)` — 解析并校验子类

模型类、工具对象、sandbox provider、guardrail provider 等，都是通过这种方式动态加载的。

```python
# 示例：配置中写
sandbox:
  use: "deerflow.sandbox.local:LocalSandboxProvider"

# 运行时解析
cls = resolve_class("deerflow.sandbox.local:LocalSandboxProvider", SandboxProvider)
provider = cls()
```

这层的意义是：

- 框架层不需要硬编码所有实现类
- 新模型、新工具、新 provider 可以通过配置接入
- 缺失依赖时会给出可操作的安装提示（如 `uv add langchain-anthropic`）

---

## 4. 模型系统

### 4.1 `ModelConfig` 配置模型

```python
class ModelConfig(BaseModel):
    name: str                              # 唯一标识，如 "claude-sonnet-4.6"
    display_name: str | None               # 人类可读标签
    use: str                               # 类路径，如 "deerflow.models.claude_provider:ClaudeChatModel"
    model: str                             # 提供商模型名，如 "claude-sonnet-4-6"
    supports_thinking: bool                # 是否支持 thinking
    supports_reasoning_effort: bool        # 是否支持 reasoning effort
    supports_vision: bool                  # 是否接受图像输入
    thinking: dict | None                  # thinking 快捷配置
    when_thinking_enabled: dict | None     # thinking 开启时的额外配置
    when_thinking_disabled: dict | None    # thinking 关闭时的额外配置
    model_config = ConfigDict(extra="allow")  # 允许透传提供商特定字段
```

`extra="allow"` 让提供商特有字段（如 `base_url`、`api_key`、`max_tokens`、`enable_prompt_caching`）可以直接写在配置里，透传到构造函数。

### 4.2 `create_chat_model()` 工厂

`deerflow/models/factory.py::create_chat_model(name, thinking_enabled, **kwargs)` 是核心入口：

1. 从 `AppConfig` 查找 `ModelConfig`
2. 通过 `resolve_class()` 动态加载模型类
3. 序列化配置字段（排除元数据字段）
4. 根据 `thinking_enabled` 合并 thinking 开关配置
5. 处理提供商特殊逻辑（Codex 映射 reasoning_effort 等）
6. 实例化模型
7. 附加 tracing 回调

### 4.3 支持的模型提供商

| 提供商 | 类 | 基础类 | 特性 |
|--------|-----|--------|------|
| Claude | `ClaudeChatModel` | `ChatAnthropic` | 自动 thinking budget、OAuth 凭证、prompt caching |
| OpenAI Codex | `CodexChatModel` | `BaseChatModel`（从头实现） | Responses API、SSE 流式、reasoning effort |
| vLLM | `VllmChatModel` | `ChatOpenAI` | 保留 `reasoning` 字段、标准化 thinking |
| DeepSeek | `PatchedChatDeepSeek` | `ChatDeepSeek` | 多轮对话保留 `reasoning_content` |
| MiniMax | `PatchedChatMiniMax` | `ChatOpenAI` | `reasoning_split`、内联 think 标签提取 |
| Gemini（via OpenAI） | `PatchedChatOpenAI` | `ChatOpenAI` | 保留 `thought_signature` |

外部提供商（如 `langchain_openai:ChatOpenAI`、`langchain_google_genai:ChatGoogleGenerativeAI`）也可以通过 `use` 字段接入。

### 4.4 Thinking 模式的多提供商适配

不同提供商的 thinking 实现差异很大，工厂层做了统一抽象：

- **Anthropic 原生**：`thinking = {"type": "disabled"}`（直接构造参数）
- **OpenAI 兼容网关**：`extra_body.thinking = {"type": "disabled"}`
- **vLLM/Qwen**：`extra_body.chat_template_kwargs.thinking = False` + `enable_thinking = False`
- **Codex**：映射为 `reasoning_effort`（"none" / "medium" / "high"）

`ClaudeChatModel` 还实现了自动 thinking budget：当 thinking 启用但未指定 `budget_tokens` 时，自动分配 `max_tokens` 的 80%。

### 4.5 凭证加载

`models/credential_loader.py` 支持：

- **Claude Code OAuth**：从 `~/.claude/.credentials.json`、环境变量或文件描述符加载，前缀 `sk-ant-oat` 检测
- **Codex CLI**：从 `~/.codex/auth.json` 加载

OAuth 模式下 prompt caching 被禁用（OAuth token 有 4 个 cache_control 块限制）。

---

## 5. Agent 装配主链路

### 5.1 两个入口函数

| 入口 | 位置 | 定位 |
|------|------|------|
| `make_lead_agent(config)` | `agents/lead_agent/agent.py` | 产品默认入口，读取全局配置和 runtime 参数 |
| `create_deerflow_agent(...)` | `agents/factory.py` | SDK 入口，纯参数装配，嵌入式复用 |

### 5.2 `make_lead_agent()` 装配步骤

```text
RunnableConfig
  -> 提取 runtime configurable（model_name, thinking_enabled, subagent_enabled 等）
  -> 读取 agent profile 配置（agents/<agent_name>/config.yaml）
  -> 解析最终模型名（runtime override > agent profile > 全局默认）
  -> create_chat_model(...)
  -> get_available_tools(...)
  -> _build_middlewares(...)
  -> apply_prompt_template(...)
  -> create_agent(...)
```

### 5.3 自定义 Agent

目录结构：

```text
{DEER_FLOW_HOME}/agents/{agent_name}/
├── config.yaml    # 模型、tool_groups、skills
└── SOUL.md        # agent 身份、风格、行为约束
```

自定义 agent 不是另一套引擎，而是同一个 lead agent 工厂通过不同 profile 注入。

---

## 6. Prompt 组装原理

`agents/lead_agent/prompt.py::apply_prompt_template(...)` 把 system prompt 拼成运行时合成文档：

- 基础角色说明
- 当前日期与上下文
- `SOUL.md`（agent 人格和方法论）
- memory context（从记忆系统加载，按 token 预算截断）
- skills section（工作流说明和领域知识）
- deferred tools section（延迟工具检索说明）
- subagent section（动态生成，根据 sandbox 能力调整）
- 工作目录和文件管理约束
- clarification 工作流约束
- response style 和 citations 要求

Prompt 不是固定"人设"文本，而是把多来源运行时约束统一投影成系统指令。

---

## 7. 中间件链：Harness 的执行主干

### 7.1 共享 runtime 中间件

`build_lead_runtime_middlewares()` 装配：

| 顺序 | 中间件 | 职责 |
|------|--------|------|
| 1 | `ThreadDataMiddleware` | 计算线程目录路径，写入 `state["thread_data"]` |
| 2 | `UploadsMiddleware` | 准备上传文件状态 |
| 3 | `SandboxMiddleware` | 获取或复用 sandbox，写入 `state["sandbox"]` |
| 4 | `DanglingToolCallMiddleware` | 修复悬挂的工具调用 |
| 5 | `LLMErrorHandlingMiddleware` | LLM 调用错误处理 |
| 6 | `GuardrailMiddleware` | 护栏：工具调用授权检查 |
| 7 | `SandboxAuditMiddleware` | bash 命令风险审计 |
| 8 | `ToolErrorHandlingMiddleware` | 工具异常转 `ToolMessage(status="error")` |

### 7.2 Lead agent 增强中间件

| 中间件 | 条件 | 职责 |
|--------|------|------|
| `SummarizationMiddleware` | 配置启用 | 长对话摘要压缩 |
| `TodoMiddleware` | plan mode | 待办事项管理 |
| `TokenUsageMiddleware` | 配置启用 | Token 使用统计 |
| `TitleMiddleware` | 配置启用 | 自动生成线程标题 |
| `MemoryMiddleware` | 配置启用 | 记忆排队更新 |
| `ViewImageMiddleware` | vision 模型 | 图像内容注入 |
| `DeferredToolFilterMiddleware` | tool search 启用 | 延迟工具过滤 |
| `SubagentLimitMiddleware` | subagent 启用 | 子代理并发截断 |
| `LoopDetectionMiddleware` | 总是 | 循环检测与阻断 |
| `ClarificationMiddleware` | 总是（最后） | 澄清优先拦截 |

### 7.3 双层治理

- **Prompt**：引导模型如何思考和决策
- **Middleware**：在系统层真正约束执行行为

---

## 8. 状态模型：`ThreadState`

`agents/thread_state.py` 在 `AgentState` 基础上扩展：

| 字段 | 类型 | 用途 |
|------|------|------|
| `sandbox` | `SandboxState` | 当前沙箱状态 |
| `thread_data` | `ThreadDataState` | 线程级目录路径 |
| `title` | `str` | 线程标题 |
| `artifacts` | `list` | 产物文件列表（带 reducer） |
| `todos` | `list` | 待办列表 |
| `uploaded_files` | `list` | 上传文件列表 |
| `viewed_images` | `dict` | 已查看图像（带 reducer） |

### 8.1 Reducer 的意义

`artifacts` 和 `viewed_images` 使用 reducer 而非简单覆盖：

- `merge_artifacts`：追加并去重
- `merge_viewed_images`：支持合并，也支持空字典清空

这避免了多个工具或多个回合同时更新时的状态写冲突。

---

## 9. 工具系统：多源合并

`tools/tools.py::get_available_tools()` 合并 5 个来源：

1. `config.yaml` 声明的普通工具（通过反射装载）
2. harness built-in 工具（`present_file`、`ask_clarification` 等）
3. MCP 工具（从缓存读取）
4. ACP agent 工具（汇总成单工具入口）
5. 运行时条件工具（`task`、`view_image`）

安全策略：

- `is_host_bash_allowed()` 检查不通过时，直接从工具列表移除 bash 工具
- `view_image` 仅在 `supports_vision=True` 时暴露
- `task` 仅在 `subagent_enabled=True` 时暴露

大规模工具场景：

- `tool_search` 启用时，MCP 工具不直接暴露，只暴露 `tool_search` 工具
- `DeferredToolFilterMiddleware` 在中间件层过滤掉 deferred tools

---

## 10. 沙箱系统

### 10.1 两层抽象

| 抽象 | 职责 |
|------|------|
| `Sandbox` | 执行命令、读写文件、列目录的能力接口 |
| `SandboxProvider` | sandbox 的获取、缓存、释放与销毁 |

### 10.2 提供商

| 提供商 | 位置 | 特点 |
|--------|------|------|
| `LocalSandboxProvider` | `sandbox/local/` | 单例，直接宿主机执行，虚拟路径映射 |
| `AioSandboxProvider` | `community/aio_sandbox/` | Docker 容器化，warm pool，idle timeout，远程 provisioner |

### 10.3 虚拟路径

| 虚拟路径 | 物理路径 |
|----------|----------|
| `/mnt/user-data/workspace` | `backend/.deer-flow/threads/{thread_id}/user-data/workspace/` |
| `/mnt/user-data/uploads` | `backend/.deer-flow/threads/{thread_id}/user-data/uploads/` |
| `/mnt/user-data/outputs` | `backend/.deer-flow/threads/{thread_id}/user-data/outputs/` |
| `/mnt/skills` | `skills/` 目录 |
| `/mnt/acp-workspace` | ACP workspace 目录 |

---

## 11. 子代理系统

### 11.1 `task` 工具入口

`tools/builtins/task_tool.py::task_tool` 是子代理唯一入口。

调用链：

1. 校验 `subagent_type`
2. 检查 sandbox 是否允许该类型
3. 读取 `SubagentConfig`
4. 拼接 skills section 到 subagent prompt
5. 继承父 runtime 的 sandbox、thread_data、thread_id、model_name、trace_id
6. 重新获取子代理工具，但强制 `subagent_enabled=False`（禁止递归）
7. 创建 `SubagentExecutor`
8. 后台启动任务
9. 后端轮询状态并通过 stream writer 发事件
10. 任务结束返回最终结果

### 11.2 `SubagentExecutor`

`subagents/executor.py`：

- 子代理也是 `create_agent(...)` 组装的
- 复用共享 runtime middlewares
- 使用双层线程池（调度 + 执行）
- 用 `_background_tasks` 跟踪状态

### 11.3 后端轮询而非模型轮询

`task_tool` 启动任务后：

- 后端每 5 秒轮询 `get_background_task_result(task_id)`
- 状态变化时通过 stream writer 发事件
- 完成时直接把结果返回主 agent

好处：减少 token 消耗，避免模型陷入机械轮询循环。

---

## 12. 记忆系统

### 12.1 数据结构

```json
{
  "version": "1.0",
  "lastUpdated": "ISO-8601Z",
  "user": { "workContext": {}, "personalContext": {}, "topOfMind": {} },
  "history": { "recentMonths": {}, "earlierContext": {}, "longTermBackground": {} },
  "facts": [{ "id": "fact_xxx", "content": "...", "category": "...", "confidence": 0.8 }]
}
```

### 12.2 工作流程

```
Agent 执行完成 -> MemoryMiddleware.after_agent()
                    |
                    v
          过滤消息（去工具调用、去上传块）
          检测纠正（correction）/ 强化（reinforcement）
                    |
                    v
          MemoryUpdateQueue.add()  （debounce 30s，同线程去重）
                    |
           (30s 后触发)
                    |
                    v
          MemoryUpdater.update_memory()
          -> LLM 分析对话，生成结构化更新
          -> _apply_updates() 合并到现有记忆
          -> storage.save() 原子写入
```

### 12.3 Prompt 注入

下次对话时，`_get_memory_context()` 从存储加载记忆，按 token 预算（默认 2000 tokens）格式化后注入 system prompt 的 `<memory>` 块。

---

## 13. 持久化：Checkpointer 与 Store

### 13.1 分工

| 维度 | Checkpointer | Store |
|------|-------------|-------|
| LangGraph 类 | `BaseCheckpointSaver` | `BaseStore` |
| 用途 | 图状态持久化和恢复 | 线程元数据、标题、索引 |
| 数据模型 | 顺序 checkpoint | 分层 namespace/key/value |
| 后端 | memory / sqlite / postgres | memory / sqlite / postgres |
| 注入方式 | 编译时 baked into graph | 通过 `Runtime(store=...)` |

### 13.2 为什么共享同一配置

Store 与 checkpointer 使用同一套 `checkpointer` 配置，确保图状态和线程元数据落在同类持久化后端，避免"线程标题持久化了但对话状态丢了"的不一致。

### 13.3 标题同步

`TitleMiddleware` 把标题写到 checkpoint 状态里；线程搜索接口读的是 store。所以 run 结束后 Gateway 需要额外做一次标题同步：从 checkpoint 读标题，回写到 store。

---

## 14. 流式运行时

### 14.1 `RunManager`

`runtime/runs/manager.py`：内存型 run registry，管理：

- `pending / running / success / interrupted / error` 状态
- 同线程并发策略（`reject` / `interrupt` / `rollback`）
- cancel / interrupt / rollback 语义

### 14.2 `run_agent()`

`runtime/runs/worker.py`：真正驱动图执行的地方

1. 标记 run 为 running
2. 构造 `Runtime(context={"thread_id": ...}, store=store)`
3. 写入 `config["configurable"]["__pregel_runtime"]`
4. 用 `agent_factory(config=...)` 动态构建 agent
5. 挂上 checkpointer / store
6. `agent.astream(...)`
7. 序列化输出 publish 到 `StreamBridge`
8. 结束时写最终状态并发送 `end`

### 14.3 `StreamBridge`

把 graph 执行侧的事件生产和 HTTP SSE 侧的事件消费解耦：

- 每个 run 一条 `asyncio.Queue`
- 单调递增 event id
- heartbeat 防止 SSE 超时
- `END_SENTINEL` 强保证送达（队列满时也会为 END 让路）

---

## 15. Gateway 如何接入 Harness

### 15.1 生命周期初始化

`app/gateway/deps.py` 的 `langgraph_runtime()` 在 FastAPI lifespan 中通过 `AsyncExitStack` 初始化：

```python
async with AsyncExitStack() as stack:
    app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge())
    app.state.checkpointer = await stack.enter_async_context(make_checkpointer())
    app.state.Store = await stack.enter_async_context(make_store())
    app.state.run_manager = RunManager()
    yield
```

### 15.2 `start_run()` 的本质

1. 创建或拒绝 run（处理并发冲突）
2. 保证线程在 store 里存在
3. 构造 `RunnableConfig`
4. `asyncio.create_task(run_agent(...))`

Gateway 只承担协议解析、生命周期接入、SSE 输出。Agent 本身是 Harness 内核在运行。

---

## 16. `DeerFlowClient`：同一套内核的嵌入式入口

`client.py` 直接复用 Harness 内核：

- `create_chat_model(...)`
- `_build_middlewares(...)`
- `apply_prompt_template(...)`
- `get_available_tools(...)`
- `ThreadState`

提供同步 Python API：

- 对话/流式
- 线程管理
- 模型/skill/MCP/记忆查询和更新
- 文件上传和产物访问

Gateway 适合服务端 API，Client 适合脚本、测试、嵌入式集成。两者装配核心是同一套。

---

## 17. 关键设计原则

| 原则 | 说明 |
|------|------|
| 配置驱动 | 模型、工具、MCP、guardrail、sandbox 都通过配置和反射装配 |
| 单一执行内核，多入口复用 | Gateway、Client、自定义 agent 共享核心装配链 |
| Prompt 引导，Middleware 约束 | 澄清、子代理并发、错误恢复都是双层协作 |
| 图状态与应用状态分离 | checkpointer 管图状态，store 管线程元数据 |
| 线程是逻辑+文件隔离单元 | `ThreadState`、thread 目录、sandbox 挂载围绕 `thread_id` |
| 机械控制逻辑下沉到程序 | 工具错误转 ToolMessage、子代理后端轮询、StreamBridge 解耦 |

---

## 18. 模块依赖关系

```
client.py (DeerFlowClient)
  ├── agents.lead_agent.agent
  ├── agents.thread_state
  ├── config.*
  ├── models (create_chat_model)
  └── agents.checkpointer

agents/lead_agent/agent.py (make_lead_agent)
  ├── agents/lead_agent/prompt.py
  ├── agents/middlewares/*
  ├── config.* (get_app_config)
  ├── models (create_chat_model)
  └── tools (get_available_tools)

tools/tools.py (get_available_tools)
  ├── tools/builtins/*
  ├── subagents (task_tool)
  ├── mcp (get_mcp_tools)
  └── community/* (tavily, jina_ai, etc.)

runtime/runs/worker.py (run_agent)
  ├── runtime/stream_bridge/
  ├── agents/lead_agent/agent.py
  └── runtime/serialization.py

runtime/store/
  └── config/checkpointer_config.py

agents/checkpointer/
  └── config/checkpointer_config.py
```

---

## 19. 总结

DeerFlow Harness 的核心不是某一个 Agent，而是一套围绕 `ThreadState`、中间件链、工具聚合、沙箱隔离和流式运行时构建出来的 Agent 执行框架。

理解这个项目时，最应该抓住四条主线：

1. **配置如何变成真实对象** — 反射层 + 配置驱动
2. **Agent 如何被动态装配** — `make_lead_agent()` 的 5 步装配
3. **一次 run 如何被持久化、流式化、可取消地执行** — RunManager + StreamBridge + Worker
4. **工具、沙箱、子代理如何围绕同一个 `thread_id` 协作** — ThreadState 统一状态

这四条线串起来，Harness 的实现骨架就清楚了。

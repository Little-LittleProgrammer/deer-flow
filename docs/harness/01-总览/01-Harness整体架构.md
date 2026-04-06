# DeerFlow Harness 实现架构原理

> 目标：从当前仓库实现出发，解释 DeerFlow Harness 如何把配置、Agent、工具、沙箱、子代理、持久化和流式运行时装配成一套可复用框架。
>
> 代码范围：以 `backend/packages/harness/deerflow/` 为主，必要时补充 `backend/app/gateway/` 的接入层实现。

补充专题：

- `../02-安全与沙箱/01-Bash安全措施与执行链.md`：模型输出 `bash` 命令的安全措施与执行链

---

## 1. 定位

DeerFlow Harness 不是一个简单的“LLM + 工具列表”，而是一层 Agent 运行时内核。

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

---

## 2. 总体分层

从职责看，Harness 大致可以拆成 7 层：

| 层 | 目录 | 作用 |
|---|---|---|
| 配置层 | `config/` | 解析 `config.yaml`、扩展配置和专项配置 |
| 反射层 | `reflection/` | 把配置里的字符串路径解析成 Python 对象 |
| Agent 装配层 | `agents/` | lead agent、状态模型、中间件链、prompt |
| 能力层 | `tools/`、`mcp/`、`community/` | 普通工具、MCP 工具、社区能力 |
| 执行环境层 | `sandbox/`、`subagents/` | 沙箱、文件系统隔离、子代理执行 |
| 运行时层 | `runtime/`、`agents/checkpointer/` | run 生命周期、持久化、流式桥接 |
| 接入层 | `client.py` | 进程内嵌入式调用 |

可以把主链路理解成：

```text
配置
  -> 模型/工具/Prompt/中间件装配
  -> create_agent(...)
  -> graph 执行
  -> 状态写入 checkpointer/store
  -> 事件写入 stream bridge
  -> Gateway / Client 消费结果
```

---

## 3. 启动与配置装载

### 3.1 `AppConfig` 是总入口

主入口在 `deerflow/config/app_config.py` 的 `AppConfig.from_file()`。

它不只是读 YAML，而是做一次总装配：

1. 定位 `config.yaml`
2. 读取 YAML
3. 解析 `$ENV_VAR` 形式的环境变量引用
4. 把 memory、summarization、guardrails、subagents、checkpointer、stream_bridge、tool_search 等配置分发到对应模块
5. 额外读取 `ExtensionsConfig`
6. 最终生成 `AppConfig`

这意味着 DeerFlow 的配置体系不是“一个大对象”，而是：

- `AppConfig` 负责总入口
- 多个专项配置模块负责各自的运行时开关和参数

### 3.2 反射层让能力可插拔

`deerflow/reflection/resolvers.py` 提供：

- `resolve_variable("pkg.module:name")`
- `resolve_class("pkg.module:Class")`

模型类、工具对象、sandbox provider、guardrail provider 等，都是通过这种方式动态加载的。

这层的意义是：

- 框架层不需要硬编码所有实现类
- 新模型、新工具、新 provider 可以通过配置接入

---

## 4. Agent 装配主链路

### 4.1 两个入口函数

Harness 里有两个关键入口：

#### `make_lead_agent(config)`

位置：`deerflow/agents/lead_agent/agent.py`

这是项目默认的应用级入口，负责 DeerFlow 的 lead agent 装配。

#### `create_deerflow_agent(...)`

位置：`deerflow/agents/factory.py`

这是更偏 SDK 的入口，强调“纯参数装配”，用于不依赖完整应用配置的场景。

可以概括为：

- `make_lead_agent`：产品默认装配方式
- `create_deerflow_agent`：框架复用方式

### 4.2 `make_lead_agent()` 做了什么

`make_lead_agent()` 的关键步骤是：

1. 从 `config.configurable` 读取运行时参数
2. 解析 `model_name`、`thinking_enabled`、`reasoning_effort`、`is_plan_mode`、`subagent_enabled`、`agent_name`
3. 读取自定义 agent 配置 `agents/<name>/config.yaml`
4. 调用 `create_chat_model(...)`
5. 调用 `get_available_tools(...)`
6. 调用 `_build_middlewares(...)`
7. 调用 `apply_prompt_template(...)`
8. 最终 `create_agent(...)`

所以它并不是“返回一个固定 agent”，而是根据运行时参数动态拼出一张图。

### 4.3 自定义 agent 的实现方式

自定义 agent 目录结构是：

```text
{DEER_FLOW_HOME}/agents/{agent_name}/
├── config.yaml
└── SOUL.md
```

其中：

- `config.yaml` 决定模型、tool_groups、skills
- `SOUL.md` 注入 agent 的身份、风格和行为约束

因此 DeerFlow 的多 agent 不是多套独立引擎，而是：

- 同一个 lead agent 工厂
- 通过 `agent_name` 注入不同 profile

---

## 5. Prompt 组装原理

位置：`deerflow/agents/lead_agent/prompt.py`

Prompt 在这里不是固定字符串，而是模板拼装结果。

最终 system prompt 会动态插入这些 section：

- 基础角色说明
- 当前日期与上下文
- `SOUL.md`
- memory context
- skills section
- deferred tools section
- subagent section
- 工作目录和文件管理约束
- clarification 工作流约束

这说明 Prompt 的作用不是单纯“告诉模型你是谁”，而是把多来源运行时约束统一投影成系统指令。

其中有两个点很关键：

### 5.1 Skills 主要通过 Prompt 暴露给模型

`deerflow/skills/loader.py` 扫描 `skills/public` 和 `skills/custom` 下的 `SKILL.md`，再结合扩展配置判断是否启用。

这些 skills 更多是：

- 工作流说明
- 任务处理规范
- 专项知识注入

它们首先是 Prompt 资源，而不是自动注册成工具。

### 5.2 Subagent 规则由 Prompt 和 Middleware 双重约束

Prompt 里会告诉模型如何拆任务、何时使用 `task` 工具、并发上限是多少；但真正的硬约束还会由 `SubagentLimitMiddleware` 执行。

这体现了 Harness 的一个核心策略：

- Prompt 负责引导
- 系统层负责兜底

---

## 6. 状态模型：`ThreadState`

位置：`deerflow/agents/thread_state.py`

Harness 的所有运行时能力都围绕一份统一状态展开，而不是散落在局部变量里。

`ThreadState` 在默认消息状态之外，额外承载了：

- `sandbox`
- `thread_data`
- `title`
- `artifacts`
- `todos`
- `uploaded_files`
- `viewed_images`

这带来三个效果：

1. 中间件之间可以通过统一状态协作
2. checkpointer 可以直接持久化完整线程上下文
3. 工具与 UI 呈现能力可以通过状态而不是隐式副作用对接

### 6.1 Reducer 的意义

像 `artifacts` 和 `viewed_images` 这类字段不是简单覆盖，而需要合并或去重。

Reducer 的作用就是把“如何合并状态”显式写进状态模型里，避免多个工具或多个回合同时更新时互相覆盖。

---

## 7. 中间件链：Harness 的执行主干

### 7.1 中间件链是动态拼装的

当前实现并不是固定数量的中间件，而是按“共享 runtime 中间件 + lead agent 专属中间件”拼出来的动态链路。

#### 共享 runtime 中间件

`build_lead_runtime_middlewares()` 当前负责装配：

1. `ThreadDataMiddleware`
2. `UploadsMiddleware`
3. `SandboxMiddleware`
4. `DanglingToolCallMiddleware`
5. `LLMErrorHandlingMiddleware`
6. `GuardrailMiddleware`（配置启用时）
7. `SandboxAuditMiddleware`
8. `ToolErrorHandlingMiddleware`

#### Lead agent 专属中间件

`_build_middlewares()` 会继续追加：

- `SummarizationMiddleware`
- `TodoMiddleware`
- `TokenUsageMiddleware`
- `TitleMiddleware`
- `MemoryMiddleware`
- `ViewImageMiddleware`
- `DeferredToolFilterMiddleware`
- `SubagentLimitMiddleware`
- `LoopDetectionMiddleware`
- `ClarificationMiddleware`

其中：

- 是否启用某些中间件，取决于配置和模型能力
- `ClarificationMiddleware` 被强制放在最后

### 7.2 这条链体现了什么设计

这条链路大致分成三段：

#### 环境准备

- thread 目录
- 上传文件信息
- sandbox 获取

#### 可靠性与安全性

- dangling tool call 修复
- LLM 错误处理
- guardrail
- sandbox 审计
- tool 异常转消息

#### 业务增强与行为控制

- 摘要
- todo
- token usage
- title
- memory
- 图像处理
- 工具延迟暴露
- 子代理并发上限
- 循环检测
- 澄清优先

也就是说，Prompt 决定“模型倾向怎么想”，中间件决定“系统允许它怎么跑”。

### 7.3 `ToolErrorHandlingMiddleware` 的工程意义

它会把工具异常转成 `ToolMessage(status="error")`，而不是让整个 run 崩掉。

这样做的好处是：

- agent 还能根据错误继续推理
- SSE 和 Gateway 层不必因为单个工具失败整体中断

这是 DeerFlow 很典型的“让系统尽量继续跑”的工程取向。

---

## 8. 工具系统：多源合并而不是单一注册表

位置：`deerflow/tools/tools.py`

`get_available_tools()` 会把几个来源合并成最终工具集：

1. `config.yaml` 中声明的普通工具
2. harness 内置工具
3. MCP 工具
4. ACP agent 工具
5. 运行时条件工具，比如 `task` 和 `view_image`

### 8.1 普通工具通过配置和反射装载

`config.tools[].use` 会通过 `resolve_variable(...)` 变成真实 `BaseTool`。

这让 DeerFlow 的工具层天然支持外部扩展，而不用修改核心装配逻辑。

### 8.2 Built-in 工具承担的是框架能力

典型内置工具包括：

- `present_files`
- `ask_clarification`
- `task`
- `view_image`

它们更多是在做运行时治理，而不是业务领域操作。

例如：

- `present_files` 把产物文件安全地暴露给前端
- `ask_clarification` 让澄清变成显式可中断流程
- `task` 用来委派子代理

### 8.3 MCP 是外部能力总线

位置：`deerflow/mcp/tools.py`

MCP 集成会：

1. 读取启用的 MCP server 配置
2. 通过 `MultiServerMCPClient` 拉取工具
3. 对 async-only 工具补一个同步 wrapper
4. 可选地接入 OAuth 头和拦截器

这让 MCP 工具最终也收敛成标准 `BaseTool`，后续执行链路无需区分它们的来源。

### 8.4 Deferred Tool Search 是规模治理能力

当 `tool_search` 启用时，MCP 工具不会全量直接暴露给模型，而是：

- 先注册进 deferred registry
- 对模型暴露 `tool_search`
- 真正需要时再检索

它解决的是：

- 工具 schema 太多导致 prompt 膨胀
- 模型面对超大工具集合时选择质量下降

---

## 9. 文件系统与线程隔离

位置：`deerflow/config/paths.py`

DeerFlow 的 thread 不只是逻辑概念，也对应真实目录结构：

```text
{base_dir}/threads/{thread_id}/
  user-data/
    workspace/
    uploads/
    outputs/
  acp-workspace/
```

在沙箱里的虚拟路径对应为：

- `/mnt/user-data/workspace`
- `/mnt/user-data/uploads`
- `/mnt/user-data/outputs`
- `/mnt/acp-workspace`

### 9.1 `ThreadDataMiddleware`

位置：`deerflow/agents/middlewares/thread_data_middleware.py`

它负责：

- 从 runtime/config 取出 `thread_id`
- 计算当前线程的目录路径
- 把路径写入 `state["thread_data"]`

默认 `lazy_init=True`，即：

- 先算路径
- 不立即创建所有目录

### 9.2 `present_files` 如何保证结果可控

位置：`deerflow/tools/builtins/present_file_tool.py`

这个工具只允许呈现当前线程 `outputs/` 下的文件，并把路径统一规范成 `/mnt/user-data/outputs/...`。

它不是直接操作前端，而是通过 `Command(update=...)` 更新状态里的 `artifacts`。

这说明 DeerFlow 的“文件展示”也是状态驱动的，而不是 UI 直连文件系统。

---

## 10. 沙箱系统

### 10.1 两层抽象

沙箱层被拆成：

- `Sandbox`：执行命令、读写文件、列目录的能力接口
- `SandboxProvider`：sandbox 的获取、缓存、释放与销毁

因此：

- `Sandbox` 关心“能做什么”
- `SandboxProvider` 关心“怎么管理生命周期”

### 10.2 `SandboxMiddleware`

位置：`deerflow/sandbox/middleware.py`

它负责：

1. 在需要时通过 `provider.acquire(thread_id)` 获取 `sandbox_id`
2. 把 `sandbox_id` 写入状态
3. 在 `after_agent()` 中调用 `provider.release(sandbox_id)`

这里需要特别注意：

- 中间件层面会调用 `release`
- 但底层 provider 可以把 release 设计成 no-op、放回 warm pool，或者真正释放资源

因此“同一线程是否复用沙箱”，最终由 provider 语义决定。

### 10.3 `LocalSandboxProvider`

位置：`deerflow/sandbox/local/local_sandbox_provider.py`

特点：

- 维护单例 `LocalSandbox`
- `release()` 基本不做实际清理
- 更像本地开发视角下的宿主机映射执行环境

### 10.4 `AioSandboxProvider`

位置：`deerflow/community/aio_sandbox/aio_sandbox_provider.py`

这是更完整的沙箱生命周期管理器，支持：

- `thread_id -> sandbox_id` 映射
- deterministic sandbox id
- warm pool
- idle timeout
- replicas 软上限
- 本地容器 backend 或远程 provisioner backend
- 自动挂载 thread 目录和 skills 目录

它说明 DeerFlow 的沙箱能力已经不是“调用个 bash”那么简单，而是一套带资源池的执行环境管理系统。

---

## 11. 子代理系统

### 11.1 入口是 `task` 工具

位置：`deerflow/tools/builtins/task_tool.py`

主 agent 并不是直接 new 一个子 agent，而是通过 `task(...)` 工具委派任务。

`task_tool` 会：

1. 读取 `subagent_type` 对应配置
2. 从父 runtime 继承 thread_id、sandbox、thread_data、trace_id、父模型信息
3. 重新构造一份工具集，但禁用递归 subagent
4. 创建 `SubagentExecutor`
5. 把任务放到后台执行
6. 在后端轮询结果，并通过 stream writer 发状态事件

### 11.2 `SubagentExecutor`

位置：`deerflow/subagents/executor.py`

它的关键实现点：

- 子代理本身也是 `create_agent(...)` 组装出来的
- 复用共享 runtime middlewares
- 使用线程池调度和执行
- 用 `_background_tasks` 跟踪状态
- 收集 AI messages 以便实时回传

### 11.3 为什么轮询在后端做

这里有个非常重要的工程决策：

- 子代理后台执行
- 轮询由后端做
- LLM 最后直接拿到完成后的结果

好处是：

- 避免模型自己反复查询状态浪费 token
- 避免形成“任务状态轮询循环”

这体现了 DeerFlow 的一条明显原则：把机械控制逻辑尽量从模型下沉到程序。

---

## 12. 记忆系统

### 12.1 `MemoryMiddleware` 只负责排队

位置：`deerflow/agents/middlewares/memory_middleware.py`

它在 `after_agent()` 中做的不是直接更新 memory，而是：

1. 从消息历史中过滤出用户输入和最终 AI 回复
2. 去掉 `<uploaded_files>` 这种会话性上下文
3. 检测用户是否在纠正模型
4. 把结果推到 memory queue

### 12.2 `MemoryUpdater` 才负责真正持久化

位置：`deerflow/agents/memory/updater.py`

它负责：

- 读取当前 memory
- 调模型生成结构化更新
- 清洗上传文件等临时信息
- 保存到全局或 agent 级 memory

因此 memory 是一条异步、去噪、可失败但不应拖垮主链路的后台能力。

---

## 13. 持久化：Checkpointer 与 Store 的分工

### 13.1 Checkpointer

位置：

- `deerflow/agents/checkpointer/provider.py`
- `deerflow/agents/checkpointer/async_provider.py`

用途：

- 持久化 LangGraph 图状态
- 支持多轮线程恢复
- 支持内存、SQLite、Postgres 三种后端

### 13.2 Store

位置：

- `deerflow/runtime/store/provider.py`
- `deerflow/runtime/store/async_provider.py`

用途：

- 存线程元数据
- 支撑线程索引、搜索和标题同步等应用层需求

### 13.3 为什么后端保持一致

Store 与 checkpointer 使用同一套 `checkpointer` 配置，意味着：

- 图状态和线程元数据尽量落在同类持久化后端
- 部署复杂度更低

可以简化记忆为：

- checkpointer：图的状态
- store：应用的线程记录

---

## 14. 流式运行时：RunManager + StreamBridge + Worker

### 14.1 `RunManager`

位置：`deerflow/runtime/runs/manager.py`

它负责：

- 创建 run 记录
- 管理 pending/running/success/interrupted/error 状态
- 执行同线程并发策略
- 处理 cancel / interrupt / rollback 语义

### 14.2 `StreamBridge`

位置：`deerflow/runtime/stream_bridge/`

它把：

- graph 执行侧的事件生产
- HTTP SSE 侧的事件消费

解耦成一个桥。

默认实现 `MemoryStreamBridge` 使用每个 run 一条 `asyncio.Queue`，并提供：

- event id
- heartbeat
- end sentinel
- 队列满时的丢弃保护

### 14.3 `run_agent()`

位置：`deerflow/runtime/runs/worker.py`

它是真正驱动图执行的地方，关键动作是：

1. 标记 run 为 running
2. 构造 `Runtime(context={"thread_id": ...})`
3. 调用 `agent_factory(config=...)`
4. 给 agent 注入 checkpointer 和 store
5. `agent.astream(...)`
6. 把 LangGraph 输出序列化后 publish 到 `StreamBridge`
7. 结束时写入最终状态并发送 `end`

所以让 DeerFlow 支持 SSE 的核心，并不是 FastAPI，而是 Harness 内部这套事件桥接设计。

---

## 15. Gateway 如何接入 Harness

位置：`backend/app/gateway/`

### 15.1 生命周期初始化

`app/gateway/deps.py` 的 `langgraph_runtime()` 会在 FastAPI lifespan 中初始化：

- `stream_bridge`
- `checkpointer`
- `store`
- `run_manager`

并挂到 `app.state`。

### 15.2 `start_run()` 的本质

`app/gateway/services.py::start_run()` 做的事情可以概括成：

1. 根据请求创建或拒绝 run
2. 保证线程在 store 里存在
3. 构造 `RunnableConfig`
4. 合并 DeerFlow 自己的 `context` 字段到 `configurable`
5. `asyncio.create_task(run_agent(...))`

也就是说，Gateway 真正承担的是：

- 协议解析
- 线程/run 生命周期接入
- SSE 输出

Agent 本身仍然是 Harness 内核在运行。

### 15.3 标题同步是跨存储层补偿逻辑

`TitleMiddleware` 把标题写到 checkpoint 的状态里；而线程搜索接口读的是 store。

所以 Gateway 需要在 run 结束后额外做一次标题同步，把 checkpoint 中的 `title` 回写到 store。

这再次体现了 checkpointer 和 store 的职责分离。

---

## 16. `DeerFlowClient`：同一套内核的嵌入式入口

位置：`deerflow/client.py`

`DeerFlowClient` 不是另一套简化实现，而是直接复用 Harness 内核：

- `create_chat_model(...)`
- `_build_middlewares(...)`
- `apply_prompt_template(...)`
- `get_available_tools(...)`
- `ThreadState`

它解决的是“进程内直连调用”问题，而不是重新实现 agent 逻辑。

因此：

- Gateway 适合服务端 API
- `DeerFlowClient` 适合脚本、测试、嵌入式集成

两者的装配核心是同一套。

---

## 17. 关键设计原则

结合实现，可以把 Harness 的核心设计原则总结为 6 点。

### 17.1 配置驱动

模型、工具、MCP、guardrail、sandbox 都尽量通过配置和反射装配，而不是硬编码。

### 17.2 单一执行内核，多入口复用

Gateway、Client、自定义 agent 都共享同一条核心装配链。

### 17.3 Prompt 负责引导，Middleware 负责约束

像澄清优先、子代理并发上限、错误恢复这类能力，都不是只靠 Prompt，而是 Prompt 与运行时双重协作。

### 17.4 图状态与应用状态分离

- checkpointer：图状态
- store：应用线程元数据

### 17.5 线程既是逻辑隔离单元，也是文件隔离单元

`ThreadState`、thread 目录、sandbox 挂载共同围绕 `thread_id` 工作。

### 17.6 把机械控制逻辑从模型下沉到程序

比如：

- 工具错误转 `ToolMessage`
- 子代理轮询由后端完成
- StreamBridge 解耦生产和消费

这类策略都在减少模型承担的状态机复杂度。

---

## 18. 总结

如果把整个实现压缩成一句判断：

> DeerFlow Harness 的核心不是某一个 Agent，而是一套围绕 `ThreadState`、中间件链、工具聚合、沙箱隔离和流式运行时构建出来的 Agent 执行框架。

理解这个项目时，最应该抓住四条主线：

1. 配置如何变成真实对象
2. Agent 如何被动态装配
3. 一次 run 如何被持久化、流式化、可取消地执行
4. 工具、沙箱、子代理如何围绕同一个 `thread_id` 协作

这四条线串起来，Harness 的实现骨架就清楚了。

# DeerFlow Harness task 工具与 Subagent 执行模型

> 目标：从当前实现出发，说明 DeerFlow 的子代理不是“模型自己轮询的小技巧”，而是一套由 `task` 工具、后台执行器和流式事件共同构成的执行模型。
>
> 代码范围：以 `backend/packages/harness/deerflow/tools/builtins/task_tool.py` 和 `subagents/` 为主。

补充专题：

- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：lead agent 的 subagent prompt 与 middleware 约束
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时和流式桥接侧

---

## 1. 子代理入口不是内部 API，而是 `task` 工具

DeerFlow 里 lead agent 不会直接在代码路径里“偷偷 new 一个子 agent”。

子代理入口被显式设计成工具：

- `deerflow/tools/builtins/task_tool.py::task_tool`

这意味着在模型视角里：

- 子代理是一种显式能力选择
- 与普通工具调用处在同一决策层

这也方便把子代理纳入统一治理：

- prompt 指导何时调用
- middleware 限制并发数量
- runtime 负责执行和流式回传

---

## 2. `task_tool` 调用链做了什么

一次 `task(...)` 调用的关键步骤是：

1. 校验 `subagent_type`
2. 检查当前 sandbox 是否允许该类型，尤其是 `bash`
3. 读取对应 `SubagentConfig`
4. 拼接 skills section 到 subagent system prompt
5. 继承父 runtime 里的 `sandbox`、`thread_data`、`thread_id`、`model_name`、`trace_id`
6. 重新获取子代理可用工具，但强制 `subagent_enabled=False`
7. 创建 `SubagentExecutor`
8. 后台启动任务
9. 后端轮询状态并通过 stream writer 持续发事件
10. 任务结束后返回最终结果给主 agent

这条链路说明 DeerFlow 的子代理不是纯 prompt trick，而是完整程序流程。

---

## 3. 为什么子代理要继承父上下文

`task_tool` 会把父级 runtime 中这些信息传下去：

- `sandbox_state`
- `thread_data`
- `thread_id`
- `parent_model`
- `trace_id`

这样做有几个直接目的。

### 3.1 共享线程工作区

子代理和父代理围绕同一个 `thread_id` 工作，因此它们看到的是同一套 thread 目录和输出空间。

### 3.2 共享或复用 sandbox

如果 provider 允许，父子代理可以沿着同一线程上下文复用执行环境，而不必每次新建隔离资源。

### 3.3 追踪链路可关联

`trace_id` 继承下来后，日志和运行链路更容易把主代理与子任务串起来。

所以 subagent 在这里不是完全独立的会话，而是同线程下的受控分工。

---

## 4. 为什么要禁止递归 subagent

`task_tool` 在给子代理重新装配工具时，显式传入：

- `subagent_enabled=False`

也就是说，子代理默认不能继续拿到 `task` 工具。

这条规则的工程意义很大：

- 防止递归爆炸
- 避免多层 task 树让状态管理失控
- 保持执行模型简单：主代理编排，子代理执行

这说明 DeerFlow 的子代理定位更接近：

- orchestrator / worker

而不是任意层级可递归分裂的 agent swarm。

---

## 5. `SubagentExecutor`：子代理执行器

`deerflow/subagents/executor.py::SubagentExecutor` 负责真正启动和跟踪子任务。

它的初始化输入包括：

- `SubagentConfig`
- 可用工具列表
- 父模型信息
- `sandbox_state`
- `thread_data`
- `thread_id`
- `trace_id`

这表明 executor 不是一个通用线程池包装器，而是面向 DeerFlow runtime 语义的执行器。

---

## 6. 子代理自身也是 `create_agent(...)`

在 `_create_agent()` 里，子代理会：

1. 根据配置和父模型解析最终模型
2. `create_chat_model(...)`
3. 复用 `build_subagent_runtime_middlewares(...)`
4. 调 `langchain.agents.create_agent(...)`

也就是说，子代理和主代理共享同一种 agent graph 执行内核，只是：

- prompt 不同
- 工具集更窄
- middleware 是 subagent 版本
- 没有递归 subagent 能力

所以 DeerFlow 的 subagent 不是“简化脚本执行器”，而是真正的 agent runtime 复用。

---

## 7. `build_subagent_runtime_middlewares()` 复用了哪些能力

子代理的共享 runtime middleware 与 lead agent 很接近，主要包括：

- `ThreadDataMiddleware`
- `SandboxMiddleware`
- `DanglingToolCallMiddleware`
- `LLMErrorHandlingMiddleware`
- `GuardrailMiddleware`（若启用）
- `SandboxAuditMiddleware`
- `ToolErrorHandlingMiddleware`

和 lead agent 相比，最明显的差异是：

- 不包含 `UploadsMiddleware`
- 不追加标题、记忆、todo、view image、clarification 这类面向主会话的增强链

这非常合理，因为 subagent 目标是专注完成子任务，而不是承担完整对话治理职责。

---

## 8. 后台执行为什么分两层线程池

`subagents/executor.py` 当前有两层池：

- `_scheduler_pool`
- `_execution_pool`

设计目的不是复杂化，而是把：

- 调度与编排
- 实际 agent 执行

分开处理，并为 timeout 和后台状态跟踪留出空间。

这说明 subagent 运行在当前实现里不是“直接 await 一个协程”，而是带有后台任务登记和超时管理的执行模型。

---

## 9. 为什么 `task_tool` 要在后端轮询

这是 DeerFlow 子代理设计里最关键的一点。

`task_tool` 启动任务后，并不是要求主模型自己不断调用“查询状态”工具，而是：

- 后端循环调用 `get_background_task_result(task_id)`
- 每 5 秒轮询一次
- 状态变化时通过 stream writer 发事件
- 完成时直接把最终结果返回给主 agent

这样做的好处非常明显：

1. 减少无意义 token 消耗
2. 避免模型陷入“轮询状态工具”的机械循环
3. 把状态机复杂度下沉到程序，而不是交给 prompt

这和 DeerFlow 整体风格一致：

- 机械控制逻辑尽量程序化
- 模型主要负责判断和综合

---

## 10. 子代理过程事件如何暴露给前端

`task_tool` 会通过 `get_stream_writer()` 写出这些事件：

- `task_started`
- `task_running`
- `task_completed`
- `task_failed`
- `task_timed_out`

并且 `task_running` 会附带新生成的 AI message。

这使得前端或 SSE 消费方可以看到子任务进展，而不是只在最后拿到一个成败结果。

所以这里的用户体验不是“静默等待异步任务”，而是“后台执行 + 可观测进度”。

---

## 11. `SubagentLimitMiddleware` 为什么必不可少

Prompt 中虽然已经写明每轮最多多少个 `task` 调用，但 prompt 不足以形成硬约束。

因此还需要 `SubagentLimitMiddleware(max_concurrent=...)`。

它的作用是：

- 对单轮响应里的并行 task 调用数做截断

这意味着 DeerFlow 把 subagent 并发控制放在两层：

- prompt：告诉模型如何批次化规划
- middleware：防止超额调用真的落地

如果没有这层 middleware，模型在复杂任务下仍然可能一次打出过多子任务。

---

## 12. `bash` 子代理为什么受 sandbox 配置约束

当前可用的 subagent 类型会根据 sandbox 能力动态变化。

尤其是 `bash` subagent：

- 若 host bash 不允许，`task_tool` 会直接返回错误
- prompt 里的 subagent section 也会同步提示 bash 不可用

这又体现了 DeerFlow 的双层策略：

- 能力说明在 prompt 中同步
- 硬阻断在程序逻辑中落实

---

## 13. 当前实现的边界

子代理系统已经比较完整，但当前仍有几个边界需要明确。

### 13.1 结果登记依赖进程内全局表

`_background_tasks` 是进程内全局存储，不是持久化任务队列。

### 13.2 轮询间隔是固定的

当前是 5 秒一次，属于简单可靠优先，而不是极致实时。

### 13.3 子代理更偏单层编排模型

默认禁止嵌套 task，说明当前不是多层级自治 agent swarm。

这些边界并不妨碍它处理多数复杂任务，但决定了它更适合当前 DeerFlow 的“主代理编排 + 子代理分工”架构。

---

## 14. 总结

DeerFlow 当前的 subagent 核心机制可以概括成：

> `task` 负责把委派显式化，`SubagentExecutor` 负责后台执行，后端轮询和流式事件负责把进度与结果带回主链路。

如果只看 prompt，很容易误以为这是“模型自己拆分任务”的能力；但从实现上看，更准确的理解是：

- 模型只负责决定何时拆、怎么拆
- 真正的并行执行、状态轮询、结果回传都由 harness runtime 完成

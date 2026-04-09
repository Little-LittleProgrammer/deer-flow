# DeerFlow Harness Lead Agent 装配与 Middleware 链

> 目标：基于当前仓库实现，拆开说明 DeerFlow 如何从 `RunnableConfig` 出发，装配出一个可执行的 lead agent，以及 middleware 链在整个执行流程中的职责分工。
>
> 代码范围：以 `backend/packages/harness/deerflow/agents/` 为主，必要时补充 `models/`、`tools/` 和 `config/`。

补充专题：

- `../01-总览/01-Harness整体架构.md`：Harness 的全局分层和主执行链
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时状态与流式执行侧

---

## 1. 入口定位

当前仓库里有两条 agent 装配入口：

- `deerflow/agents/lead_agent/agent.py::make_lead_agent(config)`
- `deerflow/agents/factory.py::create_deerflow_agent(...)`

两者不是重复实现，而是面向不同层次：

- `make_lead_agent`：应用默认入口，读取全局配置和 runtime 参数，负责 DeerFlow 产品化场景
- `create_deerflow_agent`：SDK 入口，强调“纯参数装配”，用于更轻量的嵌入式复用

如果从项目默认运行路径看，真正最核心的是 `make_lead_agent()`。

---

## 2. `make_lead_agent()` 的装配步骤

`make_lead_agent(config)` 接收的是 `RunnableConfig`，不是一个静态 agent profile。它会从 `config["configurable"]` 动态解析这次 run 的运行模式：

- `thinking_enabled`
- `reasoning_effort`
- `model_name`
- `is_plan_mode`
- `subagent_enabled`
- `max_concurrent_subagents`
- `is_bootstrap`
- `agent_name`

随后装配链路大致是：

```text
RunnableConfig
  -> 提取 runtime configurable
  -> 读取 agent profile 配置
  -> 解析最终模型名
  -> create_chat_model(...)
  -> get_available_tools(...)
  -> _build_middlewares(...)
  -> apply_prompt_template(...)
  -> create_agent(...)
```

这说明 DeerFlow 的 lead agent 不是预先常驻的一份对象，而是“按 run 动态拼装”的。

---

## 3. 模型选择不是单点决策

模型解析逻辑至少有三层来源：

1. 请求级 runtime 参数 `model_name` / `model`
2. 自定义 agent 配置里的 `agent_config.model`
3. 全局配置里的默认模型

`_resolve_model_name()` 只负责兜底和回退；真正生效的顺序是：

- 优先 runtime override
- 其次 agent profile
- 再其次全局默认模型

另外还有两个运行时修正：

- 如果模型不支持 `thinking`，会自动降级为非 thinking 模式
- `reasoning_effort` 作为运行参数写入 metadata，便于后续 tracing 和调试

这套机制体现了 DeerFlow 在模型层的一个取向：

- 产品默认有稳定基线
- 单次请求仍然允许精细覆盖

---

## 4. 自定义 agent 不是另一套引擎

`agent_name` 会触发 `load_agent_config(agent_name)` 和 `load_agent_soul(agent_name)`。

这意味着所谓“自定义 agent”，本质上是对以下几项进行 profile 注入：

- 使用什么模型
- 暴露哪些 `tool_groups`
- 启用哪些 skills
- 注入什么 `SOUL.md`

也就是说，DeerFlow 的多 agent 方案不是多套运行时，而是：

- 同一个 lead agent 工厂
- 不同的配置和 prompt profile

这种设计的好处是：

- 运行时行为一致
- 安全和 middleware 约束天然复用
- Gateway 与 client 不需要理解多套 agent 类型

---

## 5. Prompt 装配：把运行时约束投影成系统指令

Prompt 入口在 `deerflow/agents/lead_agent/prompt.py::apply_prompt_template(...)`。

这里不是单纯填一个角色名，而是按运行时条件拼多个 section：

- role
- soul
- memory context
- thinking style
- clarification system
- skills section
- deferred tools section
- subagent section
- working directory 约束
- response style
- citations 要求

因此 DeerFlow 的 system prompt 更像一份运行时合成文档，而不是一段固定“人设”文本。

### 5.1 `SOUL.md` 的作用

`SOUL.md` 负责定义 agent 的身份、风格和行为约束，但它并不直接替代框架 prompt。

更准确地说：

- `SOUL.md` 是 profile 层人格和方法论
- prompt template 是框架层运行规则

### 5.2 Subagent section 是动态生成的

`_build_subagent_section(max_concurrent)` 会根据当前配置生成：

- 并发上限提示
- 可用 subagent 类型
- direct tool 与 task 的使用边界

并且它会根据当前 sandbox 是否允许 bash，切换对 `bash` subagent 的说明。

所以 subagent 并不是 prompt 中硬编码的一段静态描述，而是和 runtime 能力面联动。

---

## 6. Middleware 链的装配规则

`_build_middlewares(...)` 分两段做：

1. `build_lead_runtime_middlewares(lazy_init=True)` 提供共享 runtime 链
2. lead agent 再追加业务增强和行为治理 middleware

### 6.1 共享 runtime middleware

当前顺序是：

1. `ThreadDataMiddleware`
2. `UploadsMiddleware`
3. `SandboxMiddleware`
4. `DanglingToolCallMiddleware`
5. `LLMErrorHandlingMiddleware`
6. `GuardrailMiddleware`（配置启用时）
7. `SandboxAuditMiddleware`
8. `ToolErrorHandlingMiddleware`

这一段主要解决三类问题：

- 环境准备：thread 目录、uploads、sandbox
- 稳定性：dangling tool call 修复、LLM 错误处理、tool 异常转消息
- 安全性：guardrail、sandbox audit

### 6.2 Lead agent 增强 middleware

随后 `_build_middlewares()` 会追加：

- `SummarizationMiddleware`
- `TodoMiddleware`（仅 plan mode）
- `TokenUsageMiddleware`
- `TitleMiddleware`
- `MemoryMiddleware`
- `ViewImageMiddleware`（模型支持 vision 时）
- `DeferredToolFilterMiddleware`（tool search 启用时）
- `SubagentLimitMiddleware`（subagent 启用时）
- `LoopDetectionMiddleware`
- `ClarificationMiddleware`

这段更偏产品行为治理和会话增强。

---

## 7. 顺序为什么重要

源码注释已经明确说明 middleware 次序不能随意换位，核心原因有三类。

### 7.1 前置依赖关系

例如：

- `ThreadDataMiddleware` 必须早于 `SandboxMiddleware`
- `UploadsMiddleware` 要依赖 thread data
- `ViewImageMiddleware` 需要在模型继续推理前注入图像信息

这类顺序是“数据依赖型”的。

### 7.2 错误和控制流拦截

例如：

- `ToolErrorHandlingMiddleware` 要包住工具执行
- `ClarificationMiddleware` 被强制放最后，用于在最终阶段拦截澄清请求

这类顺序是“控制流兜底型”的。

### 7.3 行为治理优先级

例如：

- `SubagentLimitMiddleware` 在真正形成 tool call 后做并发截断
- `LoopDetectionMiddleware` 用于阻断重复模式

这类顺序是“行为约束型”的。

因此 middleware 链不是普通插件列表，而是 DeerFlow 执行策略的主干。

---

## 8. Prompt 与 Middleware 的分工

DeerFlow 很明显采用了双层治理：

- Prompt：引导模型如何思考和决策
- Middleware：在系统层真正约束执行

几个典型例子：

- 澄清优先：prompt 里要求先澄清，`ClarificationMiddleware` 负责执行中断
- 子代理并发：prompt 里写明上限，`SubagentLimitMiddleware` 负责裁剪超额调用
- 工具失败恢复：prompt 不足以保证稳定，`ToolErrorHandlingMiddleware` 负责把异常转成 `ToolMessage`

这类设计比“只写 prompt”更接近工程化 agent runtime。

---

## 9. `create_deerflow_agent()` 的意义

`deerflow/agents/factory.py` 里的 `create_deerflow_agent(...)` 并不依赖 YAML 或全局单例完成基础装配。

它做的事是：

- 接收模型、工具、prompt、middleware、features 这些纯 Python 参数
- 根据 `RuntimeFeatures` 自动拼装最小 DeerFlow 风格 middleware 链
- 最终调用 `langchain.agents.create_agent(...)`

它的价值主要体现在两点：

1. 把 DeerFlow 的工程化能力从应用配置中抽出来，方便嵌入式复用
2. 保持与 `make_lead_agent()` 相似的 middleware 顺序和执行语义

但需要注意：

- factory 本身是 config-free 的
- 某些运行时能力在调用期仍可能回读全局配置，例如子代理相关工具

所以它更接近“Phase 1 的轻量 SDK 化”，而不是完全脱离应用环境的纯内核。

---

## 10. 总结

从实现上看，lead agent 装配最关键的不是 `create_agent(...)` 这一步本身，而是它之前的一系列动态决策：

1. 这次 run 用哪个模型、什么模式
2. 该暴露哪些工具
3. 要不要启用 plan、vision、subagent、tool search
4. prompt 里要注入哪些 runtime section
5. middleware 链怎样排序，哪些约束要前置

因此理解 DeerFlow lead agent 的正确方式不是“它创建了一个 agent”，而是：

> 它把一组配置、能力面和运行时约束，编译成了一次具体可执行的 agent graph。

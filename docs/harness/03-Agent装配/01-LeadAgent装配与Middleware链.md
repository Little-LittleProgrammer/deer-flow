# DeerFlow Harness Lead Agent 装配与 Middleware 链

> 目标：基于当前仓库实现，拆开说明 DeerFlow 如何从 `RunnableConfig` 出发，装配出一个可执行的 lead agent，以及 middleware 链在整个执行流程中的职责分工。
>
> 代码范围：以 `backend/packages/harness/deerflow/agents/` 为主。

补充专题：

- `../01-总览/01-Harness整体架构.md`：Harness 的全局分层和主执行链
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时状态与流式执行侧

---

## 1. 入口定位

仓库里有两条 agent 装配入口：

| 入口 | 位置 | 定位 |
|------|------|------|
| `make_lead_agent(config)` | `agents/lead_agent/agent.py` | 产品默认入口，读取全局配置和 runtime 参数 |
| `create_deerflow_agent(...)` | `agents/factory.py` | SDK 入口，纯参数装配，嵌入式复用 |

两者不是重复实现：

- `make_lead_agent` 面向 DeerFlow 产品，读 YAML 配置
- `create_deerflow_agent` 面向框架复用，接收纯 Python 参数

---

## 2. `make_lead_agent()` 的完整装配步骤

`make_lead_agent(config)` 接收的是 `RunnableConfig`，不是静态 agent profile。它从 `config["configurable"]` 动态解析运行模式：

| 参数 | 类型 | 用途 |
|------|------|------|
| `model_name` | `str | None` | 指定使用的模型 |
| `thinking_enabled` | `bool` | 是否启用 thinking 模式 |
| `reasoning_effort` | `str | None` | 推理强度 |
| `is_plan_mode` | `bool` | 是否为计划模式 |
| `subagent_enabled` | `bool` | 是否启用子代理 |
| `max_concurrent_subagents` | `int` | 子代理并发上限 |
| `is_bootstrap` | `bool` | 是否为初始化引导 |
| `agent_name` | `str | None` | 自定义 agent profile 名 |

### 2.1 装配流程图

```text
RunnableConfig
  |
  v
[1] 提取 runtime configurable
  |
  v
[2] 读取 agent profile 配置
    agents/<agent_name>/config.yaml
    ├── model: 指定模型
    ├── tool_groups: 指定工具组
    └── skills: 指定技能
  |
  v
[3] 解析最终模型名
    优先级: runtime override > agent profile > 全局默认
  |
  v
[4] create_chat_model(name, thinking_enabled, reasoning_effort)
    → 动态加载模型类
    → 合并 thinking 配置
    → 实例化
  |
  v
[5] get_available_tools(config, subagent_enabled, ...)
    → 普通工具（配置 + 反射）
    → built-in 工具（条件暴露）
    → MCP 工具（缓存读取）
    → 条件工具（task, view_image）
  |
  v
[6] _build_middlewares(...)
    → 共享 runtime middleware（8 个）
    → lead agent 增强 middleware（10 个）
  |
  v
[7] apply_prompt_template(model, tools, middlewares, ...)
    → 合成 system prompt
  |
  v
[8] create_agent(model, tools, middlewares, prompt, state_schema)
    → LangGraph create_agent
    → 返回可执行的 CompiledStateGraph
```

**lead agent 不是预先常驻的对象，而是"按 run 动态拼装"的**。

---

## 3. 模型选择的三层来源

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1（最高） | 请求级 `model_name` | 单次请求覆盖 |
| 2 | Agent profile `config.model` | 自定义 agent 配置 |
| 3（兜底） | 全局 `AppConfig.models[0]` | 默认模型 |

### 3.1 运行时修正

- 如果模型不支持 `thinking`，自动降级为非 thinking 模式
- `reasoning_effort` 写入 metadata，便于 tracing 和调试

---

## 4. 自定义 Agent 的实现方式

### 4.1 目录结构

```text
{DEER_FLOW_HOME}/agents/{agent_name}/
├── config.yaml    # agent profile
└── SOUL.md        # agent 人格和方法论
```

### 4.2 `config.yaml` 内容

```yaml
model: claude-sonnet-4.6    # 指定使用的模型
tool_groups:                # 指定工具组（覆盖全局配置）
  - web_search
  - code_execution
skills:                     # 指定启用的技能
  - data-analysis
  - report-writing
```

### 4.3 `SOUL.md` 内容

定义 agent 的身份、风格和行为约束。例如：

```markdown
# SOUL

You are a senior data analyst specializing in business intelligence.
- Always start by understanding the user's business context
- Prefer charts over raw tables when presenting data
- When uncertain about data sources, ask before proceeding
```

### 4.4 多 Agent 的本质

DeerFlow 的多 agent 不是多套独立引擎，而是：

- **同一个 lead agent 工厂**
- **不同的配置和 prompt profile**

运行时行为一致，安全和 middleware 约束天然复用。

---

## 5. Prompt 装配：运行时合成文档

`agents/lead_agent/prompt.py::apply_prompt_template(...)` 合成 system prompt。

### 5.1 Prompt Section 清单

| Section | 条件 | 内容 |
|---------|------|------|
| role | 总是 | 基础角色说明 |
| date | 总是 | 当前日期 |
| soul | `agent_name` 存在 | `SOUL.md` 内容 |
| memory context | 记忆启用 | 从记忆系统加载的内容 |
| thinking style | thinking 启用 | thinking 风格指导 |
| clarification system | 总是 | 澄清工作流约束 |
| skills section | 有启用的 skills | 工作流说明和领域知识 |
| deferred tools section | tool search 启用 | 延迟工具检索指导 |
| subagent section | subagent 启用 | 子代理使用指导（动态生成） |
| working directory | 总是 | 文件管理约束 |
| response style | 总是 | 回复风格 |
| citations | 总是 | 引用要求 |

### 5.2 Subagent Section 动态生成

`_build_subagent_section(max_concurrent)` 根据 runtime 能力面动态生成：

- 并发上限提示
- 可用 subagent 类型（general-purpose, bash）
- direct tool 与 task 的使用边界
- 如果 host bash 不允许，切换对 bash subagent 的说明

### 5.3 Memory Context 注入

`_get_memory_context(agent_name)` 从记忆系统加载：

1. 检查 `config.enabled` 和 `config.injection_enabled`
2. 加载记忆数据
3. 按 token 预算（默认 2000 tokens）格式化
4. 按 confidence 排序 facts
5. 包装成 `<memory>...</memory>` XML 块

---

## 6. Middleware 链的完整装配

### 6.1 两段式装配

`_build_middlewares()` 分两段：

1. `build_lead_runtime_middlewares(lazy_init=True)` → 共享 runtime 链
2. lead agent 追加业务增强和行为治理 middleware

### 6.2 共享 Runtime Middleware（8 个）

| # | 中间件 | 职责 | 前置依赖 |
|---|--------|------|----------|
| 1 | `ThreadDataMiddleware` | 计算线程目录路径 | 无 |
| 2 | `UploadsMiddleware` | 准备上传文件状态 | ThreadDataMiddleware |
| 3 | `SandboxMiddleware` | 获取/复用 sandbox | ThreadDataMiddleware |
| 4 | `DanglingToolCallMiddleware` | 修复悬挂的工具调用 | 无 |
| 5 | `LLMErrorHandlingMiddleware` | LLM 调用错误处理 | 无 |
| 6 | `GuardrailMiddleware` | 工具调用授权（可选） | 无 |
| 7 | `SandboxAuditMiddleware` | bash 命令风险审计 | 无 |
| 8 | `ToolErrorHandlingMiddleware` | 工具异常转 ToolMessage | 包住工具执行 |

### 6.3 Lead Agent 增强 Middleware（10 个）

| 中间件 | 条件 | 职责 |
|--------|------|------|
| `SummarizationMiddleware` | 配置启用 | 长对话摘要压缩 |
| `TodoMiddleware` | plan mode | 待办事项管理 |
| `TokenUsageMiddleware` | 配置启用 | Token 使用统计 |
| `TitleMiddleware` | 配置启用 | 自动生成线程标题 |
| `MemoryMiddleware` | 配置启用 | 记忆排队更新（after_agent） |
| `ViewImageMiddleware` | vision 模型 | 图像内容注入（before_agent） |
| `DeferredToolFilterMiddleware` | tool search 启用 | 延迟工具过滤 |
| `SubagentLimitMiddleware` | subagent 启用 | 子代理并发截断 |
| `LoopDetectionMiddleware` | 总是 | 循环检测与阻断 |
| `ClarificationMiddleware` | 总是（最后） | 澄清优先拦截 |

---

## 7. Middleware 顺序为什么不能随意换位

源码注释明确说明 middleware 次序不能随意换位，原因分三类：

### 7.1 数据依赖型

| 依赖 | 原因 |
|------|------|
| `ThreadDataMiddleware` 必须在 `SandboxMiddleware` 之前 | sandbox 获取需要 thread 目录路径 |
| `UploadsMiddleware` 要依赖 thread data | 上传目录在 thread 目录下 |
| `ViewImageMiddleware` 需要在模型继续推理前注入 | 图像内容影响模型后续输出 |

### 7.2 控制流兜底型

| 中间件 | 原因 |
|--------|------|
| `ToolErrorHandlingMiddleware` 要包住工具执行 | 异常必须被捕获并转成 ToolMessage |
| `ClarificationMiddleware` 被强制放最后 | 澄清请求是最终阶段的拦截信号 |

### 7.3 行为约束型

| 中间件 | 原因 |
|--------|------|
| `SubagentLimitMiddleware` 在 tool call 形成后截断 | 需要看到实际的工具调用才能计数 |
| `LoopDetectionMiddleware` 在行为发生后检测 | 需要分析工具调用模式 |

---

## 8. 双层治理：Prompt + Middleware

| 能力 | Prompt 层 | Middleware 层 |
|------|-----------|---------------|
| 澄清优先 | 告诉模型"先提问再行动" | `ClarificationMiddleware` 拦截澄清请求 |
| 子代理并发 | 告诉模型"每轮最多调用 N 次 task" | `SubagentLimitMiddleware` 裁剪超额调用 |
| 工具失败恢复 | 告诉模型"遇到错误请重试" | `ToolErrorHandlingMiddleware` 转异常为 ToolMessage |
| 循环检测 | 告诉模型"不要重复相同操作" | `LoopDetectionMiddleware` 检测并阻断 |

这类设计比"只写 prompt"更接近工程化 agent runtime。

---

## 9. `create_deerflow_agent()` 的 SDK 入口

`agents/factory.py` 不依赖 YAML 或全局单例：

```python
def create_deerflow_agent(
    model: BaseChatModel,
    tools: list,
    prompt: str,
    features: RuntimeFeatures | None = None,
    middlewares: list | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
```

### 9.1 做了什么

1. 接收纯 Python 参数
2. 根据 `RuntimeFeatures` 自动拼装最小 DeerFlow 风格 middleware 链
3. 调用 `langchain.agents.create_agent(...)`

### 9.2 与 `make_lead_agent` 的关系

- 共享相似的 middleware 顺序和执行语义
- 但 factory 是 config-free 的
- 某些运行时能力仍可能回读全局配置（如子代理）

更接近"轻量 SDK 化"，而不是完全脱离应用环境的纯内核。

---

## 10. `RuntimeFeatures` 特性标志

`agents/features.py` 定义了可启用的运行时特性：

```python
@dataclass
class RuntimeFeatures:
    memory: bool = False           # 记忆更新
    summarization: bool = False    # 对话摘要
    title: bool = False            # 标题生成
    todo: bool = False             # 待办管理
    clarification: bool = False    # 澄清优先
    loop_detection: bool = False   # 循环检测
```

`create_deerflow_agent()` 根据这些标志自动决定包含哪些 middleware。

---

## 11. 中间件的 before/after 钩子

中间件实现 `AgentMiddleware` 协议，有两个钩子：

| 钩子 | 时机 | 用途 |
|------|------|------|
| `before_agent(state, runtime)` | 模型推理前 | 注入上下文、预处理状态 |
| `after_agent(state, runtime)` | 模型推理后 | 后处理结果、排队更新 |

典型使用：

- `ViewImageMiddleware`：`before_agent` 注入图像内容
- `MemoryMiddleware`：`after_agent` 排队记忆更新
- `TitleMiddleware`：`after_agent` 生成标题

---

## 12. 总结

从实现上看，lead agent 装配最关键的不是 `create_agent(...)` 本身，而是它之前的一系列动态决策：

1. 这次 run 用哪个模型、什么模式
2. 该暴露哪些工具
3. 要不要启用 plan、vision、subagent、tool search
4. prompt 里要注入哪些 runtime section
5. middleware 链怎样排序，哪些约束要前置

理解 DeerFlow lead agent 的正确方式不是"它创建了一个 agent"，而是：

> 它把一组配置、能力面和运行时约束，**编译**成了一次具体可执行的 agent graph。

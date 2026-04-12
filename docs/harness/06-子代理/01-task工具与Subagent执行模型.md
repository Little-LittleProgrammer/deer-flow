# DeerFlow Harness task 工具与 Subagent 执行模型

> 目标：从当前实现出发，说明 DeerFlow 的子代理不是"模型自己轮询的小技巧"，而是一套由 `task` 工具、后台执行器和流式事件共同构成的执行模型。
>
> 代码范围：以 `backend/packages/harness/deerflow/tools/builtins/task_tool.py` 和 `subagents/` 为主。

补充专题：

- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：lead agent 的 subagent prompt 与 middleware 约束
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时和流式桥接侧

---

## 1. 子代理入口：`task` 工具

DeerFlow 里 lead agent 不会在代码路径里"偷偷 new 一个子 agent"。

子代理入口被显式设计成工具：

```python
# deerflow/tools/builtins/task_tool.py
def task_tool(
    subagent_type: str,
    description: str,
    expected_output: str,
    ...
) -> dict:
```

在模型视角里：

- 子代理是一种显式能力选择
- 与普通工具调用处在同一决策层

治理方式：

- **Prompt**：指导何时调用
- **Middleware**：`SubagentLimitMiddleware` 限制并发数量
- **Runtime**：`SubagentExecutor` 负责执行和流式回传

---

## 2. `task_tool` 完整调用链

```text
task(subagent_type="general-purpose", description="...", expected_output="...")
  |
  +-- 1. 校验 subagent_type
  |      必须是已注册的子代理类型
  |
  +-- 2. 检查 sandbox 是否允许该类型
  |      特别是 bash subagent，若 host bash 不允许则直接报错
  |
  +-- 3. 读取 SubagentConfig
  |      subagents/builtins/general_purpose.py
  |      subagents/builtins/bash_agent.py
  |
  +-- 4. 拼接 skills section 到 subagent system prompt
  |
  +-- 5. 继承父 runtime 上下文
  |      sandbox_state, thread_data, thread_id,
  |      model_name, trace_id
  |
  +-- 6. 重新获取子代理可用工具
  |      get_available_tools(..., subagent_enabled=False)
  |      ← 禁止递归 subagent
  |
  +-- 7. 创建 SubagentExecutor
  |
  +-- 8. 后台启动任务
  |      executor.execute(description, expected_output)
  |
  +-- 9. 后端轮询状态
  |      while not done:
  |          sleep(5s)
  |          result = get_background_task_result(task_id)
  |          if status_changed:
  |              stream_writer({"type": f"task_{status}", ...})
  |
  +-- 10. 返回最终结果给主 agent
  |       {"output": final_result, "status": "completed"}
```

---

## 3. 子代理为什么继承父上下文

| 继承项 | 目的 |
|--------|------|
| `sandbox_state` | 复用同一沙箱执行环境 |
| `thread_data` | 共享线程目录路径 |
| `thread_id` | 围绕同一个 thread 工作 |
| `model_name` | 使用与父代理相同的模型 |
| `trace_id` | 日志和运行链路可关联 |

### 3.1 共享线程工作区

父子代理围绕同一个 `thread_id` 工作，看到的是同一套 thread 目录和输出空间。

### 3.2 共享或复用 Sandbox

如果 provider 允许，父子代理可以沿同一线程上下文复用执行环境。

### 3.3 追踪链路可关联

`trace_id` 继承后，日志更容易把主代理与子任务串起来。

Subagent 不是完全独立的会话，而是同线程下的受控分工。

---

## 4. 为什么禁止递归 Subagent

`task_tool` 给子代理重新装配工具时，显式传入 `subagent_enabled=False`。

| 原因 | 说明 |
|------|------|
| 防止递归爆炸 | 子代理不能再开子代理 |
| 状态管理可控 | 避免多层 task 树让状态失控 |
| 保持模型简单 | 主代理编排，子代理执行 |

Subagent 定位是 **orchestrator / worker**，不是任意层级可递归分裂 agent swarm。

---

## 5. `SubagentExecutor`：子代理执行器

### 5.1 初始化输入

| 参数 | 类型 | 用途 |
|------|------|------|
| `config` | `SubagentConfig` | 子代理配置（名称、描述、模型） |
| `tools` | `list[BaseTool]` | 可用工具列表 |
| `parent_model` | `str | None` | 父模型信息 |
| `sandbox_state` | `dict` | 沙箱状态 |
| `thread_data` | `dict` | 线程数据 |
| `thread_id` | `str` | 线程 ID |
| `trace_id` | `str` | 追踪 ID |

### 5.2 子代理也是 `create_agent(...)`

```python
def _create_agent(self, ...):
    # 1. 解析最终模型
    model = create_chat_model(name=model_name, thinking_enabled=False)

    # 2. 构建 subagent middleware
    middlewares = build_subagent_runtime_middlewares(...)

    # 3. 构建 system prompt
    prompt = build_subagent_prompt(config, skills_section=...)

    # 4. 创建 agent
    agent = langchain.agents.create_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        middlewares=middlewares,
    )
```

子代理和主代理共享同一种 agent graph 执行内核，只是：

- prompt 不同（更专注于子任务）
- 工具集更窄（无递归 subagent）
- middleware 是 subagent 版本（无 title、memory 等）

---

## 6. Subagent 与 Lead Agent 的 Middleware 差异

| Middleware | Lead Agent | Subagent | 说明 |
|-----------|:----------:|:--------:|------|
| `ThreadDataMiddleware` | ✓ | ✓ | 共享 |
| `UploadsMiddleware` | ✓ | ✗ | 子代理不处理上传 |
| `SandboxMiddleware` | ✓ | ✓ | 共享 |
| `DanglingToolCallMiddleware` | ✓ | ✓ | 共享 |
| `LLMErrorHandlingMiddleware` | ✓ | ✓ | 共享 |
| `GuardrailMiddleware` | ✓ | ✓ | 共享 |
| `SandboxAuditMiddleware` | ✓ | ✓ | 共享 |
| `ToolErrorHandlingMiddleware` | ✓ | ✓ | 共享 |
| `SummarizationMiddleware` | ✓ | ✗ | 子代理不需要摘要 |
| `TodoMiddleware` | ✓ | ✗ | 子代理不需要待办 |
| `TokenUsageMiddleware` | ✓ | ✗ | 子代理不统计 token |
| `TitleMiddleware` | ✓ | ✗ | 子代理不生成标题 |
| `MemoryMiddleware` | ✓ | ✗ | 子代理不更新记忆 |
| `ViewImageMiddleware` | ✓ | ✗ | 子代理不处理图像 |
| `DeferredToolFilterMiddleware` | ✓ | ✗ | 子代理不需要延迟工具过滤 |
| `SubagentLimitMiddleware` | ✓ | ✗ | 子代理没有子代理 |
| `LoopDetectionMiddleware` | ✓ | ✓ | 共享 |
| `ClarificationMiddleware` | ✓ | ✗ | 子代理不向用户提问 |

子代理目标是专注完成子任务，不承担完整对话治理职责。

---

## 7. 后台执行：双层线程池

`subagents/executor.py` 有两层池：

| 池 | 职责 |
|----|------|
| `_scheduler_pool` | 调度与编排 |
| `_execution_pool` | 实际 agent 执行 |

分开处理的目的：

- 为 timeout 管理留出空间
- 后台状态跟踪与调度解耦
- 避免单个任务阻塞影响其他任务

Subagent 不是"直接 await 一个协程"，而是带有后台任务登记和超时管理的执行模型。

---

## 8. 后端轮询 vs 模型轮询

### 8.1 轮询机制

```python
# task_tool.py 中
while True:
    result = get_background_task_result(task_id)
    if result.status in ("completed", "failed", "timed_out"):
        break
    await stream_writer({
        "type": f"task_{result.status}",
        "message": result.ai_message,
    })
    await asyncio.sleep(5)
```

### 8.2 为什么后端做轮询

| 好处 | 说明 |
|------|------|
| 减少 token 消耗 | 模型不需要反复调用"查询状态"工具 |
| 避免机械循环 | 不让模型陷入"轮询状态工具"的循环 |
| 状态机下沉 | 复杂度下沉到程序，不靠 prompt 控制 |

DeerFlow 的一条明显原则：**机械控制逻辑尽量程序化，模型主要负责判断和综合**。

---

## 9. 子代理过程事件如何暴露给前端

`task_tool` 通过 `get_stream_writer()` 写出事件：

| 事件类型 | 时机 | 内容 |
|---------|------|------|
| `task_started` | 任务开始 | 任务描述 |
| `task_running` | 任务执行中 | 最新 AI message |
| `task_completed` | 任务完成 | 最终结果 |
| `task_failed` | 任务失败 | 错误信息 |
| `task_timed_out` | 任务超时 | 超时信息 |

前端或 SSE 消费方可以看到子任务进展，不是"静默等待异步任务"，而是"后台执行 + 可观测进度"。

---

## 10. `SubagentLimitMiddleware` 为什么必不可少

Prompt 中虽然写了每轮最多多少个 `task` 调用，但 prompt 不足以形成硬约束。

`SubagentLimitMiddleware(max_concurrent=N)` 的作用：

- 对单轮响应里的并行 task 调用数做截断
- 超额调用被静默丢弃或报错

DeerFlow 把 subagent 并发控制放在两层：

| 层 | 职责 |
|----|------|
| **Prompt** | 告诉模型如何批次化规划 |
| **Middleware** | 防止超额调用真的落地 |

---

## 11. Bash 子代理受 Sandbox 配置约束

当前可用的 subagent 类型根据 sandbox 能力动态变化：

- 若 host bash 不允许，`task_tool` 直接返回错误
- prompt 里的 subagent section 也会同步提示 bash 不可用

双层策略：

- **Prompt 中**：能力说明同步
- **程序逻辑中**：硬阻断落实

---

## 12. 子代理注册与配置

### 12.1 内置子代理

| 名称 | 文件 | 用途 |
|------|------|------|
| `general-purpose` | `subagents/builtins/general_purpose.py` | 通用子代理 |
| `bash` | `subagents/builtins/bash_agent.py` | Bash 执行子代理 |

### 12.2 子代理配置

`SubagentConfig` 定义在 `subagents/config.py`：

```python
@dataclass
class SubagentConfig:
    name: str                   # 唯一名称
    description: str            # 描述
    model: str | None           # 模型（默认继承父模型）
    system_prompt: str          # 系统提示
    tool_groups: list[str]      # 工具组
```

### 12.3 注册表

`subagents/registry.py` 管理子代理注册：

```python
def list_subagents() -> list[str]:
    """列出所有可用子代理名称"""

def get_subagent_config(name: str) -> SubagentConfig:
    """获取子代理配置"""

def get_available_subagent_names() -> list[str]:
    """获取可用子代理名称列表"""
```

---

## 13. 当前实现的边界

### 13.1 结果登记依赖进程内全局表

`_background_tasks` 是进程内全局存储，不是持久化任务队列。

### 13.2 轮询间隔是固定的

当前是 5 秒一次，属于简单可靠优先，而不是极致实时。

### 13.3 子代理更偏单层编排模型

默认禁止嵌套 task，不是多层级自治 agent swarm。

---

## 14. 总结

DeerFlow 当前的 subagent 核心机制：

> `task` 负责把委派显式化，`SubagentExecutor` 负责后台执行，后端轮询和流式事件负责把进度与结果带回主链路。

理解 subagent 的三个关键判断：

| 维度 | 说明 |
|------|------|
| **模型职责** | 决定何时拆、怎么拆 |
| **Runtime 职责** | 并行执行、状态轮询、结果回传 |
| **边界** | 禁止递归、单层编排、同线程协作 |

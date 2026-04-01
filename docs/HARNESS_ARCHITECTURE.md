# DeerFlow Harness 工程实现架构

> 本文档详细描述 Harness 框架包 (`deerflow-harness`) 的内部实现架构。

---

## 一、概述

**Harness** 是 DeerFlow 的核心 Agent 框架包，是一个**可独立发布**的 Python 包，提供了构建和运行 AI Agent 所需的全部能力。

**核心定位**：
- 可发布的框架包 (`backend/packages/harness/`)
- 导入前缀: `deerflow.*`
- 与 `app/` 层严格隔离：harness **不能**导入 app

**模块结构**：

```
backend/packages/harness/deerflow/
├── agents/              # Agent 系统
│   ├── lead_agent/      # Lead Agent 入口工厂
│   ├── middlewares/     # 14 个中间件组件
│   ├── memory/          # 记忆系统
│   └── thread_state.py  # ThreadState 状态定义
├── sandbox/             # 沙箱执行系统
├── subagents/           # 子代理委托系统
├── tools/               # 工具系统
│   └── builtins/        # 内置工具
├── mcp/                 # MCP 集成
├── models/              # LLM 模型工厂
├── skills/              # Skills 发现系统
├── config/              # 配置加载系统
├── reflection/          # 动态模块加载
├── runtime/             # 运行时支持
├── community/           # 社区工具扩展
├── guardrails/          # 工具调用授权
└── client.py            # 嵌入式 Python 客户端
```

---

## 二、核心架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DeerFlow Harness                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Agent 系统                                    │    │
│  │  ┌───────────────┐   ┌────────────────────────────────────────────┐ │    │
│  │  │  Lead Agent   │ → │        Middleware Chain (14个中间件)        │ │    │
│  │  │  (入口工厂)   │   │ ThreadData → Sandbox → Guardrails → ...    │ │    │
│  │  └───────────────┘   └────────────────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│  ┌──────────────┬──────────────────┼──────────────────┬────────────────┐   │
│  │              │                  │                  │                │   │
│  ▼              ▼                  ▼                  ▼                ▼   │
│ ┌────────┐ ┌──────────┐ ┌────────────────┐ ┌─────────────┐ ┌────────────┐ │
│ │ Models │ │  Tools   │ │    Sandbox     │ │  Subagents  │ │    MCP     │ │
│ │ Factory│ │  System  │ │    System      │ │   System    │ │  Integration│ │
│ └────────┘ └──────────┘ └────────────────┘ └─────────────┘ └────────────┘ │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        配置系统                                      │   │
│  │  AppConfig (config.yaml) + ExtensionsConfig (extensions_config.json)│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      支撑系统                                        │   │
│  │  Memory | Skills | Reflection | Runtime | Client                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心组件详解

### 3.1 Agent 系统

**入口文件**: `deerflow/agents/lead_agent/agent.py`

#### make_lead_agent() 工厂函数

```python
def make_lead_agent(config: RunnableConfig) -> CompiledStateGraph:
    # 1. 解析运行时配置
    thinking_enabled = cfg.get("thinking_enabled", True)
    model_name = cfg.get("model_name")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)

    # 2. 创建 LLM 模型
    model = create_chat_model(name=model_name, thinking_enabled=thinking_enabled)

    # 3. 加载工具集
    tools = get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled)

    # 4. 构建中间件链
    middlewares = _build_middlewares(config, model_name=model_name)

    # 5. 生成系统提示
    system_prompt = apply_prompt_template(subagent_enabled=subagent_enabled, ...)

    # 6. 创建 Agent
    return create_agent(
        model=model,
        tools=tools,
        middleware=middlewares,
        system_prompt=system_prompt,
        state_schema=ThreadState,
    )
```

#### ThreadState 状态结构

**文件**: `deerflow/agents/thread_state.py`

```python
class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]           # 沙箱 ID
    thread_data: NotRequired[ThreadDataState | None]    # 线程数据路径
    title: NotRequired[str | None]                      # 自动标题
    artifacts: Annotated[list[str], merge_artifacts]    # 产物列表 (自动去重)
    todos: NotRequired[list | None]                     # 任务列表
    uploaded_files: NotRequired[list[dict] | None]      # 上传文件
    viewed_images: Annotated[dict, merge_viewed_images] # 已查看图像
```

**自定义 Reducer**:

```python
def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """合并并去重 artifacts"""
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))

def merge_viewed_images(existing: dict | None, new: dict | None) -> dict:
    """合并图像字典，空字典表示清空"""
    if len(new) == 0:
        return {}  # 特殊情况：清空
    return {**existing, **new}
```

---

### 3.2 中间件链

**构建函数**: `_build_middlewares()` in `agent.py`

#### 执行顺序

| 序号 | 中间件 | 职责 | 条件 |
|------|--------|------|------|
| 1 | `build_lead_runtime_middlewares()` | 基础运行时中间件组 | 始终 |
| 2 | `SummarizationMiddleware` | 上下文摘要 | 配置启用 |
| 3 | `TodoMiddleware` | 任务跟踪 | `is_plan_mode=True` |
| 4 | `TokenUsageMiddleware` | Token 使用统计 | 配置启用 |
| 5 | `TitleMiddleware` | 自动生成标题 | 始终 |
| 6 | `MemoryMiddleware` | 对话记忆队列 | 始终 |
| 7 | `ViewImageMiddleware` | 图像 base64 注入 | 模型支持视觉 |
| 8 | `DeferredToolFilterMiddleware` | 工具延迟加载 | `tool_search.enabled` |
| 9 | `SubagentLimitMiddleware` | 限制并发子代理 | `subagent_enabled=True` |
| 10 | `LoopDetectionMiddleware` | 检测循环工具调用 | 始终 |
| 11 | `ClarificationMiddleware` | 拦截澄清请求 | **必须最后** |

#### 基础运行时中间件组

`build_lead_runtime_middlewares()` 包含:

1. **ThreadDataMiddleware** - 创建线程隔离目录
2. **UploadsMiddleware** - 注入上传文件信息
3. **SandboxMiddleware** - 获取沙箱环境
4. **DanglingToolCallMiddleware** - 修复缺失的 ToolMessage
5. **GuardrailMiddleware** - 工具调用授权 (可选)
6. **ToolErrorHandling** - 工具异常处理

#### SandboxMiddleware 示例

**文件**: `deerflow/sandbox/middleware.py`

```python
class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    def __init__(self, lazy_init: bool = True):
        self._lazy_init = lazy_init

    def before_agent(self, state, runtime):
        if self._lazy_init:
            return  # 延迟初始化：首次工具调用时获取
        thread_id = runtime.context.get("thread_id")
        sandbox_id = self._acquire_sandbox(thread_id)
        return {"sandbox": {"sandbox_id": sandbox_id}}

    def after_agent(self, state, runtime):
        sandbox = state.get("sandbox")
        if sandbox:
            get_sandbox_provider().release(sandbox["sandbox_id"])
```

---

### 3.3 Sandbox 执行系统

#### 抽象接口

**文件**: `deerflow/sandbox/sandbox.py`

```python
class Sandbox(ABC):
    _id: str

    @abstractmethod
    def execute_command(self, command: str) -> str:
        """执行 bash 命令"""

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容"""

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False):
        """写入文件"""

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出目录内容"""
```

#### Provider 模式

```python
class SandboxProvider(ABC):
    def acquire(self, thread_id: str) -> str      # 获取沙箱
    def get(self, sandbox_id: str) -> Sandbox     # 获取实例
    def release(self, sandbox_id: str)            # 释放资源
```

#### 虚拟路径映射

```
Agent 视角 (虚拟路径)              实际物理路径
─────────────────────────────────────────────────────────────────
/mnt/user-data/workspace      →    .deer-flow/threads/{id}/user-data/workspace
/mnt/user-data/uploads        →    .deer-flow/threads/{id}/user-data/uploads
/mnt/user-data/outputs        →    .deer-flow/threads/{id}/user-data/outputs
/mnt/skills                   →    skills/ (项目根目录)
/mnt/acp-workspace            →    .deer-flow/threads/{id}/acp-workspace
```

**设计原理**: Agent 只看到统一的虚拟路径，物理路径由系统自动映射，实现线程隔离和跨平台兼容。

#### 实现类型

| 类型 | 类路径 | 使用场景 |
|------|--------|----------|
| **Local** | `deerflow.sandbox.local:LocalSandboxProvider` | 本地开发 |
| **Docker** | `deerflow.community.aio_sandbox:AioSandboxProvider` | 生产环境 |

#### Sandbox 工具

| 工具 | 函数 | 说明 |
|------|------|------|
| `bash` | `bash_tool()` | 执行命令 (带路径转换) |
| `ls` | `ls_tool()` | 列出目录 (树形) |
| `read_file` | `read_file_tool()` | 读取文件 |
| `write_file` | `write_file_tool()` | 写入文件 |
| `str_replace` | `str_replace_tool()` | 字符串替换 |

---

### 3.4 Subagent 系统

#### SubagentConfig 结构

**文件**: `deerflow/subagents/config.py`

```python
@dataclass
class SubagentConfig:
    name: str                    # 唯一标识
    description: str             # 何时委托
    system_prompt: str           # 行为指导
    tools: list[str] | None      # 允许的工具
    disallowed_tools: list[str]  # 禁止的工具
    model: str = "inherit"       # 模型选择
    max_turns: int = 50          # 最大轮次
    timeout_seconds: int = 900   # 超时时间 (15分钟)
```

#### 内置子代理

| 名称 | 用途 | 工具限制 |
|------|------|----------|
| `general-purpose` | 复杂多步骤任务 | 禁止 `task`, `ask_clarification` |
| `bash` | 命令执行专家 | 仅限 sandbox 工具 |

#### SubagentExecutor 执行器

**文件**: `deerflow/subagents/executor.py`

```python
class SubagentExecutor:
    def __init__(self, config, tools, parent_model, sandbox_state, thread_data, ...):
        self.tools = _filter_tools(tools, config.tools, config.disallowed_tools)

    def execute(self, task: str) -> SubagentResult:
        """同步执行 (包装异步)"""
        return asyncio.run(self._aexecute(task))

    def execute_async(self, task: str) -> str:
        """后台执行，返回 task_id"""
        task_id = str(uuid.uuid4())[:8]
        _scheduler_pool.submit(run_task)
        return task_id
```

#### 双线程池架构

```python
_scheduler_pool = ThreadPoolExecutor(max_workers=3)   # 调度池
_execution_pool = ThreadPoolExecutor(max_workers=3)   # 执行池
MAX_CONCURRENT_SUBAGENTS = 3                           # 并发上限
```

#### 执行流程

```
Lead Agent 调用 task 工具
    ↓
SubagentExecutor 创建独立 Agent
    ├─ 过滤工具 (允许/禁止列表)
    ├─ 继承 sandbox/thread_data
    └─ 设置独立系统提示
    ↓
_scheduler_pool 提交任务
    ↓
_execution_pool 执行 (超时控制 15min)
    ↓
轮询结果 (5s 间隔)
    ↓
返回 SubagentResult
    ├─ task_started
    ├─ task_running
    └─ task_completed / task_failed / task_timed_out
```

---

### 3.5 模型工厂

**文件**: `deerflow/models/factory.py`

#### create_chat_model() 核心函数

```python
def create_chat_model(name: str | None = None, thinking_enabled: bool = False, **kwargs) -> BaseChatModel:
    config = get_app_config()
    model_config = config.get_model_config(name)

    # 反射加载模型类
    model_class = resolve_class(model_config.use, BaseChatModel)

    # 处理 thinking 配置
    if thinking_enabled and model_config.when_thinking_enabled:
        model_settings.update(model_config.when_thinking_enabled)

    # 处理 reasoning_effort
    if not model_config.supports_reasoning_effort:
        kwargs.pop("reasoning_effort", None)

    # 实例化模型
    return model_class(**model_settings, **kwargs)
```

#### 支持的特性

| 特性 | 配置字段 | 说明 |
|------|----------|------|
| 扩展思考 | `supports_thinking` | 启用模型深度思考 |
| 视觉输入 | `supports_vision` | 支持图像理解 |
| 推理力度 | `supports_reasoning_effort` | low/medium/high |
| Codex API | `use_responses_api` | OpenAI Responses API |

#### 配置示例

```yaml
models:
  - name: claude-sonnet-4
    use: langchain_anthropic:ChatAnthropic
    model: claude-sonnet-4-20250514
    supports_thinking: true
    supports_vision: true
    when_thinking_enabled:
      thinking:
        type: enabled
        budget_tokens: 10000
```

---

### 3.6 工具系统

**文件**: `deerflow/tools/tools.py`

#### get_available_tools() 组装逻辑

```python
def get_available_tools(groups=None, include_mcp=True, model_name=None, subagent_enabled=False):
    tools = []

    # 1. 配置定义的工具 (从 config.yaml)
    tools.extend([resolve_variable(t.use, BaseTool) for t in config.tools])

    # 2. 内置工具
    tools.extend([present_file_tool, ask_clarification_tool])

    # 3. 子代理工具 (条件)
    if subagent_enabled:
        tools.append(task_tool)

    # 4. 视觉工具 (条件)
    if model_config.supports_vision:
        tools.append(view_image_tool)

    # 5. MCP 工具 (从缓存)
    if include_mcp:
        tools.extend(get_cached_mcp_tools())

    # 6. ACP 代理工具
    if acp_agents:
        tools.append(build_invoke_acp_agent_tool(acp_agents))

    # 7. 工具搜索 (延迟加载)
    if config.tool_search.enabled:
        tools.append(tool_search_tool)

    return tools
```

#### 内置工具

| 工具 | 功能 |
|------|------|
| `present_files` | 展示输出文件给用户 |
| `ask_clarification` | 请求用户澄清 |
| `view_image` | 读取图像为 base64 |
| `task` | 委托给子代理 |
| `tool_search` | 搜索延迟加载的工具 |

#### 工具过滤

```python
# 安全检查：LocalSandboxProvider 时默认不暴露 host bash
if not is_host_bash_allowed(config):
    tool_configs = [t for t in tool_configs if not _is_host_bash_tool(t)]
```

---

### 3.7 MCP 集成

**文件**: `deerflow/mcp/tools.py`

#### get_mcp_tools() 加载流程

```python
async def get_mcp_tools() -> list[BaseTool]:
    extensions_config = ExtensionsConfig.from_file()
    servers_config = build_servers_config(extensions_config)

    # 创建多服务器客户端
    client = MultiServerMCPClient(servers_config, tool_interceptors=[...])

    # 获取所有工具
    tools = await client.get_tools()

    # 为异步工具创建同步包装器
    for tool in tools:
        if tool.coroutine and not tool.func:
            tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)

    return tools
```

#### 同步包装器

```python
def _make_sync_tool_wrapper(coro, tool_name):
    def sync_wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 使用全局线程池避免嵌套循环
            future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, coro(*args, **kwargs))
            return future.result()
        else:
            return asyncio.run(coro(*args, **kwargs))

    return sync_wrapper
```

#### 支持的传输类型

| 类型 | 配置字段 | 说明 |
|------|----------|------|
| `stdio` | `command`, `args` | 命令行启动 |
| `sse` | `url`, `headers` | Server-Sent Events |
| `http` | `url`, `headers` | HTTP 流 |

#### OAuth 支持

- 自动 token 刷新
- Authorization header 注入
- 支持 `client_credentials` 和 `refresh_token` 流程

---

### 3.8 配置系统

#### AppConfig 主配置

**文件**: `deerflow/config/app_config.py`

```python
class AppConfig(BaseModel):
    log_level: str = "info"
    token_usage: TokenUsageConfig
    models: list[ModelConfig]
    sandbox: SandboxConfig
    tools: list[ToolConfig]
    tool_groups: list[ToolGroupConfig]
    skills: SkillsConfig
    extensions: ExtensionsConfig
    tool_search: ToolSearchConfig
    checkpointer: CheckpointerConfig | None
    stream_bridge: StreamBridgeConfig | None
```

#### 配置加载优先级

```
1. 显式传入 config_path 参数
2. DEER_FLOW_CONFIG_PATH 环境变量
3. 当前目录 config.yaml
4. 父目录 config.yaml (推荐位置)
```

#### 热重载机制

```python
def get_app_config() -> AppConfig:
    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)

    should_reload = (
        _app_config is None or
        _app_config_path != resolved_path or
        _app_config_mtime != current_mtime
    )

    if should_reload:
        return _load_and_cache_app_config(str(resolved_path))
    return _app_config
```

#### 环境变量替换

```python
@classmethod
def resolve_env_variables(cls, config: Any) -> Any:
    if isinstance(config, str) and config.startswith("$"):
        return os.getenv(config[1:])
    # 递归处理 dict 和 list
```

#### ExtensionsConfig 扩展配置

**文件**: `deerflow/config/extensions_config.py`

```python
class ExtensionsConfig(BaseModel):
    mcp_servers: dict[str, McpServerConfig]
    skills: dict[str, SkillStateConfig]
```

---

### 3.9 嵌入式客户端

**文件**: `deerflow/client.py`

#### DeerFlowClient 类

```python
class DeerFlowClient:
    def __init__(
        self,
        config_path: str | None = None,
        checkpointer = None,
        model_name: str | None = None,
        thinking_enabled: bool = True,
        subagent_enabled: bool = False,
        plan_mode: bool = False,
        agent_name: str | None = None,
        middlewares: Sequence[AgentMiddleware] | None = None,
    ):
        # 延迟创建 Agent
        self._agent = None
        self._agent_config_key = None
```

#### 核心方法

| 方法 | 说明 |
|------|------|
| `stream(message, thread_id)` | 流式响应，返回 `StreamEvent` |
| `chat(message, thread_id)` | 同步响应，返回最终文本 |
| `reset_agent()` | 强制重建 Agent |

#### StreamEvent 事件类型

```python
@dataclass
class StreamEvent:
    type: str    # "values" | "messages-tuple" | "end"
    data: dict
```

- `"values"`: 完整状态快照
- `"messages-tuple"`: 单条消息更新
- `"end"`: 流结束

#### Gateway 等价方法

| 分类 | 方法 | 返回格式 |
|------|------|----------|
| Models | `list_models()`, `get_model(name)` | dict |
| MCP | `get_mcp_config()`, `update_mcp_config(servers)` | dict |
| Skills | `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)` | dict |
| Memory | `get_memory()`, `reload_memory()`, `get_memory_config()` | dict |
| Uploads | `upload_files(thread_id, files)`, `list_uploads(thread_id)` | dict |
| Artifacts | `get_artifact(thread_id, path)` | `tuple[bytes, str]` |

---

## 四、设计模式应用

| 模式 | 应用场景 | 代码位置 |
|------|----------|----------|
| **抽象工厂** | `SandboxProvider` 创建不同类型沙箱 | `sandbox/sandbox.py` |
| **策略模式** | 不同 `Sandbox` 实现 | `sandbox/local/`, `community/aio_sandbox/` |
| **责任链** | Middleware Chain 顺序执行 | `agents/lead_agent/agent.py:_build_middlewares()` |
| **单例模式** | 配置/沙箱提供者缓存 | `config/app_config.py:get_app_config()` |
| **观察者模式** | Memory 队列、MessageBus | `agents/memory/queue.py` |
| **线程池** | Subagent 后台执行 | `subagents/executor.py` |
| **反射** | 动态加载模型类/工具函数 | `reflection/resolvers.py` |

---

## 五、扩展点总览

| 扩展点 | 方式 | 配置位置 |
|--------|------|----------|
| 自定义模型 | `models[].use` 类路径 | `config.yaml` |
| 自定义工具 | `tools[].use` 函数路径 | `config.yaml` |
| 自定义沙箱 | 实现 `Sandbox` + `SandboxProvider` | `config.yaml: sandbox.use` |
| 自定义中间件 | `custom_middlewares` 参数 | 运行时传入 |
| 自定义子代理 | 注册到 `BUILTIN_SUBAGENTS` | `subagents/builtins/` |
| MCP 服务器 | `mcpServers` 配置 | `extensions_config.json` |
| Skills | 目录结构 | `skills/custom/` |
| ACP 代理 | `acp_agents` 配置 | `config.yaml` |

---

## 六、关键文件索引

| 功能模块 | 核心文件 |
|----------|----------|
| Agent 入口 | `agents/lead_agent/agent.py` |
| 状态定义 | `agents/thread_state.py` |
| 系统提示 | `agents/lead_agent/prompt.py` |
| 中间件 | `agents/middlewares/*.py` |
| 记忆系统 | `agents/memory/updater.py`, `queue.py` |
| 沙箱抽象 | `sandbox/sandbox.py` |
| 沙箱工具 | `sandbox/tools.py` |
| 子代理执行 | `subagents/executor.py` |
| 子代理配置 | `subagents/config.py`, `registry.py` |
| 模型工厂 | `models/factory.py` |
| 工具组装 | `tools/tools.py` |
| 内置工具 | `tools/builtins/*.py` |
| MCP 工具 | `mcp/tools.py`, `mcp/client.py` |
| 主配置 | `config/app_config.py` |
| 扩展配置 | `config/extensions_config.py` |
| 动态加载 | `reflection/resolvers.py` |
| 嵌入式客户端 | `client.py` |

---

## 七、阅读路径建议

按以下顺序深入理解 Harness 工程:

1. **配置系统** (`config/app_config.py`) → 理解配置加载和热重载
2. **Agent 入口** (`agents/lead_agent/agent.py`) → 理解 Agent 创建流程
3. **中间件链** (`agents/middlewares/`) → 理解请求处理管道
4. **Sandbox** (`sandbox/sandbox.py`, `middleware.py`) → 理解虚拟路径和生命周期
5. **工具系统** (`tools/tools.py`) → 理解工具组装逻辑
6. **子代理** (`subagents/executor.py`) → 理解后台执行机制
7. **客户端** (`client.py`) → 理解嵌入式使用方式
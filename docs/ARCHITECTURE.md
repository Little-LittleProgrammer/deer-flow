# DeerFlow 项目架构详解

> 本文档面向新人，详细介绍 DeerFlow 的整体架构、核心组件和设计原理。

---

## 一、项目概述

**DeerFlow** 是一个全栈"超级 Agent 框架"(Super Agent Harness)，能够编排子代理、记忆系统和沙箱执行环境，通过可扩展的 Skills 系统完成几乎任何任务。

### 技术栈

| 层级 | 技术 |
|------|------|
| **Backend** | Python 3.12+, LangGraph + FastAPI, Sandbox/Tool 系统, MCP 集成 |
| **Frontend** | Next.js 16 + React 19 + TypeScript 5.8 + Tailwind CSS 4 + pnpm 10.26.2 |
| **代理层** | nginx (统一入口) |
| **本地开发** | `make dev` 启动所有服务于 `http://localhost:2026` |

---

## 二、服务拓扑架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Browser                                          │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         nginx (Port 2026)                                     │
│                         统一入口，反向代理                                     │
└──────────────────────────────────────────────────────────────────────────────┘
          │                       │                       │
          │ /                     │ /api/*                │ /api/langgraph/*
          ▼                       ▼                       ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────────────┐
│   Frontend (3000)    │ │   Gateway API (8001) │ │   LangGraph Server (2024)    │
│   Next.js App Router │ │   FastAPI            │ │   Agent 核心引擎             │
│   React 组件 + UI    │ │   业务 API 路由      │ │   Lead Agent + Subagents     │
│   用户界面层         │ │   Artifacts/Memory   │ │   Middleware Chain           │
│                      │ │   Skills/MCP 管理    │ │   Tools + Sandbox            │
└──────────────────────┘ └──────────────────────┘ └──────────────────────────────┘
```

### 各服务职责

| 服务 | 端口 | 职责 |
|------|------|------|
| **nginx** | 2026 | 统一入口，路由分发，静态资源 |
| **Frontend** | 3000 | 用户界面，聊天交互，状态管理 |
| **Gateway API** | 8001 | 业务 API：模型列表、Skills、Artifacts、Threads |
| **LangGraph Server** | 2024 | Agent 执行引擎，流式响应 |

---

## 三、项目目录结构

```
deer-flow/
├── Makefile                    # 根命令入口
├── config.yaml                 # 主配置文件
├── extensions_config.json      # MCP/Skills 扩展配置
├── docker/nginx/               # nginx 配置
│
├── backend/                    # 后端应用
│   ├── packages/harness/       # deerflow-harness 包 (import: deerflow.*)
│   │   └── deerflow/
│   │       ├── agents/         # Agent 系统 (Lead Agent, Middleware)
│   │       ├── sandbox/        # Sandbox 执行系统
│   │       ├── subagents/      # Subagent 委托系统
│   │       ├── mcp/            # MCP 集成
│   │       ├── models/         # LLM 模型工厂
│   │       ├── skills/         # Skills 发现系统
│   │       ├── config/         # 配置加载
│   │       └── middlewares/    # Agent 中间件
│   ├── app/                    # 应用层 (import: app.*)
│   │   ├── gateway/            # FastAPI Gateway API
│   │   └── channels/           # IM 平台集成 (飞书/Slack/Telegram)
│   └── tests/                  # 测试套件
│
├── frontend/                   # 前端应用
│   └── src/
│       ├── app/                # Next.js App Router
│       ├── components/         # React 组件
│       │   ├── ui/             # Shadcn UI 基础组件
│       │   ├── ai-elements/    # AI 交互组件
│       │   ├── workspace/      # 工作台组件
│       │   └── landing/        # 落地页组件
│       └── core/               # 业务逻辑层
│           ├── api/            # LangGraph 客户端
│           ├── threads/        # 线程管理
│           ├── artifacts/      # 工件加载
│           ├── i18n/           # 国际化
│           ├── settings/       # 用户设置
│           └── memory/         # 记忆系统
│
└── skills/                     # Agent Skills 目录
    ├── public/                 # 内置技能 (Git tracked)
    └── custom/                 # 自定义技能 (.gitignore)
```

### 关键边界规则

**Harness/App 分离**: `app/` 可以导入 `deerflow/`，但 `deerflow/` **绝对不能**导入 `app/`。

此规则由 `tests/test_harness_boundary.py` 在 CI 中强制执行。

---

## 四、Backend 核心架构

### 4.1 Agent 系统

#### Lead Agent 入口

**文件**: `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

```python
def make_lead_agent(config: RunnableConfig) -> CompiledStateGraph:
    """
    创建 Lead Agent 实例

    关键配置参数:
    - thinking_enabled: 启用模型扩展思考
    - model_name: 选择特定 LLM
    - is_plan_mode: 启用 TodoList 中间件
    - subagent_enabled: 启用任务委托
    - max_concurrent_subagents: 并发子代理上限
    """
```

#### ThreadState - Agent 状态

```python
class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]           # 沙箱 ID
    thread_data: NotRequired[ThreadDataState | None]    # 线程数据
    title: NotRequired[str | None]                      # 自动标题
    artifacts: Annotated[list[str], merge_artifacts]    # 产物列表
    todos: NotRequired[list | None]                     # 任务列表
    uploaded_files: NotRequired[list[dict] | None]      # 上传文件
    viewed_images: Annotated[dict, merge_viewed_images] # 已查看图像
```

#### 中间件链 (14 个中间件)

```
请求处理管道执行顺序:

1. ThreadDataMiddleware    → 创建线程隔离目录
2. UploadsMiddleware       → 注入上传文件
3. SandboxMiddleware       → 获取沙箱环境
4. DanglingToolCall        → 修复缺失 ToolMessage
5. GuardrailMiddleware     → 工具调用授权 (可选)
6. ToolErrorHandling       → 工具异常处理
7. SummarizationMiddleware → 上下文摘要 (可选)
8. TodoMiddleware          → 任务跟踪 (plan_mode)
9. TitleMiddleware         → 自动生成标题
10. MemoryMiddleware       → 对话记忆队列
11. ViewImageMiddleware    → 图像 base64 注入 (vision)
12. SubagentLimitMiddleware→ 限制并发 task 调用
13. LoopDetectionMiddleware→ 检测循环工具调用
14. ClarificationMiddleware→ 拦截澄清请求 (必须最后)
```

#### 系统提示结构

```xml
<role>DeerFlow 2.0 - open-source super agent</role>
<soul>agent personality</soul>
<memory>记忆上下文</memory>
<thinking_style>思考模式指导</thinking_style>
<skill_system>可用技能列表</skill_system>
<subagent_system>子代理委托指导</subagent_system>
<working_directory>
  /mnt/user-data/uploads   → 用户上传
  /mnt/user-data/workspace → 临时工作
  /mnt/user-data/outputs   → 最终产物
</working_directory>
<response_style>响应风格</response_style>
```

### 4.2 Sandbox 执行系统

#### 抽象接口

```python
class Sandbox(ABC):
    def execute_command(self, command: str) -> str  # 执行 bash
    def read_file(self, path: str) -> str           # 读取文件
    def write_file(self, path: str, content: str)   # 写入文件
    def list_dir(self, path: str, max_depth=2)      # 列出目录

class SandboxProvider(ABC):
    def acquire(self, thread_id: str) -> str        # 获取沙箱
    def get(self, sandbox_id: str) -> Sandbox       # 获取实例
    def release(self, sandbox_id: str)              # 释放资源
```

#### 虚拟路径映射

```
Agent 视角 (虚拟路径)          →    实际物理路径
─────────────────────────────────────────────────────
/mnt/user-data/workspace      →    backend/.deer-flow/threads/{id}/user-data/workspace
/mnt/user-data/uploads        →    backend/.deer-flow/threads/{id}/user-data/uploads
/mnt/user-data/outputs        →    backend/.deer-flow/threads/{id}/user-data/outputs
/mnt/skills                   →    skills/ (项目根目录)
```

**设计原理**: Agent 只看到统一的虚拟路径，物理路径由系统自动映射，实现线程隔离和跨平台兼容。

#### Sandbox 工具

| 工具 | 函数 | 说明 |
|------|------|------|
| `bash` | `bash_tool()` | 执行命令 (带路径转换) |
| `ls` | `ls_tool()` | 列出目录 (树形) |
| `read_file` | `read_file_tool()` | 读取文件 |
| `write_file` | `write_file_tool()` | 写入文件 |
| `str_replace` | `str_replace_tool()` | 字符串替换 |

#### 沙箱类型

| 类型 | 类路径 | 使用场景 |
|------|--------|----------|
| **Local** | `deerflow.sandbox.local:LocalSandboxProvider` | 本地开发 |
| **Docker** | `deerflow.community.aio_sandbox:AioSandboxProvider` | 生产环境 |

### 4.3 Subagent 系统

#### SubagentConfig 结构

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
    timeout_seconds: int = 900   # 超时时间
```

#### 内置子代理

| 名称 | 用途 | 工具限制 |
|------|------|----------|
| `general-purpose` | 复杂多步骤任务 | 禁止 `task`, `ask_clarification` |
| `bash` | 命令执行专家 | 仅限 sandbox 工具 |

#### 执行流程

```
Lead Agent 调用 task 工具
    ↓
SubagentExecutor 创建独立 Agent
    ↓ (过滤工具，继承 sandbox/thread_data)
后台线程池异步执行
    ↓ (超时控制)
返回 SubagentResult
    ↓
Lead Agent 整合结果继续执行
```

**并发限制**: 默认最多 3 个并发 task 调用。

### 4.4 MCP 集成

#### 服务器配置格式

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "$GITHUB_TOKEN" }
    },
    "postgres": {
      "enabled": true,
      "type": "sse",
      "url": "https://mcp.example.com/sse",
      "headers": { "Authorization": "Bearer xxx" }
    }
  }
}
```

#### 工具加载流程

```
extensions_config.json → build_servers_config → MultiServerMCPClient → get_tools()
    ↓
为异步工具创建同步包装器 (线程池执行)
    ↓
注入到 Lead Agent 可用工具列表
```

---

## 五、Gateway API 架构

### 5.1 主要路由

| 路由 | 文件 | 职责 |
|------|------|------|
| `/api/models` | `routers/models.py` | 模型列表 |
| `/api/mcp` | `routers/mcp.py` | MCP 配置管理 |
| `/api/skills` | `routers/skills.py` | Skills 管理 |
| `/api/memory` | `routers/memory.py` | 记忆 CRUD |
| `/api/threads` | `routers/threads.py` | 线程管理 |
| `/api/threads/{id}/artifacts` | `routers/artifacts.py` | 工件下载 |
| `/api/threads/{id}/uploads` | `routers/uploads.py` | 文件上传 |
| `/api/threads/{id}/runs` | `routers/thread_runs.py` | 运行管理 |
| `/api/runs` | `routers/runs.py` | 无状态运行 |

### 5.2 依赖注入模式

通过 FastAPI 的 `app.state` 存储运行时单例:

- `StreamBridge` - SSE 事件桥接
- `RunManager` - 运行生命周期
- `Checkpointer` - 检查点持久化
- `Store` - 元数据存储

---

## 六、Frontend 架构

### 6.1 目录分层

```
src/
├── app/                # 页面层 (Next.js App Router)
│   ├── page.tsx        # 落地页
│   └── workspace/      # 工作台
│       ├── layout.tsx  # 布局 (QueryClient + Sidebar)
│       └ chats/[thread_id]/page.tsx  # 聊天页面
│       └ agents/       # Agent 管理
│
├── components/         # 组件层
│   ├── ui/             # Shadcn UI (自动生成)
│   ├── ai-elements/    # Vercel AI SDK 组件
│   ├── workspace/      # 业务组件
│   └── landing/        # 落地页组件
│
└── core/               # 业务逻辑层
    ├── api/            # LangGraph 客户端单例
    ├── threads/        # 线程流式处理
    ├── artifacts/      # 工件加载
    ├── i18n/           # 国际化
    ├── settings/       # localStorage 设置
    └── memory/         # 记忆系统
```

### 6.2 数据流

```
用户输入 (InputBox)
    ↓
sendMessage() → 乐观更新 (立即显示)
    ↓
thread.submit() → LangGraph SDK 流式提交
    ↓
事件回调处理:
    - onCreated → 设置 threadId
    - onUpdateEvent → 更新标题
    - onCustomEvent → 更新子任务
    - onFinish → 刷新查询
    ↓
Thread State 更新 → UI 重渲染
```

### 6.3 状态管理策略

| 数据类型 | 管理方式 | 位置 |
|----------|----------|------|
| **流式对话** | LangGraph SDK `useStream` | `core/threads/hooks.ts` |
| **Thread 列表** | TanStack Query | `core/threads/api.ts` |
| **用户设置** | localStorage | `core/settings/local.ts` |
| **国际化** | React Context | `core/i18n/context.tsx` |

### 6.4 消息分组渲染

```typescript
// 消息类型分组
groupMessages(messages, (group) => {
  if (group.type === "human") return <HumanMessage />
  if (group.type === "assistant") return <AIMessage />
  if (group.type === "assistant:processing") return <ProcessingGroup />
  if (group.type === "assistant:subagent") return <SubtaskCard />
})
```

---

## 七、IM Channels 集成

### 7.1 架构概览

```
外部平台 (飞书/Slack/Telegram)
        ↓ WebSocket/Poll
    Channel 实现
        ↓
    MessageBus (pub/sub)
        ↓
    ChannelManager
        ↓ (langgraph-sdk)
    LangGraph Server
```

### 7.2 Channel 抽象

```python
class Channel(ABC):
    async def start(self) -> None      # 启动监听
    async def stop(self) -> None       # 优雅停止
    async def send(self, msg) -> None  # 发送消息
    async def send_file(self, msg, attachment)  # 发送文件
```

### 7.3 平台特性对比

| 平台 | 连接方式 | 流式支持 | 特殊功能 |
|------|----------|----------|----------|
| **飞书** | WebSocket | ✅ | 卡片就地更新 |
| **Slack** | Socket Mode | ❌ | Mrkdwn 转换 |
| **Telegram** | Long Polling | ❌ | 线程回复 |

### 7.4 消息处理流程

```
1. 接收 IM 事件 → 解析消息内容
2. 添加 emoji 反应 → 发送 "Working on it..."
3. 发布 InboundMessage 到 MessageBus
4. ChannelManager 处理:
   - 查询/创建 thread
   - 调用 LangGraph SDK
5. 提取响应 → 发布 OutboundMessage
6. Channel 发送响应 → 添加完成 emoji
```

---

## 八、配置系统

### 8.1 主配置 (config.yaml)

#### 模型配置

```yaml
models:
  - name: gpt-4o
    use: langchain_openai:ChatOpenAI  # 类路径
    model: gpt-4o
    api_key: $OPENAI_API_KEY          # 环境变量
    supports_thinking: true           # 扩展思考
    supports_vision: true             # 视觉输入
```

#### Sandbox 配置

```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  # 或 Docker:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: xxx/sandbox:latest
  replicas: 3
  mounts: [{ host_path: /data, container_path: /mnt/shared }]
```

#### Memory 配置

```yaml
memory:
  enabled: true
  storage_path: memory.json
  debounce_seconds: 30
  injection_enabled: true
```

### 8.2 扩展配置 (extensions_config.json)

```json
{
  "mcpServers": { ... },
  "skills": {
    "data-analysis": { "enabled": true },
    "image-generation": { "enabled": false }
  }
}
```

### 8.3 配置加载机制

```
路径解析优先级:
1. 显式传入路径
2. 环境变量 (DEER_FLOW_CONFIG_PATH)
3. 当前目录/父目录查找

环境变量替换: $VAR → os.getenv("VAR")

热重载: 检测 mtime 变化自动刷新
```

---

## 九、Skills 系统

### 9.1 目录结构

```
skills/
├── public/              # 内置技能
│   └── data-analysis/
│       ├── SKILL.md     # 元数据 (name, description)
│       └ scripts/      # 实现脚本
│       └ references/   # 参考资料
└── custom/              # 自定义技能
```

### 9.2 SKILL.md 格式

```markdown
---
name: data-analysis
description: 分析 Excel/CSV 文件
license: MIT
---

# 技能说明
...
```

### 9.3 技能注入

启用后的技能会出现在 Agent 系统提示中:

```xml
<skills>
- data-analysis: /mnt/skills/public/data-analysis
- image-generation: /mnt/skills/public/image-generation
</skills>
```

---

## 十、关键设计模式

| 模式 | 应用 |
|------|------|
| **抽象工厂** | SandboxProvider |
| **策略模式** | 不同 Sandbox 实现 |
| **责任链** | Middleware Chain |
| **单例模式** | 配置/沙箱提供者 |
| **观察者** | Memory 队列, MessageBus |
| **发布/订阅** | IM Channels |
| **线程池** | Subagent 执行 |

---

## 十一、新人入门建议

### 阅读顺序

1. **配置系统**: `config.example.yaml` → 了解整体配置结构
2. **Agent 入口**: `backend/packages/harness/deerflow/agents/lead_agent/agent.py`
3. **中间件链**: 理解请求处理管道
4. **Sandbox**: `backend/packages/harness/deerflow/sandbox/` → 虚拟路径映射
5. **前端数据流**: `frontend/src/core/threads/hooks.ts` → 流式处理

### 运行验证

```bash
# 1. 检查环境
make check

# 2. 安装依赖
make install

# 3. 生成配置
make config

# 4. 启动服务
make dev

# 5. 访问
open http://localhost:2026
```

### 测试验证

```bash
# Backend 测试
cd backend && make test

# Frontend 类型检查
cd frontend && pnpm typecheck

# Harness 边界测试 (CI 必须)
pytest tests/test_harness_boundary.py
```

---

## 十二、扩展点

| 扩展点 | 方式 |
|--------|------|
| **自定义模型** | `config.yaml` → `models[].use` 类路径 |
| **自定义工具** | `config.yaml` → `tools[].use` 函数路径 |
| **自定义沙箱** | 实现 `Sandbox` + `SandboxProvider` |
| **自定义中间件** | `create_deerflow_agent(extra_middleware=...)` |
| **自定义子代理** | 注册到 `BUILTIN_SUBAGENTS` |
| **MCP 服务器** | `extensions_config.json` |
| **Skills** | `skills/custom/` 目录 |

---

本文档整合了 DeerFlow 各子系统架构，建议结合具体源码深入理解各组件实现细节。
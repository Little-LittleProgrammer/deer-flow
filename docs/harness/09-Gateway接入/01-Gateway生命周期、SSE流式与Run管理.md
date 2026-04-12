# DeerFlow Harness Gateway 接入、SSE 流式与 Run 管理

> 目标：说明 Gateway 如何作为 Harness 的 HTTP/SSE 适配层，把 Agent 运行时能力暴露给前端。
>
> 代码范围：以 `backend/app/gateway/` 和 `backend/packages/harness/deerflow/runtime/` 为主。

补充专题：

- `../01-总览/01-Harness整体架构.md`：全局架构和 Harness 内核
- `../05-运行时与状态/01-ThreadState、RunManager与StreamBridge.md`：运行时骨架

---

## 1. Gateway 不是 Agent 本身

Gateway（`backend/app/gateway/`）的定位很明确：

- **Harness 内核**（`deerflow/`）：Agent 装配、执行、状态、工具、沙箱
- **Gateway**（`app/gateway/`）：HTTP 协议解析、SSE 输出、线程/run 生命周期接入

Gateway 不实现任何 agent 逻辑，它只做：

1. 接收 HTTP 请求
2. 创建/管理 run 记录
3. 启动 Harness worker 执行 agent
4. 从 StreamBridge 消费事件
5. 通过 SSE 推送给前端

---

## 2. 服务拓扑

```text
Browser
  |
  v
nginx (port 2026)          ← 统一入口
  ├→ /                    → Frontend (Next.js, port 3000)
  ├→ /api/langgraph/*     → LangGraph Server (port 2024)
  ├→ /api/*               → Gateway API (FastAPI, port 8001)
  └→ /api/models, /api/mcp, /api/skills  → Gateway 管理接口
```

Gateway 监听 8001 端口，通过 nginx 代理到 `/api/*`。

---

## 3. 生命周期初始化：`langgraph_runtime()`

`app/gateway/deps.py` 定义了 FastAPI lifespan 上下文管理器：

```python
@asynccontextmanager
async def langgraph_runtime(app: FastAPI):
    async with AsyncExitStack() as stack:
        # 1. 流式桥
        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge())
        # 2. Checkpointer（图状态持久化）
        app.state.checkpointer = await stack.enter_async_context(make_checkpointer())
        # 3. Store（线程元数据）
        app.state.Store = await stack.enter_async_context(make_store())
        # 4. Run Manager（运行控制面）
        app.state.run_manager = RunManager()
        yield
```

### 3.1 为什么用 `AsyncExitStack`

这四个组件有严格的依赖和清理顺序：

- stream_bridge、checkpointer、store 都需要初始化
- 关闭时需要按相反顺序释放资源
- `AsyncExitStack` 自动保证退出时按 LIFO 顺序 cleanup

### 3.2 挂到 `app.state`

所有运行时组件挂到 FastAPI `app.state` 上，路由 handler 通过 `Depends()` 获取：

```python
async def get_run_manager() -> RunManager:
    return app.state.run_manager
```

---

## 4. Run 管理：从请求到执行

### 4.1 `start_run()` 流程

`app/gateway/services.py::start_run()` 是核心入口：

```text
start_run(thread_id, messages, ...)
  |
  +-- 1. run_manager.create_or_reject(thread_id, strategy)
  |     检查同线程是否有 inflight run
  |     策略: reject / interrupt / rollback
  |
  +-- 2. 确保线程在 store 中存在
  |     _ensure_thread_in_store(thread_id)
  |
  +-- 3. 构造 RunnableConfig
  |     config = {"configurable": {"thread_id": thread_id}}
  |
  +-- 4. 合并 DeerFlow context 到 configurable
  |     config["configurable"].update({
  |         "model_name": ...,
  |         "thinking_enabled": ...,
  |         "subagent_enabled": ...,
  |         ...
  |     })
  |
  +-- 5. asyncio.create_task(run_agent(...))
  |     启动后台 worker
  |
  +-- 6. 返回 run_id
```

### 4.2 并发策略

`RunManager.create_or_reject()` 原子处理同线程并发冲突：

| 策略 | 行为 |
|------|------|
| `reject` | 已有 inflight run 时直接拒绝 |
| `interrupt` | 中断当前 inflight run，启动新的 |
| `rollback` | 中断并回滚到 pre-run checkpoint |

### 4.3 `run_agent()` Worker

`deerflow/runtime/runs/worker.py::run_agent()` 是 Harness 侧真正驱动图执行的地方：

1. 标记 run 为 `running`
2. 捕获 pre-run checkpoint（rollback 用）
3. 通过 bridge 发布 metadata 事件
4. 构造 `Runtime(context={"thread_id": ...}, store=store)`
5. 写入 `config["configurable"]["__pregel_runtime"]`
6. `agent_factory(config=runnable_config)` 动态构建 agent
7. 注入 checkpointer / store
8. `agent.astream(...)` 逐步消费图输出
9. 序列化输出 publish 到 `StreamBridge`
10. 结束时写最终状态，发送 `end` 事件

---

## 5. SSE 流式：从 Bridge 到 HTTP

### 5.1 生产侧：Worker 发布事件

```python
# worker.py 中
async for chunk in agent.astream(...):
    event = serialize(chunk)
    await bridge.publish(run_id, event)
```

### 5.2 消费侧：Gateway 订阅 Bridge

```python
# routers/chat.py 中
async def stream_events(run_id, bridge):
    async for event in bridge.subscribe(run_id):
        if event is END_SENTINEL:
            break
        yield format_sse(event)
```

### 5.3 StreamBridge 的关键设计

| 特性 | 说明 |
|------|------|
| 按 run 隔离 | 每个 run 一条独立 `asyncio.Queue`，不互相污染 |
| Heartbeat | 超时后发 `HEARTBEAT_SENTINEL`，防止 SSE 连接超时断开 |
| END_SENTINEL | 强保证送达，队列满时也会为 END 让路 |
| 队列满保护 | 丢弃最旧事件，但 END 不被丢弃 |

### 5.4 SSE 只是消费协议的一种

StreamBridge 抽象了事件桥接，SSE 只是其中一种消费协议。未来可以接入：

- WebSocket
- 消息总线
- 进程内订阅

核心运行时不需要重写。

---

## 6. 线程管理

### 6.1 线程搜索

`/api/threads/search` 从 Store 读取线程元数据：

```python
# Store 中存的是应用级文档
store.aput(
    namespace=("threads", thread_id),
    key="metadata",
    value={"title": "...", "created_at": "...", "updated_at": "..."}
)
```

### 6.2 标题同步

这是一个重要的跨层补偿逻辑：

1. `TitleMiddleware` 把标题写到 **checkpoint** 的状态里
2. 线程搜索接口读的是 **store**
3. 所以 run 结束后，Gateway 需要做标题同步：

```python
# services.py
async def _sync_thread_title_after_run(thread_id, checkpointer, store):
    # 从 checkpoint 读标题
    title = get_title_from_checkpoint(checkpointer, thread_id)
    # 回写到 store
    await update_thread_in_store(store, thread_id, {"title": title})
```

### 6.3 线程删除

删除线程时需要同步清理：

- Store 中的线程元数据
- Checkpointer 中的 checkpoint 记录
- 磁盘上的 thread 目录（workspace/uploads/outputs）
- Sandbox 资源（如果有）

---

## 7. 模型/技能/MCP 管理接口

Gateway 还提供配置管理 API：

### 7.1 模型列表

`/api/models` 返回 `AppConfig.models` 中配置的模型列表，供前端下拉选择。

### 7.2 MCP 管理

`/api/mcp/servers` 管理 MCP server 的启用状态，写入 `extensions_config.json`。

### 7.3 Skills 管理

`/api/skills` 列出已加载的 skills，支持启用/禁用。

这些接口操作的都是磁盘配置文件，不是内存状态：

- `config.yaml` — 主配置
- `extensions_config.json` — MCP 和 skills 启停

因为 Gateway 和 LangGraph worker 可能是不同进程，所以配置变更通过磁盘文件同步。

---

## 8. 文件上传与产物

### 8.1 上传接口

`/api/threads/{thread_id}/uploads` 处理文件上传：

1. 接收文件
2. 写入线程的 `uploads/` 目录
3. 如果是文档（PDF/PPT/Excel/Word），转换为 markdown
4. 返回虚拟路径 `/mnt/user-data/uploads/filename`

### 8.2 产物接口

`/api/threads/{thread_id}/artifacts` 从 Store 或 checkpoint 读取 `artifacts` 状态，返回产物文件列表。

产物由 agent 通过 `present_file_tool` 登记到 `ThreadState.artifacts` 中。

---

## 9. 错误处理

### 9.1 SSE 错误

Worker 捕获异常后：

1. 发布 error 事件到 StreamBridge
2. 标记 run 状态为 `error`
3. 发送 END_SENTINEL

前端收到 error 事件后展示错误信息。

### 9.2 HTTP 错误

Gateway 路由层使用 FastAPI 的 HTTPException：

- 400：参数错误
- 404：线程/run 不存在
- 409：并发冲突（同线程已有 inflight run 且策略为 reject）
- 500：内部错误

---

## 10. 部署拓扑

### 10.1 开发模式（`make dev`）

```text
nginx:2026
  ├→ Frontend:3000
  ├→ Gateway:8001
  └→ LangGraph Server:2024
```

所有进程独立运行，通过 nginx 统一代理。

### 10.2 生产模式

可以拆分到不同容器：

```text
nginx
  ├→ Frontend (容器 A)
  ├→ Gateway (容器 B)
  └→ LangGraph Worker (容器 C, 可多实例)
```

Gateway 和 Worker 通过共享存储（SQLite/Postgres）同步状态。

### 10.3 嵌入式模式（`DeerFlowClient`）

不需要 Gateway，直接进程内调用 Harness 内核：

```python
from deerflow import DeerFlowClient

client = DeerFlowClient()
response = client.chat("hello", thread_id="xxx")
```

适合脚本、测试、嵌入式集成。

---

## 11. 关键代码索引

| 文件 | 职责 |
|------|------|
| `app/gateway/deps.py` | 生命周期初始化，`langgraph_runtime()` |
| `app/gateway/services.py` | `start_run()`、线程管理、标题同步 |
| `app/gateway/routers/chat.py` | SSE 聊天接口 |
| `app/gateway/routers/threads.py` | 线程 CRUD 和搜索 |
| `app/gateway/routers/models.py` | 模型列表 |
| `app/gateway/routers/mcp.py` | MCP 管理 |
| `app/gateway/routers/skills.py` | Skills 管理 |
| `app/gateway/routers/uploads.py` | 文件上传 |
| `deerflow/runtime/runs/manager.py` | RunManager |
| `deerflow/runtime/runs/worker.py` | run_agent() worker |
| `deerflow/runtime/stream_bridge/` | StreamBridge |
| `deerflow/runtime/store/` | Store 提供商 |
| `deerflow/agents/checkpointer/` | Checkpointer 提供商 |

---

## 12. 总结

Gateway 的核心职责可以概括为：

> 接收请求 → 管理 run 生命周期 → 启动 Harness worker → 从 StreamBridge 消费事件 → SSE 推送给前端

Gateway 不实现 agent 逻辑，它只是 Harness 内核的 HTTP/SSE 适配层。真正让 SSE 工作的不是 FastAPI，而是 Harness 内部的 `RunManager + StreamBridge + Worker` 三层架构。

理解 Gateway 的关键是理解三层分工：

| 层 | 职责 |
|------|------|
| **RunManager** | run 生命周期控制（创建、取消、中断、回滚） |
| **Worker** | 驱动 graph 执行，生产事件到 Bridge |
| **StreamBridge** | 缓冲和桥接事件，供 SSE 消费 |

这三层配合，才有了上层看到的流式、可取消、可恢复的 Agent API。

# DeerFlow Harness ThreadState、RunManager 与 StreamBridge

> 目标：说明 DeerFlow 当前实现里，线程状态、run 生命周期和流式事件桥接是如何协作的，以及为什么它们是 Gateway 能力背后的真正运行时核心。
>
> 代码范围：以 `backend/packages/harness/deerflow/agents/thread_state.py` 和 `runtime/` 为主。

补充专题：

- `../01-总览/01-Harness整体架构.md`：全局架构和主链路
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：agent 组装和 middleware 顺序

---

## 1. `thread_id` 是运行时主键

在 DeerFlow 里，很多能力最终都围绕同一个键工作：`thread_id`。

| 能力 | 如何使用 thread_id |
|------|-------------------|
| 会话消息历史 | checkpoint 中按 thread_id 索引 |
| 线程元数据 | store 中按 thread_id 存标题和时间 |
| 文件目录 | `threads/{thread_id}/user-data/` |
| 沙箱 | provider 按 thread_id 获取/复用 sandbox |
| Run 记录 | run_manager 按 thread_id 追踪 inflight run |
| 子代理 | 继承父 thread_id，共享工作区 |

Thread 在这里不是前端概念，而是整个 harness runtime 的隔离单元。

---

## 2. `ThreadState`：统一状态载体

### 2.1 状态字段

`agents/thread_state.py` 在 `AgentState` 基础上扩展：

| 字段 | 类型 | 用途 | Reducer |
|------|------|------|---------|
| `sandbox` | `SandboxState` | 当前沙箱 ID 和状态 | 无（覆盖） |
| `thread_data` | `ThreadDataState` | 线程级目录路径 | 无（覆盖） |
| `title` | `str` | 线程标题 | 无（覆盖） |
| `artifacts` | `list[dict]` | 产物文件列表 | `merge_artifacts`（追加去重） |
| `todos` | `list[dict]` | 待办事项 | 无（覆盖） |
| `uploaded_files` | `list[str]` | 上传文件列表 | 无（覆盖） |
| `viewed_images` | `dict[str, Any]` | 已查看图像 | `merge_viewed_images` |

### 2.2 统一状态的好处

1. **中间件协作**：多个 middleware 通过统一 state 读写，不依赖隐式全局变量
2. **Checkpoint 持久化**：checkpointer 直接序列化完整状态
3. **UI 对接**：前端所需的衍生信息从 state 读取，不需要额外协议

### 2.3 Reducer 的并发语义

Reducer 不是代码整洁，而是显式定义状态合并规则：

```python
def merge_artifacts(left: list[dict], right: list[dict]) -> list[dict]:
    """追加并去重，相同 path 只保留最新"""
    seen = {a["path"]: a for a in left}
    seen.update({a["path"]: a for a in right})
    return list(seen.values())

def merge_viewed_images(left: dict, right: dict) -> dict:
    """合并；空字典代表清空"""
    if not right:
        return {}
    return {**left, **right}
```

如果没有 reducer，多个工具或多个回合同时更新这些字段时，很容易互相覆盖。

---

## 3. `ThreadDataMiddleware`：逻辑线程映射成真实目录

### 3.1 做什么

根据当前 `thread_id` 计算线程级目录信息，写入 `state["thread_data"]`：

| 字段 | 虚拟路径 | 物理路径 |
|------|----------|----------|
| `workspace_path` | `/mnt/user-data/workspace` | `threads/{tid}/user-data/workspace/` |
| `uploads_path` | `/mnt/user-data/uploads` | `threads/{tid}/user-data/uploads/` |
| `outputs_path` | `/mnt/user-data/outputs` | `threads/{tid}/user-data/outputs/` |

### 3.2 Lazy Init

默认 `lazy_init=True`：

- 先建立路径语义
- 不立刻创建全部目录

好处是减少不必要的 IO，后续 sandbox、uploads、文件工具都共享同一份路径上下文。

---

## 4. `SandboxMiddleware`：执行环境挂进 state

### 4.1 职责

不是执行命令本身，而是：

1. 根据 provider 获取或复用 `sandbox_id`
2. 把 `sandbox_id` 写入 `state["sandbox"]`
3. 在 `after_agent()` 里调用 provider 的 `release(...)`

### 4.2 设计分离

| 关注点 | 负责方 |
|--------|--------|
| "能做什么" | `Sandbox`（执行命令、读写文件） |
| "怎么管理生命周期" | `SandboxProvider`（获取、缓存、释放） |

工具只关心当前 state 里有没有 sandbox；provider 决定资源是立即释放、warm pool 复用，还是 no-op。

### 4.3 Release 的语义

`provider.release(sandbox_id)` 不是一定真正释放：

| Provider | release 行为 |
|----------|-------------|
| `LocalSandboxProvider` | no-op（单例常驻） |
| `AioSandboxProvider` | 放回 warm pool 或真正销毁 |

---

## 5. `RunManager`：run 生命周期控制器

### 5.1 内存型 Registry

`runtime/runs/manager.py` 管理运行中的 run 记录：

| 字段 | 类型 | 用途 |
|------|------|------|
| `run_id` | `str` | 唯一标识 |
| `thread_id` | `str` | 所属线程 |
| `status` | `RunStatus` | pending/running/success/interrupted/error |
| `on_disconnect` | `DisconnectMode` | 断开连接时的行为 |
| `multitask_strategy` | `str` | reject/interrupt/rollback |
| `abort_event` | `asyncio.Event` | 取消信号 |
| `abort_action` | `str` | 取消后执行的动作 |
| `task` | `asyncio.Task` | 实际执行的协程 |
| `error` | `str | None` | 错误信息 |

### 5.2 `create_or_reject()` 原子处理并发

```python
async def create_or_reject(self, thread_id, strategy="reject"):
    # 1. 检查同线程是否有 inflight run
    # 2. 如果有:
    #    - reject:  抛 ConflictError
    #    - interrupt: 取消当前 run
    #    - rollback: 取消 + 回滚 checkpoint
    # 3. 如果没有: 创建新 run 记录
```

这一步避免了把并发 run 冲突交给上层调用方自己处理。

### 5.3 `cancel()` 的语义

取消不只是 `task.cancel()`：

1. 设置 `abort_event`（通知 worker 停止）
2. 记录 `abort_action`（停止后做什么）
3. 更新 run 状态和时间戳

DeerFlow 把"取消"视作显式运行时事件，而不是隐式任务异常。

---

## 6. `run_agent()`：真正驱动 graph 执行的地方

`runtime/runs/worker.py::run_agent(...)` 是后台执行函数。

### 6.1 执行步骤

```text
run_agent(thread_id, messages, config, bridge, checkpointer, store, ...)
  |
  +-- 1. 标记 run 为 running
  |
  +-- 2. 捕获 pre-run checkpoint（rollback 用）
  |     pre_run_checkpoint_id = get_latest_checkpoint_id(checkpointer, thread_id)
  |
  +-- 3. 通过 bridge 发布 metadata 事件
  |     await bridge.publish(run_id, {"type": "metadata", ...})
  |
  +-- 4. 构造 LangGraph Runtime
  |     runtime = Runtime(context={"thread_id": thread_id}, store=store)
  |     config["configurable"]["__pregel_runtime"] = runtime
  |
  +-- 5. 动态构建 agent
  |     agent = agent_factory(config=runnable_config)
  |     agent.checkpointer = checkpointer
  |     agent.store = store
  |
  +-- 6. 执行图
  |     async for chunk in agent.astream(messages, config):
  |         event = serialize(chunk)
  |         await bridge.publish(run_id, event)
  |
  +-- 7. 结束处理
  |     正常: status = success
  |     Abort + rollback: 恢复 pre-run checkpoint
  |     异常: status = error
  |
  +-- 8. 发送 end 事件
  |     await bridge.publish_end(run_id)
```

### 6.2 为什么要自己注入 `Runtime`

LangGraph CLI 会自动处理部分 runtime context，但 DeerFlow 作为自定义 Gateway/worker，需要自己补上：

```python
runtime = Runtime(context={"thread_id": thread_id}, store=store)
config["configurable"]["__pregel_runtime"] = runtime
```

这一步之后，middleware 和工具才能稳定拿到 `thread_id`、`store`、runtime context。

---

## 7. StreamBridge：生产与消费解耦

### 7.1 抽象作用

把 graph 执行侧的事件生产和 HTTP SSE 侧的事件消费隔离开。

### 7.2 `MemoryStreamBridge` 核心结构

```python
class MemoryStreamBridge(StreamBridge):
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}  # run_id → queue
        self._event_ids: dict[str, int] = {}         # run_id → counter

    async def publish(self, run_id: str, event: dict):
        queue = self._queues[run_id]
        event["id"] = self._event_ids[run_id]
        self._event_ids[run_id] += 1
        await queue.put(event)

    async def subscribe(self, run_id: str):
        queue = self._queues[run_id]
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                yield event
                if event.get("type") == "end":
                    break
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
```

### 7.3 关键细节

| 特性 | 说明 |
|------|------|
| 按 run 隔离 | 每个 run 一条独立队列，不互相污染 |
| 心跳 | 超时后发 `HEARTBEAT_SENTINEL`，防止 SSE 超时断开 |
| END_SENTINEL | 强保证送达，队列满时也会为 END 让路 |
| Event ID | 单调递增，用于未来 replay 支持 |

### 7.4 END_SENTINEL 为什么优先级最高

如果 END 丢了：

- 客户端会一直挂起
- run 相关资源不容易回收

`publish_end()` 在队列满时会主动驱逐旧事件，也要为 END 让路。

---

## 8. Checkpointer、Store 与 RunManager 的分工

| 组件 | 职责 | 生命周期 | 后端 |
|------|------|----------|------|
| **Checkpointer** | 图状态持久化和恢复 | 长期 | memory / sqlite / postgres |
| **Store** | 线程元数据、标题、索引 | 长期 | memory / sqlite / postgres |
| **RunManager** | 当前运行中的 run 控制面 | 进程内 | 内存 |

### 8.1 数据流关系

```text
Agent 执行
  → Checkpointer 保存每一步图状态
  → Store 保存线程元数据（通过 Runtime 注入）
  → RunManager 跟踪运行状态

前端查询
  → /api/threads 读 Store
  → /api/threads/{id}/messages 读 Checkpointer
  → /api/runs/{id}/status 读 RunManager
```

### 8.2 标题同步补偿

`TitleMiddleware` 把标题写到 checkpoint 状态里；线程搜索接口读的是 store。

所以 run 结束后 Gateway 需要补偿同步：

```python
# services.py
async def _sync_thread_title_after_run(thread_id, checkpointer, store):
    # 从 checkpoint 读取标题
    title = get_title_from_checkpoint(checkpointer, thread_id)
    # 回写到 store
    await update_thread_in_store(store, thread_id, {"title": title})
```

---

## 9. SSE 不是流式能力本体

从实现看，SSE 只是消费 `StreamBridge` 的一种协议适配层。

真正关键的是 harness 内部三层：

| 层 | 职责 |
|------|------|
| `run_agent()` | 生产事件 |
| `StreamBridge` | 缓冲和桥接 |
| Gateway | 转成 HTTP SSE |

如果未来接 WebSocket、消息总线、进程内订阅，核心运行时基本不需要重写。

---

## 10. 当前实现的边界

### 10.1 RunManager 是内存型

进程重启后 inflight run registry 不保留。

### 10.2 Rollback 语义预留

`run_agent()` 已记录 `pre_run_checkpoint_id`，但真正的 checkpoint 回滚逻辑还没有完全补完。

### 10.3 MemoryStreamBridge 没有 replay

`last_event_id` 目前接受但忽略，还不是可追放的 durable event log。

### 10.4 单进程运行时

更接近单进程运行时，而不是分布式 durable runtime。

---

## 11. 总结

DeerFlow 当前运行时设计：

> `ThreadState` 负责统一状态，`RunManager` 负责生命周期控制，`StreamBridge` 负责把图执行变成可消费的流。

三者配合后，才有了：

- 同线程隔离（RunManager 的并发策略）
- 可取消 run（abort_event + abort_action）
- 状态可恢复（checkpoint rollback 预留）
- SSE 流式输出（StreamBridge 桥接）
- 工具与中间件共享上下文（ThreadState 统一状态）

理解 Gateway 为什么能工作，真正要看的不是 HTTP 层，而是这套 runtime 骨架。

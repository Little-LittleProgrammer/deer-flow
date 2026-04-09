# DeerFlow Harness ThreadState、RunManager 与 StreamBridge

> 目标：说明 DeerFlow 当前实现里，线程状态、run 生命周期和流式事件桥接是如何协作的，以及为什么它们是 Gateway 能力背后的真正运行时核心。
>
> 代码范围：以 `backend/packages/harness/deerflow/agents/thread_state.py` 和 `runtime/` 为主，必要时补充 `agents/middlewares/` 与 `client.py`。

补充专题：

- `../01-总览/01-Harness整体架构.md`：全局架构和主链路
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：agent 组装和 middleware 顺序

---

## 1. `thread_id` 是运行时主键

在 DeerFlow 里，很多能力最终都围绕同一个键工作：`thread_id`。

它同时关联：

- 会话消息历史
- checkpoint 状态
- store 中的线程元数据
- 线程对应的 workspace/uploads/outputs 目录
- sandbox 获取与复用
- Gateway 的 run 记录

因此 thread 在这里不是前端概念，而是整个 harness runtime 的隔离单元。

---

## 2. `ThreadState`：统一状态载体

`deerflow/agents/thread_state.py` 在 `AgentState` 基础上扩展了几类字段：

- `sandbox`
- `thread_data`
- `title`
- `artifacts`
- `todos`
- `uploaded_files`
- `viewed_images`

这意味着 DeerFlow 并没有把这些运行时信息散落在各 middleware 或工具内部，而是显式纳入 graph state。

这样做至少有三个直接收益：

1. 中间件之间可以通过统一 state 协作
2. checkpoint 可以直接持久化更完整的线程上下文
3. UI 所需的衍生信息可以从 state 读取，而不是靠额外旁路协议

---

## 3. Reducer 不是细节，而是并发语义

`ThreadState` 里有两个字段带 reducer：

- `artifacts -> merge_artifacts`
- `viewed_images -> merge_viewed_images`

它们的意义不是代码整洁，而是显式定义状态合并规则。

例如：

- `artifacts` 需要追加并去重
- `viewed_images` 需要支持 merge，也需要支持“空字典代表清空”

如果没有 reducer，多个工具或多个 middleware 在同一轮更新这些字段时，很容易互相覆盖。

所以 reducer 本质上是在把“状态写冲突怎么解决”内建到 state schema 里。

---

## 4. `ThreadDataMiddleware`：把逻辑线程映射成真实目录

`ThreadDataMiddleware` 会根据当前 `thread_id` 计算线程级目录信息，并写入 `state["thread_data"]`。

典型包括：

- `workspace_path`
- `uploads_path`
- `outputs_path`

默认是 `lazy_init=True`，意味着：

- 先建立路径语义
- 不一定立刻创建全部目录

这样做的好处是减少不必要的 IO，同时让后续 sandbox、uploads、文件工具都共享同一份路径上下文。

---

## 5. `SandboxMiddleware`：把执行环境挂进 state

`SandboxMiddleware` 的职责不是执行命令本身，而是：

1. 根据 provider 获取或复用 `sandbox_id`
2. 把 `sandbox_id` 写入 `state["sandbox"]`
3. 在 `after_agent()` 里调用 provider 的 `release(...)`

这个设计把“执行能力”和“资源生命周期”拆开了：

- 工具只关心当前 state 里有没有 sandbox
- provider 决定资源是立即释放、warm pool 复用，还是 no-op

所以 sandbox 的抽象边界并不在工具，而在 middleware + provider。

---

## 6. `RunManager`：run 生命周期控制器

`deerflow/runtime/runs/manager.py` 当前实现的是一个内存型 run registry。

每个 `RunRecord` 记录的核心字段包括：

- `run_id`
- `thread_id`
- `status`
- `on_disconnect`
- `multitask_strategy`
- `abort_event`
- `abort_action`
- `task`
- `error`

这说明 run 在 DeerFlow 里不是一次裸 `asyncio.Task`，而是有显式状态机的对象。

### 6.1 `create_or_reject()` 的意义

这个方法不是简单创建 record，而是原子处理“线程上是否已有 inflight run”。

当前支持的策略有：

- `reject`
- `interrupt`
- `rollback`

这一步很关键，因为它避免了把并发 run 冲突交给上层调用方自己处理。

### 6.2 `cancel()` 的语义

取消并不只是 `task.cancel()`。

它还会：

- 记录 `abort_action`
- 设置 `abort_event`
- 更新 run 状态和时间戳

也就是说，DeerFlow 把“取消”视作显式运行时事件，而不是隐式任务异常。

---

## 7. `run_agent()`：真正驱动 graph 执行的地方

`deerflow/runtime/runs/worker.py::run_agent(...)` 是实际的后台执行函数。

它大致做这些事：

1. 把 run 状态改成 `running`
2. 读取 pre-run checkpoint 信息，给回滚预留钩子
3. 通过 bridge 发布 metadata
4. 构造 `Runtime(context={"thread_id": ...}, store=store)`
5. 把 runtime 注入 `config["configurable"]["__pregel_runtime"]`
6. 用 `agent_factory(config=runnable_config)` 动态构建 agent
7. 挂上 checkpointer / store
8. 调 `agent.astream(...)` 逐步消费图输出
9. 把输出序列化后发往 `StreamBridge`
10. 根据 abort 或异常，写最终状态并发送 `end`

这一层是 DeerFlow 能同时做到“可流式、可取消、可恢复”的关键。

---

## 8. 为什么要自己注入 `Runtime`

在 `run_agent()` 里，代码手动构造了：

```python
Runtime(context={"thread_id": thread_id}, store=store)
```

并写入：

```python
config["configurable"]["__pregel_runtime"] = runtime
```

原因是：

- LangGraph CLI 会自动处理部分 runtime context
- DeerFlow 作为自定义 Gateway/worker，需要自己补上这层注入

这一步之后，middleware 和工具才能稳定拿到：

- `thread_id`
- `store`
- runtime context

所以这不是兼容性细节，而是 DeerFlow 自己运行 LangGraph 时必须补齐的 glue code。

---

## 9. StreamBridge：把执行侧和 SSE 消费侧解耦

`StreamBridge` 的抽象作用是把：

- graph 执行期间产生的事件
- HTTP SSE 或其他订阅方消费的事件

隔离开。

默认实现 `MemoryStreamBridge` 的核心结构是：

- 每个 `run_id` 一条 `asyncio.Queue`
- 发布时生成单调递增 event id
- 订阅时支持 heartbeat
- 结束时发 `END_SENTINEL`

这意味着 DeerFlow 的流式能力不是“直接在 FastAPI 里边跑边写”，而是先经过一个中间桥。

---

## 10. `MemoryStreamBridge` 的几个关键细节

### 10.1 队列按 run 隔离

每个 run 一条独立队列，保证不同请求的流式事件不会相互污染。

### 10.2 心跳不是可有可无

`subscribe()` 在超时后会发 `HEARTBEAT_SENTINEL`，避免 SSE 长连接因为长时间无数据而被误判死亡。

### 10.3 `END_SENTINEL` 必须强保证送达

`publish_end()` 在队列满时会主动驱逐旧事件，也要为 END 让路。

这是个很重要的工程选择，因为如果 END 丢了：

- 客户端会一直挂起
- run 相关资源也更容易泄漏

说明 DeerFlow 在流式链路里把“正确结束”优先级放得很高。

---

## 11. SSE 并不是流式能力本体

从实现看，SSE 只是消费 `StreamBridge` 的一种协议适配层。

真正关键的是 harness 内部这三层：

1. `run_agent()` 负责生产事件
2. `StreamBridge` 负责缓冲和桥接
3. Gateway 才把这些事件转成 HTTP SSE

所以如果未来要接别的消费侧，例如 WebSocket、消息总线、进程内订阅，核心运行时基本不需要重写。

---

## 12. Checkpointer、Store 与 RunManager 的分工

这三者很容易混，但职责其实不同。

### 12.1 Checkpointer

负责 graph state 持久化和线程恢复。

### 12.2 Store

负责线程元数据、标题、索引等更应用层的数据。

### 12.3 RunManager

负责当前运行中的 run 生命周期，不是长期存储。

因此它们更准确的关系是：

- checkpointer：图执行历史
- store：应用级线程记录
- run manager：进程内运行控制面

---

## 13. 当前实现的边界

从代码看，运行时层已经比较完整，但也有几个边界需要明确。

### 13.1 `RunManager` 仍是内存型

这意味着进程重启后 inflight run registry 不保留。

### 13.2 `rollback` 语义还预留在位

`run_agent()` 已记录 `pre_run_checkpoint_id`，但真正的 checkpoint 回滚逻辑还没有补完。

### 13.3 `MemoryStreamBridge` 没有 replay

`last_event_id` 目前接受但忽略，说明它还不是可追放的 durable event log。

这些边界不影响当前 Gateway 工作，但决定了它更接近单进程运行时，而不是分布式 durable runtime。

---

## 14. 总结

DeerFlow 当前运行时设计可以压缩成一句话：

> `ThreadState` 负责统一状态，`RunManager` 负责生命周期控制，`StreamBridge` 负责把图执行变成可消费的流。

三者配合后，才有了上层看到的这些能力：

- 同线程隔离
- 可取消 run
- 状态可恢复
- SSE 流式输出
- 工具与中间件共享上下文

所以如果要理解 Gateway 为什么能工作，真正要看的不是 HTTP 层，而是这里这套 runtime 骨架。

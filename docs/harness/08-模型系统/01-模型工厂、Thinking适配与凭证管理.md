# DeerFlow Harness 模型系统

> 目标：说明 DeerFlow 如何支持多模型提供商、thinking 模式、凭证管理和 tracing 集成。
>
> 代码范围：以 `backend/packages/harness/deerflow/models/` 和 `config/model_config.py` 为主。

补充专题：

- `../01-总览/01-Harness整体架构.md`：全局架构和配置驱动
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：模型在 agent 装配中的角色

---

## 1. 模型不是硬编码的，是配置驱动的

DeerFlow 不在代码里写死"用 Claude"或"用 GPT-4"。模型完全由 `config.yaml` 的 `models[]` 数组声明：

```yaml
models:
  - name: claude-sonnet-4.6
    display_name: Claude Sonnet 4.6
    use: "deerflow.models.claude_provider:ClaudeChatModel"
    model: claude-sonnet-4-6
    supports_thinking: true
    supports_vision: true
    api_key: $ANTHROPIC_API_KEY
    max_tokens: 8192
    enable_prompt_caching: true
```

这意味着：

- 新模型接入只需加配置，不改代码
- 可以同时配置多个模型，运行时按需切换
- 提供商特有字段（`api_key`、`base_url`、`enable_prompt_caching`）直接透传

---

## 2. `ModelConfig` 配置结构

`deerflow/config/model_config.py` 定义了模型配置的 schema：

| 字段 | 类型 | 用途 |
|------|------|------|
| `name` | `str` | 唯一标识，如 `"claude-sonnet-4.6"` |
| `display_name` | `str | None` | 人类可读标签 |
| `use` | `str` | 类路径，如 `"deerflow.models.claude_provider:ClaudeChatModel"` |
| `model` | `str` | 提供商模型名，如 `"claude-sonnet-4-6"` |
| `supports_thinking` | `bool` | 是否支持 thinking 模式 |
| `supports_reasoning_effort` | `bool` | 是否支持 reasoning effort 级别 |
| `supports_vision` | `bool` | 是否接受图像输入 |
| `thinking` | `dict | None` | thinking 快捷配置（合并到 `when_thinking_enabled`） |
| `when_thinking_enabled` | `dict | None` | thinking 开启时的额外配置 |
| `when_thinking_disabled` | `dict | None` | thinking 关闭时的额外配置 |
| `use_responses_api` | `bool | None` | 是否使用 OpenAI /v1/responses 端点 |
| `output_version` | `str | None` | 结构化输出版本 |

`extra="allow"` 让任意额外字段直接透传到模型构造函数。

---

## 3. `create_chat_model()` 工厂流程

`deerflow/models/factory.py::create_chat_model(name, thinking_enabled, **kwargs)` 是核心入口。

### 3.1 执行步骤

```text
create_chat_model(name, thinking_enabled, **kwargs)
  |
  +-- 1. get_app_config() 获取 AppConfig 单例
  |
  +-- 2. config.get_model_config(name) 查找 ModelConfig
  |     （name 为空时取第一个模型）
  |
  +-- 3. resolve_class(model_config.use, BaseChatModel)
  |     动态加载模型类，校验子类关系
  |
  +-- 4. model_config.model_dump(exclude=元数据字段)
  |     序列化配置字段，透传提供商特有字段
  |
  +-- 5. 处理 thinking 模式
  |     thinking_enabled=True:  合并 when_thinking_enabled
  |     thinking_enabled=False: 合并 when_thinking_disabled
  |                             或提供商特定的 thinking 关闭方式
  |
  +-- 6. 提供商特殊逻辑
  |     Codex: 移除 max_tokens，映射 reasoning_effort
  |
  +-- 7. model_class(**settings, **kwargs) 实例化
  |
  +-- 8. build_tracing_callbacks() 附加 tracing
  |
  +-- 9. 返回 BaseChatModel 实例
```

### 3.2 模型名解析的三层优先级

1. **请求级 runtime 参数** `model_name`（最高优先级）
2. **Agent profile 配置** `agent_config.model`
3. **全局默认模型** `AppConfig.models[0]`（兜底）

---

## 4. Thinking 模式的多提供商适配

不同提供商的 thinking/reasoning 实现差异很大，工厂层做了统一抽象：

### 4.1 Anthropic 原生 Thinking

```python
# 关闭时
thinking = {"type": "disabled"}

# 开启时（ClaudeChatModel 自动分配 budget）
thinking = {"type": "enabled", "budget_tokens": 6553}  # 8192 * 0.8
```

`ClaudeChatModel` 的 `THINKING_BUDGET_RATIO = 0.8`，当 thinking 启用但未指定 `budget_tokens` 时自动分配。

### 4.2 OpenAI 兼容网关

```python
# 关闭时
extra_body = {
    "thinking": {"type": "disabled"},
    "reasoning_effort": "minimal"
}
```

### 4.3 vLLM/Qwen

```python
# 关闭时
extra_body = {
    "chat_template_kwargs": {
        "thinking": False,
        "enable_thinking": False
    }
}
```

### 4.4 Codex Responses API

Codex 不使用 thinking 概念，而是用 `reasoning_effort`：

```python
reasoning_effort = "none"    # thinking 关闭
reasoning_effort = "medium"  # thinking 启用（默认）
reasoning_effort = "high"    # thinking 启用（高强度）
```

### 4.5 DeepSeek 多轮 `reasoning_content`

DeepSeek API 要求所有 assistant 消息在多轮对话中携带 `reasoning_content`。`PatchedChatDeepSeek` 重写 `_get_request_payload`，从 `additional_kwargs` 中恢复 `reasoning_content` 字段。

### 4.6 MiniMax `reasoning_split`

MiniMax 返回 `reasoning_details` 结构，LangChain 默认丢弃。`PatchedChatMiniMax`：

- 强制 `extra_body.reasoning_split = True`
- 从流式 delta 提取 reasoning 文本
- 把内联 `<think>...</think>` 标签移到 `additional_kwargs.reasoning_content`

### 4.7 Gemini `thought_signature`

Gemini thinking 通过 OpenAI 兼容网关时，tool call 对象需要回显 `thought_signature`。`PatchedChatOpenAI` 的 `_restore_tool_call_signatures` 按 ID 匹配（退化到位置匹配）恢复签名。

### 4.8 vLLM `reasoning` 字段

vLLM 0.19.0 使用非标准 `reasoning` 字段。`VllmChatModel`：

- 标准化 `thinking` 到 `enable_thinking`
- 在多轮对话中恢复 `reasoning` 字段
- 在非流式和流式输出中保留 `reasoning`

---

## 5. 凭证加载系统

`models/credential_loader.py` 管理 OAuth 和 API key 凭证。

### 5.1 Claude Code OAuth

```python
class ClaudeCodeCredential:
    # 加载优先级：
    # 1. 环境变量 CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_AUTH_TOKEN
    # 2. ~/.claude/.credentials.json
    # 3. 文件描述符
```

OAuth token 通过 `sk-ant-oat` 前缀检测。OAuth 模式需要 beta headers：`oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14`。

OAuth 模式下 prompt caching 被禁用（OAuth token 有 4 个 `cache_control` 块限制）。

### 5.2 Codex CLI

```python
class CodexCliCredential:
    # 从 ~/.codex/auth.json 加载
```

### 5.3 自动加载

`ClaudeChatModel.model_post_init()` 在没有有效 API key 时自动加载凭证：

```python
def model_post_init(self, __context):
    if not self.api_key or self.api_key == "test":
        credential = load_claude_code_credential()
        self.api_key = credential.api_key
```

---

## 6. Tracing 集成

`deerflow/tracing/factory.py::build_tracing_callbacks()` 根据配置构建 tracing 回调。

支持的提供商：

- **LangSmith**：`langsmith` tracing
- **Langfuse**：`langfuse` tracing

配置在 `config.yaml` 的 `tracing` 部分：

```yaml
tracing:
  langsmith:
    enabled: true
    project: my-project
  langfuse:
    enabled: false
```

tracing 回调附加到模型实例上，每次 LLM 调用自动上报。

---

## 7. 模型在 Agent 装配中的角色

`make_lead_agent()` 中模型装配是关键步骤之一：

```python
# 1. 解析最终模型名
model_name = _resolve_model_name(runtime_params, agent_config, global_config)

# 2. 创建模型实例
model = create_chat_model(
    name=model_name,
    thinking_enabled=thinking_enabled,
    reasoning_effort=reasoning_effort,
)

# 3. 传给 create_agent
agent = create_agent(model=model, tools=tools, ...)
```

模型选择不是静态的，而是每次 run 都根据 runtime 参数动态决定。

---

## 8. 配置示例

```yaml
models:
  # Claude Sonnet - 主力模型
  - name: claude-sonnet-4.6
    use: "deerflow.models.claude_provider:ClaudeChatModel"
    model: claude-sonnet-4-6
    supports_thinking: true
    supports_vision: true
    api_key: $ANTHROPIC_API_KEY
    max_tokens: 8192
    enable_prompt_caching: true

  # OpenAI GPT-4o
  - name: gpt-4o
    use: "langchain_openai:ChatOpenAI"
    model: gpt-4o
    supports_thinking: false
    supports_vision: true
    api_key: $OPENAI_API_KEY

  # vLLM 本地部署
  - name: qwen-local
    use: "deerflow.models.vllm_provider:VllmChatModel"
    model: Qwen/Qwen2.5-72B-Instruct
    supports_thinking: true
    supports_vision: false
    base_url: http://localhost:8000/v1
    api_key: not-needed
```

---

## 9. 总结

DeerFlow 的模型系统核心设计原则：

| 原则 | 说明 |
|------|------|
| 配置驱动 | 模型通过 YAML 声明，不改代码 |
| 反射加载 | `resolve_class()` 动态实例化 |
| 透传字段 | `extra="allow"` 支持任意提供商配置 |
| Thinking 抽象 | 工厂层统一处理各提供商的 thinking 差异 |
| 凭证自动加载 | OAuth/API key 自动发现，不需要硬编码 |
| 运行时切换 | 每次 run 动态选择模型，不绑定到 agent |

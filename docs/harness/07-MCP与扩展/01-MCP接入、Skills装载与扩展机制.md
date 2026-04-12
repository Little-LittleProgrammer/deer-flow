# DeerFlow Harness MCP 接入、Skills 装载与扩展机制

> 目标：说明 DeerFlow 当前实现里，MCP、skills 和反射式扩展是如何共同构成"可插拔能力面"的，以及这些能力为什么没有直接耦合进核心 agent 代码。
>
> 代码范围：以 `backend/packages/harness/deerflow/mcp/`、`skills/`、`reflection/` 和 `config/` 为主。

补充专题：

- `../04-工具系统/01-工具加载、内置工具与Deferred Tool Search.md`：工具系统主链路
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：prompt 装配和 runtime 条件注入

---

## 1. 扩展不是单一机制

DeerFlow 至少有三种扩展面：

| 扩展类型 | 作用面 | 本质 |
|---------|--------|------|
| 反射式 Python 扩展 | 代码对象 | 配置字符串 → 真实 Python 对象 |
| MCP server 扩展 | 工具调用 | 外部能力系统 → 标准 BaseTool |
| Skills 文本扩展 | Prompt 注入 | 工作流知识 → system prompt section |

"扩展"在 DeerFlow 里不等于"新增一个工具"：

- 反射式扩展：加载代码实现（模型、sandbox provider、guardrail）
- MCP：加载外部执行能力
- Skills：加载方法论和领域知识

---

## 2. 反射层：最基础的扩展底座

### 2.1 核心函数

`deerflow/reflection/resolvers.py`：

| 函数 | 签名 | 用途 |
|------|------|------|
| `resolve_variable` | `(path: str) -> Any` | 解析任意 Python 对象 |
| `resolve_class` | `(path: str, base_class: Type) -> Type` | 解析并校验子类 |

### 2.2 解析格式

```python
# 格式: "模块路径:对象名"
resolve_variable("deerflow.sandbox.local:LocalSandboxProvider")
resolve_class("deerflow.models.claude_provider:ClaudeChatModel", BaseChatModel)
```

### 2.3 被谁使用

| 模块 | 使用场景 |
|------|----------|
| 工具加载 | 普通工具通过 `use` 字段装载 |
| 模型工厂 | 模型类通过 `use` 字段装载 |
| Sandbox Provider | provider 类通过 `use` 字段装载 |
| Guardrail Provider | 护栏 provider 动态加载 |

### 2.4 缺失依赖提示

当模块无法导入时，`_build_missing_dependency_hint()` 给出可操作提示：

```
Failed to import langchain_anthropic. Try: uv add langchain-anthropic
```

---

## 3. MCP 接入流程

### 3.1 主入口

`deerflow/mcp/tools.py::get_mcp_tools()`：

```text
get_mcp_tools()
  |
  +-- 1. 读取最新 ExtensionsConfig
  |      ExtensionsConfig.from_file()  ← 总是读磁盘
  |
  +-- 2. 根据配置构造 server config
  |      包括 URL、headers、OAuth 等
  |
  +-- 3. 准备 OAuth 初始头
  |      如果 server 配置了 OAuth credentials
  |
  +-- 4. 构造 MultiServerMCPClient
  |      langchain_mcp_adapters 客户端
  |
  +-- 5. 从所有启用的 server 拉取工具
  |
  +-- 6. 对 async-only 工具补 sync wrapper
  |      _make_sync_tool_wrapper()
  |
  +-- 7. 返回标准 BaseTool 列表
```

### 3.2 缓存机制

```text
initialize_mcp_tools()       ← 启动/更新时调用
  → 读取磁盘配置
  → 初始化 MCP 客户端
  → 拉取工具
  → 补同步 wrapper
  → 缓存到全局变量

get_cached_mcp_tools()       ← Agent 装配时调用
  → 返回缓存的工具列表
```

### 3.3 为什么总是重新读磁盘

| 原因 | 说明 |
|------|------|
| 多进程解耦 | Gateway 进程和 LangGraph worker 可能不是同一进程 |
| 配置变更 | 配置更新可能由另一个进程写回磁盘 |
| 及时性 | 保证配置变更后下次装配能读到最新值 |

---

## 4. 同步 Wrapper 的原理

MCP server 返回的工具可能只有异步接口，但 DeerFlow 某些调用面仍需要同步可调用函数。

`_make_sync_tool_wrapper()` 处理：

```python
def _make_sync_tool_wrapper(async_fn):
    def sync_wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的 event loop，可以直接 await
            return asyncio.run(async_fn(*args, **kwargs))
        # 有运行中的 event loop，投递到线程池
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, async_fn(*args, **kwargs))
            return future.result()
    return sync_wrapper
```

这避免了嵌套 event loop 问题，让 MCP 工具最终都收敛成 DeerFlow 可统一调用的形态。

---

## 5. Skills 不是工具，是 Prompt 资源

### 5.1 装载流程

`deerflow/skills/loader.py::load_skills()`：

```text
load_skills(enabled_skills, skills_root_path)
  |
  +-- 1. 扫描 skills/public/ 和 skills/custom/
  |
  +-- 2. 发现 SKILL.md 文件
  |
  +-- 3. 解析 frontmatter（YAML）和内容（Markdown）
  |      name, description, version
  |
  +-- 4. 校验 frontmatter schema
  |
  |   → Skill(
  |       name="data-analysis",
  |       description="...",
  |       content="<SKILL_CONTENT>",
  |       enabled=True,
  |   )
  |
  +-- 5. 结合 ExtensionsConfig 判断是否启用
  |
  +-- 6. 返回启用的 Skill 列表
```

### 5.2 Skill 数据结构

```python
@dataclass
class Skill:
    name: str                   # 唯一名称
    description: str            # 描述
    content: str                # SKILL.md 内容
    version: str | None         # 版本号
    enabled: bool               # 是否启用
```

### 5.3 用途

Skills 的主用途不是自动注册成工具，而是：

- 作为 prompt 注入素材
- 为模型提供领域工作流、规范和专用说明

粗略理解：

- **Tool** = 执行能力
- **Skill** = 策略知识

---

## 6. Public / Custom 分离的设计

| 目录 | 用途 | 管理方式 |
|------|------|----------|
| `skills/public/` | 平台自带、可共享的技能 | 随项目发布 |
| `skills/custom/` | 项目或用户侧自定义技能 | gitignore 或独立管理 |

启用控制通过 `ExtensionsConfig`：

```json
{
  "skills": {
    "data-analysis": { "enabled": true },
    "report-writing": { "enabled": false }
  }
}
```

好处：

1. 技能文件可以长期存在，但按需启停
2. 平台能力和业务定制共用同一套装载机制

---

## 7. Skill 安装与安全管理

### 7.1 压缩包安装

`skills/installer.py::install_skill_from_archive()`：

1. 校验压缩包格式（zip/tar.gz）
2. 安全检查（路径穿越、符号链接）
3. 解压到 `skills/custom/`
4. 验证 `SKILL.md` 存在
5. 更新 `ExtensionsConfig`

### 7.2 安全扫描

`skills/security_scanner.py`：

- 检测路径穿越
- 检测恶意文件类型
- 检测符号链接攻击
- 校验文件大小

### 7.3 验证

`skills/validation.py`：

- frontmatter schema 校验
- 必填字段检查
- 版本格式校验

---

## 8. MCP 与 Skills 的关系

| 维度 | MCP | Skills |
|------|-----|--------|
| 解决什么 | 系统可以调用哪些外部能力 | 模型该如何使用这些能力 |
| 作用面 | 工具（执行） | Prompt（策略） |
| 来源 | 外部 server（HTTP/gRPC） | 本地文件（SKILL.md） |
| 运行时形态 | BaseTool 列表 | system prompt section |

### 8.1 常见组合

```text
MCP 提供: 数据库查询工具、API 调用工具
Skill 教导: 什么时候查数据库、按什么步骤调用 API
```

DeerFlow 扩展体系的完整性：

- 不只扩动作（MCP）
- 也扩方法（Skills）

---

## 9. ExtensionsConfig：扩展控制平面

### 9.1 文件位置

`extensions_config.json`，位于项目根目录或 `backend/` 目录。

### 9.2 结构

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "enabled": true
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
      "enabled": false
    }
  },
  "skills": {
    "data-analysis": { "enabled": true },
    "report-writing": { "enabled": true }
  }
}
```

### 9.3 职责分离

| 配置 | 职责 |
|------|------|
| `config.yaml` | 主应用配置（模型、sandbox、tools） |
| `extensions_config.json` | 扩展控制（MCP、skills 启停） |

拆出来的好处：

- Gateway 可以提供扩展开关 API
- 避免核心 `AppConfig` 过度膨胀
- 扩展配置变更不影响主应用配置

---

## 10. Skill Evolution：技能的动态演进

### 10.1 配置

`config/skill_evolution_config.py`：

```yaml
skill_evolution:
  enabled: true
  model: claude-sonnet-4.6     # 用于分析技能使用情况的模型
```

### 10.2 目的

让系统能够根据使用反馈自动改进 SKILL.md 内容：

1. 跟踪 skill 的使用效果
2. 分析哪些指导有效、哪些无效
3. 生成改进建议
4. 更新 SKILL.md

---

## 11. 扩展体系的设计原则

| 原则 | 说明 |
|------|------|
| 核心运行时瘦身 | 具体能力通过配置、反射和扩展模块接入 |
| 工具与知识扩展分离 | MCP 解决工具接入，skills 解决方法论注入 |
| 多进程以磁盘配置为准 | Gateway 与 worker 解耦下的现实选择 |
| 扩展收敛为可消费形态 | MCP → BaseTool，Skill → prompt section |

---

## 12. 总结

DeerFlow 的扩展体系不是"在核心里加更多 if/else"，而是：

> 用反射层加载代码扩展，用 MCP 接入外部执行能力，用 skills 注入工作流知识，再由 agent 装配层把它们统一编译进一次具体运行。

核心判断：

- DeerFlow 的可扩展性不只在工具层
- 它同时扩展执行能力（MCP）、配置控制面（ExtensionsConfig）和 prompt 知识面（Skills）

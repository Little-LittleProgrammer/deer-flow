# DeerFlow Harness Bash 安全措施与执行链

> 目标：基于当前仓库实现，说明 Harness 对模型输出的 `bash` 命令做了哪些安全控制，以及一条 `bash` 工具调用从模型到沙箱的完整执行链。
>
> 代码范围：以 `backend/packages/harness/deerflow/` 为主。

---

## 1. 结论概览

当前 Harness 对模型输出的 `bash` 命令，主要做了 4 层控制：

1. 默认不向模型暴露宿主机 `bash`
2. 在本地沙箱模式下对命令中的路径做白名单校验和路径穿越拦截
3. 在 middleware 层对高风险命令做阻断、对中风险命令做告警和审计
4. 对执行结果做宿主机路径脱敏和输出截断

除此之外，文件工具本身还有单独的读写边界控制，和 `bash` 一起构成整个 sandbox 能力面的约束。

需要特别注意的是：当前分支里 `bash_tool` 的 git 写操作拦截逻辑存在接线缺陷，见本文第 7 节。

---

## 2. 第一层：默认不暴露宿主机 Bash

### 2.1 本地沙箱默认认为 host bash 不安全

当 sandbox provider 是 `LocalSandboxProvider` 时，`allow_host_bash` 默认值为 `false`。

这意味着框架明确认为：

- 本地宿主机执行不是安全沙箱边界
- 只有在“完全可信的本地环境”里才允许显式打开

相关代码：

- `backend/packages/harness/deerflow/config/sandbox_config.py`
- `backend/packages/harness/deerflow/sandbox/security.py`

关键逻辑：

- `uses_local_sandbox_provider()`：判断当前是否为本地沙箱
- `is_host_bash_allowed()`：只有非本地 provider，或显式开启 `allow_host_bash` 时才返回 `True`

### 2.2 工具加载阶段就把 bash 从模型可见工具列表里移除

这一步很重要，因为它不是“执行时拒绝”，而是“默认不给模型看到这把刀”。

`get_available_tools()` 会在 `allow_host_bash` 为 `False` 时，把以下工具从可用工具列表移除：

- `group == "bash"` 的工具
- `use == "deerflow.sandbox.tools:bash_tool"` 的工具

相关代码：

- `backend/packages/harness/deerflow/tools/tools.py`

这意味着在本地沙箱默认配置下，模型通常根本拿不到 `bash` 工具 schema。

---

## 3. 第二层：本地 Bash 的路径安全校验

如果宿主机 `bash` 被显式打开，Harness 仍然会在 `bash_tool()` 内对命令参数做前置校验。

相关代码：

- `backend/packages/harness/deerflow/sandbox/tools.py`

### 3.1 拦截路径穿越

`_reject_path_traversal()` 会拒绝路径中出现 `..` segment，不论是 `/` 还是 `\` 风格。

这条规则会被多个地方复用：

- 文件工具路径校验
- `bash` 命令路径校验
- skills/acp workspace 路径解析

### 3.2 限制 Bash 中允许出现的绝对路径

`validate_local_bash_command_paths()` 会扫描命令中的绝对路径，只允许这些路径族：

- `/mnt/user-data/*`
- `/mnt/skills/*`
- `/mnt/acp-workspace/*`
- 配置里的自定义 mount 路径
- 少量系统路径前缀，如 `/bin/`、`/usr/bin/`、`/usr/sbin/`、`/sbin/`、`/opt/homebrew/bin/`、`/dev/`
- MCP filesystem server 配置中允许的路径

不在白名单里的绝对路径会被拒绝，比如：

- `/etc/passwd`
- `/Users/...`
- `/home/...`

### 3.3 拦截 `file://` URL

`file://` 不会被普通绝对路径正则稳定覆盖，因此代码专门增加了 `_FILE_URL_PATTERN` 检测。

只要命令里出现 `file://...`，就会直接拒绝，避免通过 URL 形式读本地文件。

### 3.4 注意：这里是 best-effort，不是强隔离

源码注释已经写得很直接：

- 这只是对显式开启 host bash 时的“最佳努力防护”
- 不是可信的宿主机隔离边界

也就是说，真正的强隔离仍然应优先依赖容器化的 `AioSandboxProvider`，而不是本地 host bash。

---

## 4. 第三层：文件工具自身的读写边界

除了 `bash`，Harness 的 `ls` / `read_file` / `write_file` / `str_replace` 等文件工具还有单独的访问控制。

相关代码：

- `backend/packages/harness/deerflow/sandbox/tools.py`
- `backend/packages/harness/deerflow/sandbox/local/local_sandbox.py`

### 4.1 虚拟路径白名单

`validate_local_tool_path()` 只允许访问以下虚拟路径：

- `/mnt/user-data/*`
- `/mnt/skills/*`
- `/mnt/acp-workspace/*`
- configured mounts

不在这些路径下的访问会直接报错。

### 4.2 skills 和 acp workspace 只读

`/mnt/skills/*` 和 `/mnt/acp-workspace/*` 只允许读，不允许写。

也就是说：

- `read_file` / `ls` 可以读
- `write_file` / `str_replace` 不能写

### 4.3 user-data 解析后还会再次验证边界

`/mnt/user-data/*` 映射到宿主机路径后，不是直接信任，而是继续通过 `_validate_resolved_user_data_path()` 做一次真实路径校验，确保最终路径仍然位于当前 thread 的：

- `workspace_path`
- `uploads_path`
- `outputs_path`

这能防住“虚拟路径看起来合法，但 resolve 后逃出目录”的情况。

### 4.4 本地 mount 支持只读

`LocalSandbox` 的 path mapping 支持 `read_only`，写操作前会检查 `_is_read_only_path()`。

因此自定义 mount 也可以做成只读共享。

---

## 5. 第四层：Middleware 级风险命令拦截与审计

`SandboxAuditMiddleware` 是专门针对 `bash` 工具调用做的额外风控层。

相关代码：

- `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py`
- `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`

### 5.1 中间件接入顺序

基础运行时 middleware 的装配顺序是：

1. `ThreadDataMiddleware`
2. `UploadsMiddleware`（lead agent）
3. `SandboxMiddleware`
4. `DanglingToolCallMiddleware`
5. `LLMErrorHandlingMiddleware`
6. `GuardrailMiddleware`（若启用）
7. `SandboxAuditMiddleware`
8. `ToolErrorHandlingMiddleware`

因此 `SandboxAuditMiddleware` 是在真正调用工具前执行的，且比 `ToolErrorHandlingMiddleware` 更早。

### 5.2 高风险命令直接 block

当前硬编码高风险规则包括：

- `rm -rf /`
- `curl ... | bash`
- `wget ... | sh`
- `dd if=...`
- `mkfs`
- `cat /etc/shadow`
- 覆盖 `/etc/*`

对于这些命令：

- 不会调用真正的 `bash` handler
- 直接返回 error `ToolMessage`

### 5.3 中风险命令只警告不拦截

当前中风险规则包括：

- `chmod 777`
- `pip install`
- `pip3 install`
- `apt install`
- `apt-get install`

这些命令会继续执行，但 middleware 会在结果后面附加 warning，提醒模型这是会修改运行环境的命令。

### 5.4 所有 bash 调用都会写审计日志

middleware 会记录：

- timestamp
- thread_id
- command
- verdict

日志通过标准 logger 输出，便于后续审计。

---

## 6. 第五层：执行结果脱敏与输出限制

即使命令执行通过，Harness 还会继续对结果做安全处理。

### 6.1 宿主机路径映射回虚拟路径

本地沙箱下，输出中的真实宿主机路径会被替换回虚拟路径，避免直接泄露机器上的真实目录结构。

覆盖范围包括：

- thread 的 user-data 目录
- skills host path
- acp workspace host path
- custom mount host path

相关代码：

- `mask_local_paths_in_output()`
- `LocalSandbox._reverse_resolve_paths_in_output()`

### 6.2 输出截断

`bash_output_max_chars` 用于限制 `bash` 返回给模型的内容长度。

截断方式是保留头尾两端，中间截断，避免长日志占满上下文，同时保留更可能有价值的：

- 头部上下文
- 尾部错误信息 / 退出码

---

## 7. 额外策略：Git 高危命令阻断

`bash_tool()` 在真正执行前会调用 `is_high_risk_git_command()`（历史别名为 `is_git_write_command`），仅拦截**高危** git 子命令。

相关代码：

- `backend/packages/harness/deerflow/sandbox/security.py`
- `backend/packages/harness/deerflow/sandbox/tools.py`（`if is_high_risk_git_command(command): ...`）

当前被列入 block 的子命令为：

- `push`（写入远程，可能影响共享仓库）
- `clean`（可大量删除未跟踪文件）

其余 git CLI（如 `commit`、`fetch`、`pull`、`merge`、`rebase`、`remote`、`clone` 等）不在拦截列表中，由使用方自行权衡风险。

---

## 8. Bash 工具完整执行链

下面按代码执行顺序，给出一条模型调用 `bash` 的完整链路。

### 8.1 lead agent 装配阶段

`make_lead_agent()` 会：

1. 创建模型
2. 调用 `get_available_tools()`
3. 调用 `_build_middlewares()`
4. `create_agent(...)`

如果当前是 `LocalSandboxProvider` 且 `allow_host_bash=false`，那么 `bash` 工具在这一步就可能已经被剔除。

### 8.2 模型产出 tool call

当模型输出一个 `bash` tool call 后，请求进入 middleware 链。

### 8.3 middleware 链处理

按当前实现，关键节点是：

1. `ThreadDataMiddleware`
   作用：准备 thread 维度上下文和 `thread_data`
2. `UploadsMiddleware`
   作用：准备 upload 相关状态
3. `SandboxMiddleware`
   作用：按 thread 获取或延迟创建 sandbox
4. `GuardrailMiddleware`（若启用）
   作用：按 provider 决定工具是否允许调用
5. `SandboxAuditMiddleware`
   作用：按规则将命令分为 `block` / `warn` / `pass`
6. `ToolErrorHandlingMiddleware`
   作用：把未捕获异常转成 error `ToolMessage`

如果在第 4 或第 5 步被拒绝，则不会进入 `bash_tool()`。

### 8.4 `bash_tool()` 内部处理

如果进入工具函数，关键步骤是：

1. 设计上先检查 git 写命令
2. `ensure_sandbox_initialized(runtime)`
3. 判断是否是 local sandbox
4. 若是 local sandbox：
   - 检查 `is_host_bash_allowed()`
   - `ensure_thread_directories_exist()`
   - `validate_local_bash_command_paths()`
   - `replace_virtual_paths_in_command()`
   - `_apply_cwd_prefix()`，把 cwd 锚到 thread workspace
   - `sandbox.execute_command()`
   - `mask_local_paths_in_output()`
   - `_truncate_bash_output()`
5. 若是非 local sandbox：
   - 直接在 provider 对应的 sandbox 中执行
   - 再做输出截断

### 8.5 `LocalSandbox.execute_command()` 的最后一层处理

本地沙箱真正执行命令时还会做两件事：

1. 将容器路径映射到宿主机路径
2. 执行结束后，再把输出里的宿主机路径映射回容器路径

因此模型最终看到的是：

- 线程级工作目录语义
- 虚拟路径语义

而不是宿主机的真实目录布局。

---

## 9. 执行链示意图

```text
make_lead_agent()
  -> get_available_tools()
     -> LocalSandboxProvider 且 allow_host_bash=false
        -> 从工具列表隐藏 bash
  -> _build_middlewares()
     -> ThreadDataMiddleware
     -> UploadsMiddleware
     -> SandboxMiddleware
     -> GuardrailMiddleware(optional)
     -> SandboxAuditMiddleware
     -> ToolErrorHandlingMiddleware
  -> create_agent(...)

模型输出 bash tool call
  -> GuardrailMiddleware(optional)
     -> deny 则返回 error ToolMessage
  -> SandboxAuditMiddleware
     -> high risk: block
     -> medium risk: warn
     -> safe: pass
  -> bash_tool()
     -> 设计上检查 git 写命令
     -> ensure_sandbox_initialized()
     -> local sandbox?
        -> no:
           -> sandbox.execute_command()
           -> truncate output
        -> yes:
           -> is_host_bash_allowed()
           -> validate_local_bash_command_paths()
           -> replace_virtual_paths_in_command()
           -> cd <thread workspace> &&
           -> LocalSandbox.execute_command()
              -> 映射虚拟路径到宿主机路径
              -> subprocess.run(...)
              -> 输出中的宿主机路径映射回虚拟路径
           -> mask_local_paths_in_output()
           -> truncate output
  -> ToolErrorHandlingMiddleware
     -> 未捕获异常转成 error ToolMessage
```

---

## 10. 当前实现的边界与风险

### 10.1 真正硬边界主要依赖“工具暴露控制 + 路径约束 + 中间件拦截”

这套设计对常见误用和明显危险命令是有效的，但它不是等价于完整的 OS 级隔离。

### 10.2 LocalSandbox 的 host bash 仍然不是可信隔离边界

源码已经明确承认这一点，因此：

- 默认不开启 host bash 是合理的
- 需要强隔离时，应优先用 `AioSandboxProvider`

### 10.3 当前分支存在 git 写拦截接线问题

这不是设计问题，而是实现问题。只要不修，`bash_tool()` 在进入 git 拦截分支前就可能抛 `NameError`，影响后续预期行为。

---

## 11. 代码索引

核心代码位置如下：

- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/deerflow/sandbox/security.py`
- `backend/packages/harness/deerflow/sandbox/tools.py`
- `backend/packages/harness/deerflow/sandbox/middleware.py`
- `backend/packages/harness/deerflow/sandbox/local/local_sandbox.py`
- `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py`
- `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

相关测试：

- `backend/tests/test_sandbox_tools_security.py`
- `backend/tests/test_sandbox_audit_middleware.py`
- `backend/tests/test_sandbox_feishu_git.py`
- `backend/tests/test_local_bash_tool_loading.py`

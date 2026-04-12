# DeerFlow Harness Bash 安全措施与执行链

> 目标：基于当前仓库实现，说明 Harness 对模型输出的 `bash` 命令做了哪些安全控制，以及一条 `bash` 工具调用从模型到沙箱的完整执行链。
>
> 代码范围：以 `backend/packages/harness/deerflow/` 为主。

补充专题：

- `../04-工具系统/01-工具加载、内置工具与Deferred Tool Search.md`：工具如何被暴露给模型
- `../03-Agent装配/01-LeadAgent装配与Middleware链.md`：middleware 链顺序

---

## 1. 结论概览

当前 Harness 对模型输出的 `bash` 命令，主要做了 5 层控制：

1. **默认不暴露**：工具加载阶段就从模型可见列表移除 `bash`
2. **路径白名单**：本地沙箱下对命令中的路径做白名单校验和路径穿越拦截
3. **中间件审计**：middleware 层对高风险命令阻断、中风险命令告警
4. **结果脱敏**：执行结果中的宿主机路径映射回虚拟路径，输出截断
5. **Git 高危拦截**：`push`、`clean` 等高危 git 子命令直接阻断

除此之外，文件工具（`ls`/`read_file`/`write_file`/`str_replace`）有单独的读写边界控制。

---

## 2. 第一层：默认不暴露宿主机 Bash

### 2.1 安全假设

当 sandbox provider 是 `LocalSandboxProvider` 时，`allow_host_bash` 默认值为 `false`。

这意味着框架明确认为：

- 本地宿主机执行不是安全沙箱边界
- 只有在"完全可信的本地环境"里才允许显式打开

### 2.2 关键函数

| 函数 | 位置 | 作用 |
|------|------|------|
| `uses_local_sandbox_provider()` | `config/sandbox_config.py` | 判断当前是否为本地沙箱 |
| `is_host_bash_allowed(config)` | `sandbox/security.py` | 只有非本地 provider 或显式开启时才返回 `True` |

### 2.3 工具加载阶段剔除

`get_available_tools()` 在 `allow_host_bash=False` 时移除：

- `group == "bash"` 的所有工具
- `use == "deerflow.sandbox.tools:bash_tool"` 的工具

**这不是"执行时拒绝"，而是"默认不给模型看到这把刀"**。

---

## 3. 第二层：本地 Bash 的路径安全校验

如果宿主机 `bash` 被显式打开，`bash_tool()` 内仍然对命令参数做前置校验。

### 3.1 路径穿越拦截

`_reject_path_traversal(cmd)` 拒绝路径中出现 `..` segment：

```python
# 拒绝这些
cat ../../../etc/passwd
ls /mnt/user-data/../../etc
```

覆盖 `/` 和 `\` 两种风格。被多处复用：

- 文件工具路径校验
- `bash` 命令路径校验
- skills/ACP workspace 路径解析

### 3.2 绝对路径白名单

`validate_local_bash_command_paths()` 扫描命令中的绝对路径，只允许：

| 允许的路径族 | 说明 |
|-------------|------|
| `/mnt/user-data/*` | 线程工作区 |
| `/mnt/skills/*` | 技能目录（只读） |
| `/mnt/acp-workspace/*` | ACP 工作区 |
| 配置的自定义 mount 路径 | 用户自定义挂载 |
| `/bin/`, `/usr/bin/`, `/usr/sbin/`, `/sbin/` | 系统可执行文件 |
| `/opt/homebrew/bin/` | Homebrew（macOS） |
| `/dev/` | 设备文件 |
| MCP filesystem server 允许的路径 | MCP 配置中的路径 |

**不在白名单中的路径直接拒绝**：

```
/etc/passwd      → 拒绝
/Users/evanwu/.ssh/id_rsa  → 拒绝
/home/user/.bashrc  → 拒绝
```

### 3.3 `file://` URL 拦截

`file://` 不会被普通绝对路径正则覆盖，因此单独检测：

```python
_FILE_URL_PATTERN = re.compile(r"file://")
```

### 3.4 Best-effort 声明

源码注释明确说明这是 best-effort 防护，不是强隔离。真正的强隔离应优先依赖容器化的 `AioSandboxProvider`。

---

## 4. 第三层：文件工具的读写边界

### 4.1 虚拟路径白名单

`validate_local_tool_path()` 只允许访问：

- `/mnt/user-data/*`
- `/mnt/skills/*`
- `/mnt/acp-workspace/*`
- configured mounts

### 4.2 Skills 和 ACP 只读

| 路径 | 读 | 写 |
|------|---|---|
| `/mnt/user-data/*` | 允许 | 允许 |
| `/mnt/skills/*` | 允许 | 拒绝 |
| `/mnt/acp-workspace/*` | 允许 | 拒绝 |

### 4.3 user-data 解析后二次验证

`/mnt/user-data/*` 映射到宿主机路径后，继续通过 `_validate_resolved_user_data_path()` 校验，确保最终路径位于当前 thread 的：

- `workspace_path`
- `uploads_path`
- `outputs_path`

这防住"虚拟路径合法，但 resolve 后逃出目录"的情况。

### 4.4 本地 Mount 只读支持

`LocalSandbox` 的 path mapping 支持 `read_only` 标记，写操作前检查 `_is_read_only_path()`。

---

## 5. 第四层：Middleware 级风险审计

`SandboxAuditMiddleware` 是专门针对 `bash` 的风控层。

### 5.1 中间件接入顺序

```
ThreadDataMiddleware
  → UploadsMiddleware
    → SandboxMiddleware
      → DanglingToolCallMiddleware
        → LLMErrorHandlingMiddleware
          → GuardrailMiddleware（可选）
            → SandboxAuditMiddleware    ← 风险审计
              → ToolErrorHandlingMiddleware
```

`SandboxAuditMiddleware` 在真正调用工具前执行，比 `ToolErrorHandlingMiddleware` 更早。

### 5.2 高风险命令（直接 Block）

| 规则 | 风险 |
|------|------|
| `rm -rf /` | 删除整个文件系统 |
| `curl ... | bash` | 远程代码执行 |
| `wget ... | sh` | 远程代码执行 |
| `dd if=...` | 磁盘写入 |
| `mkfs` | 格式化文件系统 |
| `cat /etc/shadow` | 读取密码哈希 |
| 覆盖 `/etc/*` | 系统配置篡改 |

处理方式：不调用 `bash` handler，直接返回 error `ToolMessage`。

### 5.3 中风险命令（Warning）

| 规则 | 风险 |
|------|------|
| `chmod 777` | 权限过度开放 |
| `pip install` | 环境污染 |
| `pip3 install` | 环境污染 |
| `apt install` | 系统变更 |
| `apt-get install` | 系统变更 |

处理方式：继续执行，但在结果后面附加 warning。

### 5.4 审计日志

每条 bash 调用记录：

- timestamp
- thread_id
- command
- verdict（block / warn / pass）

---

## 6. 第五层：执行结果脱敏与截断

### 6.1 路径映射回虚拟路径

`mask_local_paths_in_output()` 把输出中的真实宿主机路径替换回虚拟路径：

```
# 执行前
cd /Users/evanwu/code-workspace/github/deer-flow/backend/.deer-flow/threads/abc/user-data/workspace

# 输出
Created file at /Users/evanwu/code-workspace/github/deer-flow/backend/.deer-flow/threads/abc/user-data/workspace/output.txt

# 脱敏后
Created file at /mnt/user-data/workspace/output.txt
```

覆盖范围：

- thread 的 user-data 目录
- skills host path
- ACP workspace host path
- custom mount host path

### 6.2 输出截断

`bash_output_max_chars` 限制返回内容长度。截断方式是保留头尾两端，中间用 `...` 代替：

```
[前 2000 字符]...[后 500 字符（通常是错误信息/退出码）]
```

---

## 7. 额外策略：Git 高危命令阻断

`bash_tool()` 执行前调用 `is_high_risk_git_command()`：

| 拦截的子命令 | 原因 |
|-------------|------|
| `git push` | 写入远程，影响共享仓库 |
| `git clean` | 可大量删除未跟踪文件 |

其余 git CLI（`commit`、`fetch`、`pull`、`merge`、`rebase` 等）不拦截，由使用方自行权衡。

---

## 8. Bash 工具完整执行链

```text
模型输出 bash tool call
  |
  v
[Middleware 链]
  ThreadDataMiddleware      → 准备 thread 目录上下文
    UploadsMiddleware       → 准备上传文件状态
      SandboxMiddleware     → 获取/复用 sandbox
        DanglingToolCallMiddleware → 修复悬挂工具调用
          LLMErrorHandlingMiddleware → LLM 错误处理
            GuardrailMiddleware（可选）→ 工具调用授权
              SandboxAuditMiddleware   → 命令风险审计
                high risk: 直接 block，返回 error ToolMessage
                medium risk: 标记 warn，继续执行
                safe: pass
  |
  v
[bash_tool()]
  1. is_high_risk_git_command()  → 拦截 git push/clean
  2. ensure_sandbox_initialized()
  3. local sandbox?
     → No:
       sandbox.execute_command(command)
       truncate_output(result)
     → Yes:
       is_host_bash_allowed()      → 不允许则报错
       ensure_thread_directories_exist()
       validate_local_bash_command_paths()  → 路径白名单
       replace_virtual_paths_in_command()   → 虚拟路径 → 宿主机路径
       _apply_cwd_prefix()       → 锚定到 thread workspace
       sandbox.execute_command() → LocalSandbox.execute_command()
         → 映射虚拟路径到宿主机路径
         → subprocess.run(...)
         → 输出中宿主机路径映射回虚拟路径
       mask_local_paths_in_output()  → 路径脱敏
       _truncate_bash_output()       → 输出截断
  |
  v
[ToolErrorHandlingMiddleware]
  未捕获异常 → 转成 error ToolMessage
  |
  v
模型收到 ToolMessage（成功结果或错误信息）
```

---

## 9. LocalSandbox 执行细节

`LocalSandbox.execute_command()` 是最终执行点：

```python
def execute_command(self, command: str, cwd: str | None = None):
    # 1. 映射虚拟路径到宿主机路径
    real_command = self._resolve_virtual_paths(command)

    # 2. 确定工作目录
    real_cwd = cwd or self._workspace_path

    # 3. 执行
    result = subprocess.run(
        real_command,
        shell=True,
        cwd=real_cwd,
        capture_output=True,
        text=True,
        timeout=self._timeout,
    )

    # 4. 输出中的路径映射回虚拟路径
    output = self._reverse_resolve_paths_in_output(result.stdout)

    # 5. 返回
    return BashResult(
        stdout=output,
        stderr=result.stderr,
        returncode=result.returncode,
    )
```

---

## 10. 安全设计的分层原则

| 层 | 策略 | 拦截时机 |
|----|------|----------|
| 工具暴露 | 默认不给模型看到 bash | 装配阶段 |
| 路径校验 | 白名单 + 穿越拦截 | 工具执行前 |
| 命令审计 | 高风险 block，中风险 warn | 中间件层 |
| 结果脱敏 | 路径映射 + 截断 | 执行完成后 |
| Git 拦截 | 高危子命令 block | 工具执行前 |

这是一种 **纵深防御（Defense in Depth）** 策略：每一层都提供保护，即使某一层失效，其他层仍然起作用。

---

## 11. 当前实现的边界与风险

### 11.1 LocalSandbox 不是可信隔离边界

源码已明确承认这一点。需要强隔离时应优先使用 `AioSandboxProvider`（Docker 容器化）。

### 11.2 路径白名单是 best-effort

正则匹配不能覆盖所有绕过方式（如符号链接、特殊 shell 语法）。这不是 OS 级隔离。

### 11.3 Git 写拦截范围有限

只拦截 `push` 和 `clean`，不拦截 `commit`、`remote add` 等可能有写副作用的命令。

---

## 12. 代码索引

| 文件 | 职责 |
|------|------|
| `deerflow/tools/tools.py` | 工具加载，bash 剔除逻辑 |
| `deerflow/sandbox/security.py` | `is_host_bash_allowed()`, `_reject_path_traversal()`, `validate_local_bash_command_paths()` |
| `deerflow/sandbox/tools.py` | `bash_tool()`, `validate_local_tool_path()`, `mask_local_paths_in_output()` |
| `deerflow/sandbox/local/local_sandbox.py` | `LocalSandbox.execute_command()`, 路径映射 |
| `deerflow/agents/middlewares/sandbox_audit_middleware.py` | 命令风险审计 |
| `deerflow/agents/middlewares/tool_error_handling_middleware.py` | 工具异常处理 |

相关测试：

- `backend/tests/test_sandbox_tools_security.py`
- `backend/tests/test_sandbox_audit_middleware.py`
- `backend/tests/test_local_bash_tool_loading.py`

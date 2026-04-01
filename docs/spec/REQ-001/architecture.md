# DeerFlow 智能研发工作流 - 架构与流程图

本文档基于 `deer-flow` 的 LangGraph + Sandbox 底座，结合飞书与 Codeup 生态，梳理了完整的智能研发工作流架构图。

## 1. 整体系统架构图 (System Architecture)

```mermaid
graph TD
    %% 用户与外部平台
    subgraph Users ["👨‍💻 研发团队 (Human-in-the-loop)"]
        PM[产品经理]
        TL[技术负责人]
        Dev[开发/测试]
    end

    subgraph External ["🌐 外部生态系统"]
        subgraph Feishu ["飞书 (Lark)"]
            F_Doc[云文档]
            F_Proj[飞书项目]
            F_Bot[群组消息机器人]
        end
        
        subgraph Codeup ["阿里云 Codeup"]
            C_Repo[Git 仓库]
            C_Branch[特性分支]
            C_MR[Merge Request]
        end
    end

    %% DeerFlow 核心系统
    subgraph DeerFlow ["🦌 DeerFlow Harness (Super Agent)"]
        Gateway[FastAPI Gateway]
        
        subgraph Engine ["LangGraph 状态机与编排"]
            State[状态持久化 Checkpoint]
            Router[Phase Router Agent]
        end
        
        subgraph Agents ["🤖 智能体集群 (Ultra Mode)"]
            A_Plan[Planning Agent]
            A_Review[Tech Review Agent]
            A_Code[Coding Agent]
            A_Eval[Evaluation Agent]
        end
        
        subgraph Env ["🛠 执行环境与工具链"]
            MCP_F[Lark MCP Server]
            MCP_C[Codeup OpenAPI Tools]
            CLI_F[Feishu CLI]
            Sandbox[安全沙盒 Sandbox]
        end
    end

    %% 连接与交互
    PM -->|触发任务/提供链接| Gateway
    TL -->|审批架构/文档| Gateway
    Dev -->|人工 Code Review| Codeup

    Gateway --> Engine
    Engine <--> Agents
    State -.-> Agents
    
    A_Plan --> MCP_F & MCP_C
    A_Review --> CLI_F & MCP_F
    A_Code --> Sandbox
    A_Eval --> Sandbox & MCP_C & CLI_F
    
    MCP_F <--> F_Proj & F_Doc
    CLI_F --> F_Doc & F_Bot
    MCP_C <--> C_Repo & C_MR & C_Branch
```

---

## 2. 研发工作流时序图 (Workflow Sequence)

该时序图展示了从需求规划到代码合并的完整生命周期，强调了 Agent 的执行动作、自动化闭环以及“人在回路（Human-in-the-loop）”的关键节点。

```mermaid
sequenceDiagram
    autonumber
    actor Human as 研发团队
    participant DF as DeerFlow (LangGraph)
    participant Agent as 智能体集群
    participant Sandbox as 安全沙盒
    participant Feishu as 飞书生态
    participant Codeup as 阿里云 Codeup

    %% 阶段一：产品规划
    rect rgb(240, 248, 255)
        Note right of Human: 【阶段一】 产品规划 (Planning)
        Human->>DF: 提交飞书需求链接 & Codeup 仓库地址
        DF->>Agent: 路由至 Planning Agent (Ultra Mode)
        Agent->>Feishu: 通过 MCP 读取需求文档内容
        Agent->>Codeup: 获取仓库目录树与上下文
        Agent-->>Agent: 综合分析需求可行性与逻辑遗漏
        Agent->>Feishu: 调用 Comment API 在文档标注评审意见
        Feishu-->>Human: 飞书消息提醒查看评论
    end

    %% 阶段二：技术评审
    rect rgb(255, 250, 240)
        Note right of Human: 【阶段二】 技术评审 (Tech Review)
        Human->>Feishu: 解决需求评论，点击"确认需求"
        Feishu->>DF: Webhook/状态流转触发
        DF->>Agent: 路由至 Tech Review Agent
        Agent-->>Agent: 自动生成 Spec, Design, Task, Test 文档
        Agent->>Feishu: 将四例文档写入飞书项目空间
        DF->>Human: 暂停执行 (Human-in-the-loop)，等待审批
        Human->>DF: Tech Lead 审批通过 (Approve)
    end

    %% 阶段三：代码开发
    rect rgb(240, 255, 240)
        Note right of Human: 【阶段三】 代码开发 (Development)
        DF->>Agent: 路由至 Coding Agent
        Agent->>Sandbox: 挂载代码仓库，分配开发环境
        
        loop TDD / 反馈循环 (Feedback Loop)
            Agent->>Sandbox: 编写业务代码
            Sandbox->>Agent: 返回 Linter / 语法检查结果
            Agent-->>Agent: 基于报错自动纠错修改
        end
        Agent->>Sandbox: 本地 Commit 代码
    end

    %% 阶段四：测试与评估
    rect rgb(255, 245, 245)
        Note right of Human: 【阶段四】 测试与评估 (Evaluation)
        DF->>Agent: 路由至 Evaluation Agent (引入 Anthropic Eval)
        Agent->>Sandbox: 编写并执行单元测试/集成测试
        Sandbox-->>Agent: 返回测试执行结果 (Outcome)
        
        alt 测试失败 (Failed)
            Agent->>DF: 携带 Trace 记录回退状态
            DF->>Agent: 重新路由至 Coding Agent 修复 Bug
        else 测试通过 (Passed)
            Agent-->>Agent: LLM Grader 执行代码规范/安全审计
            Agent->>Codeup: Push 至特性分支并创建 Merge Request
            Agent->>Feishu: 发送测试报告及 MR 链接至研发群组
            Feishu-->>Human: 收到通知，进入人工 Code Review 阶段
        end
    end
```

## 3. 架构设计关键点说明

1. **状态机与断点恢复 (Checkpointing)**
   - 依赖 LangGraph 的 Durable Execution，每一步（例如：代码写到一半、等待人类审批）都会进行状态持久化。即使服务重启，系统依然能从数据库读取 Checkpoint 并恢复上下文，继续开发。
2. **多智能体协作 (Sub-agent Orchestration)**
   - **Phase Router Agent** 充当大脑，根据当前的 LangGraph 节点决定调用哪个专业 Agent。
   - **Coding Agent** 专注于在 Sandbox 中实现功能，具备持续的“执行-报错-修复”反馈循环（Harness 理念）。
   - **Evaluation Agent** 包含多个 Grader（例如代码逻辑的 LLM Grader，运行测试覆盖率的 Code-based Grader），充当独立的验收裁判。
3. **环境物理隔离**
   - 外部生态（飞书/Codeup）的交互严格依赖 MCP 和指定的 OpenAPI 工具封装。
   - 代码的编译、构建、测试全部在隔离的 Docker / Pydantic Sandbox 中运行，防止 Agent 的不安全命令破坏宿主环境。
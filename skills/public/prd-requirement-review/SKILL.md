---
name: prd-requirement-review
description: Review the rationality, completeness, boundary conditions, and acceptance criteria of the Product Requirement Document (PRD), and perform a reverse check against existing code. Use rd-workflow-base to retrieve basic requirement information and workspace; use lark-doc as needed to read or supplement Feishu documents. Invoke when the user requests checking requirement documents, PRD review, identifying gaps in requirements, verifying completeness of acceptance criteria, or assessing requirement rationality combined with code review.
---

# PRD Requirement Review

## 适用场景

当用户有以下诉求时使用本技能：

- 检查产品需求文档是否合理
- 查漏补缺，补全边界条件、异常流程、依赖关系
- 判断 PRD 与现有实现是否一致
- 评估验收标准是否完整、可测试、可落地
- 结合代码库反推产品需求是否遗漏关键约束

## 核心原则

- 先拿上下文，再下结论：先用 `rd-workflow-base` 获取需求基础信息、工作区和仓库上下文。
- 必须查代码：技术判断必须基于真实代码，而不是凭经验猜测。
- 先找问题，再给建议：输出以发现的问题和缺漏为主，建议为辅。
- 缺信息时要显式说明：无法确认的部分列为假设、待确认问题或信息缺口。
- **重要**：本技能只是用来评价 prd 产品需求文档写的是否合理，是否存在问题，是否需要补充，是否需要修改，并不是用来评审代码的

## 工作流

### Step 1: 获取基础信息

优先使用 `rd-workflow-base` 获取：

- 需求 ID、需求名称、需求概要
- 飞书 PRD 链接或其他关联文档链接
- 本地工作区路径和相关仓库代码

如果用户没有提供需求 ID、文档链接或足够上下文，先向用户索取最小必要信息。

### Step 2: 读取需求文档

- 优先读取 `rd-workflow-base` 提供的需求文档内容。
- 如果还需要更完整内容、关联文档或交叉验证，使用 `lark-doc` 继续读取飞书文档。
- 除主 PRD 外，使用 `lark-doc` skill 的 `docs +search` 命令按需搜索其他文件相关文件：
  - 例如: prd 是关于签约功能的，可以使用 `docs +search` 命令搜索签约相关的文件，如签约流程、签约协议、签约合同等。

### Step 3: 阅读相关代码

在本地工作区中定位并阅读与需求相关的代码，重点关注：

- 核心数据模型、字段约束、状态流转
- 权限、角色、开关、配置项
- 前后端交互链路和接口契约
- 已有异常处理、兜底逻辑、边界分支
- 与需求相关的测试、校验规则、文案、埋点

如果能定位到现有实现，优先基于现状反向推导产品约束，再比对 PRD 是否覆盖。

### Step 4: 反向检查需求

至少从以下维度审查：

1. 合理性
   - 业务目标是否清晰
   - 流程是否闭环
   - 是否存在自相矛盾、无法执行或收益不明确的设计

2. 完整性
   - 前置条件、依赖项、角色差异是否写清
   - 主流程、异常流程、回退流程是否完整
   - 非功能要求、灰度、兼容性、监控是否遗漏

3. 与代码一致性
   - 是否与现有数据模型、接口契约、状态机冲突
   - 是否忽略了现有系统约束，导致实现成本异常高
   - 是否需要额外重构，但文档未体现

4. 可验收性
   - 验收标准是否可测试、可观察、可判定
   - 是否缺少输入、输出、边界值、失败场景

### Step 5: 输出评审结果

输出时优先列出发现的问题，按严重程度排序；如果没有明确问题，也要说明剩余风险和信息缺口。

使用以下模板：

```markdown

# PRD 评审报告：[需求名称/ID]

## 背景与评审范围
- 评审对象：
- 参考材料：
- 涉及代码范围：

## 主要发现
### 🔴 Critical
- [问题] 描述冲突、缺失或高风险点
- [依据] 需求文档 / 代码现状(代码现状只需要描述逻辑，不需要列源码) / 关联文档
- [影响] 为什么必须在开发前明确
- [建议] 推荐补充方式

### 🟡 Suggestion
- [问题]
- [依据]
- [建议]

### 🟢 Nice to have
- [补充建议]

## 需求缺漏清单
- 前置条件：
- 角色与权限：
- 状态与分支：
- 异常与边界：
- 验收标准：
- 数据与埋点：

## 代码一致性与技术可行性
- 现有实现是否支持：
- 可能受影响的模块：
- 潜在重构点或技术风险：

## 待确认问题
- [需要产品/研发进一步确认的问题]
```

### Step 6: 添加文档评论

对 prd 需求文档进行评论，调用 `lark-drive` skill 的 `+add-comment` 命令 添加评论
如果遇到需要用户认证的情况，返回认证链接让用户打开
如果最后无法添加评论，则调用 `FeishuProjectMcp` 工具 评论到飞书项目中(project_key 读取环境变量 `FEISHU_PROJECT_KEY`)

## 评审清单

- [ ] 已通过 `rd-workflow-base` 获取基础信息和工作区
- [ ] 已阅读主 PRD，必要时补充读取关联飞书文档
- [ ] 已阅读相关代码，而非仅基于文档做判断
- [ ] 已检查主流程、异常流程、边界条件和权限差异
- [ ] 已检查数据模型、状态流转、接口契约是否一致
- [ ] 已检查验收标准是否具体、可测试、可观察
- [ ] 输出中已区分事实、推断、待确认项

## 注意事项

- 不要只复述 PRD，要结合代码指出真正的风险和缺口。
- 如果仓库或文档信息不足，先说明缺口，不要编造结论。
- 发现问题时尽量给出补充建议、示例场景或建议验收项。

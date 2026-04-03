import type { LarkRequirement, WorkMode } from "./types";

export interface BuildInitialMessageParams {
  requirement: LarkRequirement;
  workMode: WorkMode;
  repoUrls: string[];
}

type PromptBuilder = (params: BuildInitialMessageParams) => string;

const WORK_MODE_PROMPTS: Record<WorkMode, PromptBuilder> = {
  "requirement-review": ({ requirement, repoUrls }) => {
    const repoLines =
      repoUrls.length > 0
        ? repoUrls.map((url) => `- ${url}`).join("\n")
        : "（未选择仓库）";
    return (
      `请对以下飞书研发需求进行 PRD 需求评审：\n\n` +
      `**需求ID**: ${requirement.id}\n` +
      `**需求名称**: ${requirement.title}\n` +
      `**代码仓库**:\n${repoLines}\n\n` +
      `请按照 prd-requirement-review 技能的完整流程，评审需求文档的完整性、合理性、边界条件与验收标准。`
    );
  },

  planning: ({ requirement, repoUrls }) => {
    const repoLines =
      repoUrls.length > 0
        ? repoUrls.map((url) => `- ${url}`).join("\n")
        : "（未选择仓库）";
    return (
      `请对以下飞书研发需求进行技术规划：\n\n` +
      `**需求ID**: ${requirement.id}\n` +
      `**需求名称**: ${requirement.title}\n` +
      `**代码仓库**:\n${repoLines}\n\n` +
      `请按照 rd-workflow 技能的完整流程，分析需求并生成技术方案，等待人工审批后继续。`
    );
  },

  development: ({ requirement, repoUrls }) => {
    const repoLines =
      repoUrls.length > 0
        ? repoUrls.map((url) => `- ${url}`).join("\n")
        : "（未选择仓库）";
    return (
      `请对以下飞书研发需求直接开始编码实现：\n\n` +
      `**需求ID**: ${requirement.id}\n` +
      `**需求名称**: ${requirement.title}\n` +
      `**代码仓库**:\n${repoLines}\n\n` +
      `请按照 rd-workflow 技能的完整流程，跳过规划阶段直接开始编码。`
    );
  },
};

export function buildInitialMessage(params: BuildInitialMessageParams): string {
  return WORK_MODE_PROMPTS[params.workMode](params);
}

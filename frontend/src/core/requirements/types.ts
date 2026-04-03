/**
 * Types for the R&D Requirements feature.
 * Mirrors the backend's LarkRequirement and CodeupRepositoryResponse models.
 */

export interface LarkRequirement {
  id: string;
  title: string;
  status: string;
  type: string;
  assignee: string | null;
  doc_url: string | null;
  iteration: string | null;
  /** 业务线 */
  business_line: string | null;
  /** 功能模块 */
  feature_module: string | null;
  /** 优先级 */
  priority: string | null;
}

export interface CodeupRepository {
  id: number;
  name: string;
  path: string;
  path_with_namespace: string;
  description: string | null;
  visibility: string;
  web_url: string;
  archived: boolean;
}

export type WorkMode = "requirement-review" | "planning" | "development";

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

export type WorkMode = "planning" | "development";

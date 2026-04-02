import { getBackendBaseURL } from "../config";

import type { CodeupRepository, LarkRequirement } from "./types";

export async function fetchRequirements(iteration?: string): Promise<LarkRequirement[]> {
  const query = iteration ? `?iteration=${encodeURIComponent(iteration)}` : "";
  const res = await fetch(`${getBackendBaseURL()}/api/lark/requirements${query}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { message?: string };
    };
    throw new Error(body.detail?.message ?? `Failed to fetch requirements (${res.status})`);
  }
  const data = (await res.json()) as { requirements: LarkRequirement[]; total: number };
  return data.requirements;
}

export async function fetchCodeupRepositories(search?: string): Promise<CodeupRepository[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  const res = await fetch(`${getBackendBaseURL()}/api/codeup/repositories${query}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { message?: string };
    };
    throw new Error(body.detail?.message ?? `Failed to fetch repositories (${res.status})`);
  }
  const data = (await res.json()) as { repositories: CodeupRepository[]; total: number };
  return data.repositories;
}

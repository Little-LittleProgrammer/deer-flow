"use client";

import {
  CheckIcon,
  CodeIcon,
  FileTextIcon,
  LightbulbIcon,
  Loader2Icon,
  SearchIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getAPIClient } from "@/core/api";
import {
  buildInitialMessage,
  fetchCodeupRepositories,
  type CodeupRepository,
  type LarkRequirement,
  type WorkMode,
} from "@/core/requirements";

interface DispatchDialogProps {
  requirement: LarkRequirement | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const WORK_MODE_OPTIONS: {
  value: WorkMode;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    value: "requirement-review",
    label: "PRD 需求评审",
    description: "评审 PRD 需求文档，确保需求文档的完整性、合理性、边界条件、验收标准",
    icon: FileTextIcon,
  },
  {
    value: "planning",
    label: "规划模式",
    description: "Agent 分析需求，生成技术方案，人工审批后继续",
    icon: LightbulbIcon,
  },
  {
    value: "development",
    label: "开发模式",
    description: "Agent 直接开始编码实现，跳过规划阶段",
    icon: CodeIcon,
  },
];

export function DispatchDialog({
  requirement,
  open,
  onOpenChange,
}: DispatchDialogProps) {
  const router = useRouter();
  const [workMode, setWorkMode] = useState<WorkMode>("requirement-review");
  const [repositories, setRepositories] = useState<CodeupRepository[]>([]);
  const [selectedRepoIds, setSelectedRepoIds] = useState<Set<number>>(
    new Set(),
  );
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [repoSearch, setRepoSearch] = useState("");

  useEffect(() => {
    if (!open) {
      setRepoSearch("");
      return;
    }
    setLoadingRepos(true);
    setRepoError(null);
    fetchCodeupRepositories()
      .then((repos) => {
        setRepositories(repos);
      })
      .catch((err: Error) => {
        setRepoError(err.message || "Failed to load repositories");
      })
      .finally(() => setLoadingRepos(false));
  }, [open]);

  const filteredRepositories = useMemo(() => {
    const q = repoSearch.trim().toLowerCase();
    if (!q) return repositories;
    return repositories.filter((repo) => {
      const haystack = [
        repo.name,
        repo.path_with_namespace,
        repo.path,
        repo.description ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [repositories, repoSearch]);

  const toggleRepo = useCallback((id: number) => {
    setSelectedRepoIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleLaunch = useCallback(async () => {
    if (!requirement) return;
    setLaunching(true);
    try {
      const client = getAPIClient();
      const selectedRepos = repositories
        .filter((r) => selectedRepoIds.has(r.id))
        .map((r) => r.web_url);

      const thread = await client.threads.create({
        metadata: {
          type: "lark_requirement_task",
          lark_requirement_id: requirement.id,
          work_mode: workMode,
          codeup_repositories: selectedRepos,
          title: `[${workMode === "requirement-review" ? "PRD 需求评审" : workMode === "planning" ? "规划" : "开发"}] ${requirement.title}`,
        },
      });

      const initialMessage = buildInitialMessage({
        requirement,
        workMode,
        repoUrls: selectedRepos,
      });

      const run = await client.runs.create(thread.thread_id, "lead_agent", {
        input: {
          messages: [{ role: "human", content: initialMessage }],
        },
        streamResumable: true,
        streamSubgraphs: true,
        config: {
          recursion_limit: 1000,
          configurable: {
            thread_id: thread.thread_id,
          },
        },
      });

      // useStream(reconnectOnMount: true) reconnects via sessionStorage key "lg:stream:{threadId}".
      // client.runs.create() bypasses the SDK submit path, so we must write the key manually.
      sessionStorage.setItem(`lg:stream:${thread.thread_id}`, run.run_id);

      onOpenChange(false);
      router.push(`/workspace/chats/${thread.thread_id}`);
    } catch (err) {
      toast.error(
        "启动失败：" + (err instanceof Error ? err.message : String(err)),
      );
    } finally {
      setLaunching(false);
    }
  }, [
    requirement,
    repositories,
    selectedRepoIds,
    workMode,
    onOpenChange,
    router,
  ]);

  const launchLabel = workMode === "requirement-review" ? "启动 PRD 需求评审" : workMode === "planning" ? "启动智能规划" : "启动开发";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>派发给 Agent</DialogTitle>
          {requirement && (
            <DialogDescription className="line-clamp-2 text-sm">
              {requirement.id} · {requirement.title}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="space-y-4">
          {/* Work Mode Selection */}
          <div>
            <p className="mb-2 text-sm font-medium">工作模式</p>
            <div className="grid grid-cols-2 gap-2">
              {WORK_MODE_OPTIONS.map((mode) => {
                const Icon = mode.icon;
                const isSelected = workMode === mode.value;
                return (
                  <button
                    key={mode.value}
                    type="button"
                    onClick={() => setWorkMode(mode.value)}
                    className={`hover:border-primary/60 flex flex-col gap-1 rounded-lg border p-3 text-left transition-all ${
                      isSelected
                        ? "border-primary bg-primary/5 ring-primary ring-1"
                        : "border-border"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon
                        className={`size-4 ${isSelected ? "text-primary" : "text-muted-foreground"}`}
                      />
                      <span
                        className={`text-sm font-medium ${isSelected ? "text-primary" : ""}`}
                      >
                        {mode.label}
                      </span>
                    </div>
                    <p className="text-muted-foreground text-xs leading-snug">
                      {mode.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Repository Selection */}
          <div>
            <p className="mb-2 text-sm font-medium">
              关联代码仓库{" "}
              <span className="text-muted-foreground text-xs font-normal">
                （可多选）
              </span>
            </p>
            {loadingRepos ? (
              <div className="text-muted-foreground flex items-center gap-2 rounded-lg border p-3 text-sm">
                <Loader2Icon className="size-4 animate-spin" />
                <span>加载仓库列表...</span>
              </div>
            ) : repoError ? (
              <div className="border-destructive/50 bg-destructive/5 text-destructive rounded-lg border p-3 text-xs">
                {repoError}
              </div>
            ) : repositories.length === 0 ? (
              <div className="text-muted-foreground rounded-lg border p-3 text-xs">
                未找到可用仓库。请确认 CODEUP_TOKEN 已配置。
              </div>
            ) : (
              <div className="space-y-2">
                <div className="relative">
                  <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
                  <Input
                    placeholder="搜索仓库名称或路径..."
                    className="h-9 pl-9"
                    value={repoSearch}
                    onChange={(e) => setRepoSearch(e.target.value)}
                  />
                </div>
                <ScrollArea className="h-[140px] rounded-lg border">
                  <div className="p-1">
                    {filteredRepositories.length === 0 ? (
                      <div className="text-muted-foreground px-3 py-6 text-center text-xs">
                        没有匹配的仓库
                      </div>
                    ) : (
                      filteredRepositories.map((repo) => {
                        const isSelected = selectedRepoIds.has(repo.id);
                        return (
                          <button
                            key={repo.id}
                            type="button"
                            onClick={() => toggleRepo(repo.id)}
                            className={`hover:bg-accent flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                              isSelected ? "bg-primary/5" : ""
                            }`}
                          >
                            <div
                              className={`flex size-4 shrink-0 items-center justify-center rounded border ${
                                isSelected
                                  ? "bg-primary border-primary"
                                  : "border-border"
                              }`}
                            >
                              {isSelected && (
                                <CheckIcon className="text-primary-foreground size-3" />
                              )}
                            </div>
                            <div className="min-w-0">
                              <div className="truncate font-medium">
                                {repo.name}
                              </div>
                              <div className="text-muted-foreground truncate text-xs">
                                {repo.path_with_namespace}
                              </div>
                            </div>
                            <Badge
                              variant="outline"
                              className="ml-auto shrink-0 text-xs"
                            >
                              {repo.visibility}
                            </Badge>
                          </button>
                        );
                      })
                    )}
                  </div>
                </ScrollArea>
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={() => void handleLaunch()} disabled={launching}>
            {launching ? (
              <>
                <Loader2Icon className="size-4 animate-spin" />
                启动中...
              </>
            ) : (
              launchLabel
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

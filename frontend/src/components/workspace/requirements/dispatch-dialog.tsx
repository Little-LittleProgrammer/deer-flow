"use client";

import { CheckIcon, CodeIcon, LightbulbIcon, Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { getAPIClient } from "@/core/api";
import { fetchCodeupRepositories, type CodeupRepository, type LarkRequirement, type WorkMode } from "@/core/requirements";

interface DispatchDialogProps {
  requirement: LarkRequirement | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const WORK_MODE_OPTIONS: { value: WorkMode; label: string; description: string; icon: React.ComponentType<{ className?: string }> }[] = [
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

export function DispatchDialog({ requirement, open, onOpenChange }: DispatchDialogProps) {
  const router = useRouter();
  const [workMode, setWorkMode] = useState<WorkMode>("planning");
  const [repositories, setRepositories] = useState<CodeupRepository[]>([]);
  const [selectedRepoIds, setSelectedRepoIds] = useState<Set<number>>(new Set());
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  useEffect(() => {
    if (!open) return;
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
        .map((r) => r.name);

      const thread = await client.threads.create({
        metadata: {
          type: "lark_requirement_task",
          lark_requirement_id: requirement.id,
          work_mode: workMode,
          codeup_repositories: selectedRepos,
          title: `[${workMode === "planning" ? "规划" : "开发"}] ${requirement.title}`,
        },
      });

      onOpenChange(false);
      router.push(`/workspace/chats/${thread.thread_id}`);
    } catch (err) {
      toast.error("启动失败：" + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLaunching(false);
    }
  }, [requirement, repositories, selectedRepoIds, workMode, onOpenChange, router]);

  const launchLabel = workMode === "planning" ? "启动智能规划" : "启动开发";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>派发给 Agent</DialogTitle>
          {requirement && (
            <DialogDescription className="text-sm line-clamp-2">
              {requirement.id} · {requirement.title}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="space-y-4">
          {/* Work Mode Selection */}
          <div>
            <p className="text-sm font-medium mb-2">工作模式</p>
            <div className="grid grid-cols-2 gap-2">
              {WORK_MODE_OPTIONS.map((mode) => {
                const Icon = mode.icon;
                const isSelected = workMode === mode.value;
                return (
                  <button
                    key={mode.value}
                    type="button"
                    onClick={() => setWorkMode(mode.value)}
                    className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-all hover:border-primary/60 ${
                      isSelected
                        ? "border-primary bg-primary/5 ring-1 ring-primary"
                        : "border-border"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon className={`size-4 ${isSelected ? "text-primary" : "text-muted-foreground"}`} />
                      <span className={`text-sm font-medium ${isSelected ? "text-primary" : ""}`}>
                        {mode.label}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground leading-snug">{mode.description}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Repository Selection */}
          <div>
            <p className="text-sm font-medium mb-2">
              关联代码仓库{" "}
              <span className="text-muted-foreground font-normal text-xs">（可多选）</span>
            </p>
            {loadingRepos ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground p-3 rounded-lg border">
                <Loader2Icon className="size-4 animate-spin" />
                <span>加载仓库列表...</span>
              </div>
            ) : repoError ? (
              <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-xs text-destructive">
                {repoError}
              </div>
            ) : repositories.length === 0 ? (
              <div className="rounded-lg border p-3 text-xs text-muted-foreground">
                未找到可用仓库。请确认 CODEUP_TOKEN 已配置。
              </div>
            ) : (
              <ScrollArea className="h-[140px] rounded-lg border">
                <div className="p-1">
                  {repositories.map((repo) => {
                    const isSelected = selectedRepoIds.has(repo.id);
                    return (
                      <button
                        key={repo.id}
                        type="button"
                        onClick={() => toggleRepo(repo.id)}
                        className={`w-full flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-accent transition-colors ${
                          isSelected ? "bg-primary/5" : ""
                        }`}
                      >
                        <div
                          className={`size-4 rounded border flex items-center justify-center shrink-0 ${
                            isSelected ? "bg-primary border-primary" : "border-border"
                          }`}
                        >
                          {isSelected && <CheckIcon className="size-3 text-primary-foreground" />}
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium truncate">{repo.name}</div>
                          <div className="text-xs text-muted-foreground truncate">
                            {repo.path_with_namespace}
                          </div>
                        </div>
                        <Badge variant="outline" className="ml-auto text-xs shrink-0">
                          {repo.visibility}
                        </Badge>
                      </button>
                    );
                  })}
                </div>
              </ScrollArea>
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

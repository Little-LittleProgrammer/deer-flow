"use client";

import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchRequirements, type LarkRequirement } from "@/core/requirements";

import { DispatchDialog } from "./dispatch-dialog";
import { RequirementCard } from "./requirement-card";

const STATUS_FILTERS = ["全部", "进行中", "待排期", "已完成"];

export function RequirementsListView() {
  const [requirements, setRequirements] = useState<LarkRequirement[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeStatus, setActiveStatus] = useState("全部");
  const [dispatchTarget, setDispatchTarget] = useState<LarkRequirement | null>(null);

  const loadRequirements = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchRequirements()
      .then((data) => {
        setRequirements(data);
      })
      .catch((err: Error) => {
        setError(err.message || "加载失败");
        toast.error("无法加载需求列表：" + err.message);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadRequirements();
  }, [loadRequirements]);

  const filteredRequirements = useMemo(() => {
    return requirements.filter((req) => {
      const matchesSearch =
        !searchQuery ||
        req.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        req.id.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesStatus =
        activeStatus === "全部" || req.status.includes(activeStatus);
      return matchesSearch && matchesStatus;
    });
  }, [requirements, searchQuery, activeStatus]);

  return (
    <div className="flex flex-col gap-4 p-4 h-full">
      {/* Header toolbar */}
      <div className="flex items-center justify-between gap-3">
        <div className="relative flex-1 max-w-sm">
          <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="搜索需求标题或 ID..."
            className="pl-9 h-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <Button variant="outline" size="sm" onClick={loadRequirements} disabled={loading}>
          <RefreshCwIcon className={`size-4 ${loading ? "animate-spin" : ""}`} />
          刷新列表
        </Button>
      </div>

      {/* Status filters */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_FILTERS.map((status) => (
          <button
            key={status}
            type="button"
            onClick={() => setActiveStatus(status)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              activeStatus === status
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            {status}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 w-full rounded-lg" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
            <p className="text-sm">{error}</p>
            <Button variant="outline" size="sm" onClick={loadRequirements}>
              重试
            </Button>
          </div>
        ) : filteredRequirements.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
            <p className="text-sm">
              {requirements.length === 0 ? "暂无需求，点击刷新列表" : "没有符合条件的需求"}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredRequirements.map((req) => (
              <RequirementCard
                key={req.id}
                requirement={req}
                onDispatch={setDispatchTarget}
              />
            ))}
          </div>
        )}
      </div>

      {/* Dispatch Dialog */}
      <DispatchDialog
        requirement={dispatchTarget}
        open={dispatchTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDispatchTarget(null);
        }}
      />
    </div>
  );
}

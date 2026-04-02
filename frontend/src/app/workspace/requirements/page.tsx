import { RequirementsListView } from "@/components/workspace/requirements/requirements-list-view";

export default function RequirementsPage() {
  return (
    <div className="flex flex-col h-full">
      <div className="border-b px-4 py-3">
        <h1 className="text-base font-semibold">研发需求</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          从飞书项目拉取当前迭代需求，派发给 Agent 自动规划或开发
        </p>
      </div>
      <div className="flex-1 overflow-hidden">
        <RequirementsListView />
      </div>
    </div>
  );
}

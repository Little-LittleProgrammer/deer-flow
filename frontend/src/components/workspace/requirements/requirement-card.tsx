"use client";

import { ExternalLinkIcon, UserIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { LarkRequirement } from "@/core/requirements";

interface RequirementCardProps {
  requirement: LarkRequirement;
  onDispatch: (requirement: LarkRequirement) => void;
}

function getStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  const lowerStatus = status.toLowerCase();
  if (lowerStatus.includes("进行中") || lowerStatus.includes("in progress") || lowerStatus.includes("开发中")) {
    return "default";
  }
  if (lowerStatus.includes("完成") || lowerStatus.includes("done") || lowerStatus.includes("已完成")) {
    return "secondary";
  }
  if (lowerStatus.includes("待") || lowerStatus.includes("pending") || lowerStatus.includes("未开始")) {
    return "outline";
  }
  return "secondary";
}

function getTypeVariant(type: string): "default" | "secondary" | "outline" {
  const lowerType = type.toLowerCase();
  if (lowerType.includes("缺陷") || lowerType.includes("bug")) return "destructive" as "default";
  if (lowerType.includes("需求") || lowerType.includes("feature")) return "default";
  return "outline";
}

export function RequirementCard({ requirement, onDispatch }: RequirementCardProps) {
  return (
    <Card className="hover:shadow-md transition-shadow duration-200">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-1.5 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-muted-foreground text-xs font-mono">{requirement.id}</span>
              {requirement.status && (
                <Badge variant={getStatusVariant(requirement.status)} className="text-xs">
                  {requirement.status}
                </Badge>
              )}
              {requirement.type && (
                <Badge variant={getTypeVariant(requirement.type)} className="text-xs">
                  {requirement.type}
                </Badge>
              )}
            </div>
            <h3 className="font-medium text-sm leading-snug line-clamp-2">{requirement.title}</h3>
          </div>
          <Button
            size="sm"
            variant="default"
            className="shrink-0 text-xs"
            onClick={() => onDispatch(requirement)}
          >
            派发给 Agent
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {requirement.priority && <span className="shrink-0">优先级: {requirement.priority}</span>}
          {requirement.business_line && (
            <span className="truncate max-w-[14rem]" title={requirement.business_line}>
              业务线: {requirement.business_line}
            </span>
          )}
          {requirement.feature_module && <span className="shrink-0">模块: {requirement.feature_module}</span>}
          {requirement.assignee && (
            <div className="flex items-center gap-1 min-w-0 max-w-[20rem]">
              <UserIcon className="size-3 shrink-0" />
              <span className="truncate" title={requirement.assignee}>
                {requirement.assignee}
              </span>
            </div>
          )}
          {requirement.iteration && (
            <span className="truncate max-w-[18rem]" title={requirement.iteration}>
              迭代: {requirement.iteration}
            </span>
          )}
          {requirement.doc_url && (
            <a
              href={requirement.doc_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-foreground transition-colors"
            >
              <ExternalLinkIcon className="size-3" />
              <span>查看文档</span>
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

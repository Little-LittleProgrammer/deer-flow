"use client";

import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { CheckCircle, XCircle } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AgentThreadState } from "@/core/threads/types";

interface HumanApprovalInterruptValue {
  type: "human_approval";
  message: string;
  technical_design_preview?: string;
  requirement_id?: string;
}

function isHumanApprovalInterrupt(
  value: unknown,
): value is HumanApprovalInterruptValue {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    (value as Record<string, unknown>).type === "human_approval"
  );
}

interface HumanApprovalBannerProps {
  thread: BaseStream<AgentThreadState>;
  threadId: string;
}

export function HumanApprovalBanner({
  thread,
  threadId,
}: HumanApprovalBannerProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleDecision = useCallback(
    async (decision: "approved" | "rejected") => {
      if (isSubmitting) return;
      setIsSubmitting(true);
      try {
        await thread.submit(
          { command: { resume: decision } } as Parameters<
            typeof thread.submit
          >[0],
          {
            threadId,
            streamSubgraphs: true,
            streamResumable: true,
          },
        );
      } catch (error) {
        console.error("Failed to submit approval decision:", error);
        setIsSubmitting(false);
      }
    },
    [isSubmitting, thread, threadId],
  );

  const interruptValue = thread.interrupt?.value;

  if (!isHumanApprovalInterrupt(interruptValue)) {
    return null;
  }

  const { message, technical_design_preview, requirement_id } = interruptValue;

  return (
    <div className="mx-auto w-full max-w-(--container-width-md) px-4 pb-4">
      <Card className="border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base text-amber-800 dark:text-amber-200">
            <span className="text-lg">🔍</span>
            需要审批
            {requirement_id && (
              <span className="text-muted-foreground ml-auto text-xs font-normal">
                需求 #{requirement_id}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-sm text-amber-700 dark:text-amber-300">{message}</p>

          {technical_design_preview && (
            <div className="flex flex-col gap-1">
              <p className="text-muted-foreground text-xs font-medium">
                技术方案预览
              </p>
              <ScrollArea className="max-h-40">
                <pre className="bg-background/60 rounded-md border p-3 text-xs whitespace-pre-wrap">
                  {technical_design_preview}
                </pre>
              </ScrollArea>
            </div>
          )}

          <div className="flex gap-3">
            <Button
              variant="default"
              size="sm"
              className="flex items-center gap-2 bg-green-600 hover:bg-green-700"
              disabled={isSubmitting}
              onClick={() => void handleDecision("approved")}
            >
              <CheckCircle className="size-4" />
              审批通过
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex items-center gap-2 border-red-300 text-red-600 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/30"
              disabled={isSubmitting}
              onClick={() => void handleDecision("rejected")}
            >
              <XCircle className="size-4" />
              拒绝
            </Button>
            {isSubmitting && (
              <span className="text-muted-foreground self-center text-xs">
                处理中...
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

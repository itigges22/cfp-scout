import { type HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** Loading placeholder. Use as: <Skeleton className="h-8 w-40" />. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-surface-2", className)}
      {...props}
    />
  );
}

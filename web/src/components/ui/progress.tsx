"use client"

import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"

import { cn } from "@/lib/utils"

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => {
  const percentage = Math.max(0, Math.min(100, Number(value) || 0))

  return (
    <ProgressPrimitive.Root
      ref={ref}
      className={cn(
        "relative h-4 w-full overflow-hidden rounded-full",
        className
      )}
      style={{ background: 'var(--surface-hover)' }}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className="h-full transition-all"
        style={{
          width: `${percentage}%`,
          background: percentage > 0 ? 'var(--primary)' : 'transparent',
          borderRadius: 'inherit',
        }}
      />
    </ProgressPrimitive.Root>
  )
})
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }

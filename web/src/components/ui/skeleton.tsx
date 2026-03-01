import { cn } from "@/lib/utils"

function Skeleton({
  className,
  style,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md", className)}
      style={{
        background: 'linear-gradient(90deg, var(--surface), var(--surface-hover), var(--surface))',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.5s infinite, pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        borderRadius: 'var(--radius-sm)',
        ...style,
      }}
      {...props}
    />
  )
}

export { Skeleton }

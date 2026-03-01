import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/components/ui/button"

const badgeVariants = cva(
    "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-offset-2",
    {
        variants: {
            variant: {
                default: "border-transparent",
                secondary: "border-transparent",
                destructive: "border-transparent",
                outline: "",
            },
        },
        defaultVariants: {
            variant: "default",
        },
    }
)

const badgeStyleMap: Record<string, React.CSSProperties> = {
    default: {
        background: 'var(--primary)',
        color: '#fff',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    secondary: {
        background: 'var(--surface-hover)',
        color: 'var(--text-secondary)',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    destructive: {
        background: 'var(--danger)',
        color: '#fff',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    outline: {
        background: 'transparent',
        color: 'var(--text)',
        borderColor: 'var(--border)',
        transition: 'all 0.2s var(--ease-smooth)',
    },
}

export interface BadgeProps
    extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> { }

function Badge({ className, variant, style, ...props }: BadgeProps) {
    const v = variant || "default"
    return (
        <div
            className={cn(badgeVariants({ variant }), className)}
            style={{ ...badgeStyleMap[v], ...style }}
            {...props}
        />
    )
}

export { Badge, badgeVariants }

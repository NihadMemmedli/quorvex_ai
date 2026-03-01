import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs))
}

const buttonVariants = cva(
    "inline-flex items-center justify-center whitespace-nowrap text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
    {
        variants: {
            variant: {
                default: "",
                destructive: "",
                outline: "",
                secondary: "",
                ghost: "",
                link: "underline-offset-4 hover:underline",
            },
            size: {
                default: "h-10 px-4 py-2",
                sm: "h-9 px-3",
                lg: "h-11 px-8",
                icon: "h-10 w-10",
            },
        },
        defaultVariants: {
            variant: "default",
            size: "default",
        },
    }
)

const variantStyles: Record<string, React.CSSProperties> = {
    default: {
        background: 'var(--primary)',
        color: '#fff',
        borderRadius: 'var(--radius)',
        border: 'none',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    destructive: {
        background: 'var(--danger)',
        color: '#fff',
        borderRadius: 'var(--radius)',
        border: 'none',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    outline: {
        background: 'transparent',
        color: 'var(--text)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    secondary: {
        background: 'var(--surface)',
        color: 'var(--text)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    ghost: {
        background: 'transparent',
        color: 'var(--text)',
        border: 'none',
        borderRadius: 'var(--radius)',
        transition: 'all 0.2s var(--ease-smooth)',
    },
    link: {
        background: 'transparent',
        color: 'var(--primary)',
        border: 'none',
        transition: 'all 0.2s var(--ease-smooth)',
    },
}

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
    asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant, size, asChild = false, style, ...props }, ref) => {
        const Comp = asChild ? Slot : "button"
        const v = variant || "default"
        return (
            <Comp
                className={cn(buttonVariants({ variant, size, className }))}
                style={{ ...variantStyles[v], ...style }}
                ref={ref}
                {...props}
            />
        )
    }
)
Button.displayName = "Button"

export { Button, buttonVariants }

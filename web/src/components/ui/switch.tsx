"use client"

import * as React from "react"
import * as SwitchPrimitives from "@radix-ui/react-switch"

import { cn } from "@/lib/utils"

const Switch = React.forwardRef<
    React.ElementRef<typeof SwitchPrimitives.Root>,
    React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, style, ...props }, ref) => (
    <SwitchPrimitives.Root
        className={cn(
            "quorvex-switch",
            className
        )}
        style={{
            position: 'relative',
            display: 'inline-flex',
            alignItems: 'center',
            width: 44,
            height: 24,
            padding: 2,
            flexShrink: 0,
            borderRadius: 999,
            border: '1px solid var(--border-bright)',
            verticalAlign: 'middle',
            transition: 'background 0.2s var(--ease-smooth), border-color 0.2s var(--ease-smooth), box-shadow 0.2s var(--ease-smooth)',
            ...style,
        }}
        {...props}
        ref={ref}
    >
        <SwitchPrimitives.Thumb
            className={cn(
                "quorvex-switch-thumb"
            )}
            style={{
                display: 'block',
                width: 18,
                height: 18,
                borderRadius: 999,
                background: '#fff',
                border: '1px solid rgba(15, 23, 42, 0.22)',
                boxShadow: '0 2px 6px rgba(0,0,0,0.22)',
                pointerEvents: 'none',
                transition: 'transform 0.2s var(--ease-smooth)',
            }}
        />
    </SwitchPrimitives.Root>
))
Switch.displayName = SwitchPrimitives.Root.displayName

export { Switch }

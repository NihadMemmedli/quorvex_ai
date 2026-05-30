"use client";

import type { CSSProperties, ReactNode } from "react";

export type SpecKind = "standard" | "prd" | "native_plan" | "standard_multi" | "template";

export interface SpecRowData {
    name: string;
    path: string;
    href: string;
    specType?: SpecKind;
    testCount?: number;
    tags?: string[];
    isAutomated?: boolean;
    hasTestRailMapping?: boolean;
    description?: string;
}

export interface SpecRowAction {
    id: string;
    label: string;
    icon?: ReactNode;
    tone?: "default" | "primary" | "success" | "danger" | "accent";
    disabled?: boolean;
    hidden?: boolean;
    onSelect: () => void;
}

export interface SpecOverflowMenuRequest<TItem> {
    item: TItem;
    anchor: HTMLButtonElement;
}

export interface SpecFolderRowData {
    name: string;
    path: string;
    depth?: number;
    specCount: number;
    selectedCount?: number;
    isExpanded?: boolean;
    isDropTarget?: boolean;
}

export const stopRowEvent = (event: React.SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
};

export function getSelectionState(total: number, selected = 0): boolean | "mixed" {
    if (total > 0 && selected >= total) return true;
    if (selected > 0) return "mixed";
    return false;
}

export function getIndent(depth = 0): string {
    return `clamp(0rem, ${depth * 1.25}rem, 5rem)`;
}

export const rowShellStyle: CSSProperties = {
    display: "flex",
    alignItems: "stretch",
    width: "100%",
    minWidth: 0,
    borderBottom: "1px solid var(--border)",
    color: "var(--text)",
    transition: "background 0.15s var(--ease-smooth), opacity 0.15s var(--ease-smooth)",
};

export const rowMainStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
    flex: "1 1 18rem",
    minWidth: 0,
    padding: "0.75rem clamp(0.75rem, 2vw, 1rem)",
};

export const rowActionsStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: "0.375rem",
    flex: "0 0 auto",
    padding: "0.5rem clamp(0.5rem, 1.4vw, 0.875rem)",
};

export const iconButtonStyle: CSSProperties = {
    width: "2rem",
    height: "2rem",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: "1px solid transparent",
    borderRadius: "var(--radius-sm)",
    background: "rgba(255, 255, 255, 0.05)",
    color: "var(--text-secondary)",
    cursor: "pointer",
    flex: "0 0 auto",
};

export const selectionCellStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flex: "0 0 auto",
    padding: "0 0.25rem 0 clamp(0.75rem, 2vw, 1rem)",
};

export const nativeCheckboxStyle: CSSProperties = {
    width: "1.125rem",
    height: "1.125rem",
    margin: 0,
    accentColor: "var(--primary)",
    cursor: "pointer",
};

export function toneStyle(tone: SpecRowAction["tone"]): CSSProperties {
    switch (tone) {
        case "primary":
            return { color: "var(--primary)", background: "var(--primary-glow)" };
        case "success":
            return { color: "var(--success)", background: "var(--success-muted)" };
        case "danger":
            return { color: "var(--danger)", background: "var(--danger-muted)" };
        case "accent":
            return { color: "var(--accent)", background: "rgba(192, 132, 252, 0.12)" };
        default:
            return {};
    }
}

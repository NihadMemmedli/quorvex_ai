"use client";

import Link from "next/link";
import { CheckCircle, FileText, Link2, MoreVertical, TestTube } from "lucide-react";
import type { DragEventHandler } from "react";
import {
    iconButtonStyle,
    nativeCheckboxStyle,
    rowActionsStyle,
    rowMainStyle,
    rowShellStyle,
    selectionCellStyle,
    SpecOverflowMenuRequest,
    SpecRowAction,
    SpecRowData,
    stopRowEvent,
    toneStyle,
} from "./spec-row-types";

interface SpecRowProps {
    spec: SpecRowData;
    depth?: number;
    selected?: boolean;
    draggable?: boolean;
    dragging?: boolean;
    actions?: SpecRowAction[];
    showSelection?: boolean;
    selectionLabel?: string;
    onSelectionChange?: (spec: SpecRowData, selected: boolean) => void;
    onOpen?: (spec: SpecRowData) => void;
    onOpenMenu?: (request: SpecOverflowMenuRequest<SpecRowData>) => void;
    onDragStart?: DragEventHandler<HTMLDivElement>;
    onDragEnd?: DragEventHandler<HTMLDivElement>;
}

function specTypeLabel(specType: SpecRowData["specType"]): string | null {
    if (specType === "native_plan") return "Test Plan";
    if (specType === "standard_multi") return "Multi-Test";
    if (specType === "prd") return "PRD";
    if (specType === "template") return "Template";
    return null;
}

function specTypeTone(specType: SpecRowData["specType"]): "primary" | "success" | "accent" | undefined {
    if (specType === "native_plan") return "success";
    if (specType === "standard_multi" || specType === "template") return "primary";
    if (specType === "prd") return "accent";
    return undefined;
}

function Badge({
    children,
    tone = "primary",
}: {
    children: React.ReactNode;
    tone?: "primary" | "success" | "accent";
}) {
    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                maxWidth: "100%",
                padding: "0.125rem 0.5rem",
                borderRadius: "9999px",
                background:
                    tone === "success"
                        ? "var(--success-muted)"
                        : tone === "accent"
                          ? "rgba(192, 132, 252, 0.12)"
                          : "var(--primary-glow)",
                color: tone === "success" ? "var(--success)" : tone === "accent" ? "var(--accent)" : "var(--primary)",
                fontSize: "0.7rem",
                fontWeight: 600,
                lineHeight: 1.35,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
            }}
        >
            {children}
        </span>
    );
}

export function SpecRow({
    spec,
    depth = 0,
    selected = false,
    draggable = false,
    dragging = false,
    actions = [],
    showSelection = true,
    selectionLabel,
    onSelectionChange,
    onOpen,
    onOpenMenu,
    onDragStart,
    onDragEnd,
}: SpecRowProps) {
    const visibleActions = actions.filter((action) => !action.hidden);
    const typeLabel = specTypeLabel(spec.specType);
    const typeTone = specTypeTone(spec.specType);

    return (
        <div
            draggable={draggable}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            data-spec-row={spec.path}
            style={{
                ...rowShellStyle,
                paddingLeft: `clamp(0rem, ${depth * 1.25}rem, 5rem)`,
                background: selected ? "rgba(96, 165, 250, 0.04)" : "transparent",
                opacity: dragging ? 0.55 : 1,
                cursor: draggable ? "grab" : "default",
                flexWrap: "wrap",
            }}
        >
            {showSelection && (
                <div style={selectionCellStyle}>
                    <input
                        type="checkbox"
                        checked={selected}
                        aria-label={selectionLabel ?? `Select ${spec.name}`}
                        onChange={(event) => onSelectionChange?.(spec, event.currentTarget.checked)}
                        onClick={(event) => event.stopPropagation()}
                        style={nativeCheckboxStyle}
                    />
                </div>
            )}

            <Link
                href={spec.href}
                onClick={() => onOpen?.(spec)}
                style={{
                    ...rowMainStyle,
                    color: "inherit",
                    textDecoration: "none",
                    paddingLeft: showSelection ? "0.5rem" : rowMainStyle.padding,
                }}
            >
                <span
                    aria-hidden="true"
                    style={{
                        width: "2rem",
                        height: "2rem",
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flex: "0 0 auto",
                        borderRadius: "6px",
                        background: "var(--primary-glow)",
                        color: "var(--primary)",
                    }}
                >
                    <FileText size={16} />
                </span>

                <span style={{ display: "flex", flexDirection: "column", gap: "0.25rem", flex: "1 1 12rem", minWidth: 0 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", minWidth: 0 }}>
                        <span
                            style={{
                                minWidth: 0,
                                maxWidth: "min(100%, 34rem)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                fontSize: "0.9rem",
                                color: "var(--text)",
                            }}
                        >
                            {spec.name}
                        </span>
                        {typeLabel && typeTone && <Badge tone={typeTone}>{typeLabel}</Badge>}
                        {(spec.testCount ?? 0) > 1 && (
                            <Badge>
                                <TestTube size={10} />
                                {spec.testCount} tests
                            </Badge>
                        )}
                        {spec.isAutomated && (
                            <Badge tone="success">
                                <CheckCircle size={10} />
                                Automated
                            </Badge>
                        )}
                        {spec.hasTestRailMapping && (
                            <Badge>
                                <Link2 size={10} />
                                TestRail
                            </Badge>
                        )}
                    </span>

                    {spec.description && (
                        <span
                            style={{
                                maxWidth: "min(100%, 46rem)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                color: "var(--text-secondary)",
                                fontSize: "0.75rem",
                            }}
                        >
                            {spec.description}
                        </span>
                    )}

                    {!!spec.tags?.length && (
                        <span style={{ display: "flex", gap: "0.375rem", flexWrap: "wrap", minWidth: 0 }}>
                            {spec.tags.map((tag) => (
                                <Badge key={tag}>{tag}</Badge>
                            ))}
                        </span>
                    )}
                </span>
            </Link>

            <div style={{ ...rowActionsStyle, marginLeft: "auto" }}>
                {visibleActions.map((action) => (
                    <button
                        key={action.id}
                        type="button"
                        title={action.label}
                        aria-label={action.label}
                        disabled={action.disabled}
                        onClick={(event) => {
                            stopRowEvent(event);
                            action.onSelect();
                        }}
                        style={{
                            ...iconButtonStyle,
                            ...toneStyle(action.tone),
                            opacity: action.disabled ? 0.5 : 1,
                            cursor: action.disabled ? "not-allowed" : "pointer",
                        }}
                    >
                        {action.icon}
                    </button>
                ))}
                {onOpenMenu && (
                    <button
                        type="button"
                        title="More actions"
                        aria-label={`More actions for ${spec.name}`}
                        onClick={(event) => {
                            stopRowEvent(event);
                            onOpenMenu({ item: spec, anchor: event.currentTarget });
                        }}
                        style={iconButtonStyle}
                    >
                        <MoreVertical size={16} />
                    </button>
                )}
            </div>
        </div>
    );
}

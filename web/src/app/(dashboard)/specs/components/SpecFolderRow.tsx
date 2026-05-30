"use client";

import { useEffect, useRef } from "react";
import type { DragEventHandler } from "react";
import { ChevronDown, ChevronRight, FolderClosed, FolderOpen, MoreVertical } from "lucide-react";
import {
    getSelectionState,
    iconButtonStyle,
    nativeCheckboxStyle,
    rowActionsStyle,
    rowShellStyle,
    selectionCellStyle,
    SpecFolderRowData,
    SpecOverflowMenuRequest,
    SpecRowAction,
    stopRowEvent,
    toneStyle,
} from "./spec-row-types";

interface SpecFolderRowProps {
    folder: SpecFolderRowData;
    draggable?: boolean;
    dragging?: boolean;
    actions?: SpecRowAction[];
    showSelection?: boolean;
    onToggle?: (folder: SpecFolderRowData) => void;
    onSelectionChange?: (folder: SpecFolderRowData, selected: boolean) => void;
    onOpenMenu?: (request: SpecOverflowMenuRequest<SpecFolderRowData>) => void;
    onDragStart?: DragEventHandler<HTMLDivElement>;
    onDragEnd?: DragEventHandler<HTMLDivElement>;
    onDragOver?: DragEventHandler<HTMLDivElement>;
    onDragLeave?: DragEventHandler<HTMLDivElement>;
    onDrop?: DragEventHandler<HTMLDivElement>;
}

export function SpecFolderRow({
    folder,
    draggable = false,
    dragging = false,
    actions = [],
    showSelection = true,
    onToggle,
    onSelectionChange,
    onOpenMenu,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragLeave,
    onDrop,
}: SpecFolderRowProps) {
    const checkboxRef = useRef<HTMLInputElement>(null);
    const selectedState = getSelectionState(folder.specCount, folder.selectedCount);
    const visibleActions = actions.filter((action) => !action.hidden);

    useEffect(() => {
        if (checkboxRef.current) {
            checkboxRef.current.indeterminate = selectedState === "mixed";
        }
    }, [selectedState]);

    return (
        <div
            draggable={draggable}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            data-spec-folder-row={folder.path}
            style={{
                ...rowShellStyle,
                paddingLeft: `clamp(0rem, ${(folder.depth ?? 0) * 1.25}rem, 5rem)`,
                background: folder.isDropTarget ? "rgba(96, 165, 250, 0.15)" : "transparent",
                boxShadow: folder.isDropTarget ? "inset 0 0 0 2px var(--primary)" : "none",
                opacity: dragging ? 0.55 : 1,
                cursor: draggable ? "grab" : "default",
                flexWrap: "wrap",
                userSelect: "none",
            }}
        >
            {showSelection && (
                <div style={selectionCellStyle}>
                    <input
                        ref={checkboxRef}
                        type="checkbox"
                        checked={selectedState === true}
                        aria-label={`Select all specs in ${folder.name}`}
                        aria-checked={selectedState}
                        onChange={(event) => onSelectionChange?.(folder, event.currentTarget.checked)}
                        onClick={(event) => event.stopPropagation()}
                        style={nativeCheckboxStyle}
                    />
                </div>
            )}

            <button
                type="button"
                onClick={() => onToggle?.(folder)}
                aria-expanded={folder.isExpanded}
                aria-controls={`spec-folder-${folder.path}`}
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                    flex: "1 1 18rem",
                    minWidth: 0,
                    padding: "0.75rem clamp(0.75rem, 2vw, 1rem)",
                    paddingLeft: showSelection ? "0.5rem" : "clamp(0.75rem, 2vw, 1rem)",
                    border: "none",
                    background: "transparent",
                    color: "var(--text)",
                    cursor: "pointer",
                    textAlign: "left",
                    font: "inherit",
                }}
            >
                <span aria-hidden="true" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, flex: "0 0 auto" }}>
                    {folder.isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
                <span aria-hidden="true" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", color: folder.isExpanded ? "var(--primary)" : "var(--text-secondary)", flex: "0 0 auto" }}>
                    {folder.isExpanded ? <FolderOpen size={16} /> : <FolderClosed size={16} />}
                </span>
                <span
                    style={{
                        flex: "1 1 auto",
                        minWidth: 0,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        fontSize: "0.85rem",
                        fontWeight: 700,
                    }}
                >
                    {folder.name}
                </span>
                <span
                    style={{
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flex: "0 0 auto",
                        minWidth: "1.75rem",
                        padding: "0.125rem 0.45rem",
                        borderRadius: "999px",
                        background: "rgba(156, 163, 175, 0.1)",
                        color: "var(--text-secondary)",
                        fontSize: "0.7rem",
                        fontWeight: 700,
                    }}
                >
                    {folder.specCount}
                </span>
            </button>

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
                        aria-label={`More actions for ${folder.name}`}
                        onClick={(event) => {
                            stopRowEvent(event);
                            onOpenMenu({ item: folder, anchor: event.currentTarget });
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

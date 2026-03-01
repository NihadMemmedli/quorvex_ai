'use client';
import React from 'react';

interface MiniSparklineProps {
    data: number[];
    width?: number;
    height?: number;
    color?: string;
    strokeWidth?: number;
}

export default function MiniSparkline({
    data,
    width = 80,
    height = 24,
    color = 'var(--primary)',
    strokeWidth = 1.5,
}: MiniSparklineProps) {
    if (!data || data.length === 0) {
        return (
            <svg width={width} height={height}>
                <line
                    x1={0} y1={height / 2} x2={width} y2={height / 2}
                    stroke="var(--border)" strokeWidth={1} strokeDasharray="3,3"
                />
            </svg>
        );
    }

    if (data.length === 1) {
        return (
            <svg width={width} height={height}>
                <circle cx={width / 2} cy={height / 2} r={2.5} fill={color} />
            </svg>
        );
    }

    const padding = 2;
    const chartWidth = width - padding * 2;
    const chartHeight = height - padding * 2;

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;

    const points = data.map((value, index) => {
        const x = padding + (index / (data.length - 1)) * chartWidth;
        const y = padding + chartHeight - ((value - min) / range) * chartHeight;
        return `${x},${y}`;
    });

    return (
        <svg width={width} height={height} style={{ display: 'block' }}>
            <polyline
                points={points.join(' ')}
                fill="none"
                stroke={color}
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
}

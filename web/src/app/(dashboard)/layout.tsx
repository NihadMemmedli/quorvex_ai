'use client';

import { Sidebar } from '@/components/Sidebar';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { ChatProvider } from '@/components/assistant/ChatProvider';
import { ChatBubble } from '@/components/assistant/ChatBubble';
import { CommandPaletteProvider } from '@/components/command-palette/CommandPaletteProvider';
import { CommandPalette } from '@/components/command-palette/CommandPalette';
import { NextStepBanner } from '@/components/workflow/NextStepBanner';

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <ProtectedRoute>
            <ChatProvider>
                <CommandPaletteProvider>
                    <div style={{ display: 'flex' }}>
                        <Sidebar />
                        <main style={{ flex: 1, padding: '1.5rem 2rem', overflowY: 'auto', height: '100vh' }}>
                            <NextStepBanner />
                            {children}
                        </main>
                    </div>
                    <ChatBubble />
                    <CommandPalette />
                </CommandPaletteProvider>
            </ChatProvider>
        </ProtectedRoute>
    );
}

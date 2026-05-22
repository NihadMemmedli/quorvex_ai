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
                    <div className="dashboard-shell" style={{ display: 'flex' }}>
                        <Sidebar />
                        <main className="dashboard-main" style={{ flex: 1, padding: '1.5rem 2rem', overflowY: 'auto', height: '100vh', minWidth: 0 }}>
                            <NextStepBanner />
                            {children}
                        </main>
                    </div>
                    <ChatBubble />
                    <CommandPalette />
                    <style jsx global>{`
                        @media (max-width: 760px) {
                            .dashboard-shell {
                                display: block !important;
                            }

                            .dashboard-shell > aside {
                                display: none !important;
                            }

                            .dashboard-main {
                                padding: 1rem !important;
                            }
                        }
                    `}</style>
                </CommandPaletteProvider>
            </ChatProvider>
        </ProtectedRoute>
    );
}

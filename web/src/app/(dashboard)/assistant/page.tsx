'use client';

import { AssistantThread } from '@/components/assistant/AssistantThread';
import { ConversationList } from '@/components/assistant/ConversationList';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

export default function AssistantPage() {
  return (
    <PageLayout tier="full" style={{ height: 'calc(100vh - 4rem)', display: 'flex', flexDirection: 'column' }}>
      <PageHeader
        title="AI Assistant"
        subtitle="Ask me about your tests, explore features, or get help with the platform."
        gradient={false}
      />
      <div className="animate-in stagger-1" style={{
        flex: 1,
        display: 'flex',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-card)',
      }}>
        <div style={{ width: '260px', flexShrink: 0 }}>
          <ConversationList />
        </div>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <AssistantThread />
        </div>
      </div>
    </PageLayout>
  );
}

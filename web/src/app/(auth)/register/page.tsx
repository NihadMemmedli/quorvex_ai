'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense, useEffect } from 'react';
import { RegisterForm } from '@/components/auth/RegisterForm';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2 } from 'lucide-react';

function RegisterContent() {
    const searchParams = useSearchParams();
    const router = useRouter();
    const { isAuthenticated, isLoading } = useAuth();
    const returnTo = searchParams.get('returnTo') || '/';

    // Redirect to dashboard if already authenticated
    useEffect(() => {
        if (!isLoading && isAuthenticated) {
            router.push(returnTo);
        }
    }, [isAuthenticated, isLoading, router, returnTo]);

    // Show loading while checking auth or redirecting
    if (isLoading || isAuthenticated) {
        return (
            <div
                className="min-h-screen flex items-center justify-center"
                style={{ backgroundColor: '#0f172a' }}
            >
                <Loader2 className="h-8 w-8 animate-spin" style={{ color: '#3b82f6' }} />
            </div>
        );
    }

    return (
        <div
            className="min-h-screen flex items-center justify-center px-4 py-12"
            style={{ backgroundColor: '#0f172a' }}
        >
            <div style={{ width: '100%', maxWidth: '400px' }}>
                {/* Logo/Brand */}
                <div className="text-center mb-8">
                    <img src="/quorvex-logo.svg" alt="Quorvex AI" width={48} height={48} className="mb-4 inline-block" />
                    <h1 className="text-2xl font-bold" style={{ color: '#f8fafc' }}>
                        Create an account
                    </h1>
                    <p className="mt-2 text-sm" style={{ color: '#94a3b8' }}>
                        Get started with your test automation journey
                    </p>
                </div>

                {/* Form Card */}
                <div
                    className="p-6"
                    style={{
                        backgroundColor: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: '12px',
                        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.4)',
                    }}
                >
                    <RegisterForm redirectTo={returnTo} />
                </div>
            </div>
        </div>
    );
}

export default function RegisterPage() {
    return (
        <Suspense fallback={
            <div className="min-h-screen flex items-center justify-center"
                style={{ backgroundColor: '#0f172a' }}>
                <div className="animate-pulse" style={{ color: '#f8fafc' }}>Loading...</div>
            </div>
        }>
            <RegisterContent />
        </Suspense>
    );
}

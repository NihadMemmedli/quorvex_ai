'use client';

import { Suspense, useEffect } from 'react';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2 } from 'lucide-react';

interface ProtectedRouteProps {
    children: React.ReactNode;
    requireAuth?: boolean;
    requireAdmin?: boolean;
    fallbackUrl?: string;
}

function ProtectedRouteLoading() {
    return (
        <div className="flex items-center justify-center min-h-[400px]">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
        </div>
    );
}

/**
 * Wrapper component that protects routes requiring authentication.
 *
 * During the migration period (REQUIRE_AUTH=false on backend),
 * this component allows access to all routes. When authentication
 * is enforced, it redirects unauthenticated users to the login page.
 *
 * Usage:
 * ```tsx
 * <ProtectedRoute>
 *   <SensitiveContent />
 * </ProtectedRoute>
 * ```
 *
 * For admin-only routes:
 * ```tsx
 * <ProtectedRoute requireAdmin>
 *   <AdminPanel />
 * </ProtectedRoute>
 * ```
 */
export function ProtectedRoute({
    children,
    requireAuth = true,
    requireAdmin = false,
    fallbackUrl = '/login',
}: ProtectedRouteProps) {
    return (
        <Suspense fallback={<ProtectedRouteLoading />}>
            <ProtectedRouteInner
                requireAuth={requireAuth}
                requireAdmin={requireAdmin}
                fallbackUrl={fallbackUrl}
            >
                {children}
            </ProtectedRouteInner>
        </Suspense>
    );
}

function ProtectedRouteInner({
    children,
    requireAuth,
    requireAdmin,
    fallbackUrl,
}: Required<ProtectedRouteProps>) {
    const { user, isLoading, isAuthenticated } = useAuth();
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const search = searchParams.toString();

    useEffect(() => {
        // Skip redirect while still loading auth state
        if (isLoading) return;

        // Check authentication requirement
        if (requireAuth && !isAuthenticated) {
            // Redirect to login with return URL
            const returnUrl = encodeURIComponent(`${pathname}${search ? `?${search}` : ''}`);
            router.push(`${fallbackUrl}?returnTo=${returnUrl}`);
            return;
        }

        // Check admin requirement
        if (requireAdmin && (!user || !user.is_superuser)) {
            router.push('/');
            return;
        }
    }, [isLoading, isAuthenticated, user, requireAuth, requireAdmin, router, pathname, search, fallbackUrl]);

    // Show loading state while checking auth
    if (isLoading) {
        return <ProtectedRouteLoading />;
    }

    // During migration period, allow access if auth is not required
    // The backend will handle permission checks
    if (!requireAuth) {
        return <>{children}</>;
    }

    // If authenticated (and admin if required), render children
    if (isAuthenticated && (!requireAdmin || user?.is_superuser)) {
        return <>{children}</>;
    }

    // Fallback loading while redirecting
    return <ProtectedRouteLoading />;
}

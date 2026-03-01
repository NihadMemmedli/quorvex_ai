'use client';

import { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2 } from 'lucide-react';

interface ProtectedRouteProps {
    children: React.ReactNode;
    requireAuth?: boolean;
    requireAdmin?: boolean;
    fallbackUrl?: string;
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
    const { user, isLoading, isAuthenticated } = useAuth();
    const router = useRouter();
    const pathname = usePathname();

    useEffect(() => {
        // Skip redirect while still loading auth state
        if (isLoading) return;

        // Check authentication requirement
        if (requireAuth && !isAuthenticated) {
            // Redirect to login with return URL
            const returnUrl = encodeURIComponent(pathname);
            router.push(`${fallbackUrl}?returnTo=${returnUrl}`);
            return;
        }

        // Check admin requirement
        if (requireAdmin && (!user || !user.is_superuser)) {
            router.push('/');
            return;
        }
    }, [isLoading, isAuthenticated, user, requireAuth, requireAdmin, router, pathname, fallbackUrl]);

    // Show loading state while checking auth
    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
            </div>
        );
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
    return (
        <div className="flex items-center justify-center min-h-[400px]">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
        </div>
    );
}

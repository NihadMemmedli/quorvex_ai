'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2, AlertCircle, Eye, EyeOff, Mail, Lock } from 'lucide-react';

interface LoginFormProps {
    redirectTo?: string;
}

export function LoginForm({ redirectTo = '/' }: LoginFormProps) {
    const router = useRouter();
    const { login } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setIsLoading(true);

        try {
            await login(email, password);
            router.push(redirectTo);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Login failed');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
                <div
                    className="flex items-center gap-3 p-3 text-sm"
                    style={{
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        borderRadius: '6px'
                    }}
                >
                    <AlertCircle className="h-4 w-4 flex-shrink-0" style={{ color: '#ef4444' }} />
                    <span style={{ color: '#fca5a5' }}>{error}</span>
                </div>
            )}

            {/* Email Field */}
            <div>
                <label
                    htmlFor="email"
                    className="block text-sm font-medium mb-2"
                    style={{ color: '#f8fafc' }}
                >
                    Email
                </label>
                <div style={{ position: 'relative' }}>
                    <div
                        style={{
                            position: 'absolute',
                            left: '12px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            pointerEvents: 'none',
                            display: 'flex',
                            alignItems: 'center'
                        }}
                    >
                        <Mail className="h-4 w-4" style={{ color: '#64748b' }} />
                    </div>
                    <input
                        id="email"
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        autoComplete="email"
                        disabled={isLoading}
                        style={{
                            width: '100%',
                            height: '44px',
                            paddingLeft: '40px',
                            paddingRight: '16px',
                            backgroundColor: '#0f172a',
                            border: '1px solid #334155',
                            borderRadius: '6px',
                            color: '#f8fafc',
                            fontSize: '14px',
                            outline: 'none',
                        }}
                    />
                </div>
            </div>

            {/* Password Field */}
            <div>
                <label
                    htmlFor="password"
                    className="block text-sm font-medium mb-2"
                    style={{ color: '#f8fafc' }}
                >
                    Password
                </label>
                <div style={{ position: 'relative' }}>
                    <div
                        style={{
                            position: 'absolute',
                            left: '12px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            pointerEvents: 'none',
                            display: 'flex',
                            alignItems: 'center'
                        }}
                    >
                        <Lock className="h-4 w-4" style={{ color: '#64748b' }} />
                    </div>
                    <input
                        id="password"
                        type={showPassword ? 'text' : 'password'}
                        placeholder="Enter your password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        autoComplete="current-password"
                        disabled={isLoading}
                        style={{
                            width: '100%',
                            height: '44px',
                            paddingLeft: '40px',
                            paddingRight: '44px',
                            backgroundColor: '#0f172a',
                            border: '1px solid #334155',
                            borderRadius: '6px',
                            color: '#f8fafc',
                            fontSize: '14px',
                            outline: 'none',
                        }}
                    />
                    <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        tabIndex={-1}
                        style={{
                            position: 'absolute',
                            right: '12px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '4px',
                            display: 'flex',
                            alignItems: 'center',
                        }}
                    >
                        {showPassword ? (
                            <EyeOff className="h-4 w-4" style={{ color: '#64748b' }} />
                        ) : (
                            <Eye className="h-4 w-4" style={{ color: '#64748b' }} />
                        )}
                    </button>
                </div>
            </div>

            {/* Submit Button */}
            <div style={{ marginTop: '24px' }}>
                <button
                    type="submit"
                    disabled={isLoading}
                    style={{
                        width: '100%',
                        height: '44px',
                        backgroundColor: isLoading ? '#3b82f6' : '#3b82f6',
                        color: '#ffffff',
                        border: 'none',
                        borderRadius: '6px',
                        fontSize: '14px',
                        fontWeight: 500,
                        cursor: isLoading ? 'not-allowed' : 'pointer',
                        opacity: isLoading ? 0.7 : 1,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                    }}
                    onMouseEnter={(e) => {
                        if (!isLoading) e.currentTarget.style.backgroundColor = '#2563eb';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = '#3b82f6';
                    }}
                >
                    {isLoading ? (
                        <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Signing in...
                        </>
                    ) : (
                        'Sign in'
                    )}
                </button>
            </div>

            {/* Sign up link */}
            <p className="text-center text-sm" style={{ color: '#94a3b8' }}>
                Don&apos;t have an account?{' '}
                <Link
                    href="/register"
                    className="font-medium hover:underline"
                    style={{ color: '#3b82f6' }}
                >
                    Sign up
                </Link>
            </p>
        </form>
    );
}

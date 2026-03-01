'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { Loader2, AlertCircle, Eye, EyeOff, Mail, Lock, User, Check, X } from 'lucide-react';

interface RegisterFormProps {
    redirectTo?: string;
}

interface PasswordRequirement {
    label: string;
    test: (password: string) => boolean;
}

const passwordRequirements: PasswordRequirement[] = [
    { label: 'At least 8 characters', test: (p) => p.length >= 8 },
    { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
    { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
    { label: 'One number', test: (p) => /\d/.test(p) },
    { label: 'One special character', test: (p) => /[!@#$%^&*(),.?":{}|<>]/.test(p) },
];

export function RegisterForm({ redirectTo = '/' }: RegisterFormProps) {
    const router = useRouter();
    const { register } = useAuth();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [fullName, setFullName] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    const allRequirementsMet = passwordRequirements.every((req) => req.test(password));
    const passwordsMatch = password === confirmPassword && password.length > 0;

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);

        if (!allRequirementsMet) {
            setError('Password does not meet all requirements');
            return;
        }

        if (!passwordsMatch) {
            setError('Passwords do not match');
            return;
        }

        setIsLoading(true);

        try {
            await register(email, password, fullName || undefined);
            router.push(redirectTo);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Registration failed');
        } finally {
            setIsLoading(false);
        }
    };

    const inputStyle = {
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
    };

    const iconWrapperStyle = {
        position: 'absolute' as const,
        left: '12px',
        top: '50%',
        transform: 'translateY(-50%)',
        pointerEvents: 'none' as const,
        display: 'flex',
        alignItems: 'center',
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

            {/* Full Name Field */}
            <div>
                <label
                    htmlFor="fullName"
                    className="block text-sm font-medium mb-2"
                    style={{ color: '#f8fafc' }}
                >
                    Full Name <span style={{ color: '#64748b' }}>(optional)</span>
                </label>
                <div style={{ position: 'relative' }}>
                    <div style={iconWrapperStyle}>
                        <User className="h-4 w-4" style={{ color: '#64748b' }} />
                    </div>
                    <input
                        id="fullName"
                        type="text"
                        placeholder="John Doe"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        autoComplete="name"
                        disabled={isLoading}
                        style={inputStyle}
                    />
                </div>
            </div>

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
                    <div style={iconWrapperStyle}>
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
                        style={inputStyle}
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
                    <div style={iconWrapperStyle}>
                        <Lock className="h-4 w-4" style={{ color: '#64748b' }} />
                    </div>
                    <input
                        id="password"
                        type={showPassword ? 'text' : 'password'}
                        placeholder="Create a strong password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        autoComplete="new-password"
                        disabled={isLoading}
                        style={{
                            ...inputStyle,
                            paddingRight: '44px',
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

                {/* Password requirements */}
                {password.length > 0 && (
                    <div
                        className="mt-3 p-3"
                        style={{
                            backgroundColor: 'rgba(15, 23, 42, 0.5)',
                            borderRadius: '6px'
                        }}
                    >
                        <div className="grid grid-cols-1 gap-1.5">
                            {passwordRequirements.map((req, index) => {
                                const met = req.test(password);
                                return (
                                    <div
                                        key={index}
                                        className="flex items-center gap-2 text-xs"
                                        style={{ color: met ? '#10b981' : '#64748b' }}
                                    >
                                        {met ? (
                                            <Check className="h-3 w-3" />
                                        ) : (
                                            <X className="h-3 w-3" />
                                        )}
                                        {req.label}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* Confirm Password Field */}
            <div>
                <label
                    htmlFor="confirmPassword"
                    className="block text-sm font-medium mb-2"
                    style={{ color: '#f8fafc' }}
                >
                    Confirm Password
                </label>
                <div style={{ position: 'relative' }}>
                    <div style={iconWrapperStyle}>
                        <Lock className="h-4 w-4" style={{ color: '#64748b' }} />
                    </div>
                    <input
                        id="confirmPassword"
                        type="password"
                        placeholder="Confirm your password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                        autoComplete="new-password"
                        disabled={isLoading}
                        style={inputStyle}
                    />
                </div>
                {confirmPassword.length > 0 && !passwordsMatch && (
                    <p className="mt-2 text-xs" style={{ color: '#ef4444' }}>
                        Passwords do not match
                    </p>
                )}
            </div>

            {/* Submit Button */}
            <div style={{ marginTop: '24px' }}>
                <button
                    type="submit"
                    disabled={isLoading || !allRequirementsMet || !passwordsMatch}
                    style={{
                        width: '100%',
                        height: '44px',
                        backgroundColor: '#3b82f6',
                        color: '#ffffff',
                        border: 'none',
                        borderRadius: '6px',
                        fontSize: '14px',
                        fontWeight: 500,
                        cursor: (isLoading || !allRequirementsMet || !passwordsMatch) ? 'not-allowed' : 'pointer',
                        opacity: (isLoading || !allRequirementsMet || !passwordsMatch) ? 0.5 : 1,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                    }}
                    onMouseEnter={(e) => {
                        if (!isLoading && allRequirementsMet && passwordsMatch) {
                            e.currentTarget.style.backgroundColor = '#2563eb';
                        }
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = '#3b82f6';
                    }}
                >
                    {isLoading ? (
                        <>
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Creating account...
                        </>
                    ) : (
                        'Create account'
                    )}
                </button>
            </div>

            {/* Sign in link */}
            <p className="text-center text-sm" style={{ color: '#94a3b8' }}>
                Already have an account?{' '}
                <Link
                    href="/login"
                    className="font-medium hover:underline"
                    style={{ color: '#3b82f6' }}
                >
                    Sign in
                </Link>
            </p>
        </form>
    );
}

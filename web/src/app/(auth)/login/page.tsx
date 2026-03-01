'use client';

import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense, useEffect } from 'react';
import { LoginForm } from '@/components/auth/LoginForm';
import { useAuth } from '@/contexts/AuthContext';

/* ------------------------------------------------------------------ */
/*  CSS Keyframes & Styles (injected via <style> tag)                 */
/* ------------------------------------------------------------------ */
const atmosphericStyles = `
  @keyframes fadeInScale {
    0% {
      opacity: 0;
      transform: scale(0.96) translateY(8px);
    }
    100% {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  @keyframes subtleFloat {
    0%, 100% {
      transform: translate(-50%, -50%) translateY(0px);
    }
    50% {
      transform: translate(-50%, -50%) translateY(-30px);
    }
  }

  @keyframes subtleFloatAlt {
    0%, 100% {
      transform: translate(50%, 50%) translateY(0px) translateX(0px);
    }
    33% {
      transform: translate(50%, 50%) translateY(20px) translateX(-10px);
    }
    66% {
      transform: translate(50%, 50%) translateY(-15px) translateX(15px);
    }
  }

  @keyframes glowPulse {
    0%, 100% {
      opacity: 0.6;
      filter: drop-shadow(0 0 8px rgba(59, 130, 246, 0.3));
    }
    50% {
      opacity: 1;
      filter: drop-shadow(0 0 20px rgba(59, 130, 246, 0.6));
    }
  }

  @keyframes fadeInUp {
    0% {
      opacity: 0;
      transform: translateY(12px);
    }
    100% {
      opacity: 1;
      transform: translateY(0);
    }
  }
`;

/* ------------------------------------------------------------------ */
/*  Background Component                                              */
/* ------------------------------------------------------------------ */
function AtmosphericBackground() {
    return (
        <>
            {/* Grid pattern overlay */}
            <div
                style={{
                    position: 'fixed',
                    inset: 0,
                    backgroundImage:
                        'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)',
                    backgroundSize: '64px 64px',
                    zIndex: 0,
                    pointerEvents: 'none',
                }}
            />

            {/* Primary blue orb - top center */}
            <div
                style={{
                    position: 'fixed',
                    width: '600px',
                    height: '600px',
                    background:
                        'radial-gradient(circle, rgba(59, 130, 246, 0.08) 0%, transparent 70%)',
                    top: '20%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    animation: 'subtleFloat 8s ease-in-out infinite',
                    filter: 'blur(60px)',
                    zIndex: 0,
                    pointerEvents: 'none',
                }}
            />

            {/* Secondary purple orb - bottom right */}
            <div
                style={{
                    position: 'fixed',
                    width: '400px',
                    height: '400px',
                    background:
                        'radial-gradient(circle, rgba(192, 132, 252, 0.06) 0%, transparent 70%)',
                    bottom: '0%',
                    right: '0%',
                    transform: 'translate(50%, 50%)',
                    animation: 'subtleFloatAlt 10s ease-in-out infinite',
                    filter: 'blur(50px)',
                    zIndex: 0,
                    pointerEvents: 'none',
                }}
            />
        </>
    );
}

/* ------------------------------------------------------------------ */
/*  Login Content                                                     */
/* ------------------------------------------------------------------ */
function LoginContent() {
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
                style={{ backgroundColor: '#060a12' }}
            >
                <style dangerouslySetInnerHTML={{ __html: atmosphericStyles }} />
                <AtmosphericBackground />
                <div
                    style={{
                        position: 'relative',
                        zIndex: 1,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: '16px',
                    }}
                >
                    <img
                        src="/quorvex-logo.svg"
                        alt="Quorvex AI"
                        width={44}
                        height={44}
                        style={{
                            animation: 'glowPulse 2s ease-in-out infinite',
                        }}
                    />
                    <span
                        style={{
                            fontSize: '0.8125rem',
                            color: '#4a5578',
                            letterSpacing: '0.06em',
                            fontWeight: 500,
                            textTransform: 'uppercase',
                        }}
                    >
                        Loading
                    </span>
                </div>
            </div>
        );
    }

    return (
        <div
            className="min-h-screen flex items-center justify-center px-4 py-12"
            style={{
                backgroundColor: '#060a12',
                position: 'relative',
                overflow: 'hidden',
            }}
        >
            <style dangerouslySetInnerHTML={{ __html: atmosphericStyles }} />
            <AtmosphericBackground />

            {/* Card container */}
            <div
                style={{
                    width: '100%',
                    maxWidth: '420px',
                    position: 'relative',
                    zIndex: 1,
                    animation: 'fadeInScale 0.6s cubic-bezier(0.16, 1, 0.3, 1) both',
                }}
            >
                <div
                    style={{
                        background: 'rgba(15, 22, 41, 0.6)',
                        backdropFilter: 'blur(20px) saturate(1.4)',
                        WebkitBackdropFilter: 'blur(20px) saturate(1.4)',
                        border: '1px solid rgba(255,255,255,0.06)',
                        borderRadius: '16px',
                        padding: '2.5rem',
                        boxShadow:
                            '0 25px 60px -15px rgba(0, 0, 0, 0.5), 0 0 40px -10px rgba(59, 130, 246, 0.1)',
                    }}
                >
                    {/* Logo / Brand Section */}
                    <div
                        style={{
                            textAlign: 'center',
                            marginBottom: '2rem',
                            animation: 'fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.15s both',
                        }}
                    >
                        <img
                            src="/quorvex-logo.svg"
                            alt="Quorvex AI"
                            width={44}
                            height={44}
                            style={{
                                marginBottom: '16px',
                                display: 'inline-block',
                            }}
                        />
                        <div
                            style={{
                                fontSize: '1.75rem',
                                fontWeight: 800,
                                letterSpacing: '-0.04em',
                                lineHeight: 1.2,
                                marginBottom: '20px',
                                background: 'linear-gradient(135deg, #f0f4fc 30%, #7e8ba8)',
                                WebkitBackgroundClip: 'text',
                                WebkitTextFillColor: 'transparent',
                                backgroundClip: 'text',
                            }}
                        >
                            Quorvex AI
                        </div>
                        <h1
                            style={{
                                fontSize: '1.5rem',
                                fontWeight: 700,
                                letterSpacing: '-0.02em',
                                color: '#f0f4fc',
                                margin: 0,
                                lineHeight: 1.3,
                            }}
                        >
                            Welcome back
                        </h1>
                        <p
                            style={{
                                fontSize: '0.875rem',
                                color: '#4a5578',
                                marginTop: '8px',
                                marginBottom: 0,
                            }}
                        >
                            Sign in to your account
                        </p>
                    </div>

                    {/* Divider */}
                    <div
                        style={{
                            height: '1px',
                            background:
                                'linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 50%, transparent)',
                            marginBottom: '1.75rem',
                        }}
                    />

                    {/* Form */}
                    <div
                        style={{
                            animation: 'fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.3s both',
                        }}
                    >
                        <LoginForm redirectTo={returnTo} />
                    </div>
                </div>
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/*  Page Export with Suspense                                          */
/* ------------------------------------------------------------------ */
export default function LoginPage() {
    return (
        <Suspense
            fallback={
                <div
                    className="min-h-screen flex items-center justify-center"
                    style={{ backgroundColor: '#060a12' }}
                >
                    <style dangerouslySetInnerHTML={{ __html: atmosphericStyles }} />
                    <AtmosphericBackground />
                    <div
                        style={{
                            position: 'relative',
                            zIndex: 1,
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '16px',
                        }}
                    >
                        <img
                            src="/quorvex-logo.svg"
                            alt="Quorvex AI"
                            width={44}
                            height={44}
                            style={{
                                animation: 'glowPulse 2s ease-in-out infinite',
                            }}
                        />
                        <span
                            style={{
                                fontSize: '0.8125rem',
                                color: '#4a5578',
                                letterSpacing: '0.06em',
                                fontWeight: 500,
                                textTransform: 'uppercase',
                            }}
                        >
                            Loading
                        </span>
                    </div>
                </div>
            }
        >
            <LoginContent />
        </Suspense>
    );
}

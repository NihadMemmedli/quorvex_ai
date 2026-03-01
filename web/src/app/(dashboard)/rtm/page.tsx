'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function RtmRedirect() {
    const router = useRouter();
    useEffect(() => { router.replace('/requirements?tab=traceability'); }, [router]);
    return null;
}

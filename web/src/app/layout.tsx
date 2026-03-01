import './globals.css';
import { Sora, JetBrains_Mono } from 'next/font/google';
import { Providers } from '@/components/Providers';
import { Toaster } from '@/components/ui/sonner';

const sora = Sora({
    subsets: ['latin'],
    variable: '--font-sora',
    display: 'swap',
    weight: ['300', '400', '500', '600', '700', '800'],
});

const jetbrainsMono = JetBrains_Mono({
    subsets: ['latin'],
    variable: '--font-mono',
    display: 'swap',
    weight: ['400', '500', '600', '700'],
});

export const metadata = {
    title: 'Quorvex AI',
    description: 'Intelligent Test Automation Platform',
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en" suppressHydrationWarning className={`${sora.variable} ${jetbrainsMono.variable}`}>
            <body>
                <Providers>
                    {children}
                    <Toaster position="bottom-right" />
                </Providers>
            </body>
        </html>
    );
}

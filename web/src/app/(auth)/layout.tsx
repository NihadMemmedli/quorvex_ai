export default function AuthLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    // Auth pages have a simple full-screen layout without the sidebar
    // Providers are already wrapped in the root layout
    return <>{children}</>;
}

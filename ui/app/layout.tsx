import type React from "react";
import "@/app/globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Navbar } from "@/components/Navbar";
import { Toaster } from "@/components/ui/toaster";
import { ScrollArea } from "@/components/ui/scroll-area";
import { PageContainer } from "@/components/PageContainer";
import { Providers } from "./providers";

export const metadata = {
  title: "MemoryCore",
  description: "Agent Memory OS — local-first memory for multi-agent systems",
  icons: {
    icon: "/icon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="h-screen font-sans antialiased flex flex-col bg-zinc-950">
        <Providers>
          <ThemeProvider
            attribute="class"
            defaultTheme="dark"
            enableSystem
            disableTransitionOnChange
          >
            <Navbar />
            <ScrollArea className="h-[calc(100vh-var(--navbar-h))]">
              <PageContainer>{children}</PageContainer>
            </ScrollArea>
            <Toaster />
          </ThemeProvider>
        </Providers>
      </body>
    </html>
  );
}

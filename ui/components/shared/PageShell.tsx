import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

interface PageShellProps {
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  /** Full-bleed pages (e.g. Graph) that manage their own container */
  fullBleed?: boolean;
  /** Constrain content width, e.g. "max-w-4xl" */
  maxWidth?: string;
  /** Render a back arrow before the title (used by deep-linked pages) */
  backHref?: string;
  backLabel?: string;
}

export function PageShell({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
  fullBleed = false,
  maxWidth,
  backHref,
  backLabel,
}: PageShellProps) {
  if (fullBleed) {
    return <div className="h-[calc(100vh-var(--navbar-h))]">{children}</div>;
  }

  return (
    <main className="py-6">
      <div className={`container ${maxWidth ?? ""}`}>
        {(title || actions || backHref) && (
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between mb-6 animate-fade-slide-down">
            <div className="space-y-1">
              {backHref && (
                <Link
                  href={backHref}
                  className="inline-flex items-center gap-1.5 rounded px-1 -ml-1 py-0.5 text-xs text-zinc-400 transition-colors hover:text-zinc-100 hover:bg-zinc-800"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> {backLabel}
                </Link>
              )}
              {eyebrow && (
                <p className="text-xs font-medium uppercase tracking-widest text-violet-300">
                  {eyebrow}
                </p>
              )}
              {title && <h1 className="text-2xl font-semibold">{title}</h1>}
              {subtitle && <p className="text-sm text-zinc-500">{subtitle}</p>}
            </div>
            {actions && (
              <div className="flex flex-wrap items-center justify-end gap-2">
                {actions}
              </div>
            )}
          </div>
        )}
        {children}
      </div>
    </main>
  );
}

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
}

export function PageShell({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
  fullBleed = false,
  maxWidth,
}: PageShellProps) {
  if (fullBleed) {
    return <div className="h-[calc(100vh-var(--navbar-h))]">{children}</div>;
  }

  return (
    <main className="py-6">
      <div className={`container ${maxWidth ?? ""}`}>
        {(title || actions) && (
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between mb-6 animate-fade-slide-down">
            <div className="space-y-1">
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

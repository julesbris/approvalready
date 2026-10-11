import type { ReactNode } from "react";

import { Wordmark } from "@/components/brand/Wordmark";
import { SiteFooter } from "@/components/public/SiteFooter";

export function AuthShell({
  title,
  intro,
  children,
  footer,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <>
      <header className="site-header">
        <div className="container">
          <Wordmark />
        </div>
      </header>
      <main className="container auth-main">
        <section className="auth-card" aria-labelledby="auth-title">
          <h1 id="auth-title">{title}</h1>
          {intro ? <div className="auth-intro">{intro}</div> : null}
          {children}
          {footer ? <div className="auth-footer">{footer}</div> : null}
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef } from "react";

/**
 * The small-screen menu: a native disclosure, so it opens without JavaScript, that closes again
 * once a link in it has been followed or Escape is pressed.
 */
export function MenuDisclosure({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (ref.current) ref.current.open = false;
  }, [pathname]);

  return (
    <details
      ref={ref}
      className="menu-disclosure"
      onKeyDown={(event) => {
        if (event.key === "Escape" && ref.current?.open) {
          ref.current.open = false;
          ref.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary>
        <span className="menu-icon" aria-hidden="true" />
        <span className="visually-hidden">Menu</span>
      </summary>
      <nav className="menu-panel" aria-label="Menu">
        {children}
      </nav>
    </details>
  );
}

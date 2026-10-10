import Link from "next/link";

/** Section links shown at the top of every admin page. */
export function AdminNav({
  current,
}: {
  current:
    | "home"
    | "sources"
    | "rules"
    | "grants"
    | "reviews"
    | "professionals"
    | "partners"
    | "leads"
    | "analytics"
    | "ai"
    | "billing"
    | "privacy"
    | "ops";
}) {
  const links = [
    ["home", "/admin", "Review queue"],
    ["sources", "/admin/sources", "Sources"],
    ["rules", "/admin/rules", "Rules"],
    ["grants", "/admin/grants", "Grants"],
    ["reviews", "/admin/reviews", "Professional reviews"],
    ["professionals", "/admin/professionals", "Professionals"],
    ["partners", "/admin/partners", "Partners"],
    ["leads", "/admin/leads", "Referrals"],
    ["analytics", "/admin/analytics", "Marketplace"],
    ["ai", "/admin/ai", "AI"],
    ["billing", "/admin/billing", "Billing"],
    ["privacy", "/admin/privacy", "Privacy"],
    ["ops", "/admin/ops", "Operations"],
  ] as const;
  return (
    <nav aria-label="Admin" className="admin-nav">
      {links.map(([key, href, label]) => (
        <Link key={key} href={href} aria-current={key === current ? "page" : undefined}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

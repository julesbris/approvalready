import Link from "next/link";

/** Section links shown at the top of every admin page. */
export function AdminNav({
  current,
}: {
  current: "home" | "sources" | "rules" | "grants" | "reviews" | "professionals";
}) {
  const links = [
    ["home", "/admin", "Review queue"],
    ["sources", "/admin/sources", "Sources"],
    ["rules", "/admin/rules", "Rules"],
    ["grants", "/admin/grants", "Grants"],
    ["reviews", "/admin/reviews", "Professional reviews"],
    ["professionals", "/admin/professionals", "Professionals"],
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

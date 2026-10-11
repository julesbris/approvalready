import type { WhatsLeftOut } from "@approvalready/shared-types";
import Link from "next/link";

/** The project's remaining steps, first thing first, each linking to where it gets done. The
 * keep-going reminder emails name the same steps. */
export function WhatsLeft({ left }: { left: WhatsLeftOut }) {
  const [first] = left.items;
  if (left.done || !first) {
    return (
      <section className="panel" aria-labelledby="whats-left-title">
        <h2 id="whats-left-title" className="section-title">
          What&apos;s left
        </h2>
        <p>
          <span className="status status-completed">Up to date</span> Nothing is waiting on you
          right now.
        </p>
      </section>
    );
  }
  return (
    <section className="panel" aria-labelledby="whats-left-title">
      <h2 id="whats-left-title" className="section-title">
        What&apos;s left
      </h2>
      <p className="muted">
        {left.items.length === 1 ? "One step" : `${left.items.length} steps`} to go. Everything you
        have done so far is saved.
      </p>
      <ol className="whats-left-steps">
        {left.items.map((item) => (
          <li key={item.step}>
            <div>
              <Link href={item.link_path} className="whats-left-title">
                {item.title}
              </Link>
              {item.details.length > 0 ? (
                <ul className="whats-left-details">
                  {item.details.map((detail, i) => (
                    <li key={i}>{detail}</li>
                  ))}
                  {item.count > item.details.length ? (
                    <li className="muted">and {item.count - item.details.length} more</li>
                  ) : null}
                </ul>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      <Link className="button" href={first.link_path}>
        Pick up where you left off
      </Link>
    </section>
  );
}

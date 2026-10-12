"use client";

import type { CouncilOut } from "@approvalready/shared-types";
import { useMemo, useState } from "react";

import { councilEnquiry, enquiryEmail, enquiryMailto } from "@/lib/councils";

type Props = {
  council: CouncilOut;
  /** Planning answers (or an assessment's facts) to fill the email from. */
  answers?: Record<string, unknown>;
  /** Heading level for the sub-heading. */
  level?: 3 | 4;
};

/**
 * A ready-to-send pre-lodgement enquiry to the council's planning team, written from the
 * person's answers. They can edit it, copy it, or open it in their own email app; nothing
 * is sent from ApprovalReady.
 */
export function CouncilEnquiryEmail({ council, answers, level = 3 }: Props) {
  const Sub = level === 3 ? "h3" : "h4";
  const to = enquiryEmail(council);
  const enquiry = useMemo(() => councilEnquiry(council, answers), [council, answers]);
  // The person's edits, until they change their answers and the email is written afresh.
  const [edited, setEdited] = useState<{ from: string; body: string } | null>(null);
  const body = edited && edited.from === enquiry.body ? edited.body : enquiry.body;
  const [copied, setCopied] = useState(false);
  // Councils that publish no email take enquiries through a web form or by phone.
  const form = to ? null : (council.pre_lodgement?.url ?? council.planning_url ?? council.website);
  if (!to && !form) return null;
  const general = !council.contact.planning_email || council.contact.planning_email_general;

  async function copy() {
    try {
      const head = to ? `To: ${to}\nSubject: ${enquiry.subject}` : `Subject: ${enquiry.subject}`;
      await navigator.clipboard.writeText(`${head}\n\n${body}`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="council-enquiry">
      <Sub className="subsection-title">Ask the planning team before you lodge</Sub>
      <p className="muted">
        {to
          ? "We've written this email from your answers. Add your name and phone number, then send it from your own email."
          : "We've written this enquiry from your answers. The council doesn't publish an email address for planning, so add your name and phone number and paste it into its enquiry form."}{" "}
        An early answer from the council can save a refused or delayed application. Attach your
        pre-lodgement pack (under Reports on your assessment) so the planning team has the full
        picture.
      </p>
      <dl className="review-list">
        <div>
          <dt>{to ? "To" : "Send it with"}</dt>
          <dd>
            {to ? (
              <>
                <a href={`mailto:${to}`}>{to}</a>
                {general ? <span className="muted"> (the council&apos;s main inbox)</span> : null}
              </>
            ) : (
              <a href={form ?? undefined} rel="noopener noreferrer" target="_blank">
                The council&apos;s enquiry form
              </a>
            )}
          </dd>
        </div>
        <div>
          <dt>Subject</dt>
          <dd>{enquiry.subject}</dd>
        </div>
      </dl>
      <div className="form">
        <label>
          Email
          <textarea
            className="council-enquiry-body"
            rows={14}
            value={body}
            onChange={(event) => {
              setEdited({ from: enquiry.body, body: event.target.value });
              setCopied(false);
            }}
          />
        </label>
      </div>
      <div className="button-row">
        {to ? (
          <a className="button" href={enquiryMailto(to, { subject: enquiry.subject, body })}>
            Open in my email
          </a>
        ) : null}
        <button type="button" className="button button-secondary" onClick={copy}>
          {copied ? "Copied" : to ? "Copy email" : "Copy enquiry"}
        </button>
      </div>
    </div>
  );
}

import type { CouncilOut } from "@approvalready/shared-types";

import { CouncilEnquiryEmail } from "@/components/councils/CouncilEnquiryEmail";
import { FormList, FormText } from "@/components/guidance/FormText";
import { LODGEMENT_LABELS, feesMayBeOutOfDate, telHref } from "@/lib/councils";
import { STATE_NAMES, stateGovernment } from "@/lib/coverage";
import { formatDate } from "@/lib/questionnaire";

type Props = {
  council: CouncilOut;
  /** Heading level for the panel title (sub-headings go one lower). */
  level?: 2 | 3;
  /** Planning answers (or an assessment's facts), to write the enquiry email from. */
  answers?: Record<string, unknown>;
};

/**
 * How to apply to a council for a development application: ways to lodge, steps, fees and
 * contacts, with where each came from. Until a person checks the council's details they are
 * labelled as gathered from the council's website.
 */
export function CouncilGuide({ council, level = 2, answers }: Props) {
  const Title = level === 2 ? "h2" : "h3";
  const Sub = level === 2 ? "h3" : "h4";
  const titleId = `council-${council.key}`;
  const steps = council.steps.length > 0 ? council.steps : council.general_steps;
  const stateName = STATE_NAMES[council.state] ?? council.state;
  const councilFees = council.fees && council.fees.items.length > 0 ? council.fees : null;
  // Fees the state sets for every council, when the council's own aren't listed.
  const stateFees = councilFees ? null : council.state_fees;
  const fees = councilFees ?? stateFees ?? council.fees;
  const lodgement =
    council.lodgement.length > 0 || !council.state_portal
      ? council.lodgement
      : [
          {
            method: "ONLINE" as const,
            label: council.state_portal.title,
            url: council.state_portal.url,
            email: null,
            address: null,
          },
        ];
  const schemeLabel =
    council.planning_scheme_label.charAt(0).toUpperCase() + council.planning_scheme_label.slice(1);
  const contact = council.contact;
  const phoneHref = contact.phone ? telHref(contact.phone) : null;
  const planningPhoneHref = contact.planning_phone ? telHref(contact.planning_phone) : null;
  const planningEmail =
    contact.planning_email_general || contact.planning_email === contact.email
      ? null
      : contact.planning_email;
  return (
    <section className="panel council-guide" aria-labelledby={titleId}>
      <div className="council-head">
        <Title id={titleId} className="section-title">
          How to apply to {council.name}
        </Title>
        {council.checked.verified ? (
          <span className="status status-verified">
            Checked by our team
            {council.checked.verified_at ? ` ${formatDate(council.checked.verified_at)}` : ""}
          </span>
        ) : (
          <span className="status confidence-review_required">Not yet checked by our team</span>
        )}
      </div>
      {council.checked.verified ? null : (
        <p className="muted">
          Gathered from official council and {stateGovernment(council.state)} websites on{" "}
          {formatDate(council.checked_on)}. Confirm the details with the council before you lodge.
        </p>
      )}

      {lodgement.length > 0 ? (
        <>
          <Sub className="subsection-title">Ways to lodge</Sub>
          <ul className="plain-list council-list">
            {lodgement.map((way) => (
              <li key={`${way.method}-${way.label}`}>
                <span className="badge council-method">{LODGEMENT_LABELS[way.method]}</span>{" "}
                {way.url ? (
                  <a href={way.url} rel="noopener noreferrer" target="_blank">
                    {way.label}
                  </a>
                ) : (
                  way.label
                )}
                {way.email ? (
                  <>
                    {" "}
                    <a href={`mailto:${way.email}`}>{way.email}</a>
                  </>
                ) : null}
                {way.address ? <span className="muted"> {way.address}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <Sub className="subsection-title">Steps</Sub>
      <ol className="council-steps">
        {steps.map((step) => (
          <li key={step}>
            <FormText text={step} forms={council.forms} />
          </li>
        ))}
      </ol>
      {council.steps.length === 0 ? (
        <p className="muted">
          {council.name} doesn&apos;t publish its own steps online, so these are the steps that
          apply across {stateName}.
        </p>
      ) : (
        <details className="council-more">
          <summary>How applications work across {stateName}</summary>
          <ol className="council-steps">
            {council.general_steps.map((step) => (
              <li key={step}>
                <FormText text={step} forms={council.forms} />
              </li>
            ))}
          </ol>
          <p className="muted">
            Source:{" "}
            <a href={council.general_source.url} rel="noopener noreferrer" target="_blank">
              {council.general_source.title}
            </a>
          </p>
        </details>
      )}

      <FormList forms={council.forms} title="Application forms" level={level === 2 ? 3 : 4} />

      {council.pre_lodgement && council.pre_lodgement.available !== null ? (
        <>
          <Sub className="subsection-title">Talk to the council first</Sub>
          <p>
            {council.pre_lodgement.available
              ? "The council offers pre-lodgement meetings."
              : "The council says it doesn't offer pre-lodgement meetings."}
            {council.pre_lodgement.note ? ` ${council.pre_lodgement.note}` : ""}
            {council.pre_lodgement.url ? (
              <>
                {" "}
                <a href={council.pre_lodgement.url} rel="noopener noreferrer" target="_blank">
                  Pre-lodgement details
                </a>
              </>
            ) : null}
          </p>
        </>
      ) : null}

      <Sub className="subsection-title">Fees</Sub>
      {fees && fees.items.length > 0 ? (
        <>
          <table className="council-fees">
            <caption className="muted">
              {fees.fee_year ? `${fees.fee_year} fees` : "Fees"}{" "}
              {stateFees
                ? `set by ${stateGovernment(council.state)} for every council.`
                : "as published by the council."}{" "}
              The fee for your application depends on its details.
            </caption>
            <thead>
              <tr>
                <th scope="col">Application</th>
                <th scope="col">Fee</th>
              </tr>
            </thead>
            <tbody>
              {fees.items.map((item) => (
                <tr key={item.label}>
                  <td>
                    {item.label}
                    {item.note ? <span className="muted"> ({item.note})</span> : null}
                  </td>
                  <td className="council-amount">{item.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {feesMayBeOutOfDate(fees.fee_year) ? (
            <p className="notice notice-warning">
              These are the {fees.fee_year} fees, the latest we found. Fees usually change each
              July, so check the current amount with the council.
            </p>
          ) : null}
        </>
      ) : (
        <p>Check with the council: we couldn&apos;t find its application fees published online.</p>
      )}
      {fees?.schedule_url ? (
        <p>
          <a href={fees.schedule_url} rel="noopener noreferrer" target="_blank">
            {stateFees ? "The fees in full" : "The council's full fee schedule"}
          </a>
        </p>
      ) : null}

      <Sub className="subsection-title">Contact the council</Sub>
      <dl className="review-list">
        {planningEmail ? (
          <div>
            <dt>Planning team email</dt>
            <dd>
              <a href={`mailto:${planningEmail}`}>{planningEmail}</a>
            </dd>
          </div>
        ) : null}
        {contact.planning_phone && contact.planning_phone !== contact.phone ? (
          <div>
            <dt>Planning team phone</dt>
            <dd>
              {planningPhoneHref ? (
                <a href={planningPhoneHref}>{contact.planning_phone}</a>
              ) : (
                contact.planning_phone
              )}
            </dd>
          </div>
        ) : null}
        {contact.phone ? (
          <div>
            <dt>Phone</dt>
            <dd>{phoneHref ? <a href={phoneHref}>{contact.phone}</a> : contact.phone}</dd>
          </div>
        ) : null}
        {contact.email ? (
          <div>
            <dt>Email</dt>
            <dd>
              <a href={`mailto:${contact.email}`}>{contact.email}</a>
            </dd>
          </div>
        ) : null}
        {contact.address ? (
          <div>
            <dt>Office</dt>
            <dd>{contact.address}</dd>
          </div>
        ) : null}
        {contact.hours ? (
          <div>
            <dt>Hours</dt>
            <dd>{contact.hours}</dd>
          </div>
        ) : null}
        {council.planning_url || council.website ? (
          <div>
            <dt>Website</dt>
            <dd>
              <a
                href={council.planning_url ?? council.website ?? undefined}
                rel="noopener noreferrer"
                target="_blank"
              >
                {council.planning_url ? "Development applications page" : "Council website"}
              </a>
            </dd>
          </div>
        ) : null}
        {council.planning_scheme?.name ? (
          <div>
            <dt>{schemeLabel}</dt>
            <dd>
              {council.planning_scheme.url ? (
                <a href={council.planning_scheme.url} rel="noopener noreferrer" target="_blank">
                  {council.planning_scheme.name}
                </a>
              ) : (
                council.planning_scheme.name
              )}
            </dd>
          </div>
        ) : null}
        {council.zoning_lookup_url ? (
          <div>
            <dt>Zone and overlays</dt>
            <dd>
              <a href={council.zoning_lookup_url} rel="noopener noreferrer" target="_blank">
                Look up your site on the state&apos;s planning map
              </a>
            </dd>
          </div>
        ) : null}
      </dl>

      <CouncilEnquiryEmail council={council} answers={answers} level={level === 2 ? 3 : 4} />

      {council.gaps.length > 0 ? (
        <details className="council-more">
          <summary>What we couldn&apos;t find</summary>
          <ul>
            {council.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <details className="council-more">
        <summary>Where this came from</summary>
        <ul>
          {council.sources.map((source) => (
            <li key={source.url}>
              <a href={source.url} rel="noopener noreferrer" target="_blank">
                {source.title}
              </a>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

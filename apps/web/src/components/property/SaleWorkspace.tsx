"use client";

import type {
  DocumentOut,
  EnquiryOut,
  OfferOut,
  OfferStatus,
  SaleDocumentOut,
  SaleOut,
  SaleStatus,
} from "@approvalready/shared-types";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatBytes } from "@/lib/documents";
import {
  DISCLOSURE_LABELS,
  ENQUIRY_STATUS_LABELS,
  OFFER_STATUS_LABELS,
  SALE_STATUS_ACTIONS,
  SALE_STATUS_LABELS,
  VAULT_CATEGORIES,
  money,
  vaultCategoryLabel,
} from "@/lib/property";
import { formatDate, parseDollars } from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  projectId: string;
  projectTitle: string;
  sale: SaleOut;
  vault: SaleDocumentOut[];
  offers: OfferOut[];
  enquiries: EnquiryOut[];
  projectDocuments: DocumentOut[];
  canWrite: boolean;
};

function text(form: FormData, name: string): string | null {
  return String(form.get(name) ?? "").trim() || null;
}

function dollars(form: FormData, name: string): number | null | "invalid" {
  const parsed = parseDollars(String(form.get(name) ?? ""));
  if ("error" in parsed) return "invalid";
  return typeof parsed.value === "number" ? parsed.value : null;
}

/** SellReady: the sale's status, disclosure and vault, offers and enquiries. */
export function SaleWorkspace({ organisationId, projectId, canWrite, ...props }: Props) {
  const [sale, setSale] = useState(props.sale);
  const [vault, setVault] = useState(props.vault);
  const [offers, setOffers] = useState(props.offers);
  const [enquiries, setEnquiries] = useState(props.enquiries);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const org = `/organisations/${organisationId}`;
  const base = `${org}/projects/${projectId}/sale`;

  async function run<T>(call: () => Promise<{ ok: true; data: T } | { ok: false; message: string }>) {
    setBusy(true);
    setError(null);
    const result = await call();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return undefined;
    }
    return result.data;
  }

  async function refreshSale() {
    const result = await apiRequest<SaleOut>("GET", base);
    if (result.ok) setSale(result.data);
  }

  async function moveTo(status: SaleStatus) {
    const updated = await run(() => apiRequest<SaleOut>("PATCH", base, { status }));
    if (updated) setSale(updated);
  }

  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const price = dollars(form, "asking_price");
    if (price === "invalid") {
      setError("Enter the asking price in dollars, for example 850000.");
      return;
    }
    const updated = await run(() =>
      apiRequest<SaleOut>("PATCH", base, {
        asking_price_cents: price,
        price_guide: text(form, "price_guide"),
        contract_on: text(form, "contract_on"),
        settlement_on: text(form, "settlement_on"),
        notes: text(form, "notes"),
      }),
    );
    if (updated) setSale(updated);
  }

  async function fileDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const created = await run(() =>
      apiRequest<SaleDocumentOut>("POST", `${base}/documents`, {
        uploaded_document_id: text(form, "document"),
        category: text(form, "category"),
        in_disclosure: form.get("in_disclosure") === "on",
      }),
    );
    if (created) {
      setVault((v) => [...v, created]);
      formElement.reset();
      await refreshSale();
    }
  }

  async function toggleDisclosure(record: SaleDocumentOut) {
    const updated = await run(() =>
      apiRequest<SaleDocumentOut>("PATCH", `${org}/sale-documents/${record.id}`, {
        in_disclosure: !record.in_disclosure,
      }),
    );
    if (updated) {
      setVault((v) => v.map((d) => (d.id === updated.id ? updated : d)));
      await refreshSale();
    }
  }

  async function removeDocument(record: SaleDocumentOut) {
    const removed = await run(() =>
      apiRequest<null>("DELETE", `${org}/sale-documents/${record.id}`),
    );
    if (removed !== undefined) {
      setVault((v) => v.filter((d) => d.id !== record.id));
      await refreshSale();
    }
  }

  async function giveDisclosure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const updated = await run(() =>
      apiRequest<SaleOut>("POST", `${base}/disclosure`, {
        given_on: text(form, "given_on"),
        given_to: text(form, "given_to"),
      }),
    );
    if (updated) setSale(updated);
  }

  async function notNeeded(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const updated = await run(() =>
      apiRequest<SaleOut>("POST", `${base}/disclosure/not-needed`, { note: text(form, "note") }),
    );
    if (updated) setSale(updated);
  }

  async function reopenDisclosure() {
    const updated = await run(() => apiRequest<SaleOut>("DELETE", `${base}/disclosure`));
    if (updated) setSale(updated);
  }

  async function addOffer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const amount = dollars(form, "amount");
    const deposit = dollars(form, "deposit");
    if (amount === "invalid" || amount === null || deposit === "invalid") {
      setError("Enter the amounts in dollars, for example 820000.");
      return;
    }
    const days = text(form, "settlement_days");
    const created = await run(() =>
      apiRequest<OfferOut>("POST", `${base}/offers`, {
        buyer_name: text(form, "buyer_name"),
        buyer_contact: text(form, "buyer_contact"),
        amount_cents: amount,
        deposit_cents: deposit,
        subject_to_finance: form.get("finance") === "on",
        subject_to_inspection: form.get("inspection") === "on",
        settlement_days: days ? Number(days) : null,
        conditions: text(form, "conditions"),
      }),
    );
    if (created) {
      setOffers((o) => [created, ...o]);
      formElement.reset();
      await refreshSale();
    }
  }

  async function setOfferStatus(offer: OfferOut, status: OfferStatus) {
    const updated = await run(() =>
      apiRequest<OfferOut>("PATCH", `${org}/sale-offers/${offer.id}`, { status }),
    );
    if (updated) {
      setOffers((o) => o.map((x) => (x.id === updated.id ? updated : x)));
      await refreshSale();
    }
  }

  async function addEnquiry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const created = await run(() =>
      apiRequest<EnquiryOut>("POST", `${base}/enquiries`, {
        name: text(form, "name"),
        contact: text(form, "contact"),
        channel: text(form, "channel"),
        message: text(form, "message"),
      }),
    );
    if (created) {
      setEnquiries((e) => [created, ...e]);
      formElement.reset();
    }
  }

  async function setEnquiryStatus(enquiry: EnquiryOut, status: string) {
    const updated = await run(() =>
      apiRequest<EnquiryOut>("PATCH", `${org}/sale-enquiries/${enquiry.id}`, { status }),
    );
    if (updated) setEnquiries((e) => e.map((x) => (x.id === updated.id ? updated : x)));
  }

  const filed = new Set(vault.map((d) => d.uploaded_document_id));
  const unfiled = props.projectDocuments.filter((d) => !filed.has(d.id));
  const disclosure = sale.disclosure;
  const given = disclosure.state === "GIVEN";
  const closed = disclosure.state === "GIVEN" || disclosure.state === "NOT_NEEDED";

  return (
    <div className="workspace">
      <section className="page-head" aria-labelledby="sale-title">
        <div>
          <h1 id="sale-title" className="page-title">
            Your sale
          </h1>
          <p className="muted">
            {props.projectTitle} ·{" "}
            <span className="status">{SALE_STATUS_LABELS[sale.status]}</span>
            {sale.asking_price_cents ? ` · Asking ${money(sale.asking_price_cents)}` : ""}
          </p>
        </div>
      </section>
      <FormError message={error} />

      <section className="panel" aria-labelledby="status-title">
        <h2 id="status-title" className="section-title">
          Where the sale is up to
        </h2>
        <ol className="steps" aria-label="Sale stages">
          {(["PREPARING", "LISTED", "UNDER_OFFER", "UNDER_CONTRACT", "SETTLED"] as const).map(
            (s) => (
              <li key={s} aria-current={sale.status === s ? "step" : undefined}>
                {SALE_STATUS_LABELS[s]}
              </li>
            ),
          )}
        </ol>
        {canWrite && sale.next_statuses.length > 0 ? (
          <div className="button-row tight">
            {sale.next_statuses.map((s) => (
              <button
                key={s}
                type="button"
                className={s === "WITHDRAWN" ? "button-link" : "button button-secondary"}
                disabled={busy}
                onClick={() => moveTo(s)}
              >
                {SALE_STATUS_ACTIONS[s]}
              </button>
            ))}
          </div>
        ) : null}
        {sale.status === "UNDER_CONTRACT" && sale.settlement_on ? (
          <p className="hint">
            Settlement {formatDate(sale.settlement_on)}. We&apos;ll remind you 14 days and 2 days
            before.
          </p>
        ) : null}
        {canWrite ? (
          <form className="form" onSubmit={saveDetails} aria-label="Sale details">
            <div className="field-row">
              <label>
                Asking price (optional)
                <input
                  name="asking_price"
                  inputMode="decimal"
                  defaultValue={sale.asking_price_cents ? String(sale.asking_price_cents / 100) : ""}
                />
              </label>
              <label>
                Price guide or method (optional)
                <input name="price_guide" maxLength={200} defaultValue={sale.price_guide ?? ""} />
              </label>
            </div>
            <div className="field-row">
              <label>
                Contract date
                <input name="contract_on" type="date" defaultValue={sale.contract_on ?? ""} />
              </label>
              <label>
                Settlement date
                <input name="settlement_on" type="date" defaultValue={sale.settlement_on ?? ""} />
              </label>
            </div>
            <label>
              Notes (optional)
              <textarea name="notes" maxLength={2000} defaultValue={sale.notes ?? ""} />
            </label>
            <button type="submit" className="button button-secondary" disabled={busy}>
              Save details
            </button>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="disclosure-title">
        <h2 id="disclosure-title" className="section-title">
          Disclosure to buyers
        </h2>
        <p className="muted">
          Your assessment and checklists say what your state asks a seller to give buyers. Mark
          those documents in the vault below, then record when you gave them to the buyer.
        </p>
        <p>
          <span className="status">{DISCLOSURE_LABELS[disclosure.state]}</span>{" "}
          {disclosure.document_ids.length} document
          {disclosure.document_ids.length === 1 ? "" : "s"} marked
        </p>
        {given ? (
          <p>
            Given to {disclosure.given_to} on {formatDate(disclosure.given_on ?? "")}.
          </p>
        ) : null}
        {disclosure.state === "NOT_NEEDED" ? <p>Not needed: {disclosure.not_needed_note}</p> : null}
        {disclosure.changed_since_given ? (
          <p className="notice">
            The documents marked for disclosure changed after it was given. Check with your
            conveyancer or solicitor whether the buyer needs the new set.
          </p>
        ) : null}
        {canWrite && !closed ? (
          <>
            <form className="form inline-form" onSubmit={giveDisclosure} aria-label="Record the disclosure">
              <label>
                Given to
                <input name="given_to" required maxLength={200} />
              </label>
              <label>
                On
                <input name="given_on" type="date" required />
              </label>
              <button type="submit" className="button" disabled={busy}>
                Record as given
              </button>
            </form>
            <details>
              <summary>No disclosure needed?</summary>
              <form className="form" onSubmit={notNeeded} aria-label="No disclosure needed">
                <label>
                  Why not (for example, what your assessment or conveyancer said)
                  <textarea name="note" required minLength={10} maxLength={1000} />
                </label>
                <button type="submit" className="button button-secondary" disabled={busy}>
                  Record why
                </button>
              </form>
            </details>
          </>
        ) : null}
        {canWrite && closed && !["UNDER_CONTRACT", "SETTLED"].includes(sale.status) ? (
          <button type="button" className="button-link" disabled={busy} onClick={reopenDisclosure}>
            Reopen the disclosure
          </button>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="vault-title">
        <h2 id="vault-title" className="section-title">
          Document vault
        </h2>
        <p className="muted">
          File the project&apos;s documents for the sale. Upload new files on the{" "}
          <Link href={`/projects/${projectId}`}>project page</Link> first.
        </p>
        {vault.length === 0 ? <p className="muted">No documents filed yet.</p> : null}
        <ul className="task-list">
          {vault.map((d) => (
            <li key={d.id} className="task">
              <span>
                <strong>{vaultCategoryLabel(d.category)}</strong> · {d.filename}{" "}
                <span className="muted">{formatBytes(d.size_bytes)}</span>
                {d.scan_status !== "CLEAN" ? (
                  <span className="badge">{d.scan_status === "PENDING" ? "Checking" : "Blocked"}</span>
                ) : null}
                {d.in_disclosure ? <span className="badge">In disclosure</span> : null}
              </span>
              {canWrite ? (
                <span className="button-row tight">
                  <button
                    type="button"
                    className="button-link"
                    disabled={busy || given}
                    onClick={() => toggleDisclosure(d)}
                  >
                    {d.in_disclosure ? "Take out of disclosure" : "Add to disclosure"}
                  </button>
                  <button
                    type="button"
                    className="button-link"
                    disabled={busy || (given && d.in_disclosure)}
                    onClick={() => removeDocument(d)}
                    aria-label={`Remove ${d.filename} from the vault`}
                  >
                    Remove
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        {canWrite && unfiled.length > 0 ? (
          <form className="form inline-form" onSubmit={fileDocument} aria-label="File a document">
            <label>
              Document
              <select name="document" required>
                {unfiled.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            </label>
            <label>
              What it is
              <select name="category" required defaultValue="OTHER">
                {VAULT_CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {!given ? (
              <label className="option">
                <input type="checkbox" name="in_disclosure" /> Part of the disclosure
              </label>
            ) : null}
            <button type="submit" className="button button-secondary" disabled={busy}>
              File it
            </button>
          </form>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="offers-title">
        <h2 id="offers-title" className="section-title">
          Offers
        </h2>
        {offers.length === 0 ? <p className="muted">No offers recorded.</p> : null}
        <ul className="task-list">
          {offers.map((o) => (
            <li key={o.id} className="task">
              <span>
                <strong>{money(o.amount_cents)}</strong> from {o.buyer_name}
                <span className="muted">
                  {" "}
                  · {formatDate(o.received_on)}
                  {o.subject_to_finance ? " · subject to finance" : ""}
                  {o.subject_to_inspection ? " · subject to inspection" : ""}
                  {o.settlement_days !== null ? ` · ${o.settlement_days}-day settlement` : ""}
                </span>
                {o.conditions ? <span className="muted"> · {o.conditions}</span> : null}
              </span>
              {canWrite ? (
                <label>
                  <span className="visually-hidden">Status of the offer from {o.buyer_name}</span>
                  <select
                    value={o.status}
                    disabled={busy}
                    onChange={(e) => setOfferStatus(o, e.target.value as OfferStatus)}
                  >
                    {Object.entries(OFFER_STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="status">{OFFER_STATUS_LABELS[o.status]}</span>
              )}
            </li>
          ))}
        </ul>
        {canWrite && !["SETTLED", "WITHDRAWN"].includes(sale.status) ? (
          <details>
            <summary>Record an offer</summary>
            <form className="form" onSubmit={addOffer} aria-label="Record an offer">
              <div className="field-row">
                <label>
                  Buyer
                  <input name="buyer_name" required maxLength={200} />
                </label>
                <label>
                  Buyer&apos;s phone or email (optional)
                  <input name="buyer_contact" maxLength={200} />
                </label>
              </div>
              <div className="field-row">
                <label>
                  Amount
                  <input name="amount" required inputMode="decimal" />
                </label>
                <label>
                  Deposit (optional)
                  <input name="deposit" inputMode="decimal" />
                </label>
                <label>
                  Settlement days (optional)
                  <input name="settlement_days" type="number" min={0} max={730} />
                </label>
              </div>
              <label className="option">
                <input type="checkbox" name="finance" /> Subject to finance
              </label>
              <label className="option">
                <input type="checkbox" name="inspection" /> Subject to building and pest inspection
              </label>
              <label>
                Other conditions (optional)
                <textarea name="conditions" maxLength={2000} />
              </label>
              <button type="submit" className="button button-secondary" disabled={busy}>
                Save offer
              </button>
            </form>
          </details>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="enquiries-title">
        <h2 id="enquiries-title" className="section-title">
          Enquiries
        </h2>
        {enquiries.length === 0 ? <p className="muted">No enquiries recorded.</p> : null}
        <ul className="task-list">
          {enquiries.map((e) => (
            <li key={e.id} className="task">
              <span>
                <strong>{e.name}</strong>
                <span className="muted">
                  {" "}
                  · {formatDate(e.received_on)}
                  {e.channel ? ` · ${e.channel}` : ""}
                  {e.contact ? ` · ${e.contact}` : ""}
                </span>
                {e.message ? <span className="muted"> · {e.message}</span> : null}
              </span>
              {canWrite ? (
                <label>
                  <span className="visually-hidden">Status of the enquiry from {e.name}</span>
                  <select
                    value={e.status}
                    disabled={busy}
                    onChange={(ev) => setEnquiryStatus(e, ev.target.value)}
                  >
                    {Object.entries(ENQUIRY_STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="status">{ENQUIRY_STATUS_LABELS[e.status]}</span>
              )}
            </li>
          ))}
        </ul>
        {canWrite ? (
          <details>
            <summary>Record an enquiry</summary>
            <form className="form" onSubmit={addEnquiry} aria-label="Record an enquiry">
              <div className="field-row">
                <label>
                  Name
                  <input name="name" required maxLength={200} />
                </label>
                <label>
                  Phone or email (optional)
                  <input name="contact" maxLength={200} />
                </label>
                <label>
                  Where from (optional)
                  <input name="channel" maxLength={60} placeholder="Open home, website…" />
                </label>
              </div>
              <label>
                What they asked (optional)
                <textarea name="message" maxLength={2000} />
              </label>
              <button type="submit" className="button button-secondary" disabled={busy}>
                Save enquiry
              </button>
            </form>
          </details>
        ) : null}
      </section>
    </div>
  );
}

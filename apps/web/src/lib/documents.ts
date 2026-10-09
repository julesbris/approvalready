/** Uploaded and generated documents: labels, sizes, URLs and waiting for background work. */

import type {
  DocumentOut,
  GeneratedDocumentOut,
  OutputFormat,
  ScanStatus,
} from "@approvalready/shared-types";

import { apiRequest, apiUpload, type ApiResult } from "@/lib/client-api";

export const SCAN_LABELS: Record<ScanStatus, string> = {
  PENDING: "Checking for viruses",
  CLEAN: "Ready",
  INFECTED: "Blocked: failed the virus check",
  ERROR: "Couldn't be checked. Upload it again",
};

export const FORMAT_LABELS: Record<OutputFormat, string> = {
  PDF: "PDF",
  DOCX: "Word",
  HTML: "Web page (HTML)",
};

/** File types the API accepts (it checks each file's contents, not just its name). */
export const ACCEPT = ".pdf,.docx,.xlsx,.csv,.txt,.jpg,.jpeg,.png,.webp,.heic,.heif";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function documentUrl(organisationId: string, documentId: string): string {
  return `/api/v1/organisations/${organisationId}/documents/${documentId}/content`;
}

export function generatedUrl(organisationId: string, generatedId: string): string {
  return `/api/v1/organisations/${organisationId}/generated-documents/${generatedId}/content`;
}

export function uploadDocument(
  organisationId: string,
  projectId: string,
  file: File,
): Promise<ApiResult<DocumentOut>> {
  return apiUpload<DocumentOut>(
    `/organisations/${organisationId}/projects/${projectId}/documents`,
    file,
  );
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Re-fetch until `done` says the background work has finished, or give up after `attempts`
 * tries (the caller then shows the last state, which the user can refresh later).
 */
export async function waitUntil<T>(
  fetchOnce: () => Promise<ApiResult<T>>,
  done: (value: T) => boolean,
  { attempts = 30, intervalMs = 2000 }: { attempts?: number; intervalMs?: number } = {},
): Promise<ApiResult<T>> {
  let result = await fetchOnce();
  for (let i = 1; i < attempts && result.ok && !done(result.data); i++) {
    await sleep(intervalMs);
    result = await fetchOnce();
  }
  return result;
}

export function waitForScan(organisationId: string, doc: DocumentOut, intervalMs?: number) {
  return waitUntil(
    () => apiRequest<DocumentOut>("GET", `/organisations/${organisationId}/documents/${doc.id}`),
    (d) => d.scan_status !== "PENDING",
    { intervalMs },
  );
}

export function waitForReport(
  organisationId: string,
  generated: GeneratedDocumentOut,
  intervalMs?: number,
) {
  return waitUntil(
    () =>
      apiRequest<GeneratedDocumentOut>(
        "GET",
        `/organisations/${organisationId}/generated-documents/${generated.id}`,
      ),
    (g) => g.status !== "PENDING",
    { intervalMs },
  );
}

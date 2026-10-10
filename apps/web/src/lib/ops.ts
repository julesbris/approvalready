import type { BackupRunOut, CheckState } from "@approvalready/shared-types";

export const CHECK_STATE_LABELS: Record<CheckState, string> = {
  OK: "OK",
  WARNING: "Check",
  FAILING: "Needs attention",
};

const OFFSITE_LABELS: Record<string, string> = {
  PENDING: "Not copied yet",
  UPLOADED: "Copied",
  FAILED: "Copy failed",
  MISSING: "Removed before it was copied",
};

/** Bytes as KB, MB or GB (decimal units, like the disk check). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "–";
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(2)} GB`;
}

/** Where a backup's copy is, in words. */
export function offsiteLabel(run: BackupRunOut, offsiteEnabled: boolean): string {
  if (run.kind !== "BACKUP" || run.status !== "OK") return "–";
  if (run.offsite_status === "UPLOADED") return "Copied";
  if (!offsiteEnabled) return "On this server only";
  return OFFSITE_LABELS[run.offsite_status ?? "PENDING"] ?? run.offsite_status ?? "–";
}

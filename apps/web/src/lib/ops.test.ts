import type { BackupRunOut } from "@approvalready/shared-types";

import { formatBytes, offsiteLabel } from "./ops";

const run: BackupRunOut = {
  id: "r1",
  kind: "BACKUP",
  status: "OK",
  started_at: "2026-10-10T02:30:00Z",
  finished_at: "2026-10-10T02:31:00Z",
  database_file: "db-20261010T023000Z.dump",
  database_bytes: 490_458,
  uploads_file: "uploads-20261010T023000Z.tgz",
  uploads_bytes: 157,
  detail: null,
  offsite_status: "PENDING",
  offsite_at: null,
  offsite_error: null,
};

describe("ops helpers", () => {
  it("formats sizes", () => {
    expect(formatBytes(null)).toBe("–");
    expect(formatBytes(157)).toBe("157 B");
    expect(formatBytes(490_458)).toBe("490.5 KB");
    expect(formatBytes(12_300_000)).toBe("12.3 MB");
    expect(formatBytes(4_500_000_000)).toBe("4.50 GB");
  });

  it("says where a backup's copy is", () => {
    expect(offsiteLabel(run, false)).toBe("On this server only");
    expect(offsiteLabel(run, true)).toBe("Not copied yet");
    expect(offsiteLabel({ ...run, offsite_status: "UPLOADED" }, true)).toBe("Copied");
    expect(offsiteLabel({ ...run, offsite_status: "FAILED" }, true)).toBe("Copy failed");
    expect(offsiteLabel({ ...run, kind: "RESTORE_CHECK", offsite_status: null }, true)).toBe("–");
    expect(offsiteLabel({ ...run, status: "FAILED" }, true)).toBe("–");
  });
});

import { safeNext } from "./redirect";

describe("safeNext", () => {
  it.each([
    ["/account", "/account"],
    ["/invitations/accept?token=x", "/invitations/accept?token=x"],
    ["//evil.example", "/account"],
    ["https://evil.example", "/account"],
    ["/\\evil.example", "/account"],
    [undefined, "/account"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

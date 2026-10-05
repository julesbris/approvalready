import { errorFrom, readCsrfToken } from "./client-api";

describe("readCsrfToken", () => {
  it("reads the secure cookie name", () => {
    expect(readCsrfToken("a=1; __Host-ar_csrf=tok%3D; b=2")).toBe("tok=");
  });
  it("reads the development cookie name", () => {
    expect(readCsrfToken("ar_csrf=dev")).toBe("dev");
  });
  it("ignores look-alike names", () => {
    expect(readCsrfToken("x_ar_csrf=nope")).toBeUndefined();
  });
});

describe("errorFrom", () => {
  it("uses the API's code and message", () => {
    expect(
      errorFrom(401, { detail: { code: "invalid_credentials", message: "Wrong." } }),
    ).toEqual({ code: "invalid_credentials", message: "Wrong." });
  });
  it("summarises validation errors", () => {
    expect(errorFrom(422, { detail: [{ msg: "Value error, Enter a valid ABN", loc: [] }] })).toEqual(
      { code: "invalid", message: "Enter a valid ABN" },
    );
  });
  it("falls back on rate limiting and unknown errors", () => {
    expect(errorFrom(429, null).code).toBe("rate_limited");
    expect(errorFrom(500, "boom").code).toBe("error");
  });
});

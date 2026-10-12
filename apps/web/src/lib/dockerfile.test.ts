import { readFileSync } from "node:fs";
import path from "node:path";

// The standalone build leaves out public/; without this copy the live site has no logo.
describe("web Dockerfile", () => {
  it("copies public/ into the runtime image", () => {
    const dockerfile = readFileSync(path.join(__dirname, "..", "..", "Dockerfile"), "utf8");
    expect(dockerfile).toMatch(
      /COPY --from=build .*\/repo\/apps\/web\/public \.\/apps\/web\/public/,
    );
  });

  it("copies the API's guides into the build for the public guide pages", () => {
    const dockerfile = readFileSync(path.join(__dirname, "..", "..", "Dockerfile"), "utf8");
    expect(dockerfile).toContain(
      "COPY apps/api/app/modules/guidance/*.json ./apps/api/app/modules/guidance/",
    );
  });
});

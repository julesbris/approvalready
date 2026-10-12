import { readFileSync } from "node:fs";
import path from "node:path";

// A rule left open (easy to do when two branches touch the end of the file) silently nests
// every rule after it, so none of them apply on the live site.
describe("globals.css", () => {
  it("closes every rule it opens", () => {
    const css = readFileSync(path.join(__dirname, "..", "app", "globals.css"), "utf8").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    let depth = 0;
    for (const ch of css) {
      if (ch === "{") depth += 1;
      if (ch === "}") depth -= 1;
      expect(depth).toBeGreaterThanOrEqual(0);
    }
    expect(depth).toBe(0);
  });
});

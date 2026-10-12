import { statesPhrase, stateGovernment } from "./coverage";

describe("coverage", () => {
  it("names the states we look up", () => {
    expect(statesPhrase(["Queensland"])).toBe("Queensland");
    expect(statesPhrase(["Queensland", "New South Wales"])).toBe("Queensland and New South Wales");
    expect(statesPhrase(["Queensland", "New South Wales", "Victoria"])).toBe(
      "Queensland, New South Wales and Victoria",
    );
    expect(stateGovernment("NSW")).toBe("the New South Wales Government");
    expect(stateGovernment("ACT")).toBe("the ACT Government");
  });
});

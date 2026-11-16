import { describe, expect, it } from "vitest";
import { formatStat } from "../format";
import { correlationStrength } from "../profile";

describe("formatStat", () => {
  it.each([
    [1234.5, "1,235"],
    [170.5, "171"],
    [12.345, "12.35"],
    [0.01234, "0.0123"],
    [2_500_000, "2.5M"],
    [-430.04, "-430"],
    [0, "0"],
  ])("%s → %s", (n, text) => {
    expect(formatStat(n)).toBe(text);
  });

  it("shows a dash for missing or non-finite values", () => {
    expect(formatStat(null)).toBe("–");
    expect(formatStat(undefined)).toBe("–");
    expect(formatStat(Number.NaN)).toBe("–");
  });
});

describe("correlationStrength", () => {
  it.each([
    [0.85, "strong positive"],
    [-0.5, "moderate negative"],
    [0.25, "weak positive"],
    [0.05, "no clear link"],
    [null, "not defined"],
  ])("%s → %s", (r, words) => {
    expect(correlationStrength(r)).toBe(words);
  });
});

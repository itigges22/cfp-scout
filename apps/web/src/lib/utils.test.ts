/**
 * The formatters every page renders through.
 *
 * `formatDate` exists because three routes each wrote
 * `new Date(x).toLocaleDateString()` inline, so a null timestamp rendered as
 * "Invalid Date" on one page and threw on another. The null and garbage
 * cases are the whole reason it was extracted, so they are what gets pinned.
 */

import { describe, expect, it } from "vitest";

import { cn, formatDate } from "./utils";

describe("formatDate", () => {
  it("renders an em dash for a missing value rather than 'Invalid Date'", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("renders an em dash for an unparseable value instead of throwing", () => {
    expect(formatDate("not-a-date")).toBe("—");
  });

  it("formats a real ISO timestamp", () => {
    const out = formatDate("2027-03-14T10:00:00Z");
    expect(out).not.toBe("—");
    expect(out).toMatch(/\d/);
  });

  it("accepts a bare date with no time component", () => {
    expect(formatDate("2027-03-14")).not.toBe("—");
  });
});

describe("cn", () => {
  it("merges conflicting tailwind classes last-wins", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("drops falsy entries so conditional classes are safe", () => {
    const off = "" as string;
    expect(cn("a", off && "b", undefined, "c")).toBe("a c");
  });
});

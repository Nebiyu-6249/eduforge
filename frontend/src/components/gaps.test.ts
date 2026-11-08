import { describe, expect, it } from "vitest";
import { gapText } from "./gaps";

// The three notes a teacher saw as raw data on Quiz #1, Version A.
describe("gapText", () => {
  it("says a type shortfall in a sentence", () => {
    const t = gapText({ type: "short_answer", count: 3, weeks: [1, 2, 3, 4],
      reason: "not enough approved, unused, non-duplicate items", clo_numbers: [1, 3] });
    expect(t).toBe("3 short-answer questions could not be added. The question bank has no more approved ones " +
      "for outcomes 1 and 3 in weeks 1 to 4 that are not already in this paper or too similar to one that is.");
  });

  it("uses the singular for one question", () => {
    expect(gapText({ type: "mcq", count: 1, weeks: [2], clo_numbers: [1], reason: "x" }))
      .toMatch(/^1 multiple-choice question could not be added.*for outcome 1 in week 2 /);
  });

  it("says an under-covered outcome, old and new wording", () => {
    expect(gapText({ type: null, count: 5, weeks: [1, 2, 3, 4], clo_numbers: [3],
      reason: "CLO 3 is under-covered (0 of ~5 items)" }))
      .toBe("Outcome 3 has no questions in this paper; about 5 would match how much of the course it covers.");
    expect(gapText({ type: null, count: 2, clo_numbers: [2],
      reason: "Outcome 2 is under-covered (1 of about 3 questions)" }))
      .toMatch(/^Outcome 2 has 1 question in this paper; about 3/);
  });

  it("passes ready sentences through and never shows raw data", () => {
    expect(gapText({ warning: "You asked for 3 and got 2." })).toBe("You asked for 3 and got 2.");
    expect(gapText({ type: "case_study", count: 2, reason: "?" })).not.toMatch(/[{}"]/);
  });
});

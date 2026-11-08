// Regression test for round 3, section 3: the quiz flow's Back button always
// works, browser Back and Forward move between steps, and a refresh keeps the
// place, because the step and every choice live in the address.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { QuizOptions } from "../types";
import QuizFlow from "./QuizFlow";

const options: QuizOptions = {
  can_create: true,
  course: "STAT 100",
  term: "Fall 2026",
  choices: [
    { name: "Quiz 1", week: 4, weight_pct: 5, subtitle: "5% · week 4", weeks: [1, 2, 3], clo_numbers: [1] },
    { name: "Quiz 2", week: 11, weight_pct: 5, subtitle: "5% · week 11", weeks: [9, 10, 11], clo_numbers: [1, 4] },
  ],
  weeks: Array.from({ length: 12 }, (_, i) => ({ week_no: i + 1, topics: [`Topic ${i + 1}`] })),
  outcomes: [1, 2, 3, 4].map((n) => ({ number: n, text: `Outcome text ${n}`, skills: false })),
  slides: [],
  types: [
    { type: "mcq", label: "Multiple choice", points: 2, minutes: 2 },
    { type: "short_answer", label: "Short answer", points: 5, minutes: 6 },
  ],
  max_questions: 20,
};

vi.mock("../api", () => ({
  api: {
    quizOptions: vi.fn(() => Promise.resolve(options)),
    createQuiz: vi.fn(() => Promise.resolve({ id: 1, link: "/v/1/quiz/7" })),
  },
  ApiError: class extends Error {},
}));

function setup(entry: string) {
  const router = createMemoryRouter(
    [
      { path: "/v/:id/quiz", element: <h1>Quizzes and exams list</h1> },
      { path: "/v/:id/quiz/new", element: <QuizFlow /> },
      { path: "/v/:id/quiz/:formId", element: <h1>The quiz page</h1> },
    ],
    { initialEntries: [entry] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

const heading = (name: string) => screen.findByRole("heading", { level: 2, name });
const step = (router: ReturnType<typeof setup>) => new URLSearchParams(router.state.location.search).get("step");

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(cleanup);

describe("Create a quiz or exam", () => {
  it("Back on step 1 is never disabled and returns to the quizzes and exams list", async () => {
    const router = setup("/v/1/quiz/new");
    await heading("What are you making?");
    const back = screen.getByRole("button", { name: /Back to quizzes and exams/ });
    expect((back as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(back);
    expect(await screen.findByText("Quizzes and exams list")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/v/1/quiz");
  });

  it("Continue explains why it can't go on yet instead of looking disabled", async () => {
    const router = setup("/v/1/quiz/new");
    await heading("What are you making?");
    const cont = screen.getByRole("button", { name: /Continue/ });
    expect((cont as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(cont);
    expect(await screen.findByText(/Pick what you are making first/)).toBeTruthy();
    expect(step(router)).toBeNull();  // still on step 1
  });

  it("browser Back and Forward move between steps and keep the choices", async () => {
    const router = setup("/v/1/quiz/new");
    await heading("What are you making?");
    fireEvent.click(screen.getByRole("button", { name: /Quiz 2/ }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await heading("What should it cover?");
    expect(step(router)).toBe("2");
    expect(router.state.location.search).toContain("for=Quiz+2");
    expect(router.state.location.search).toContain("weeks=9-11");

    await act(() => router.navigate(-1));
    await heading("What are you making?");
    expect(screen.getByRole("button", { name: /Quiz 2/ }).getAttribute("aria-pressed")).toBe("true");

    await act(() => router.navigate(1));
    await heading("What should it cover?");
  });

  it("a refresh on step 3 keeps the place and every choice", async () => {
    setup("/v/1/quiz/new?step=3&for=Quiz%202&weeks=9-11&outcomes=1,4&mix=mcq:3,short_answer:2");
    await heading("How many of each type?");
    const total = screen.getByRole("status");
    expect(total.textContent).toContain("5questions");
    expect(total.textContent).toContain("16points");  // 3 x 2 + 2 x 5
  });

  it("Create makes the quiz and opens its page, which keeps working if the teacher leaves", async () => {
    const router = setup("/v/1/quiz/new?step=4&for=Quiz%202&weeks=9-11&outcomes=1,4&mix=mcq:3");
    await heading("Write the questions");
    expect(screen.getByText(/You can leave this page/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Create 3 questions/ }));
    expect(await screen.findByText("The quiz page")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/v/1/quiz/7");
  });
});

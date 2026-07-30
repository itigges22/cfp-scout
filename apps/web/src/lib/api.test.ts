/**
 * The API client's error surface.
 *
 * `fieldErrors()` is what every form uses to put a server-side validation
 * message next to the right input. If it drops the "body" prefix wrongly, or
 * silently returns {} for a real 422, the user sees a form that refuses to
 * submit with no explanation next to any field — which is indistinguishable
 * from a broken button.
 */

import { describe, expect, it } from "vitest";

import { ApiError } from "./api";

function problem(errors: { loc: string[]; msg: string; type?: string }[]) {
  return {
    type: "https://scout.example/errors/validation",
    title: "Invalid request body",
    status: 422,
    detail: "One or more fields failed validation.",
    errors: errors.map((e) => ({ type: e.type ?? "value_error", ...e })),
  } as ConstructorParameters<typeof ApiError>[0];
}

describe("ApiError", () => {
  it("uses detail as the message, falling back to title", () => {
    expect(new ApiError(problem([])).message).toBe(
      "One or more fields failed validation.",
    );
    const noDetail = { ...problem([]), detail: "" };
    expect(new ApiError(noDetail).message).toBe("Invalid request body");
  });

  it("exposes the status so callers can branch on 404 vs 422", () => {
    expect(new ApiError(problem([])).status).toBe(422);
  });

  it("strips the 'body' prefix Pydantic adds, so forms can key by field", () => {
    const err = new ApiError(
      problem([{ loc: ["body", "name"], msg: "Field required" }]),
    );
    expect(err.fieldErrors()).toEqual({ name: "Field required" });
  });

  it("joins nested locations with a dot", () => {
    const err = new ApiError(
      problem([{ loc: ["body", "cfp", "close_at"], msg: "bad date" }]),
    );
    expect(err.fieldErrors()).toEqual({ "cfp.close_at": "bad date" });
  });

  it("keeps query-parameter errors rather than dropping them", () => {
    // per_page over the cap arrives as loc ["query", "per_page"] — a real
    // response from the server, and one a user can act on.
    const err = new ApiError(
      problem([
        { loc: ["query", "per_page"], msg: "Input should be less than or equal to 200" },
      ]),
    );
    expect(err.fieldErrors()).toEqual({
      "query.per_page": "Input should be less than or equal to 200",
    });
  });

  it("returns an empty map when there are no field errors at all", () => {
    const err = new ApiError({
      type: "about:blank",
      title: "Not Found",
      status: 404,
      detail: "No conference",
    } as ConstructorParameters<typeof ApiError>[0]);
    expect(err.fieldErrors()).toEqual({});
  });

  it("ignores an error whose loc is only 'body' — there is no field to blame", () => {
    const err = new ApiError(problem([{ loc: ["body"], msg: "malformed" }]));
    expect(err.fieldErrors()).toEqual({});
  });

  it("is a real Error, so existing catch blocks still work", () => {
    const err = new ApiError(problem([]));
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
  });
});

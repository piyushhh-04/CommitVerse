import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppErrorBoundary } from "./AppErrorBoundary";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AppErrorBoundary", () => {
  it("shows a clear recovery action when a page throws during rendering", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenPage(): never {
      throw new Error("Render failed");
    }

    render(
      <AppErrorBoundary>
        <BrokenPage />
      </AppErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("We could not render this page.");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  });
});

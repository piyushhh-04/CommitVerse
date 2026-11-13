import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("CommitVerse landing page", () => {
  it("presents all nine sections and labels its technical visual as illustrative", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /Version control,.*with room to grow\./,
    );
    expect(document.querySelectorAll("main > section")).toHaveLength(9);
    for (const section of document.querySelectorAll<HTMLElement>(
      "main > section[aria-labelledby]",
    )) {
      expect(document.getElementById(section.getAttribute("aria-labelledby") ?? "")).not.toBeNull();
    }
    expect(document.querySelector(".diagram-label")).toHaveTextContent(
      /Static architecture sketch.*not live data/,
    );
    expect(
      screen.getByText(/no sign-in, repository dashboard, live repository data, or API calls/i),
    ).toBeInTheDocument();
  });

  it("cycles the theme and persists the selected preference", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem("commitverse-theme")).toBe("dark");
  });

  it("closes the mobile navigation after selecting a destination or pressing Escape", async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole("button", { name: "Open navigation menu" });
    await user.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");

    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    await user.click(within(navigation).getByRole("link", { name: "Hub" }));
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();
  });
});

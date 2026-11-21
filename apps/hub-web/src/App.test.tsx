import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("CommitVerse landing page", () => {
  it("presents the product scope and labels its technical diagram as illustrative", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /Version control,.*built from the objects up\./,
    );
    expect(document.querySelectorAll("main > section")).toHaveLength(5);
    for (const section of document.querySelectorAll<HTMLElement>(
      "main > section[aria-labelledby]",
    )) {
      expect(document.getElementById(section.getAttribute("aria-labelledby") ?? "")).not.toBeNull();
    }
    expect(
      screen.getByRole("img", { name: /Illustrative CommitVerse object and commit graph/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Hub adds account management/)).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(within(navigation).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(within(navigation).getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByText(/Browse authorized trees/)).toBeInTheDocument();
    expect(document.title).toBe("Overview — CommitVerse");
  });

  it("selects and persists an explicit theme preference", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("radio", { name: "Switch to dark theme" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem("commitverse-theme")).toBe("dark");

    await user.click(screen.getByRole("radio", { name: "Switch to light theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");

    await user.click(screen.getByRole("radio", { name: "Switch to system theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme-mode", "system");
    expect(window.localStorage.getItem("commitverse-theme")).toBe("system");
  });

  it("updates the document title and focuses the new public route", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/");
    render(<App />);

    await user.click(
      within(screen.getByRole("navigation", { name: "Primary navigation" })).getByRole("link", {
        name: "Sign in",
      }),
    );
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(document.title).toBe("Sign in — CommitVerse");
    expect(document.querySelector("main")).toHaveFocus();
    await user.click(screen.getByRole("link", { name: "Return to the public overview" }));
  });

  it("traps focus in the mobile navigation and returns focus on Escape", async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole("button", { name: "Open navigation menu" });
    const previousOverflow = document.body.style.overflow;
    await user.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(document.body.style.overflow).toBe("hidden");

    const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
    const firstLink = within(navigation).getByRole("link", { name: "Product" });
    expect(firstLink).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(navigation).getByRole("link", { name: "Create account" })).toHaveFocus();

    await user.click(firstLink);
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(menuButton).toHaveFocus();
    expect(document.body.style.overflow).toBe(previousOverflow);

    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: "Open navigation menu" })).toHaveFocus();
    expect(document.body.style.overflow).toBe(previousOverflow);
  });
});

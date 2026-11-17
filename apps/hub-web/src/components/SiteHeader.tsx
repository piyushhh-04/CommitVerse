import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ThemeToggle } from "../theme/ThemeProvider";

const navigation = [
  { href: "#core", label: "Core" },
  { href: "#hub", label: "Hub" },
  { href: "#architecture", label: "Architecture" },
  { href: "#roadmap", label: "Roadmap" },
];

export function SiteHeader() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isMenuOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isMenuOpen]);

  return (
    <header className="site-header">
      <div className="header-inner section-shell">
        <a className="brand" href="#top" aria-label="CommitVerse home">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>CommitVerse</span>
        </a>
        <nav
          className={`site-nav${isMenuOpen ? " is-open" : ""}`}
          id="site-navigation"
          aria-label="Primary navigation"
        >
          {navigation.map((item) => (
            <a key={item.href} href={item.href} onClick={() => setIsMenuOpen(false)}>
              {item.label}
            </a>
          ))}
          <Link to="/login" onClick={() => setIsMenuOpen(false)}>
            Sign in
          </Link>
          <Link className="nav-cta" to="/register" onClick={() => setIsMenuOpen(false)}>
            Create account
          </Link>
        </nav>
        <div className="header-actions">
          <ThemeToggle />
          <button
            ref={menuButtonRef}
            className="menu-toggle"
            type="button"
            aria-label={isMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={isMenuOpen}
            aria-controls="site-navigation"
            onClick={() => setIsMenuOpen((open) => !open)}
          >
            <span />
            <span />
          </button>
        </div>
      </div>
    </header>
  );
}

import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMobileNavigation } from "../app/useMobileNavigation";
import { ThemeToggle } from "../theme/ThemeProvider";

const navigation = [
  { href: "#product", label: "Product" },
  { href: "#how-it-works", label: "How it works" },
];

export function SiteHeader() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  useMobileNavigation(isMenuOpen, menuButtonRef, navigationRef, () => setIsMenuOpen(false));

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
          ref={navigationRef}
          className={`site-nav${isMenuOpen ? " is-open" : ""}`}
          id="site-navigation"
          aria-label="Primary navigation"
        >
          {navigation.map((item) => (
            <a
              key={item.href}
              href={item.href}
              onClick={() => {
                setIsMenuOpen(false);
                menuButtonRef.current?.focus();
              }}
            >
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
            <svg viewBox="0 0 20 20" aria-hidden="true">
              {isMenuOpen ? (
                <path d="m5 5 10 10M15 5 5 15" />
              ) : (
                <path d="M3 6h14M3 10h14M3 14h14" />
              )}
            </svg>
          </button>
        </div>
      </div>
    </header>
  );
}

import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface PlaceholderPageProps {
  eyebrow: string;
  title: string;
  description: string;
  children?: ReactNode;
}

export function PlaceholderPage({ eyebrow, title, description, children }: PlaceholderPageProps) {
  return (
    <main className="foundation-page">
      <section className="foundation-content" aria-labelledby="foundation-title">
        <p className="eyebrow">{eyebrow}</p>
        <h1 id="foundation-title" tabIndex={-1}>
          {title}
        </h1>
        <p>{description}</p>
        {children}
        <Link className="foundation-link" to="/">
          Return to CommitVerse
        </Link>
      </section>
    </main>
  );
}

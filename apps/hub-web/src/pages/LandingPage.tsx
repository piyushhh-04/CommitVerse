import { SiteHeader } from "../components/SiteHeader";
import { TechnicalHeroVisual } from "../components/TechnicalHeroVisual";
import "../App.css";

function SectionHeading({
  id,
  eyebrow,
  title,
  copy,
}: {
  id?: string;
  eyebrow: string;
  title: string;
  copy?: string;
}) {
  return (
    <div className="section-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h2 id={id}>{title}</h2>
      {copy ? <p className="section-copy">{copy}</p> : null}
    </div>
  );
}

function LandingPage() {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main-content">
        <section className="hero section-shell" id="top" aria-labelledby="hero-title">
          <div className="hero-grid">
            <div className="hero-copy-block">
              <p className="eyebrow">A developer platform, built from the core up</p>
              <h1 id="hero-title">
                Version control,
                <br />
                <em>with room to grow.</em>
              </h1>
              <p className="hero-description">
                CommitVerse is building a purpose-made Git-like engine and a considered path toward
                developer collaboration. The working foundation is local; the larger product is
                still taking shape.
              </p>
              <div className="hero-actions">
                <a className="button button-primary" href="#core">
                  Meet the Core <span aria-hidden="true">↘</span>
                </a>
                <a
                  className="text-link"
                  href="https://github.com/piyushhh-04/CommitVerse"
                  target="_blank"
                  rel="noreferrer"
                >
                  Explore the project <span aria-hidden="true">↗</span>
                </a>
              </div>
              <p className="hero-footnote">
                Core foundation implemented · Hub API local · AI future work
              </p>
            </div>
            <TechnicalHeroVisual />
          </div>
          <div className="hero-status" role="group" aria-label="Project status">
            <span>
              <i className="status-dot status-dot-sage" aria-hidden="true" />
              Core <b>Implemented foundation</b>
            </span>
            <span>
              <i className="status-dot status-dot-peach" aria-hidden="true" />
              Hub <b>Local API foundation</b>
            </span>
            <span>
              <i className="status-dot status-dot-muted" aria-hidden="true" />
              AI <b>Future scope</b>
            </span>
          </div>
        </section>

        <section
          className="vision-section section-shell section-divider"
          id="vision"
          aria-labelledby="vision-title"
        >
          <div className="vision-intro">
            <p className="eyebrow">01 / The point of view</p>
            <h2 id="vision-title">
              Useful tools begin with <em>clear foundations.</em>
            </h2>
          </div>
          <div className="vision-details">
            <p>
              CommitVerse keeps version-control data, application metadata, and future assistant
              capabilities in distinct places. That makes the system easier to understand today—and
              gives each layer room to evolve without pretending the roadmap is already shipped.
            </p>
            <ul className="principle-list">
              <li>
                <span>01</span>
                <div>
                  <strong>Build the engine, don&apos;t wrap one</strong>
                  <p>Core implements its Git-like internals in Python.</p>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>Keep boundaries visible</strong>
                  <p>Repository objects stay separate from Hub metadata.</p>
                </div>
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>Say what works</strong>
                  <p>Current capabilities and future plans are labeled plainly.</p>
                </div>
              </li>
            </ul>
          </div>
        </section>

        <section className="core-section section-shell" id="core" aria-labelledby="core-title">
          <div className="section-grid">
            <SectionHeading
              id="core-title"
              eyebrow="02 / CommitVerse Core"
              title="A small engine, built deliberately."
              copy="The current foundation handles local repository work without claiming to replace all of Git."
            />
            <div className="capability-panel">
              <div className="panel-topline">
                <span className="eyebrow">Implemented · local workflows</span>
                <span className="mono-label">PYTHON / CORE</span>
              </div>
              <div className="capability-grid">
                <article>
                  <span className="capability-index">01</span>
                  <h3>Objects &amp; trees</h3>
                  <p>Canonical objects, loose storage, and Git-compatible trees.</p>
                </article>
                <article>
                  <span className="capability-index">02</span>
                  <h3>Index &amp; staging</h3>
                  <p>Index-v2 staging with bounded, explicit worktree operations.</p>
                </article>
                <article>
                  <span className="capability-index">03</span>
                  <h3>History &amp; refs</h3>
                  <p>Commits, branches, revision lookup, and history traversal.</p>
                </article>
                <article>
                  <span className="capability-index">04</span>
                  <h3>Status &amp; merge</h3>
                  <p>Read-only status/diff and a basic, non-conflict-resolving merge.</p>
                </article>
              </div>
              <p className="panel-note">
                Network Git transport, packfiles, conflict resolution, and full Git compatibility
                are not implemented.
              </p>
            </div>
          </div>
        </section>

        <section
          className="hub-section section-shell section-divider"
          id="hub"
          aria-labelledby="hub-title"
        >
          <div className="hub-copy">
            <SectionHeading
              id="hub-title"
              eyebrow="03 / CommitVerse Hub"
              title="A local API foundation—not a hosted product."
              copy="Hub connects account sessions and owner-only personal repository workflows to Core through a separate API layer."
            />
            <p className="hub-caveat">
              This landing page has no sign-in, repository dashboard, live repository data, or API
              calls. The Hub API is local-development software and is not ready for hosted
              deployment.
            </p>
          </div>
          <div className="hub-status-card">
            <p className="eyebrow">Today / Scope at a glance</p>
            <div className="status-row">
              <span className="status-symbol status-symbol-ready" aria-hidden="true">
                ✓
              </span>
              <div>
                <strong>Available in the API foundation</strong>
                <p>Browser sessions and owner-only personal repository lifecycle.</p>
              </div>
              <span className="status-tag">Local</span>
            </div>
            <div className="status-row">
              <span className="status-symbol status-symbol-next" aria-hidden="true">
                →
              </span>
              <div>
                <strong>Not available as a web workflow</strong>
                <p>Repository browsing, organization collaboration, and a product UI.</p>
              </div>
              <span className="status-tag status-tag-muted">Planned</span>
            </div>
            <div className="status-row">
              <span className="status-symbol status-symbol-next" aria-hidden="true">
                →
              </span>
              <div>
                <strong>Hosting remains unresolved</strong>
                <p>Deployment must fit the project&apos;s strict zero-cost policy.</p>
              </div>
              <span className="status-tag status-tag-muted">Deferred</span>
            </div>
          </div>
        </section>

        <section
          className="architecture-section section-shell"
          id="architecture"
          aria-labelledby="architecture-title"
        >
          <SectionHeading
            id="architecture-title"
            eyebrow="04 / System boundaries"
            title="Three layers. No blurred promises."
            copy="Each area has a different responsibility—and a different implementation status."
          />
          <div
            className="architecture-map"
            role="group"
            aria-label="CommitVerse architecture layers"
          >
            <article className="architecture-node architecture-core">
              <span className="node-kicker">01 / Working today</span>
              <h3>Core</h3>
              <p>Owns repository objects, refs, index, and local version-control operations.</p>
              <span className="node-status">Python · implemented foundation</span>
            </article>
            <span className="architecture-connector" aria-hidden="true">
              <span>narrow adapter</span>
              <i />
            </span>
            <article className="architecture-node architecture-hub">
              <span className="node-kicker">02 / Local API foundation</span>
              <h3>Hub</h3>
              <p>Owns account, permission, and repository metadata—not Git object storage.</p>
              <span className="node-status">FastAPI · local development</span>
            </article>
            <span className="architecture-connector future-connector" aria-hidden="true">
              <span>future boundary</span>
              <i />
            </span>
            <article className="architecture-node architecture-ai">
              <span className="node-kicker">03 / Future scope</span>
              <h3>AI</h3>
              <p>
                A possible assistant layer; no runtime, data access, or product integration exists.
              </p>
              <span className="node-status">Not implemented</span>
            </article>
          </div>
          <p className="architecture-caption">
            Conceptual system map · Core repository data remains distinct from Hub application data.
          </p>
        </section>

        <section
          className="workflow-section section-shell section-divider"
          id="workflow"
          aria-labelledby="workflow-title"
        >
          <SectionHeading
            id="workflow-title"
            eyebrow="05 / The Core path"
            title="From working tree to recorded history."
            copy="A simplified view of the local path already covered by the Core foundation."
          />
          <ol className="workflow-list">
            <li>
              <span className="workflow-number">01</span>
              <span className="workflow-icon" aria-hidden="true">
                ⌘
              </span>
              <h3>Working tree</h3>
              <p>Inspect and stage files in a non-bare repository.</p>
              <code>cv status</code>
            </li>
            <li>
              <span className="workflow-number">02</span>
              <span className="workflow-icon" aria-hidden="true">
                ▤
              </span>
              <h3>Index &amp; tree</h3>
              <p>Record the staged snapshot as Git-compatible tree objects.</p>
              <code>cv add -A</code>
            </li>
            <li>
              <span className="workflow-number">03</span>
              <span className="workflow-icon" aria-hidden="true">
                ◉
              </span>
              <h3>Commit</h3>
              <p>Create a commit from the current index and configured identity.</p>
              <code>cv commit -m</code>
            </li>
            <li>
              <span className="workflow-number">04</span>
              <span className="workflow-icon" aria-hidden="true">
                ⑂
              </span>
              <h3>History &amp; refs</h3>
              <p>Follow local branch state and traverse parent history.</p>
              <code>cv log</code>
            </li>
          </ol>
          <p className="workflow-note">
            These are Core CLI examples, not controls connected to this page.
          </p>
        </section>

        <section className="ai-section section-shell" id="ai" aria-labelledby="ai-title">
          <div className="ai-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="ai-copy">
            <p className="eyebrow">06 / A future layer</p>
            <h2 id="ai-title">
              Make room for <em>assistance.</em>
              <br />
              Don&apos;t pretend it&apos;s here.
            </h2>
            <p>
              CommitVerse AI is a long-term direction, not a feature in this release. There is no
              assistant, model, repository access, or generated output behind this page. Any future
              integration needs its own explicit data and permission boundaries.
            </p>
            <span className="status-tag status-tag-muted">Future scope · not implemented</span>
          </div>
        </section>

        <section
          className="roadmap-section section-shell section-divider"
          id="roadmap"
          aria-labelledby="roadmap-title"
        >
          <SectionHeading
            id="roadmap-title"
            eyebrow="07 / Build sequence"
            title="Progress, in honest increments."
            copy="A short read of what exists, what this milestone adds, and what remains a plan."
          />
          <ol className="roadmap-list">
            <li className="roadmap-item is-complete">
              <span className="roadmap-marker" aria-hidden="true">
                ✓
              </span>
              <div>
                <span className="roadmap-state">Implemented foundation</span>
                <h3>Core &amp; local Hub API</h3>
                <p>Local version-control workflows and a limited API foundation.</p>
              </div>
              <span className="roadmap-index">01</span>
            </li>
            <li className="roadmap-item is-current">
              <span className="roadmap-marker" aria-hidden="true">
                02
              </span>
              <div>
                <span className="roadmap-state">Milestone 01 / This work</span>
                <h3>Standalone web identity</h3>
                <p>Accessible landing page, responsive design system, and no backend coupling.</p>
              </div>
              <span className="roadmap-index">02</span>
            </li>
            <li className="roadmap-item">
              <span className="roadmap-marker" aria-hidden="true">
                03
              </span>
              <div>
                <span className="roadmap-state">Future work</span>
                <h3>Product workflows &amp; collaboration</h3>
                <p>
                  Plan and implement authenticated interfaces only after API contracts are ready.
                </p>
              </div>
              <span className="roadmap-index">03</span>
            </li>
            <li className="roadmap-item">
              <span className="roadmap-marker" aria-hidden="true">
                04
              </span>
              <div>
                <span className="roadmap-state">Future work</span>
                <h3>Assistant &amp; deployment decisions</h3>
                <p>Define data boundaries and a compliant hosting path before making claims.</p>
              </div>
              <span className="roadmap-index">04</span>
            </li>
          </ol>
        </section>

        <section className="closing-section section-shell" id="next" aria-labelledby="next-title">
          <div className="closing-inner">
            <p className="eyebrow">08 / Keep following the work</p>
            <h2 id="next-title">
              Thoughtful tools take
              <br />
              <em>one clear step at a time.</em>
            </h2>
            <p>
              See the implementation and its current boundaries in the project repository. This page
              is informational; it does not offer accounts or live repository features.
            </p>
            <a
              className="button button-light"
              href="https://github.com/piyushhh-04/CommitVerse"
              target="_blank"
              rel="noreferrer"
            >
              Explore CommitVerse on GitHub <span aria-hidden="true">↗</span>
            </a>
          </div>
        </section>
      </main>
      <footer className="site-footer section-shell">
        <a className="footer-brand" href="#top">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>CommitVerse</span>
        </a>
        <p>Built with care. Still being built.</p>
        <a href="https://github.com/piyushhh-04/CommitVerse" target="_blank" rel="noreferrer">
          Project repository <span aria-hidden="true">↗</span>
        </a>
      </footer>
    </>
  );
}

export default LandingPage;

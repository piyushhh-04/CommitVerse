import { SiteHeader } from "../components/SiteHeader";
import { TechnicalHeroVisual } from "../components/TechnicalHeroVisual";
import "../App.css";

function SectionHeading({ id, title, copy }: { id: string; title: string; copy: string }) {
  return (
    <div className="section-heading">
      <h2 id={id}>{title}</h2>
      <p className="section-copy">{copy}</p>
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
              <h1 id="hero-title">
                Version control,
                <br />
                built from the <span>objects up.</span>
              </h1>
              <p className="hero-description">
                Python Core builds local Git-like repositories. Hub adds account management and
                read-only repository browsing.
              </p>
              <div className="hero-actions">
                <a className="button button-primary" href="/register">
                  Create account
                </a>
                <a className="text-link" href="/login">
                  Sign in
                </a>
              </div>
            </div>
            <TechnicalHeroVisual />
          </div>
        </section>

        <section
          className="object-model-section section-shell section-divider"
          id="how-it-works"
          aria-labelledby="object-model-title"
        >
          <SectionHeading
            id="object-model-title"
            title="A repository is a chain of real objects."
            copy="Core records file contents and structure as objects, then connects them to history through commits and refs."
          />
          <ol className="object-model-list">
            <li>
              <span className="object-model-index">01</span>
              <h3>Blob</h3>
              <p>Stores a file's contents.</p>
              <code>README.md → blob</code>
            </li>
            <li>
              <span className="object-model-index">02</span>
              <h3>Tree</h3>
              <p>Maps names to blobs and nested trees.</p>
              <code>src/ → tree</code>
            </li>
            <li>
              <span className="object-model-index">03</span>
              <h3>Commit</h3>
              <p>Points to a tree and its parent history.</p>
              <code>commit → tree + parents</code>
            </li>
            <li>
              <span className="object-model-index">04</span>
              <h3>Ref</h3>
              <p>Names a commit, as a branch or tag does.</p>
              <code>main → commit</code>
            </li>
          </ol>
        </section>

        <section
          className="capabilities-section section-shell"
          id="product"
          aria-labelledby="capabilities-title"
        >
          <SectionHeading
            id="capabilities-title"
            title="What works today."
            copy="A practical local foundation, with the responsibilities of each part kept explicit."
          />
          <div
            className="capability-ledger"
            role="list"
            aria-label="Implemented CommitVerse capabilities"
          >
            <div className="capability-row" role="listitem">
              <h3>Core</h3>
              <p>
                Initialize and inspect local repositories; stage files; create commits; manage
                branches; read history, status, and diffs; perform basic merges.
              </p>
              <span>Python · local</span>
            </div>
            <div className="capability-row" role="listitem">
              <h3>Hub</h3>
              <p>
                Manage accounts, profiles, personal and organization repositories, memberships,
                invitations, issues, and pull requests through the local API.
              </p>
              <span>FastAPI · local</span>
            </div>
            <div className="capability-row" role="listitem">
              <h3>Repository browser</h3>
              <p>
                Browse authorized trees, files, branches, tags, commits, and bounded diffs without
                writing repository contents from the web app.
              </p>
              <span>Read-only</span>
            </div>
          </div>
        </section>

        <section
          className="scope-section section-shell section-divider"
          aria-labelledby="scope-title"
        >
          <SectionHeading
            id="scope-title"
            title="The boundaries are part of the product."
            copy="CommitVerse labels what is implemented and what remains unfinished."
          />
          <ul className="scope-list">
            <li>
              <strong>Core is not full Git.</strong>
              <span>
                Network transport, packfiles, conflict resolution, and complete compatibility are
                not implemented.
              </span>
            </li>
            <li>
              <strong>Hub runs locally.</strong>
              <span>
                Its filesystem lifecycle is not ready for hosted or multi-worker deployment.
              </span>
            </li>
            <li>
              <strong>Invitations are shared manually.</strong>
              <span>Hub does not send invitation email.</span>
            </li>
            <li>
              <strong>AI remains future product scope.</strong>
              <span>There is no hosted assistant or model integration on this overview.</span>
            </li>
          </ul>
        </section>

        <section className="closing-section section-shell" aria-labelledby="next-title">
          <div className="closing-inner">
            <h2 id="next-title">Read the implementation, not just the promise.</h2>
            <p>Explore the source and tests behind the current CommitVerse foundation.</p>
            <a
              className="button button-primary"
              href="https://github.com/piyushhh-04/CommitVerse"
              target="_blank"
              rel="noreferrer"
            >
              Explore the project
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
        <p>Local development foundation</p>
        <a href="https://github.com/piyushhh-04/CommitVerse" target="_blank" rel="noreferrer">
          Project repository
        </a>
      </footer>
    </>
  );
}

export default LandingPage;

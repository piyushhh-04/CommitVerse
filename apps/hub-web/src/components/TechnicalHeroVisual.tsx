export function TechnicalHeroVisual() {
  return (
    <div className="hero-visual">
      <div className="diagram-label">
        <span className="diagram-label-dot" aria-hidden="true" />
        Static architecture sketch <span>/</span> not live data
      </div>
      <svg
        className="repository-diagram"
        viewBox="0 0 640 440"
        role="img"
        aria-labelledby="diagram-title diagram-description"
      >
        <title id="diagram-title">Illustrative CommitVerse Core object flow</title>
        <desc id="diagram-description">
          A static diagram connects a working tree and index to tree objects, commits, and local
          branch references. It does not show live repository data.
        </desc>
        <defs>
          <pattern id="diagram-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" className="diagram-grid-dot" />
          </pattern>
          <linearGradient id="diagram-panel" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" className="diagram-gradient-start" />
            <stop offset="100%" className="diagram-gradient-end" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="638" height="438" rx="24" className="diagram-frame" />
        <rect x="1" y="1" width="638" height="438" rx="24" fill="url(#diagram-grid)" />
        <path d="M37 68h566" className="diagram-rule" />
        <circle cx="38" cy="42" r="4" className="diagram-window-dot" />
        <circle cx="54" cy="42" r="4" className="diagram-window-dot diagram-window-dot-2" />
        <circle cx="70" cy="42" r="4" className="diagram-window-dot diagram-window-dot-3" />
        <text x="96" y="46" className="diagram-micro">
          CORE / LOCAL OBJECT FLOW
        </text>
        <text x="543" y="46" className="diagram-micro diagram-micro-right">
          ILLUSTRATIVE
        </text>

        <rect
          x="35"
          y="105"
          width="142"
          height="72"
          rx="13"
          className="diagram-card diagram-card-worktree"
        />
        <text x="53" y="132" className="diagram-kicker">
          01 / INPUT
        </text>
        <text x="53" y="156" className="diagram-card-title">
          Working tree
        </text>
        <path d="M178 141h61" className="diagram-connector" />
        <path d="m234 136 6 5-6 5" className="diagram-arrow" />
        <text x="208" y="127" className="diagram-edge-label">
          stage
        </text>

        <rect
          x="242"
          y="105"
          width="142"
          height="72"
          rx="13"
          className="diagram-card diagram-card-index"
        />
        <text x="260" y="132" className="diagram-kicker">
          02 / SNAPSHOT
        </text>
        <text x="260" y="156" className="diagram-card-title">
          Index v2
        </text>
        <path d="M385 141h61" className="diagram-connector" />
        <path d="m441 136 6 5-6 5" className="diagram-arrow" />
        <text x="410" y="127" className="diagram-edge-label">
          write
        </text>

        <rect
          x="449"
          y="105"
          width="156"
          height="72"
          rx="13"
          className="diagram-card diagram-card-tree"
        />
        <text x="467" y="132" className="diagram-kicker">
          03 / OBJECT
        </text>
        <text x="467" y="156" className="diagram-card-title">
          Tree objects
        </text>

        <path d="M527 178v47H334v31" className="diagram-connector diagram-connector-dashed" />
        <path d="m329 250 5 7 5-7" className="diagram-arrow" />
        <text x="412" y="213" className="diagram-edge-label">
          commit tree
        </text>

        <rect x="260" y="260" width="148" height="76" rx="14" className="diagram-commit-card" />
        <text x="279" y="286" className="diagram-kicker">
          04 / HISTORY
        </text>
        <text x="279" y="312" className="diagram-card-title">
          Commit object
        </text>
        <circle cx="385" cy="281" r="5" className="diagram-commit-dot" />

        <path d="M334 337v30H147" className="diagram-connector" />
        <path d="M334 367h184v-29" className="diagram-connector" />
        <path d="m512 343 6-7 6 7" className="diagram-arrow" />
        <circle cx="147" cy="367" r="5" className="diagram-branch-dot" />
        <circle cx="518" cy="367" r="5" className="diagram-branch-dot diagram-branch-dot-sage" />
        <rect x="64" y="383" width="166" height="36" rx="18" className="diagram-branch-pill" />
        <text x="91" y="406" className="diagram-branch-text">
          main ref
        </text>
        <rect
          x="436"
          y="383"
          width="166"
          height="36"
          rx="18"
          className="diagram-branch-pill diagram-branch-pill-sage"
        />
        <text x="464" y="406" className="diagram-branch-text">
          local branch ref
        </text>
        <rect x="467" y="274" width="128" height="32" rx="16" className="diagram-object-hash" />
        <text x="483" y="294" className="diagram-hash-text">
          parent history
        </text>
      </svg>
      <div className="diagram-foot">
        <span>Working tree → index → objects → refs</span>
        <span className="mono-label">CORE / PYTHON</span>
      </div>
    </div>
  );
}

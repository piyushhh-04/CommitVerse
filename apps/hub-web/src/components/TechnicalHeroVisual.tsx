export function TechnicalHeroVisual() {
  return (
    <div
      className="hero-visual"
      role="img"
      aria-label="Illustrative CommitVerse object and commit graph. Example identifiers show a main and feature branch, and how a commit points to a tree and blob. The identifiers are not live repository data."
    >
      <svg className="repository-diagram desktop-diagram" viewBox="0 0 640 370" aria-hidden="true">
        <rect x="1" y="1" width="638" height="368" rx="10" className="diagram-frame" />
        <path d="M28 52h584" className="diagram-rule" />
        <circle cx="34" cy="28" r="3" className="diagram-window-dot" />
        <circle cx="47" cy="28" r="3" className="diagram-window-dot" />
        <circle cx="60" cy="28" r="3" className="diagram-window-dot" />
        <text x="78" y="32" className="diagram-micro">
          OBJECT GRAPH EXAMPLE
        </text>

        <path d="M88 128H548" className="diagram-connector" />
        <path d="M204 128v112h230" className="diagram-connector diagram-connector-branch" />
        <path d="M434 128v112" className="diagram-connector" />

        <circle cx="88" cy="128" r="10" className="diagram-node diagram-node-merged" />
        <circle cx="204" cy="128" r="10" className="diagram-node diagram-node-merged" />
        <circle cx="319" cy="128" r="10" className="diagram-node diagram-node-current" />
        <circle cx="434" cy="128" r="10" className="diagram-node" />
        <circle cx="434" cy="240" r="10" className="diagram-node diagram-node-branch" />
        <circle cx="548" cy="128" r="10" className="diagram-node" />

        <text x="70" y="164" className="diagram-id">
          18c2a61
        </text>
        <text x="186" y="164" className="diagram-id">
          7f4b9e2
        </text>
        <text x="301" y="164" className="diagram-id">
          c31d0a8
        </text>
        <text x="416" y="164" className="diagram-id">
          9b08f44
        </text>
        <text x="416" y="276" className="diagram-id">
          a12de70
        </text>
        <text x="530" y="164" className="diagram-id">
          e6f38b1
        </text>

        <rect x="484" y="79" width="82" height="26" rx="13" className="diagram-ref-current" />
        <text x="505" y="96" className="diagram-ref-label">
          main
        </text>
        <rect x="448" y="214" width="110" height="26" rx="13" className="diagram-ref-branch" />
        <text x="463" y="231" className="diagram-ref-label">
          feature
        </text>

        <text x="301" y="202" className="diagram-object-type">
          commit
        </text>
        <path d="M319 180v62h-106v38" className="diagram-connector" />
        <rect x="172" y="280" width="116" height="42" rx="5" className="diagram-object" />
        <text x="190" y="306" className="diagram-object-title">
          tree
        </text>
        <path d="M289 301h76" className="diagram-connector" />
        <rect x="366" y="280" width="116" height="42" rx="5" className="diagram-object" />
        <text x="384" y="306" className="diagram-object-title">
          blob
        </text>
        <text x="172" y="351" className="diagram-object-note">
          tree → blob: path and file contents
        </text>
      </svg>
      <svg className="repository-diagram mobile-diagram" viewBox="0 0 340 340" aria-hidden="true">
        <rect x="1" y="1" width="338" height="338" rx="10" className="diagram-frame" />
        <circle cx="23" cy="27" r="3" className="diagram-window-dot" />
        <circle cx="36" cy="27" r="3" className="diagram-window-dot" />
        <circle cx="49" cy="27" r="3" className="diagram-window-dot" />
        <text x="67" y="31" className="diagram-micro">
          OBJECT GRAPH EXAMPLE
        </text>
        <path d="M25 51h290" className="diagram-rule" />

        <path d="M54 91v157" className="diagram-connector" />
        <path d="M54 193v20h132" className="diagram-connector diagram-connector-branch" />
        <circle cx="54" cy="91" r="9" className="diagram-node diagram-node-merged" />
        <circle cx="54" cy="142" r="9" className="diagram-node diagram-node-merged" />
        <circle cx="54" cy="193" r="9" className="diagram-node diagram-node-current" />
        <circle cx="54" cy="248" r="9" className="diagram-node" />
        <circle cx="186" cy="213" r="9" className="diagram-node diagram-node-branch" />

        <text x="78" y="95" className="diagram-id">
          18c2a61
        </text>
        <text x="78" y="146" className="diagram-id">
          7f4b9e2
        </text>
        <text x="78" y="197" className="diagram-id">
          c31d0a8
        </text>
        <text x="78" y="252" className="diagram-id">
          e6f38b1
        </text>
        <text x="205" y="237" className="diagram-id">
          a12de70
        </text>

        <rect x="242" y="71" width="70" height="25" rx="12" className="diagram-ref-current" />
        <text x="260" y="88" className="diagram-ref-label">
          main
        </text>
        <rect x="205" y="183" width="107" height="25" rx="12" className="diagram-ref-branch" />
        <text x="222" y="200" className="diagram-ref-label">
          feature
        </text>

        <text x="27" y="284" className="diagram-object-type">
          commit → tree → blob
        </text>
        <rect x="27" y="299" width="120" height="34" rx="5" className="diagram-object" />
        <text x="43" y="321" className="diagram-object-title">
          tree
        </text>
        <path d="M148 316h44" className="diagram-connector" />
        <rect x="193" y="299" width="120" height="34" rx="5" className="diagram-object" />
        <text x="209" y="321" className="diagram-object-title">
          blob
        </text>
      </svg>
    </div>
  );
}

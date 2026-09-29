import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { DifficultyMeter, pad2, StatusLabel } from "../guides/bits";
import { GUIDES, LEVELS, type Level } from "../guides/content";
import { guideStatus, useGuideState } from "../guides/state";

export default function GuidesPage() {
  const nav = useNavigate();
  const done = useGuideState((s) => s.done);
  const steps = useGuideState((s) => s.steps);
  const opened = useGuideState((s) => s.opened);
  const openPanel = useGuideState((s) => s.openPanel);
  const [level, setLevel] = useState<Level | "all">("all");
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const visible = useMemo(
    () =>
      GUIDES.filter((g) => (level === "all" || g.level === level) && (!q || [g.title, g.summary, g.needs, ...g.learn, ...g.pages].join(" ").toLowerCase().includes(q))),
    [level, q],
  );
  const finished = GUIDES.filter((g) => done[g.slug]).length;
  const next = GUIDES.find((g) => !done[g.slug]);

  return (
    <div className="stack guides-index">
      <div className="page-head">
        <div>
          <h1>Guides</h1>
          <div className="sub">
            {GUIDES.length} hands-on projects, from a first count to a full study. Every step says what to click. The same guides are in the docs/guides folder of the repository.
          </div>
        </div>
        {next && (
          <div className="row">
            <span className="hint">
              {finished} of {GUIDES.length} done
            </span>
            <button className="btn primary" onClick={() => nav(`/guides/${next.slug}`)}>
              {finished === 0 ? `Start with guide ${next.number}` : `Continue with guide ${next.number}`}
            </button>
          </div>
        )}
      </div>

      <div className="row wrap guides-filter">
        <div className="btn-group" role="group" aria-label="Level">
          <button className={`btn sm ${level === "all" ? "active" : ""}`} onClick={() => setLevel("all")}>
            All
          </button>
          {LEVELS.map((l) => (
            <button key={l.id} className={`btn sm ${level === l.id ? "active" : ""}`} onClick={() => setLevel(l.id)}>
              {l.id}
            </button>
          ))}
        </div>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search guides, for example webcam, routes or speed" aria-label="Search guides" style={{ maxWidth: 360 }} />
        <span className="hint">Follow along opens a guide beside the app, so you can click through the pages it describes.</span>
      </div>

      {visible.length === 0 && <div className="empty">No guide matches “{query}”. Try another word, or clear the search.</div>}

      {LEVELS.map((l) => {
        const list = visible.filter((g) => g.level === l.id);
        if (!list.length) return null;
        return (
          <section key={l.id} className="guide-level">
            <div className="guide-level-head">
              <h2>{l.id}</h2>
              <span className="hint">{l.blurb}</span>
            </div>
            <ol className="guide-list">
              {list.map((g) => {
                const status = guideStatus({ done, steps, opened }, g.slug);
                return (
                  <li key={g.slug} className={`guide-row ${status}`}>
                    <span className="guide-num num" aria-hidden="true">
                      {pad2(g.number)}
                    </span>
                    <div className="guide-main">
                      <Link className="guide-title" to={`/guides/${g.slug}`}>
                        {g.title}
                      </Link>
                      <div className="guide-summary">{g.summary}</div>
                      <div className="guide-meta">
                        <span>{g.time}</span>
                        <span>You need: {g.needs}</span>
                      </div>
                    </div>
                    <div className="guide-side">
                      <DifficultyMeter level={g.level} />
                      <StatusLabel status={status} />
                      <button className="btn sm ghost" onClick={() => openPanel(g.slug)} title="Open this guide beside the app">
                        Follow along
                      </button>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

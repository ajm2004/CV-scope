import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router";
import GuideArticle, { scrollToHeading } from "../guides/GuideArticle";
import { Progress } from "../components/ui";
import { DifficultyMeter, pad2, StatusLabel } from "../guides/bits";
import { GUIDES, guideBySlug, PAGE_ROUTES, stepCount } from "../guides/content";
import { guideStatus, tickedCount, useGuideState } from "../guides/state";

export default function GuidePage() {
  const { slug } = useParams();
  const loc = useLocation();
  const guide = guideBySlug(slug);
  const state = useGuideState();
  const { markOpened, openPanel, setDone, resetGuide } = state;

  useEffect(() => {
    if (guide) markOpened(guide.slug);
  }, [guide, markOpened]);

  // Jump to a section when the address carries one (#troubleshooting).
  useEffect(() => {
    const id = decodeURIComponent(loc.hash.replace(/^#/, ""));
    if (id) window.setTimeout(() => scrollToHeading("page", id), 50);
    else document.querySelector(".main")?.scrollTo({ top: 0 });
  }, [slug, loc.hash]);

  if (!guide) {
    return (
      <div className="stack">
        <div className="empty">
          There is no guide called “{slug}”. <Link to="/guides">See all guides</Link>.
        </div>
      </div>
    );
  }

  const idx = GUIDES.findIndex((g) => g.slug === guide.slug);
  const prev = GUIDES[idx - 1];
  const next = GUIDES[idx + 1];
  const total = stepCount(guide);
  const ticked = tickedCount(state, guide.slug);
  const status = guideStatus(state, guide.slug);
  const sections = guide.headings.filter((h) => h.level === 2);

  return (
    <div className="guide-page">
      <header className="guide-head">
        <div className="guide-crumbs hint">
          <Link to="/guides">Guides</Link> / {guide.level} / guide {pad2(guide.number)} of {GUIDES.length}
        </div>
        <h1>{guide.title}</h1>
        <p className="guide-lede">{guide.summary}</p>
        <div className="guide-facts">
          <span className="row" style={{ gap: 6 }}>
            <DifficultyMeter level={guide.level} /> {guide.level}
          </span>
          <span>{guide.time}</span>
          <span>You need: {guide.needs}</span>
          <StatusLabel status={status} />
        </div>
      </header>

      <div className="guide-layout">
        <article className="guide-article">
          <GuideArticle guide={guide} mode="page" />
          <nav className="guide-pager" aria-label="Other guides">
            {prev ? (
              <Link className="pager-link" to={`/guides/${prev.slug}`}>
                <span className="hint">Previous guide</span>
                <span>
                  {pad2(prev.number)} {prev.title}
                </span>
              </Link>
            ) : (
              <span />
            )}
            {next ? (
              <Link className="pager-link next" to={`/guides/${next.slug}`}>
                <span className="hint">Next guide</span>
                <span>
                  {pad2(next.number)} {next.title}
                </span>
              </Link>
            ) : (
              <Link className="pager-link next" to="/guides">
                <span className="hint">That was the last one</span>
                <span>Back to all guides</span>
              </Link>
            )}
          </nav>
        </article>

        <aside className="guide-rail">
          <div className="rail-block">
            <button className="btn primary" onClick={() => openPanel(guide.slug)}>
              Follow along beside the app
            </button>
            <div className="hint" style={{ marginTop: 6 }}>
              The guide stays open on the right while you move between pages.
            </div>
          </div>

          {total > 0 && (
            <div className="rail-block">
              <div className="rail-title">Your progress</div>
              <Progress value={ticked / total} />
              <div className="hint" style={{ marginTop: 4 }}>
                {ticked} of {total} steps ticked. Click a step number to tick it.
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn sm" onClick={() => setDone(guide.slug, status !== "done")}>
                  {status === "done" ? "Mark as not done" : "Mark guide as done"}
                </button>
                {(ticked > 0 || status === "done") && (
                  <button className="btn sm ghost" onClick={() => resetGuide(guide.slug)}>
                    Clear ticks
                  </button>
                )}
              </div>
            </div>
          )}

          {guide.learn.length > 0 && (
            <div className="rail-block">
              <div className="rail-title">You will learn to</div>
              <ul className="rail-list">
                {guide.learn.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          )}

          {sections.length > 0 && (
            <div className="rail-block">
              <div className="rail-title">On this page</div>
              <ul className="rail-toc">
                {sections.map((h) => (
                  <li key={h.id}>
                    <a
                      href={`#${h.id}`}
                      onClick={(e) => {
                        e.preventDefault();
                        scrollToHeading("page", h.id);
                      }}
                    >
                      {h.text}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {guide.pages.length > 0 && (
            <div className="rail-block">
              <div className="rail-title">Pages this guide uses</div>
              <div className="row wrap" style={{ gap: 6 }}>
                {guide.pages.map((p) =>
                  PAGE_ROUTES[p] ? (
                    <Link key={p} className="btn sm" to={PAGE_ROUTES[p]}>
                      {p}
                    </Link>
                  ) : (
                    <span key={p} className="btn sm static" title="Opened from a camera or an experiment">
                      {p}
                    </span>
                  ),
                )}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

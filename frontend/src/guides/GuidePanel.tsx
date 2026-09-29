import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { Progress } from "../components/ui";
import GuideArticle from "./GuideArticle";
import { pad2 } from "./bits";
import { GUIDES, guideBySlug, stepCount } from "./content";
import { tickedCount, useGuideState } from "./state";

/** A guide docked beside the app, so its steps stay in view while the reader
 *  clicks through the pages they describe. */
export default function GuidePanel() {
  const slug = useGuideState((s) => s.panel);
  const collapsed = useGuideState((s) => s.collapsed);
  const steps = useGuideState((s) => s.steps);
  const done = useGuideState((s) => s.done);
  const { closePanel, setCollapsed, openPanel, setDone, markOpened } = useGuideState.getState();
  const body = useRef<HTMLDivElement | null>(null);
  const guide = guideBySlug(slug);

  useEffect(() => {
    if (guide) {
      markOpened(guide.slug);
      body.current?.scrollTo({ top: 0 });
    }
  }, [guide, markOpened]);

  if (!guide) return null;

  if (collapsed) {
    return (
      <aside className="guide-panel collapsed" aria-label="Guide">
        <button className="guide-panel-tab" onClick={() => setCollapsed(false)} title={`Show guide ${guide.number}: ${guide.title}`}>
          <span className="num">{pad2(guide.number)}</span>
          <span className="tab-title">{guide.title}</span>
        </button>
      </aside>
    );
  }

  const idx = GUIDES.findIndex((g) => g.slug === guide.slug);
  const prev = GUIDES[idx - 1];
  const next = GUIDES[idx + 1];
  const total = stepCount(guide);
  const ticked = tickedCount({ steps }, guide.slug);
  const isDone = !!done[guide.slug];

  return (
    <aside className="guide-panel" aria-label={`Guide: ${guide.title}`}>
      <div className="guide-panel-head">
        <div className="grow">
          <div className="hint">
            Guide {pad2(guide.number)} · {guide.level}
          </div>
          <div className="guide-panel-title">{guide.title}</div>
        </div>
        <button className="btn sm ghost" onClick={() => setCollapsed(true)} title="Collapse to a strip at the edge">
          Hide
        </button>
        <button className="btn sm ghost" onClick={closePanel} title="Close the guide">
          Close
        </button>
      </div>
      {total > 0 && (
        <div className="guide-panel-progress">
          <Progress value={ticked / total} />
          <span className="hint num">
            {ticked}/{total} steps
          </span>
        </div>
      )}
      <div className="guide-panel-body" ref={body}>
        <p className="guide-lede small">{guide.summary}</p>
        <GuideArticle guide={guide} mode="panel" />
      </div>
      <div className="guide-panel-foot">
        <button className="btn sm" disabled={!prev} onClick={() => prev && openPanel(prev.slug)} title={prev ? `${pad2(prev.number)} ${prev.title}` : undefined}>
          Previous
        </button>
        <button className={`btn sm ${isDone ? "" : "ok"}`} onClick={() => setDone(guide.slug, !isDone)}>
          {isDone ? "Done" : "Mark as done"}
        </button>
        <Link className="btn sm ghost" to={`/guides/${guide.slug}`}>
          Full page
        </Link>
        <span className="grow" />
        <button className="btn sm" disabled={!next} onClick={() => next && openPanel(next.slug)} title={next ? `${pad2(next.number)} ${next.title}` : undefined}>
          Next
        </button>
      </div>
    </aside>
  );
}

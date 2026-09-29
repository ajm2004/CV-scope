import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PAGE_ROUTES, type Guide } from "./content";
import { classifyLink } from "./links";
import { parseInline, plainText, type Block, type Inline } from "./markdown";
import { useGuideState } from "./state";

export type ArticleMode = "page" | "panel";

const CALLOUT_TITLES: Record<string, string> = { note: "Note", tip: "Tip", important: "Important", warning: "Warning", caution: "Caution" };

/** Element id of a heading: the GitHub anchor, prefixed in the side panel so a
 *  guide can be open in the panel and on the page at the same time. */
export function headingDomId(mode: ArticleMode, id: string): string {
  return mode === "panel" ? `panel-${id}` : id;
}

export function scrollToHeading(mode: ArticleMode, id: string) {
  document.getElementById(headingDomId(mode, id))?.scrollIntoView({ behavior: "smooth", block: "start" });
}

interface Ctx {
  mode: ArticleMode;
  steps: Record<string, boolean>;
  toggle: (key: string) => void;
  openInPanel: (slug: string) => void;
}

export default function GuideArticle({ guide, mode }: { guide: Guide; mode: ArticleMode }) {
  const steps = useGuideState((s) => s.steps[guide.slug]) ?? {};
  const toggleStep = useGuideState((s) => s.toggleStep);
  const openPanel = useGuideState((s) => s.openPanel);
  const ctx: Ctx = {
    mode,
    steps,
    toggle: (key) => toggleStep(guide.slug, key),
    openInPanel: openPanel,
  };
  return <div className={`md guide-md mode-${mode}`}>{renderBlocks(guide.blocks, ctx, 0)}</div>;
}

function renderBlocks(blocks: Block[], ctx: Ctx, depth: number): ReactNode {
  return blocks.map((b, i) => <Fragment key={i}>{renderBlock(b, ctx, depth)}</Fragment>);
}

function renderBlock(b: Block, ctx: Ctx, depth: number): ReactNode {
  switch (b.type) {
    case "heading": {
      // The page header already shows the guide title.
      if (b.level === 1) return null;
      const Tag = (`h${Math.min(b.level, 4)}`) as "h2" | "h3" | "h4";
      return (
        <Tag id={headingDomId(ctx.mode, b.id)} className="md-h">
          {renderInline(parseInline(b.text), ctx)}
        </Tag>
      );
    }
    case "paragraph":
      return <p>{renderInline(parseInline(b.text), ctx)}</p>;
    case "code":
      return <CodeBlock text={b.text} lang={b.lang} />;
    case "hr":
      return <hr />;
    case "table":
      return (
        <div className="table-wrap md-table-wrap">
          <table className="table md-table">
            <thead>
              <tr>
                {b.header.map((h, i) => (
                  <th key={i} style={{ textAlign: b.align[i] ?? undefined }}>
                    {renderInline(parseInline(h), ctx)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} style={{ textAlign: b.align[j] ?? undefined }}>
                      {renderInline(parseInline(c), ctx)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "callout":
      if (b.kind === "quote") return <blockquote className="md-quote">{renderBlocks(b.blocks, ctx, depth)}</blockquote>;
      return (
        <div className={`md-callout ${b.kind}`} role="note">
          <div className="md-callout-title">{CALLOUT_TITLES[b.kind]}</div>
          {renderBlocks(b.blocks, ctx, depth)}
        </div>
      );
    case "list": {
      // Top-level numbered lists are steps the reader can tick off.
      if (b.ordered && b.stepGroup !== undefined && depth === 0) {
        return (
          <ol className="md-steps" start={b.start}>
            {b.items.map((item, i) => {
              const key = `${b.stepGroup}.${i}`;
              const done = !!ctx.steps[key];
              const n = b.start + i;
              return (
                <li key={i} className={done ? "done" : ""}>
                  <button
                    type="button"
                    className="step-mark"
                    aria-pressed={done}
                    title={done ? `Step ${n} is ticked. Click to untick.` : `Tick step ${n} when you have done it`}
                    onClick={() => ctx.toggle(key)}
                  >
                    <span className="step-n">{n}</span>
                    <svg className="step-check" viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <div className="step-body">{renderItem(item, ctx, depth)}</div>
                </li>
              );
            })}
          </ol>
        );
      }
      const items = b.items.map((item, i) => <li key={i}>{renderItem(item, ctx, depth)}</li>);
      return b.ordered ? <ol start={b.start}>{items}</ol> : <ul>{items}</ul>;
    }
  }
}

function renderItem(blocks: Block[], ctx: Ctx, depth: number): ReactNode {
  // Tight items: a single paragraph renders inline, without paragraph spacing.
  if (blocks.length >= 1 && blocks[0].type === "paragraph") {
    const [first, ...rest] = blocks;
    return (
      <>
        <span className="md-li-text">{renderInline(parseInline((first as { text: string }).text), ctx)}</span>
        {rest.length > 0 && renderBlocks(rest, ctx, depth + 1)}
      </>
    );
  }
  return renderBlocks(blocks, ctx, depth + 1);
}

function renderInline(nodes: Inline[], ctx: Ctx): ReactNode {
  return nodes.map((n, i) => <Fragment key={i}>{renderNode(n, ctx)}</Fragment>);
}

function renderNode(n: Inline, ctx: Ctx): ReactNode {
  switch (n.t) {
    case "text":
      return n.v;
    case "code":
      return <code className="md-code-inline">{n.v}</code>;
    case "em":
      return <em>{renderInline(n.c, ctx)}</em>;
    case "strong": {
      const text = plainText(n.c);
      const route = PAGE_ROUTES[text];
      if (route) {
        return (
          <Link className="md-page-link" to={route} title={`Open ${text}`}>
            <strong>{text}</strong>
          </Link>
        );
      }
      return <strong>{renderInline(n.c, ctx)}</strong>;
    }
    case "link": {
      const target = classifyLink(n.href);
      const label = renderInline(n.c, ctx);
      switch (target.kind) {
        case "external":
          return (
            <a href={target.href} target="_blank" rel="noreferrer">
              {label}
            </a>
          );
        case "anchor":
          return (
            <a
              href={`#${target.id}`}
              onClick={(e) => {
                e.preventDefault();
                scrollToHeading(ctx.mode, target.id);
              }}
            >
              {label}
            </a>
          );
        case "guide":
          if (ctx.mode === "panel") {
            return (
              <a
                href={`/guides/${target.slug}`}
                onClick={(e) => {
                  e.preventDefault();
                  ctx.openInPanel(target.slug);
                }}
              >
                {label}
              </a>
            );
          }
          return <Link to={`/guides/${target.slug}${target.id ? `#${target.id}` : ""}`}>{label}</Link>;
        case "index":
          return <Link to="/guides">{label}</Link>;
        case "app":
          return <Link to={target.to}>{label}</Link>;
        default:
          return (
            <span className="md-plain-link" title={`${n.href} is in the repository's docs folder`}>
              {label}
            </span>
          );
      }
    }
  }
}

function CodeBlock({ text, lang }: { text: string; lang: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text can still be selected by hand */
    }
  };
  return (
    <div className="md-code">
      <div className="md-code-bar">
        <span>{lang}</span>
        <button type="button" className="md-copy" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code data-lang={lang || undefined}>{text}</code>
      </pre>
    </div>
  );
}

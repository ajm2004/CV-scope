import type { Level } from "./content";
import type { GuideStatus } from "./state";

const LEVEL_BARS: Record<Level, number> = { Beginner: 1, Intermediate: 2, Advanced: 3 };

/** Three bars, filled up to the guide's level. */
export function DifficultyMeter({ level }: { level: Level }) {
  const n = LEVEL_BARS[level];
  return (
    <span className="difficulty" role="img" aria-label={`Level: ${level}`} title={level}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={i <= n ? "on" : ""} />
      ))}
    </span>
  );
}

export function StatusLabel({ status }: { status: GuideStatus }) {
  if (status === "done") return <span className="guide-status done">Done</span>;
  if (status === "started") return <span className="guide-status started">In progress</span>;
  return null;
}

export function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

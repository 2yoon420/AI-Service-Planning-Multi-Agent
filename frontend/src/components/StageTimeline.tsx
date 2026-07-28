// StageTimeline.tsx
import { STAGE_MARK, type ResolvedStage } from "../lib/stages";

export default function StageTimeline({ stages }: { stages: ResolvedStage[] }) {
  return (
    <ol className="stages">
      {stages.map((s) => (
        <li key={s.id} className={`stage stage-${s.state}`}>
          <span className="stage-mark" aria-hidden>{STAGE_MARK[s.state]}</span>
          <span className="stage-label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

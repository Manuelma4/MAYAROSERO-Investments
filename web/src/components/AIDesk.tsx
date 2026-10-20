import { useState } from "react";
import { api } from "../lib/api";
import type { AIAnalysis } from "../lib/types";
import { Hint } from "./Hint";
import { Badge, Spinner } from "./ui";

const TONE = { favorable: "up", neutral: "", avoid: "down" } as const;

/** "Ask the AI desk": a technical, news and fundamentals review, a bull vs bear debate, and a risk verdict. */
export function AIDesk({ symbol }: { symbol: string }) {
  const [res, setRes] = useState<AIAnalysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ask = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.aiAnalyze(symbol)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  if (!res) {
    return (
      <div className="ai-desk">
        <button className="btn small" onClick={ask} disabled={busy}>{busy ? <><Spinner /> The desk is reviewing…</> : "Ask the AI desk"}</button>
        <Hint>A team of AI analysts (technical, news, fundamentals, a bull and a bear, and a risk manager) reviews this stock using the app's data and gives a verdict with reasons. Needs a Claude API key on the server; about a few cents per review.</Hint>
        {err && <p className="muted small">{err}</p>}
      </div>
    );
  }
  return (
    <div className="ai-desk open">
      <div className="ai-head">
        <span className="kpi-label">AI desk verdict</span>
        <Badge tone={TONE[res.verdict]}>{res.verdict}</Badge>
        <span className="muted small">confidence {res.confidence}/100</span>
      </div>
      <p className="ai-summary">{res.summary}</p>
      <details>
        <summary className="muted small">Full review</summary>
        <dl className="ai-roles">
          <dt>Technical</dt><dd>{res.technical}</dd>
          <dt>News</dt><dd>{res.news}</dd>
          <dt>Fundamentals</dt><dd>{res.fundamentals}</dd>
          <dt className="up">Bull case</dt><dd>{res.bull_case}</dd>
          <dt className="down">Bear case</dt><dd>{res.bear_case}</dd>
          <dt>Main risk</dt><dd>{res.main_risk}</dd>
          <dt>Wrong if</dt><dd>{res.invalidation}</dd>
        </dl>
      </details>
      <p className="muted small">AI research, not advice. It can be wrong.</p>
    </div>
  );
}

"""
bench/report.py — HTML report generator

纯 Python 模板字符串,不依赖 Jinja。输出一个自包含 HTML 文件。
"""
from __future__ import annotations

from bench.schema import BenchCase, BenchOutput, BenchRun, BenchScore


def render_html_report(run: BenchRun) -> str:
    case_map = {c.id: c for c in run.cases}
    output_map = {o.case_id: o for o in run.outputs}
    score_map = {s.case_id: s for s in run.scores}

    # 汇总指标
    summary = _render_summary(run)
    cases_html = "\n".join(
        _render_case_block(case_map[o.case_id], o, score_map.get(o.case_id))
        for o in run.outputs
    )

    return _TEMPLATE.format(
        run_id=run.run_id,
        runner_name=run.runner_name,
        judge_name=run.judge_name,
        started_at=run.started_at.strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        cases=cases_html,
    )


def _render_summary(run: BenchRun) -> str:
    if not run.scores:
        return "<p>未评分</p>"

    return f"""
    <div class="summary-grid">
        <div class="metric">
            <div class="metric-label">Direction Accuracy</div>
            <div class="metric-value">{run.direction_accuracy * 100:.0f}%</div>
        </div>
        <div class="metric">
            <div class="metric-label">Grounding</div>
            <div class="metric-value">{run.avg_grounding:.2f}<span class="unit">/5</span></div>
        </div>
        <div class="metric">
            <div class="metric-label">Coverage</div>
            <div class="metric-value">{run.avg_coverage:.2f}<span class="unit">/5</span></div>
        </div>
        <div class="metric">
            <div class="metric-label">Reasoning</div>
            <div class="metric-value">{run.avg_reasoning:.2f}<span class="unit">/5</span></div>
        </div>
        <div class="metric">
            <div class="metric-label">Risk Aware</div>
            <div class="metric-value">{run.avg_risk:.2f}<span class="unit">/5</span></div>
        </div>
        <div class="metric highlight">
            <div class="metric-label">Overall</div>
            <div class="metric-value">{run.avg_overall:.2f}<span class="unit">/5</span></div>
        </div>
        <div class="metric">
            <div class="metric-label">Fail Rate</div>
            <div class="metric-value">{run.fail_rate * 100:.0f}%</div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Latency</div>
            <div class="metric-value">{run.total_latency_seconds:.0f}<span class="unit">s</span></div>
        </div>
    </div>
    """


def _render_case_block(case: BenchCase, output: BenchOutput, score: BenchScore | None) -> str:
    status_cls = "fail" if output.failed else ("match" if (score and score.direction_match) else "mismatch")

    score_section = ""
    if score:
        score_section = f"""
        <div class="scores">
            <div class="score-row">
                <span class="score-label">方向匹配</span>
                <span class="score-val {'ok' if score.direction_match else 'bad'}">
                    {'✅' if score.direction_match else '❌'}
                </span>
            </div>
            <div class="score-row">
                <span class="score-label">Grounding</span>
                <span class="score-val">{_stars(score.grounding_score)}</span>
            </div>
            <div class="score-row">
                <span class="score-label">Coverage</span>
                <span class="score-val">{_stars(score.coverage_score)}</span>
            </div>
            <div class="score-row">
                <span class="score-label">Reasoning</span>
                <span class="score-val">{_stars(score.reasoning_score)}</span>
            </div>
            <div class="score-row">
                <span class="score-label">Risk Aware</span>
                <span class="score-val">{_stars(score.risk_awareness_score)}</span>
            </div>
            <div class="score-row overall">
                <span class="score-label">Overall</span>
                <span class="score-val">{score.overall_score} / 5</span>
            </div>
            <div class="judge-comment">
                <strong>Judge:</strong> {_html_escape(score.judge_comment)}
            </div>
            {_render_failure_modes(score.failure_modes)}
        </div>
        """

    error_section = ""
    if output.error:
        error_section = f"""
        <div class="error">
            <strong>ERROR:</strong> <pre>{_html_escape(output.error)}</pre>
        </div>
        """

    return f"""
    <div class="case {status_cls}">
        <div class="case-header">
            <div class="case-id">{case.id}</div>
            <div class="case-sym">{case.symbol} · {case.name}</div>
            <div class="case-market">{case.market}</div>
            <div class="direction-box">
                <span class="exp-dir">预期: {case.expected_direction}</span>
                <span class="ai-dir">AI: {output.direction}</span>
            </div>
            <div class="latency">{output.latency_seconds:.1f}s</div>
        </div>

        <div class="case-body">
            <div class="case-left">
                <div class="section">
                    <h4>人工标注要点</h4>
                    <ul class="kp-list">
                        {"".join(f"<li>{_html_escape(p)}</li>" for p in case.key_points)}
                    </ul>
                </div>
                <div class="section">
                    <h4>人工风险点</h4>
                    <ul class="rp-list">
                        {"".join(f"<li>{_html_escape(p)}</li>" for p in case.risk_points)}
                    </ul>
                </div>
                <div class="section">
                    <h4>人工概述</h4>
                    <p class="analyst-notes">{_html_escape(case.analyst_notes)}</p>
                </div>
            </div>

            <div class="case-right">
                {error_section}
                <div class="section">
                    <h4>AI Decision</h4>
                    <p class="rationale">{_html_escape(output.rationale or "(无)")}</p>
                    <div class="confidence">Confidence: {output.confidence:.2f}</div>
                </div>

                <details>
                    <summary>分析师摘要 (展开)</summary>
                    <div class="analyst-section">
                        <strong>基本面:</strong>
                        <pre>{_html_escape(output.fundamental_summary or "(无)")}</pre>
                        <strong>技术面:</strong>
                        <pre>{_html_escape(output.technical_summary or "(无)")}</pre>
                        <strong>情绪面:</strong>
                        <pre>{_html_escape(output.sentiment_summary or "(无)")}</pre>
                    </div>
                </details>

                {f'<details><summary>RAG Context Preview</summary><pre class="rag">{_html_escape(output.rag_context_preview)}</pre></details>' if output.rag_context_preview else ''}

                {score_section}
            </div>
        </div>
    </div>
    """


def _render_failure_modes(modes: list[str]) -> str:
    if not modes:
        return ""
    tags = "".join(f'<span class="tag">{_html_escape(m)}</span>' for m in modes)
    return f'<div class="failure-modes"><strong>Failure Modes:</strong> {tags}</div>'


def _stars(n: int) -> str:
    full = "●" * n
    empty = "○" * (5 - n)
    return f'<span class="stars">{full}<span class="empty">{empty}</span></span> <span class="num">{n}</span>'


def _html_escape(s: str | None) -> str:
    if s is None:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ════════════════════════════════════════════════════════════════
# HTML template (inline,self-contained)
# ════════════════════════════════════════════════════════════════

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>CQ-Bench Report · {run_id}</title>
<style>
    :root {{
        --bg: hsl(228, 24%, 7%);
        --card: rgba(255,255,255,0.04);
        --border: rgba(255,255,255,0.08);
        --text: rgba(255,255,255,0.92);
        --text-2: rgba(255,255,255,0.65);
        --text-3: rgba(255,255,255,0.45);
        --primary: #4facfe;
        --cyan: #00f2fe;
        --mint: #5eead4;
        --warm: #ff9a56;
        --danger: #ff6b9d;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{
        background: var(--bg); color: var(--text);
        font-family: 'Inter', system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
        font-size: 14px; line-height: 1.5;
    }}
    body {{ padding: 40px; max-width: 1400px; margin: 0 auto; }}
    h1, h2, h3, h4 {{ font-weight: 700; }}
    header {{
        padding-bottom: 24px; margin-bottom: 32px;
        border-bottom: 1px solid var(--border);
    }}
    h1 {{ font-size: 32px; letter-spacing: -0.02em; }}
    .meta {{ color: var(--text-2); font-size: 12px; margin-top: 6px; font-family: 'JetBrains Mono', monospace; }}
    .meta span {{ margin-right: 16px; }}

    .summary-grid {{
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
        margin-bottom: 40px;
    }}
    .metric {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 12px; padding: 18px 20px;
    }}
    .metric.highlight {{ background: linear-gradient(135deg,rgba(79,172,254,0.12),rgba(0,242,254,0.04)); border-color: rgba(79,172,254,0.3); }}
    .metric-label {{ font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; font-family: 'JetBrains Mono', monospace; }}
    .metric-value {{ font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }}
    .unit {{ font-size: 14px; color: var(--text-3); margin-left: 4px; }}

    .cases-section h2 {{ font-size: 18px; margin-bottom: 16px; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.04em; }}

    .case {{
        background: var(--card); border: 1px solid var(--border);
        border-radius: 14px; margin-bottom: 18px; overflow: hidden;
    }}
    .case.match {{ border-left: 3px solid var(--mint); }}
    .case.mismatch {{ border-left: 3px solid var(--warm); }}
    .case.fail {{ border-left: 3px solid var(--danger); }}

    .case-header {{
        display: flex; align-items: center; gap: 16px;
        padding: 14px 20px; background: rgba(255,255,255,0.02);
        border-bottom: 1px solid var(--border);
    }}
    .case-id {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-3); }}
    .case-sym {{ font-size: 15px; font-weight: 700; flex: 1; }}
    .case-market {{ font-size: 10px; background: rgba(255,255,255,0.06); padding: 3px 8px; border-radius: 4px; color: var(--text-2); font-family: 'JetBrains Mono', monospace; }}
    .direction-box {{ display: flex; gap: 8px; font-size: 12px; }}
    .exp-dir {{ color: var(--text-2); }}
    .ai-dir {{ color: var(--cyan); font-weight: 700; }}
    .latency {{ font-size: 11px; color: var(--text-3); font-family: 'JetBrains Mono', monospace; }}

    .case-body {{ display: grid; grid-template-columns: 1fr 1.4fr; gap: 24px; padding: 20px; }}
    .section {{ margin-bottom: 18px; }}
    .section h4 {{
        font-size: 11px; text-transform: uppercase; color: var(--text-3);
        letter-spacing: 0.06em; margin-bottom: 8px; font-family: 'JetBrains Mono', monospace;
    }}
    .kp-list, .rp-list {{ list-style: none; padding-left: 0; }}
    .kp-list li {{ padding: 4px 0 4px 16px; position: relative; font-size: 13px; color: var(--text); }}
    .kp-list li::before {{ content: "◆"; position: absolute; left: 0; color: var(--mint); }}
    .rp-list li {{ padding: 4px 0 4px 16px; position: relative; font-size: 13px; color: var(--text-2); }}
    .rp-list li::before {{ content: "▲"; position: absolute; left: 0; color: var(--warm); }}
    .analyst-notes {{ font-size: 13px; color: var(--text-2); font-style: italic; line-height: 1.65; }}

    .rationale {{
        font-size: 14px; line-height: 1.7;
        background: rgba(255,255,255,0.03); padding: 14px 16px;
        border-radius: 8px; border-left: 2px solid var(--primary);
        white-space: pre-wrap;
    }}
    .confidence {{ font-size: 11px; color: var(--text-3); margin-top: 8px; font-family: 'JetBrains Mono', monospace; }}

    details {{ margin: 16px 0; }}
    details summary {{ cursor: pointer; font-size: 12px; color: var(--primary); padding: 4px 0; }}
    details pre {{
        white-space: pre-wrap; font-family: inherit; font-size: 12px;
        color: var(--text-2); padding: 10px; background: rgba(255,255,255,0.02);
        border-radius: 6px; margin-top: 6px;
    }}
    .analyst-section strong {{ display: block; margin-top: 10px; color: var(--text); font-size: 11px; text-transform: uppercase; }}

    .scores {{
        margin-top: 16px; padding-top: 16px;
        border-top: 1px solid var(--border);
    }}
    .score-row {{
        display: flex; justify-content: space-between; align-items: center;
        padding: 6px 0; font-size: 13px;
    }}
    .score-row.overall {{ border-top: 1px dashed var(--border); margin-top: 6px; padding-top: 10px; font-weight: 700; color: var(--cyan); }}
    .score-label {{ color: var(--text-2); }}
    .stars {{ font-family: monospace; letter-spacing: 2px; color: var(--cyan); }}
    .stars .empty {{ color: var(--text-3); }}
    .stars + .num {{ color: var(--text-3); font-size: 11px; margin-left: 6px; }}
    .ok {{ color: var(--mint); }}
    .bad {{ color: var(--danger); }}

    .judge-comment {{
        margin-top: 14px; padding: 10px 12px;
        background: rgba(79,172,254,0.06); border-radius: 6px;
        font-size: 12px; line-height: 1.6; color: var(--text-2);
    }}
    .judge-comment strong {{ color: var(--primary); }}

    .failure-modes {{ margin-top: 10px; font-size: 11px; color: var(--text-3); }}
    .failure-modes .tag {{
        display: inline-block; margin: 2px 4px 2px 0;
        padding: 2px 8px; background: rgba(255,107,157,0.12);
        color: var(--danger); border-radius: 10px;
        font-family: 'JetBrains Mono', monospace;
    }}

    .error {{
        background: rgba(255,107,157,0.08); border: 1px solid rgba(255,107,157,0.3);
        padding: 12px; border-radius: 8px; margin-bottom: 14px;
    }}
    .error pre {{ white-space: pre-wrap; font-size: 11px; color: var(--danger); margin-top: 4px; }}

    @media (max-width: 900px) {{
        body {{ padding: 20px; }}
        .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .case-body {{ grid-template-columns: 1fr; }}
    }}
</style>
</head>
<body>
<header>
    <h1>CQ-Bench Report</h1>
    <div class="meta">
        <span>Run ID: {run_id}</span>
        <span>Runner: {runner_name}</span>
        <span>Judge: {judge_name}</span>
        <span>Started: {started_at}</span>
    </div>
</header>
{summary}
<section class="cases-section">
    <h2>Cases</h2>
    {cases}
</section>
</body>
</html>"""

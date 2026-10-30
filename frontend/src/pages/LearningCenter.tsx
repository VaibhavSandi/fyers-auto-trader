import { useEffect, useState } from "react";
import { api } from "../api";

function todayMinus(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}
function today() {
  return new Date().toISOString().slice(0, 10);
}

const STATUS_CLASS: Record<string, string> = {
  ACTIVE: "pill good", VALIDATED: "pill good", SHADOW: "pill warn",
  RESEARCH: "pill", REJECTED: "pill bad", PAUSED: "pill warn",
};
const DECISION_CLASS: Record<string, string> = {
  PROMOTED: "badge-win", REJECTED: "badge-loss", INCONCLUSIVE: "muted",
};

export default function LearningCenter() {
  const [active, setActive] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [experiments, setExperiments] = useState<any[]>([]);
  const [diagnosis, setDiagnosis] = useState<any>(null);
  const [strategies, setStrategies] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [hypothesis, setHypothesis] = useState("Candidate strategy may outperform the current baseline");
  const [candidate, setCandidate] = useState("ema_crossover_v1");
  const [baseline, setBaseline] = useState("rule_based_v1");
  const [symbol, setSymbol] = useState("NSE:RELIANCE-EQ");
  const [start, setStart] = useState(todayMinus(30));
  const [end, setEnd] = useState(today());
  const [experimentResult, setExperimentResult] = useState<any>(null);

  const [mlVersionLabel, setMlVersionLabel] = useState("trade_outcome_v1");
  const [mlBusy, setMlBusy] = useState(false);
  const [mlResult, setMlResult] = useState<any>(null);
  const [mlError, setMlError] = useState<string | null>(null);

  function refresh() {
    api.listActiveVersions().then(setActive).catch(() => {});
    api.listModels().then(setModels).catch(() => {});
    api.listExperiments().then(setExperiments).catch(() => {});
    api.getStrategies().then(setStrategies).catch(() => {});
  }
  useEffect(refresh, []);

  async function handleRunExperiment() {
    setBusy(true);
    setError(null);
    setExperimentResult(null);
    try {
      const result = await api.runExperiment({
        hypothesis, candidate_strategy_name: candidate, baseline_strategy_name: baseline,
        symbol, timeframe: "5", start_date: start, end_date: end,
        train_days: 3, test_days: 2, embargo_days: 1, capital: 10000, risk_profile: "conservative",
      });
      setExperimentResult(result);
      refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDiagnose(strategyName?: string) {
    try {
      setDiagnosis(await api.diagnose(strategyName));
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleTrainModel() {
    setMlBusy(true);
    setMlError(null);
    setMlResult(null);
    try {
      const result = await api.trainModel(mlVersionLabel);
      setMlResult(result);
      refresh();
    } catch (e: any) {
      setMlError(e.message);
    } finally {
      setMlBusy(false);
    }
  }

  async function handleRollback(strategyName: string) {
    if (!window.confirm(`Roll back "${strategyName}" to its previous version? This only affects research bookkeeping, not live trading.`)) return;
    try {
      await api.rollbackStrategy(strategyName, "Manual rollback from Learning Center");
      refresh();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div>
      <div className="card">
        <h2>🧠 AI Learning Center</h2>
        <p className="muted">
          Every strategy version, every promote/reject decision, and why - the full audit trail of the
          self-learning loop. Nothing here changes live or paper trading automatically; promotion only
          updates this bookkeeping.
        </p>
        {error && <div className="error-box">{error}</div>}
      </div>

      <div className="card">
        <h3>Active Strategy Versions</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Strategy</th><th>Version</th><th>Promoted</th><th>Reason</th><th></th></tr></thead>
            <tbody>
              {active.map((a) => (
                <tr key={a.id}>
                  <td>{a.strategy_name}</td>
                  <td>{a.version_label}</td>
                  <td className="muted">{a.promoted_at ? new Date(a.promoted_at + "Z").toLocaleString() : "-"}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{a.promoted_reason}</td>
                  <td><button className="btn secondary" onClick={() => handleRollback(a.strategy_name)}>Rollback</button></td>
                </tr>
              ))}
              {active.length === 0 && <tr><td colSpan={5} className="muted">No strategy has been promoted to ACTIVE yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Run a Self-Learning Experiment</h3>
        <div className="grid-3">
          <div className="form-group">
            <label>Candidate Strategy</label>
            <select value={candidate} onChange={(e) => setCandidate(e.target.value)} style={{ width: "100%", padding: 12, borderRadius: 8, background: "#0c1019", color: "inherit", border: "1px solid var(--panel-border)" }}>
              {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Baseline Strategy</label>
            <select value={baseline} onChange={(e) => setBaseline(e.target.value)} style={{ width: "100%", padding: 12, borderRadius: 8, background: "#0c1019", color: "inherit", border: "1px solid var(--panel-border)" }}>
              {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Symbol</label>
            <input type="text" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Start Date</label>
            <input type="text" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="form-group">
            <label>End Date</label>
            <input type="text" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
        <div className="form-group">
          <label>Hypothesis</label>
          <input type="text" value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} />
        </div>
        <button className="btn" onClick={handleRunExperiment} disabled={busy}>Run Experiment</button>

        {experimentResult && (
          <div className={`info-box ${experimentResult.decision === "REJECTED" ? "error-box" : ""}`} style={{ marginTop: 14 }}>
            <b>Decision: {experimentResult.decision}</b> - {experimentResult.decision_reason}
          </div>
        )}
      </div>

      <div className="card">
        <h3>ML Trade-Outcome Model (Advisory Only)</h3>
        <p className="muted">
          Trains a classifier that predicts P(win) for a setup, using real completed backtest trades
          (never synthetic data). <b>Nothing in live or paper trading reads this model's output</b> - it
          exists purely for research/inspection. Needs at least 30 usable backtest trades across your
          runs in the Research Lab tab before it can train at all.
        </p>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Version label</label>
            <input type="text" value={mlVersionLabel} onChange={(e) => setMlVersionLabel(e.target.value)} />
          </div>
          <button className="btn" onClick={handleTrainModel} disabled={mlBusy}>
            {mlBusy ? "Training..." : "Train Model"}
          </button>
        </div>
        {mlError && <div className="error-box" style={{ marginTop: 14 }}>{mlError}</div>}
        {mlResult && (
          <div className="info-box" style={{ marginTop: 14 }}>
            <b>Trained on {mlResult.training_data_summary.sample_size} examples.</b>{" "}
            Accuracy {mlResult.training_data_summary.accuracy}
            {mlResult.training_data_summary.roc_auc != null && <> · ROC-AUC {mlResult.training_data_summary.roc_auc}</>}
            {mlResult.training_data_summary.brier_score != null && <> · Brier {mlResult.training_data_summary.brier_score}</>}
            {mlResult.training_data_summary.warning && (
              <div className="muted" style={{ marginTop: 6 }}>⚠ {mlResult.training_data_summary.warning}</div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3>All Model / Strategy Versions</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Strategy</th><th>Version</th><th>Kind</th><th>Status</th><th>Metrics</th><th>Created</th></tr></thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td>{m.strategy_name}</td>
                  <td>{m.version_label}</td>
                  <td>{m.kind}</td>
                  <td><span className={STATUS_CLASS[m.status] ?? "pill"}>{m.status}</span></td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {m.kind === "ml_classifier" && m.training_data_summary
                      ? `n=${m.training_data_summary.sample_size}, acc=${m.training_data_summary.accuracy}` +
                        (m.training_data_summary.roc_auc != null ? `, AUC=${m.training_data_summary.roc_auc}` : "")
                      : "-"}
                  </td>
                  <td className="muted">{new Date(m.created_at + "Z").toLocaleString()}</td>
                </tr>
              ))}
              {models.length === 0 && <tr><td colSpan={6} className="muted">No model versions yet - train or run an experiment.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Learning Experiments Log</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Hypothesis</th><th>Strategy</th><th>Decision</th><th>Reason</th><th>When</th></tr></thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id}>
                  <td style={{ maxWidth: 220 }}>{e.hypothesis}</td>
                  <td>{e.strategy_name}</td>
                  <td className={DECISION_CLASS[e.decision] ?? ""}>{e.decision}</td>
                  <td className="muted" style={{ fontSize: 12, maxWidth: 260 }}>{e.decision_reason}</td>
                  <td className="muted">{e.decided_at ? new Date(e.decided_at + "Z").toLocaleString() : "-"}</td>
                </tr>
              ))}
              {experiments.length === 0 && <tr><td colSpan={5} className="muted">No experiments run yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Diagnose Trade Outcomes</h3>
        <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
          <button className="btn secondary" onClick={() => handleDiagnose()}>All Strategies</button>
          {strategies.map((s) => (
            <button key={s.name} className="btn secondary" onClick={() => handleDiagnose(s.name)}>{s.name}</button>
          ))}
        </div>
        {diagnosis && (
          <div className="grid-3">
            <div>
              <h4>By Market Regime</h4>
              {Object.entries(diagnosis.by_market_regime).map(([k, v]: [string, any]) => (
                <div key={k} className="status-row"><span>{k}</span><span>{v.win_rate}% ({v.total})</span></div>
              ))}
            </div>
            <div>
              <h4>By Exit Reason</h4>
              {Object.entries(diagnosis.by_exit_reason).map(([k, v]: [string, any]) => (
                <div key={k} className="status-row"><span>{k}</span><span>{v.win_rate}% ({v.total})</span></div>
              ))}
            </div>
            <div>
              <h4>By Strategy Score</h4>
              {Object.entries(diagnosis.by_strategy_score_band).map(([k, v]: [string, any]) => (
                <div key={k} className="status-row"><span>{k}</span><span>{v.win_rate}% ({v.total})</span></div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

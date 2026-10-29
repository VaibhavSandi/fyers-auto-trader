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

export default function ResearchLab() {
  const [dataStatus, setDataStatus] = useState<any[]>([]);
  const [strategies, setStrategies] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [syncDays, setSyncDays] = useState(60);

  const [btSymbol, setBtSymbol] = useState("NSE:RELIANCE-EQ");
  const [btStrategy, setBtStrategy] = useState("rule_based_v1");
  const [btStart, setBtStart] = useState(todayMinus(30));
  const [btEnd, setBtEnd] = useState(today());
  const [btCapital, setBtCapital] = useState(10000);
  const [btProfile, setBtProfile] = useState("conservative");
  const [btResult, setBtResult] = useState<any>(null);

  const [wfTrainDays, setWfTrainDays] = useState(3);
  const [wfTestDays, setWfTestDays] = useState(2);
  const [wfEmbargoDays, setWfEmbargoDays] = useState(1);
  const [wfResult, setWfResult] = useState<any>(null);

  function refresh() {
    api.getDataStatus().then(setDataStatus).catch(() => {});
    api.getStrategies().then(setStrategies).catch(() => {});
    api.listBacktests().then(setRuns).catch(() => {});
  }

  useEffect(refresh, []);

  async function handleSync() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.syncData({ timeframe: "5", days: syncDays });
      alert(`Sync started in the background for ${result.symbols} symbols (${syncDays} days). Refresh in a bit to see updated coverage.`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunBacktest() {
    setBusy(true);
    setError(null);
    setBtResult(null);
    try {
      const result = await api.runBacktest({
        symbol: btSymbol, timeframe: "5", start_date: btStart, end_date: btEnd,
        capital: btCapital, risk_profile: btProfile, strategy_name: btStrategy,
      });
      setBtResult(result);
      refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunWalkForward() {
    setBusy(true);
    setError(null);
    setWfResult(null);
    try {
      const result = await api.runWalkForward({
        symbol: btSymbol, timeframe: "5", start_date: btStart, end_date: btEnd,
        train_days: wfTrainDays, test_days: wfTestDays, embargo_days: wfEmbargoDays,
        capital: btCapital, risk_profile: btProfile, strategy_name: btStrategy,
      });
      setWfResult(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="card">
        <h2>🔬 Research Lab</h2>
        <p className="muted">
          Sync real historical data from FYERS, then backtest or walk-forward validate any registered
          strategy against it. Nothing here places real or paper orders - it only reads/writes the local
          research database.
        </p>
        {error && <div className="error-box">{error}</div>}
      </div>

      <div className="card">
        <h3>Historical Data Coverage</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Symbol</th><th>Earliest</th><th>Latest</th><th>Candles</th><th>Status</th><th>Last Sync</th></tr></thead>
            <tbody>
              {dataStatus.map((d) => (
                <tr key={d.symbol}>
                  <td>{d.symbol.replace("NSE:", "").replace("-EQ", "").replace("-INDEX", "")}</td>
                  <td>{d.earliest_synced ? new Date(d.earliest_synced + "Z").toLocaleDateString() : "-"}</td>
                  <td>{d.latest_synced ? new Date(d.latest_synced + "Z").toLocaleDateString() : "-"}</td>
                  <td>{d.candles_stored}</td>
                  <td className={d.last_sync_status === "OK" ? "badge-win" : "badge-loss"}>{d.last_sync_status}</td>
                  <td className="muted">{d.last_sync_at ? new Date(d.last_sync_at + "Z").toLocaleString() : "-"}</td>
                </tr>
              ))}
              {dataStatus.length === 0 && <tr><td colSpan={6} className="muted">No data synced yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14, alignItems: "flex-end" }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Days of history to sync (full universe + indices)</label>
            <input type="number" value={syncDays} onChange={(e) => setSyncDays(Number(e.target.value))} />
          </div>
          <button className="btn" onClick={handleSync} disabled={busy}>Sync Now</button>
        </div>
      </div>

      <div className="card">
        <h3>Run a Backtest / Walk-Forward Validation</h3>
        <div className="grid-3">
          <div className="form-group">
            <label>Symbol</label>
            <input type="text" value={btSymbol} onChange={(e) => setBtSymbol(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Strategy</label>
            <select value={btStrategy} onChange={(e) => setBtStrategy(e.target.value)} style={{ width: "100%", padding: 12, borderRadius: 8, background: "#0c1019", color: "inherit", border: "1px solid var(--panel-border)" }}>
              {strategies.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.family})</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Risk Profile</label>
            <select value={btProfile} onChange={(e) => setBtProfile(e.target.value)} style={{ width: "100%", padding: 12, borderRadius: 8, background: "#0c1019", color: "inherit", border: "1px solid var(--panel-border)" }}>
              <option value="conservative">Conservative</option>
              <option value="balanced">Balanced</option>
              <option value="aggressive">Aggressive</option>
            </select>
          </div>
          <div className="form-group">
            <label>Start Date</label>
            <input type="text" value={btStart} onChange={(e) => setBtStart(e.target.value)} />
          </div>
          <div className="form-group">
            <label>End Date</label>
            <input type="text" value={btEnd} onChange={(e) => setBtEnd(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Capital (Rs.)</label>
            <input type="number" value={btCapital} onChange={(e) => setBtCapital(Number(e.target.value))} />
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
          <button className="btn" onClick={handleRunBacktest} disabled={busy}>Run Single Backtest</button>
        </div>

        {btResult && (
          <div className="info-box">
            <b>Result (run #{btResult.run_id}):</b> {btResult.trade_count} trades, net P&amp;L{" "}
            <b className={btResult.metrics.net_pnl >= 0 ? "badge-win" : "badge-loss"}>Rs.{btResult.metrics.net_pnl}</b>,
            win rate {btResult.metrics.win_rate}%, profit factor {btResult.metrics.profit_factor}, max drawdown{" "}
            {btResult.metrics.max_drawdown_pct}%
            {btResult.warnings.length > 0 && (
              <div className="muted" style={{ marginTop: 6 }}>⚠ {btResult.warnings.join(" | ")}</div>
            )}
          </div>
        )}

        <hr style={{ borderColor: "var(--panel-border)", margin: "18px 0" }} />
        <h3 style={{ marginTop: 0 }}>Walk-Forward (purged, out-of-sample)</h3>
        <div className="grid-3">
          <div className="form-group">
            <label>Train days</label>
            <input type="number" value={wfTrainDays} onChange={(e) => setWfTrainDays(Number(e.target.value))} />
          </div>
          <div className="form-group">
            <label>Embargo days</label>
            <input type="number" value={wfEmbargoDays} onChange={(e) => setWfEmbargoDays(Number(e.target.value))} />
          </div>
          <div className="form-group">
            <label>Test days</label>
            <input type="number" value={wfTestDays} onChange={(e) => setWfTestDays(Number(e.target.value))} />
          </div>
        </div>
        <button className="btn secondary" onClick={handleRunWalkForward} disabled={busy}>Run Walk-Forward</button>

        {wfResult && (
          <div className="info-box" style={{ marginTop: 14 }}>
            <b>{wfResult.aggregate.fold_count} out-of-sample folds</b> - {wfResult.aggregate.profitable_fold_pct}% profitable.
            Combined: {wfResult.aggregate.overall_out_of_sample?.total_trades} trades, net P&amp;L{" "}
            <b className={(wfResult.aggregate.overall_out_of_sample?.net_pnl ?? 0) >= 0 ? "badge-win" : "badge-loss"}>
              Rs.{wfResult.aggregate.overall_out_of_sample?.net_pnl}
            </b>. Beat buy-and-hold baseline by Rs.{wfResult.aggregate.beat_baseline}.
            {wfResult.warnings.length > 0 && (
              <div className="muted" style={{ marginTop: 6 }}>⚠ {wfResult.warnings.slice(0, 3).join(" | ")}</div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3>Strategy Leaderboard - Recent Backtest Runs</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Symbol</th><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>Net P&amp;L</th>
                <th>Profit Factor</th><th>Max DD</th><th>Status</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.symbol.replace("NSE:", "").replace("-EQ", "")}</td>
                  <td>{r.strategy_name}</td>
                  <td>{r.total_trades}</td>
                  <td>{r.win_rate}%</td>
                  <td className={r.net_pnl >= 0 ? "badge-win" : "badge-loss"}>Rs.{r.net_pnl}</td>
                  <td>{r.profit_factor}</td>
                  <td>{r.max_drawdown_pct}%</td>
                  <td>{r.status}</td>
                </tr>
              ))}
              {runs.length === 0 && <tr><td colSpan={8} className="muted">No backtests run yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api";

export default function Journal() {
  const [trades, setTrades] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any>(null);
  const [signals, setSignals] = useState<any[]>([]);
  const [activity, setActivity] = useState<any[]>([]);
  const [tab, setTab] = useState<"trades" | "signals" | "activity">("activity");

  useEffect(() => {
    api.getTrades().then(setTrades).catch(() => {});
    api.getAnalytics().then(setAnalytics).catch(() => {});
    api.getSignals().then(setSignals).catch(() => {});
    api.getEngineActivity().then(setActivity).catch(() => {});
    const interval = setInterval(() => {
      api.getEngineActivity().then(setActivity).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      {analytics && (
        <div className="card">
          <h2>Performance</h2>
          <div className="grid-3">
            <div className="stat"><span className="label">Trading Days</span><span className="value">{analytics.trading_days}</span></div>
            <div className="stat"><span className="label">Total Trades</span><span className="value">{analytics.total_trades}</span></div>
            <div className="stat"><span className="label">Win Rate</span><span className="value">{analytics.win_rate}%</span></div>
            <div className="stat">
              <span className="label">Net P&amp;L</span>
              <span className={`value ${analytics.net_pnl >= 0 ? "positive" : "negative"}`}>₹{analytics.net_pnl.toFixed(2)}</span>
            </div>
            <div className="stat"><span className="label">Max Drawdown</span><span className="value negative">₹{analytics.max_drawdown.toFixed(2)}</span></div>
            <div className="stat"><span className="label">Profit Factor</span><span className="value">{analytics.profit_factor}</span></div>
            <div className="stat"><span className="label">Avg Win</span><span className="value positive">₹{analytics.avg_win.toFixed(2)}</span></div>
            <div className="stat"><span className="label">Avg Loss</span><span className="value negative">₹{analytics.avg_loss.toFixed(2)}</span></div>
          </div>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <button className={`btn ${tab === "activity" ? "" : "secondary"}`} onClick={() => setTab("activity")}>Live Activity Log</button>
          <button className={`btn ${tab === "trades" ? "" : "secondary"}`} onClick={() => setTab("trades")}>Trade Journal</button>
          <button className={`btn ${tab === "signals" ? "" : "secondary"}`} onClick={() => setTab("signals")}>Recent Signals</button>
        </div>

        {tab === "activity" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Time</th><th>Action</th><th>Regime</th><th>Scanned</th><th>Eligible</th><th>Message</th></tr>
              </thead>
              <tbody>
                {activity.map((a) => (
                  <tr key={a.id}>
                    <td>{new Date(a.created_at + "Z").toLocaleTimeString()}</td>
                    <td>{a.action ?? a.stage}</td>
                    <td>{a.market_regime ?? "-"}</td>
                    <td>{a.universe_size ?? "-"}</td>
                    <td>{a.eligible_count ?? "-"}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{a.message}</td>
                  </tr>
                ))}
                {activity.length === 0 && (
                  <tr><td colSpan={6} className="muted">No activity recorded yet - the engine logs one entry per ~20s tick.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ) : tab === "trades" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Qty</th>
                  <th>Exit Reason</th><th>Net P&amp;L</th><th>R:R</th><th>Score</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.date}</td>
                    <td>{t.symbol.replace("NSE:", "").replace("-EQ", "")}</td>
                    <td>{t.direction}</td>
                    <td>{t.entry_price?.toFixed(2)}</td>
                    <td>{t.exit_price?.toFixed(2)}</td>
                    <td>{t.quantity}</td>
                    <td>{t.exit_reason}</td>
                    <td className={t.net_pnl >= 0 ? "badge-win" : "badge-loss"}>₹{t.net_pnl?.toFixed(2)}</td>
                    <td>{t.risk_reward ?? "-"}</td>
                    <td>{t.strategy_score ?? "-"}/10</td>
                  </tr>
                ))}
                {trades.length === 0 && (
                  <tr><td colSpan={10} className="muted">No trades recorded yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Symbol</th><th>Direction</th><th>Score</th><th>Passed</th><th>Regime</th><th>Rejected Reason</th></tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.id}>
                    <td>{s.symbol.replace("NSE:", "").replace("-EQ", "")}</td>
                    <td>{s.direction}</td>
                    <td>{s.score}/{s.max_score}</td>
                    <td>{s.passed ? "✅" : "❌"}</td>
                    <td>{s.market_regime}</td>
                    <td className="muted">{s.rejected_reason ?? "-"}</td>
                  </tr>
                ))}
                {signals.length === 0 && (
                  <tr><td colSpan={6} className="muted">No signals evaluated yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

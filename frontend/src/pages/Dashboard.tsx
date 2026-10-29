import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDashboardSocket } from "../useDashboardSocket";
import EmergencyStop from "../components/EmergencyStop";
import CurrentTrade from "../components/CurrentTrade";
import TodaySummary from "../components/TodaySummary";
import SystemHealth from "../components/SystemHealth";
import LiveActivity from "../components/LiveActivity";

const RISK_STATUS_LABEL: Record<string, { text: string; dot: string }> = {
  SAFE: { text: "🟢 SAFE", dot: "green" },
  CAUTION: { text: "🟡 CAUTION", dot: "yellow" },
  STOPPED_DAILY_LOSS_LIMIT: { text: "🔴 DAILY LOSS LIMIT HIT", dot: "red" },
  EMERGENCY_STOP: { text: "🔴 EMERGENCY STOP", dot: "red" },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: liveData, connected } = useDashboardSocket();
  const [dashboard, setDashboard] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Initial load, so something shows up before the first WebSocket push.
  useEffect(() => {
    api.getDashboard().then(setDashboard).catch(() => {});
  }, []);

  // Every WebSocket push updates the SAME state a manual refresh() does -
  // last write wins. Previously this page kept the WebSocket's snapshot
  // forever once it arrived once, even if the socket later stalled - a
  // manual refresh() (e.g. right after deactivating the kill switch) would
  // silently be overwritten by the next stale-but-still-arriving push.
  useEffect(() => {
    if (liveData) setDashboard(liveData);
  }, [liveData]);

  useEffect(() => {
    if (dashboard?.setup_required) navigate("/setup");
  }, [dashboard, navigate]);

  if (!dashboard || dashboard.setup_required) {
    return <div className="card">Loading...</div>;
  }

  async function refresh() {
    try {
      setDashboard(await api.getDashboard());
    } catch {
      /* ignore */
    }
  }

  async function handleToggleAutoTrading() {
    setBusy(true);
    setError(null);
    try {
      if (dashboard.auto_trading_active) {
        await api.stopAutoTrading();
      } else {
        await api.startAutoTrading();
      }
      await refresh();
    } catch (e: any) {
      setError(typeof e.message === "string" ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const risk = RISK_STATUS_LABEL[dashboard.risk_status] ?? { text: dashboard.risk_status, dot: "gray" };

  return (
    <div>
      {!connected && <div className="muted" style={{ marginBottom: 10 }}>Reconnecting live updates...</div>}
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <div className="grid-3">
          <div className="stat">
            <span className="label">Capital</span>
            <span className="value">₹{dashboard.capital.toLocaleString("en-IN")}</span>
          </div>
          <div className="stat">
            <span className="label">Today's P&amp;L</span>
            <span className={`value ${dashboard.todays_pnl >= 0 ? "positive" : "negative"}`}>
              {dashboard.todays_pnl >= 0 ? "+" : ""}₹{dashboard.todays_pnl.toFixed(2)}
            </span>
          </div>
          <div className="stat">
            <span className="label">Available Capital</span>
            <span className="value">₹{dashboard.available_capital.toLocaleString("en-IN")}</span>
          </div>
        </div>

        <hr style={{ borderColor: "var(--panel-border)", margin: "16px 0" }} />

        <div className="status-row">
          <span>Market Status</span>
          <span className="status-badge">
            <span className={`dot ${dashboard.market_status === "OPEN" ? "green" : "gray"}`} />
            {dashboard.market_status === "OPEN" ? "🟢 OPEN" : "⚪ CLOSED"}
          </span>
        </div>
        <div className="status-row">
          <span>Auto Trading</span>
          <span className="status-badge">
            <span className={`dot ${dashboard.auto_trading_active ? "green" : "gray"}`} />
            {dashboard.auto_trading_active ? "🟢 ACTIVE" : "⚪ PAUSED"}
          </span>
        </div>
        <div className="status-row">
          <span>Risk Status</span>
          <span className="status-badge">
            <span className={`dot ${risk.dot}`} />
            {risk.text}
          </span>
        </div>

        <button className="btn secondary" style={{ width: "100%", marginTop: 12 }} onClick={handleToggleAutoTrading} disabled={busy || dashboard.kill_switch_active}>
          {dashboard.auto_trading_active ? "Pause Auto Trading" : "Resume Auto Trading"}
        </button>
      </div>

      <EmergencyStop killSwitchActive={dashboard.kill_switch_active} onChanged={refresh} />

      {dashboard.current_trades.length > 0 ? (
        dashboard.current_trades.map((t: any) => <CurrentTrade key={t.symbol} trade={t} />)
      ) : (
        <div className="card">
          <h3>Current Trade</h3>
          {dashboard.no_trade_reason ? (
            <div className="error-box" style={{ marginBottom: 0 }}>
              Not trading right now: <b>{dashboard.no_trade_reason}</b>
            </div>
          ) : (
            <p className="muted" style={{ marginBottom: 0 }}>
              No open position right now. See exactly what it's doing below.
            </p>
          )}
        </div>
      )}

      <LiveActivity activity={dashboard.latest_activity} />
      <div className="muted" style={{ textAlign: "center", marginTop: -8, marginBottom: 16 }}>
        <Link to="/journal">See the full history of every scan, signal and trade →</Link>
      </div>

      <TodaySummary today={dashboard.today} />

      <div className="advanced-toggle">
        <button className="btn secondary" onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? "Hide Advanced" : "Show Advanced"}
        </button>
      </div>

      {showAdvanced && (
        <>
          <SystemHealth health={dashboard.system_health} />
          <div className="card">
            <h3>Current Settings</h3>
            <p className="muted">Risk profile: <b>{dashboard.risk_profile}</b></p>
            <ul className="muted">
              <li>Max risk per trade: {dashboard.settings.max_risk_per_trade_pct}%</li>
              <li>Max daily loss: {dashboard.settings.max_daily_loss_pct}% (₹{dashboard.daily_loss_limit_amount})</li>
              <li>Max trades/day: {dashboard.settings.max_trades_per_day}</li>
              <li>Max open positions: {dashboard.settings.max_open_positions}</li>
              <li>Min risk/reward: {dashboard.settings.min_risk_reward}:1</li>
              <li>Max consecutive losses before pause: {dashboard.settings.max_consecutive_losses}</li>
            </ul>
            <Link to="/setup" className="btn secondary">Edit Settings</Link>
          </div>
          <div className="card">
            <p className="muted">
              More detail (all scanned signals, risk events, system events) is available on the{" "}
              <Link to="/journal">Journal &amp; Analytics</Link> page.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

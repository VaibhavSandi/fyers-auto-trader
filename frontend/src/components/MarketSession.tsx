export default function MarketSession({ dashboard }: { dashboard: any }) {
  const openingProtection = dashboard.opening_protection_active;
  const activity = dashboard.latest_activity;
  const lastScan = dashboard.last_scan;
  const fyersStatus = (dashboard.system_health ?? []).find((h: any) => h.component === "FYERS_API");
  const dataStatus = (dashboard.system_health ?? []).find((h: any) => h.component === "LIVE_DATA");

  return (
    <div className="card">
      <h3>📡 Market Session</h3>
      <div className="grid-3" style={{ marginBottom: 10 }}>
        <div className="stat">
          <span className="label">Analysis</span>
          <span className="value" style={{ fontSize: 16 }}>
            {dashboard.market_status === "OPEN" ? "🟢 RUNNING" : "⚪ IDLE (market closed)"}
          </span>
        </div>
        <div className="stat">
          <span className="label">Opening Protection</span>
          <span className="value" style={{ fontSize: 16 }}>
            {openingProtection ? "🟡 ACTIVE" : "🟢 COMPLETE"}
          </span>
        </div>
        <div className="stat">
          <span className="label">Trading</span>
          <span className="value" style={{ fontSize: 16 }}>
            {dashboard.auto_trading_active ? "🟢 ENABLED" : "⚪ DISABLED"}
          </span>
        </div>
      </div>
      <div className="grid-3" style={{ marginBottom: 10 }}>
        <div className="stat">
          <span className="label">Candidates Found</span>
          <span className="value" style={{ fontSize: 16 }}>{activity?.eligible_count ?? "-"}</span>
        </div>
        <div className="stat">
          <span className="label">Best Candidate</span>
          <span className="value" style={{ fontSize: 16 }}>
            {lastScan ? `${lastScan.symbol} (${lastScan.score}/${lastScan.max_score})` : "-"}
          </span>
        </div>
        <div className="stat">
          <span className="label">Market Regime</span>
          <span className="value" style={{ fontSize: 16 }}>{activity?.market_regime ?? "-"}</span>
        </div>
      </div>
      <div className="status-row">
        <span>API Status</span>
        <span className="status-badge">
          <span className={`dot ${fyersStatus?.status === "CONNECTED" ? "green" : "red"}`} />
          {fyersStatus?.status ?? "UNKNOWN"}
        </span>
      </div>
      <div className="status-row">
        <span>Data Stream</span>
        <span className="status-badge">
          <span className={`dot ${dataStatus?.status === "CONNECTED" ? "green" : "red"}`} />
          {dataStatus?.status ?? "UNKNOWN"}
        </span>
      </div>
      <div className="status-row">
        <span>Kill Switch</span>
        <span className="status-badge">
          <span className={`dot ${dashboard.kill_switch_active ? "red" : "green"}`} />
          {dashboard.kill_switch_active ? "ACTIVE" : "OFF"}
        </span>
      </div>
      <div className="status-row">
        <span>ML Model</span>
        <span className="muted" style={{ fontSize: 12 }}>
          {dashboard.ml_status === "advisory_only" ? "Advisory only - not used in ranking" : dashboard.ml_status}
        </span>
      </div>
    </div>
  );
}

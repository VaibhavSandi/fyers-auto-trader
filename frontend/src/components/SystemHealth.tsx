const STATUS_DOT: Record<string, string> = {
  HEALTHY: "green",
  OK: "green",
  CONNECTED: "green",
  DEGRADED: "yellow",
  STALE_DATA: "yellow",
  RATE_LIMITED: "yellow",
  DOWN: "red",
  DISCONNECTED: "red",
  UNKNOWN: "gray",
};

const LABELS: Record<string, string> = {
  FYERS_API: "FYERS API",
  LIVE_DATA: "Live Data",
  STRATEGY: "Strategy",
  RISK_ENGINE: "Risk Engine",
  ORDER_MANAGER: "Order Manager",
  POSITION_SYNC: "Position Sync",
  DATABASE: "Database",
  ENGINE: "Trading Engine",
};

export default function SystemHealth({ health }: { health: { component: string; status: string; message?: string }[] }) {
  return (
    <div className="card">
      <h3>System Health</h3>
      {health.map((h) => (
        <div className="status-row" key={h.component}>
          <span>{LABELS[h.component] ?? h.component}</span>
          <span className="status-badge">
            <span className={`dot ${STATUS_DOT[h.status] ?? "gray"}`} />
            {h.status}
          </span>
        </div>
      ))}
    </div>
  );
}

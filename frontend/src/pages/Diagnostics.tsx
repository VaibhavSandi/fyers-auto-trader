import { useEffect, useState } from "react";
import { api } from "../api";

function Bar({ used, limit }: { used: number; limit: number }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const color = pct >= 90 ? "var(--red)" : pct >= 70 ? "var(--yellow)" : "var(--green)";
  return (
    <div style={{ background: "#0c1019", borderRadius: 6, height: 8, overflow: "hidden", marginTop: 4 }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color }} />
    </div>
  );
}

export default function Diagnostics() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    const load = () => api.getDiagnostics().then(setData).catch(() => {});
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!data) return <div className="card">Loading diagnostics...</div>;

  return (
    <div>
      <div className="card">
        <h2>Diagnostics</h2>
        <p className="muted">
          Live view of exactly how much of FYERS' API quota is being used, the WebSocket feed's
          health, and the shared price cache - this is the "show me the plumbing" screen behind the
          simple dashboard.
        </p>
      </div>

      <div className="card">
        <h3>WebSocket Live Feed</h3>
        <div className="grid-3">
          <div className="stat">
            <span className="label">Status</span>
            <span className="value" style={{ fontSize: 16 }}>{data.websocket.status}</span>
          </div>
          <div className="stat">
            <span className="label">Subscribed Symbols</span>
            <span className="value" style={{ fontSize: 16 }}>{data.websocket.subscribed_symbol_count}</span>
          </div>
          <div className="stat">
            <span className="label">Connected For</span>
            <span className="value" style={{ fontSize: 16 }}>
              {data.websocket.connected_seconds != null ? `${Math.round(data.websocket.connected_seconds)}s` : "-"}
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Price Cache</h3>
        <div className="grid-3">
          <div className="stat">
            <span className="label">Symbols Cached</span>
            <span className="value" style={{ fontSize: 16 }}>{data.price_cache.symbol_count}</span>
          </div>
          <div className="stat">
            <span className="label">Freshest Tick</span>
            <span className="value" style={{ fontSize: 16 }}>
              {data.price_cache.newest_age_seconds != null ? `${data.price_cache.newest_age_seconds}s ago` : "-"}
            </span>
          </div>
          <div className="stat">
            <span className="label">Oldest Tick</span>
            <span className="value" style={{ fontSize: 16 }}>
              {data.price_cache.oldest_age_seconds != null ? `${data.price_cache.oldest_age_seconds}s ago` : "-"}
            </span>
          </div>
        </div>
      </div>

      {Object.entries(data.rate_limits).map(([category, stats]: [string, any]) => (
        <div className="card" key={category}>
          <h3>FYERS Rate Limit - {category === "data" ? "Data APIs (quotes/history)" : "Transaction APIs (orders/positions)"}</h3>
          <div className="grid-3">
            <div>
              <span className="muted">Per second: {stats.per_sec_used}/{stats.per_sec_limit}</span>
              <Bar used={stats.per_sec_used} limit={stats.per_sec_limit} />
            </div>
            <div>
              <span className="muted">Per minute: {stats.per_min_used}/{stats.per_min_limit}</span>
              <Bar used={stats.per_min_used} limit={stats.per_min_limit} />
            </div>
            <div>
              <span className="muted">Per day: {stats.per_day_used}/{stats.per_day_limit}</span>
              <Bar used={stats.per_day_used} limit={stats.per_day_limit} />
            </div>
          </div>
          {stats.backing_off && (
            <div className="error-box" style={{ marginTop: 12 }}>
              Backing off for {stats.backoff_seconds_remaining}s after: {stats.last_error}
            </div>
          )}
          {Object.keys(stats.calls_by_caller).length > 0 && (
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table>
                <thead><tr><th>Module</th><th>Requests</th></tr></thead>
                <tbody>
                  {Object.entries(stats.calls_by_caller).map(([caller, count]: [string, any]) => (
                    <tr key={caller}><td>{caller}</td><td>{count}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      <div className="card">
        <h3>Recent Rate-Limit Errors</h3>
        {data.recent_rate_limit_events.length === 0 ? (
          <p className="muted">None - good sign.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Component</th><th>Message</th></tr></thead>
              <tbody>
                {data.recent_rate_limit_events.map((e: any, i: number) => (
                  <tr key={i}>
                    <td>{new Date(e.created_at + "Z").toLocaleTimeString()}</td>
                    <td>{e.component}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

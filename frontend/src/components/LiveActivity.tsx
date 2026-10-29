const ACTION_LABEL: Record<string, string> = {
  NO_TRADE: "No trade",
  ENTERED_BUY: "✅ Entered BUY",
  ENTERED_SELL: "✅ Entered SELL",
  REJECTED: "Rejected",
  ERROR: "⚠️ Error",
};

function timeAgo(iso: string) {
  const diffSec = Math.max(0, Math.round((Date.now() - new Date(iso + "Z").getTime()) / 1000));
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  return `${Math.round(diffSec / 60)}m ago`;
}

export default function LiveActivity({ activity }: { activity: any }) {
  if (!activity) {
    return (
      <div className="card">
        <h3>🔎 Live Activity</h3>
        <p className="muted">Waiting for the first scan cycle (runs every ~20 seconds once connected)...</p>
      </div>
    );
  }

  const candidates = activity.candidates ?? [];

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>🔎 Live Activity</h3>
        <span className="muted">{timeAgo(activity.created_at)}</span>
      </div>

      <p style={{ marginTop: 10, marginBottom: 10 }}>
        <b>{ACTION_LABEL[activity.action] ?? activity.action ?? "..."}</b>
        {activity.message ? ` - ${activity.message}` : ""}
      </p>

      <div className="grid-3" style={{ marginBottom: 10 }}>
        <div className="stat">
          <span className="label">Market Regime</span>
          <span className="value" style={{ fontSize: 16 }}>{activity.market_regime ?? "-"}</span>
        </div>
        <div className="stat">
          <span className="label">Stocks Scanned</span>
          <span className="value" style={{ fontSize: 16 }}>{activity.universe_size ?? "-"}</span>
        </div>
        <div className="stat">
          <span className="label">Passed Filters</span>
          <span className="value" style={{ fontSize: 16 }}>{activity.eligible_count ?? "-"}</span>
        </div>
      </div>

      {candidates.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>LTP</th><th>Dir</th><th>Score</th><th>Result</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c: any, i: number) => (
                <tr key={i}>
                  <td>{c.symbol}</td>
                  <td>{c.ltp != null ? `₹${c.ltp.toFixed(2)}` : "-"}</td>
                  <td>{c.direction}</td>
                  <td>{c.score}/{c.max_score}</td>
                  <td className={c.passed ? "badge-win" : "muted"} style={{ fontSize: 12 }}>
                    {c.passed ? "Passed" : c.rejected_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

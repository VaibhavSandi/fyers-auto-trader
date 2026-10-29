export default function CurrentTrade({ trade }: { trade: any }) {
  const isBuy = trade.direction === "BUY";
  const pnlPositive = trade.unrealized_pnl >= 0;

  return (
    <div className={`card trade-card ${isBuy ? "" : "sell"}`}>
      <div className="trade-header">
        <span className="symbol">{trade.symbol.replace("NSE:", "").replace("-EQ", "")}</span>
        <span className={`direction-badge ${isBuy ? "buy" : "sell"}`}>{trade.direction}</span>
      </div>
      <div className="grid-3">
        <div className="stat">
          <span className="label">Entry</span>
          <span className="value">₹{trade.entry_price.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="label">Current</span>
          <span className="value">₹{trade.current_price?.toFixed(2) ?? "-"}</span>
        </div>
        <div className="stat">
          <span className="label">P&amp;L</span>
          <span className={`value ${pnlPositive ? "positive" : "negative"}`}>
            {pnlPositive ? "+" : ""}₹{trade.unrealized_pnl.toFixed(2)}
          </span>
        </div>
        <div className="stat">
          <span className="label">Stop Loss</span>
          <span className="value">₹{trade.stop_loss.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="label">Target</span>
          <span className="value">₹{trade.target.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="label">Quantity</span>
          <span className="value">{trade.quantity}</span>
        </div>
      </div>

      {trade.trailing_active && <p className="muted" style={{ marginTop: 10 }}>🔒 Trailing stop active - protecting profit</p>}

      {trade.explanation?.length > 0 && (
        <>
          <p style={{ marginTop: 14, marginBottom: 4, fontWeight: 600 }}>
            Why did the application {isBuy ? "buy" : "sell"} this?
          </p>
          <ul className="explain-list">
            {trade.explanation.map((reason: string, i: number) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
          <p className="muted">
            Risk: ₹{trade.risk.toFixed(2)} &nbsp;|&nbsp; Potential reward: ₹{trade.reward.toFixed(2)}
          </p>
        </>
      )}
    </div>
  );
}

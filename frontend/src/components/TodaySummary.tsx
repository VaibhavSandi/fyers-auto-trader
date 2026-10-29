export default function TodaySummary({ today }: { today: any }) {
  const pnlPositive = today.net_pnl >= 0;
  return (
    <div className="card">
      <h3>Today</h3>
      <div className="grid-3">
        <div className="stat">
          <span className="label">Trades</span>
          <span className="value">{today.trades}</span>
        </div>
        <div className="stat">
          <span className="label">Wins</span>
          <span className="value positive">{today.wins}</span>
        </div>
        <div className="stat">
          <span className="label">Losses</span>
          <span className="value negative">{today.losses}</span>
        </div>
        <div className="stat">
          <span className="label">Net P&amp;L</span>
          <span className={`value ${pnlPositive ? "positive" : "negative"}`}>
            {pnlPositive ? "+" : ""}₹{today.net_pnl.toFixed(2)}
          </span>
        </div>
        <div className="stat">
          <span className="label">Win Rate</span>
          <span className="value">{today.win_rate}%</span>
        </div>
        <div className="stat">
          <span className="label">Max Drawdown</span>
          <span className="value negative">₹{today.max_drawdown.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}

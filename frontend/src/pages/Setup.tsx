import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

const PROFILE_ORDER = ["conservative", "balanced", "aggressive"];

export default function Setup() {
  const navigate = useNavigate();
  const [capital, setCapital] = useState(10000);
  const [riskProfile, setRiskProfile] = useState("conservative");
  const [tradingMode, setTradingMode] = useState<"paper" | "live">("paper");
  const [profiles, setProfiles] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState<any>(null);
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryReport, setRecoveryReport] = useState<any>(null);

  useEffect(() => {
    api.getProfiles().then(setProfiles).catch(() => {});
    api.getSettings().then((s) => {
      setCapital(s.trading_capital);
      setRiskProfile(s.risk_profile);
      setTradingMode(s.trading_mode);
    }).catch(() => {});
    refreshBrokerStatus();
  }, []);

  useEffect(() => {
    if (capital > 0) {
      api.getDefaults(capital, riskProfile).then(setDefaults).catch(() => {});
    }
  }, [capital, riskProfile]);

  function refreshBrokerStatus() {
    api.getBrokerStatus().then(setBrokerStatus).catch(() => {});
  }

  async function handleConnectFyers() {
    try {
      const { login_url } = await api.getLoginUrl();
      window.open(login_url, "_blank", "noopener");
      setTimeout(refreshBrokerStatus, 3000);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.saveSettings({ trading_capital: capital, risk_profile: riskProfile, trading_mode: tradingMode });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleStart() {
    setStarting(true);
    setError(null);
    setRecoveryReport(null);
    try {
      await api.saveSettings({ trading_capital: capital, risk_profile: riskProfile, trading_mode: tradingMode });
      await api.startAutoTrading();
      navigate("/");
    } catch (e: any) {
      setError(typeof e.message === "string" ? e.message : "Could not start auto trading");
      try {
        const report = await api.recoveryCheck();
        setRecoveryReport(report);
      } catch {
        /* ignore */
      }
    } finally {
      setStarting(false);
    }
  }

  const brokerConnected = brokerStatus?.connected;

  return (
    <div>
      <div className="card">
        <h2>Auto Trading Setup</h2>
        <p className="muted">
          You only need to provide your capital and a few basic choices. The application decides which
          stocks to trade, when to enter, where to place stop-loss/target, and when to exit - automatically.
        </p>

        {error && <div className="error-box">{error}</div>}

        <div className="form-group">
          <label>Trading Capital (₹)</label>
          <input
            type="number"
            min={500}
            step={500}
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
          />
        </div>

        <div className="form-group">
          <label>Risk Profile</label>
          <div className="option-group">
            {PROFILE_ORDER.map((key) => (
              <label key={key} className={`option-card ${riskProfile === key ? "selected" : ""}`}>
                <input
                  type="radio"
                  name="risk-profile"
                  checked={riskProfile === key}
                  onChange={() => setRiskProfile(key)}
                />
                <div>
                  <div className="option-title">{key[0].toUpperCase() + key.slice(1)}</div>
                  <div className="option-desc">{profiles[key]}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {defaults && (
          <div className="info-box">
            With ₹{capital.toLocaleString("en-IN")} and the {defaults.profile_label} profile: risk per trade ≈{" "}
            <b>₹{defaults.max_risk_per_trade_amount}</b>, maximum daily loss ≈{" "}
            <b>₹{defaults.max_daily_loss_amount}</b>, up to <b>{defaults.max_trades_per_day}</b> trades/day,{" "}
            <b>{defaults.max_open_positions}</b> position(s) at a time.
          </div>
        )}

        <div className="form-group">
          <label>Trading Mode</label>
          <div className="toggle-row">
            <label className={`option-card ${tradingMode === "paper" ? "selected" : ""}`}>
              <input type="radio" name="mode" checked={tradingMode === "paper"} onChange={() => setTradingMode("paper")} />
              <div>
                <div className="option-title">🟡 Paper Trading</div>
                <div className="option-desc">Simulated orders using real market prices. No real money at risk.</div>
              </div>
            </label>
            <label className={`option-card ${tradingMode === "live" ? "selected" : ""}`}>
              <input type="radio" name="mode" checked={tradingMode === "live"} onChange={() => setTradingMode("live")} />
              <div>
                <div className="option-title">🔴 Live Trading</div>
                <div className="option-desc">Real orders placed on your FYERS account with real money.</div>
              </div>
            </label>
          </div>
        </div>

        {tradingMode === "live" && (
          <div className="form-group">
            <label>FYERS Connection</label>
            {brokerConnected ? (
              <div className="info-box">✅ Connected to FYERS ({brokerStatus.client_id_masked})</div>
            ) : (
              <>
                <div className="error-box">Not connected. Live trading requires connecting your FYERS account (re-connect once per trading day).</div>
                <button className="btn" onClick={handleConnectFyers}>Connect FYERS Account</button>
              </>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
          <button className="btn secondary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>

        <button
          className="start-button"
          onClick={handleStart}
          disabled={starting || (tradingMode === "live" && !brokerConnected)}
        >
          {starting ? "Starting..." : "▶ START AUTO TRADING"}
        </button>

        {recoveryReport && !recoveryReport.passed && (
          <div className="error-box" style={{ marginTop: 14 }}>
            <b>Recovery check failed:</b>
            <ul>
              {Object.entries(recoveryReport.checks).filter(([, v]: any) => !v.ok).map(([k, v]: any) => (
                <li key={k}>{k}: {v.message}</li>
              ))}
            </ul>
          </div>
        )}

        <p className="muted" style={{ marginTop: 16 }}>
          Important: this application does not guarantee profits. It follows conservative, rule-based risk
          management to try to protect your capital while attempting to generate returns.
        </p>
      </div>
    </div>
  );
}

import { useState } from "react";
import { api } from "../api";

export default function EmergencyStop({
  killSwitchActive,
  onChanged,
}: {
  killSwitchActive: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleKillSwitch() {
    if (!window.confirm("This will immediately stop all automated trading and cancel pending orders. Continue?")) return;
    setBusy(true);
    setError(null);
    try {
      await api.activateKillSwitch();
      onChanged();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeactivate() {
    setBusy(true);
    setError(null);
    try {
      await api.deactivateKillSwitch();
      onChanged();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCloseAll() {
    if (!window.confirm("This will close ALL open positions right now at the current market price. Continue?")) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.closeAllPositions();
      alert(`Closed positions: ${result.closed_positions.length ? result.closed_positions.join(", ") : "none open"}`);
      onChanged();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="emergency-section">
      {error && <div className="error-box">{error}</div>}

      {killSwitchActive ? (
        <>
          <div className="kill-switch-active-banner">
            🛑 EMERGENCY STOP ACTIVE
            <div style={{ fontSize: 13, fontWeight: 500, marginTop: 6 }}>
              AUTOMATED TRADING DISABLED. Check for open positions below, then use "Close All Positions" if needed.
            </div>
          </div>
          <button className="btn secondary" style={{ width: "100%" }} onClick={handleDeactivate} disabled={busy}>
            Deactivate Emergency Stop (you'll still need to press Start Auto Trading again)
          </button>
        </>
      ) : (
        <button className="emergency-button" onClick={handleKillSwitch} disabled={busy}>
          🛑 EMERGENCY STOP / KILL SWITCH
        </button>
      )}

      <button className="close-all-button" onClick={handleCloseAll} disabled={busy}>
        CLOSE ALL POSITIONS
      </button>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";

export function useDashboardSocket() {
  const [data, setData] = useState<any>(null);
  const [connected, setConnected] = useState(false);
  const retryRef = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${protocol}//${window.location.host}/ws/dashboard`);

      ws.onopen = () => active && setConnected(true);
      ws.onmessage = (event) => {
        if (!active) return;
        try {
          setData(JSON.parse(event.data));
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        if (!active) return;
        setConnected(false);
        retryRef.current = window.setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
    }

    connect();
    return () => {
      active = false;
      if (retryRef.current) window.clearTimeout(retryRef.current);
      ws?.close();
    };
  }, []);

  return { data, connected };
}

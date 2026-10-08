import { useEffect, useRef, useState } from "react";
import { INITIAL_RETRY_MS, nextRetryDelay, parseFrame, wsUrl } from "./liveLogic";
import type { LiveState } from "./types";

type Opts = { enabled: boolean; payload: object | null; onFeatures: (f: GeoJSON.Feature[]) => void };
export type LiveSocket = { state: LiveState; errorDetail: string | null };

export function useLiveSocket({ enabled, payload, onFeatures }: Opts): LiveSocket {
  const [state, setState] = useState<LiveState>("off");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const payloadRef = useRef(payload);
  payloadRef.current = payload;
  const cbRef = useRef(onFeatures);
  cbRef.current = onFeatures;

  useEffect(() => {
    if (!enabled) { setState("off"); setErrorDetail(null); return; }
    let closed = false;
    let retry = INITIAL_RETRY_MS;
    let timer: number | undefined;
    const open = () => {
      setState("connecting");
      const ws = new WebSocket(wsUrl(location));
      wsRef.current = ws;
      ws.onopen = () => {
        retry = INITIAL_RETRY_MS;
        setState("live");
        if (payloadRef.current) ws.send(JSON.stringify(payloadRef.current));
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        const f = parseFrame(ev.data);
        if (!f) return;
        if (f.type === "positions") { setErrorDetail(null); cbRef.current(f.features); }
        else setErrorDetail(f.detail);
      };
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (closed) return;
        setState("connecting");
        timer = window.setTimeout(open, retry);
        retry = nextRetryDelay(retry);
      };
    };
    open();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      wsRef.current?.close();
      wsRef.current = null;
      setState("off");
    };
  }, [enabled]);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && payload) ws.send(JSON.stringify(payload));
  }, [payload]);

  return { state, errorDetail };
}

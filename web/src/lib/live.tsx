import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, eventsSocketUrl } from "./api";
import { notifyEvent } from "./browserNotify";
import type { LiveEvent, LiveStatus } from "./types";

interface LiveCtx {
  events: LiveEvent[];
  status: LiveStatus | null;
  setStatus: (s: LiveStatus) => void;
  connected: boolean;
  unread: number;
  markRead: () => void;
}

const Ctx = createContext<LiveCtx | null>(null);
const SEEN_KEY = "mri.lastSeenEvent";

/** One WebSocket for the whole app: history over REST, then real-time pushes (auto-reconnect). */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastSeen, setLastSeen] = useState<number>(() => {
    try { return Number(localStorage.getItem(SEEN_KEY) || 0); } catch { return 0; }
  });
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    api.events().then(setEvents).catch(() => undefined);
    api.liveStatus().then(setStatus).catch(() => undefined);

    const connect = () => {
      ws = new WebSocket(eventsSocketUrl());
      ws.onopen = () => { setConnected(true); retry.current = 0; };
      ws.onmessage = (m) => {
        const data = JSON.parse(m.data);
        if (data.type === "status") { const { type: _t, ...s } = data; setStatus(s as LiveStatus); return; }
        notifyEvent(data as LiveEvent);
        setEvents((prev) => (prev.some((e) => e.id === data.id) ? prev : [data as LiveEvent, ...prev].slice(0, 500)));
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** retry.current++));
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);

  const value = useMemo<LiveCtx>(() => ({
    events, status, setStatus, connected,
    unread: events.filter((e) => e.id > lastSeen).length,
    markRead: () => {
      const top = events[0]?.id ?? 0;
      setLastSeen(top);
      try { localStorage.setItem(SEEN_KEY, String(top)); } catch { /* storage unavailable */ }
    },
  }), [events, status, connected, lastSeen]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLive(): LiveCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive must be used inside LiveProvider");
  return v;
}

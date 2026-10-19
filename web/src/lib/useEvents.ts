import { useEffect, useRef, useState } from "react";
import { api, eventsSocketUrl } from "./api";
import { notifyEvent } from "./browserNotify";
import type { LiveEvent, LiveStatus } from "./types";

/** Live events: initial history over REST, then real-time pushes over WebSocket (auto-reconnect). */
export function useLiveEvents() {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    api.events().then(setEvents).catch(() => undefined);

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
        const delay = Math.min(30_000, 1000 * 2 ** retry.current++);
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);

  return { events, status, setStatus, connected };
}

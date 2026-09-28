import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppStreamer, StreamType, type DirectConfig } from '@nvidia/ov-web-rtc';

type Status = 'connecting' | 'connected' | 'failed';
export type StreamMessage = { event_type: string; payload: Record<string, unknown> };
type Handler = (event: StreamMessage) => void;

type StreamingContextValue = {
  status: Status;
  errorMessage: string;
  sendMessage: (message: StreamMessage) => boolean;
  onCustomEvent: (handler: Handler) => () => void;
  host: string;
  signalingPort: number;
};

const StreamingContext = createContext<StreamingContextValue | null>(null);

function configValue(name: string, fallback: string): string {
  const params = new URLSearchParams(window.location.search);
  return params.get(name.toLowerCase()) || params.get(name) || fallback;
}

function resolveConfig() {
  const env = import.meta.env as Record<string, string | undefined>;
  const host = configValue('server', env.VITE_SERVER_HOST || window.location.hostname || '127.0.0.1');
  const portText = configValue('signalingport', env.VITE_SIGNALING_PORT || '49100');
  const signalingPort = Number.parseInt(portText, 10) || 49100;
  return { host, signalingPort };
}

export function StreamingProvider({ children }: { children: React.ReactNode }) {
  const [{ host, signalingPort }] = useState(resolveConfig);
  const [status, setStatus] = useState<Status>('connecting');
  const [errorMessage, setErrorMessage] = useState('');
  const connectedRef = useRef(false);
  const handlersRef = useRef(new Set<Handler>());

  const routeEvent = useCallback((raw: unknown) => {
    let event = raw as StreamMessage | null;
    const wrapped = raw as { data?: unknown; messageType?: unknown } | null;
    if (wrapped && typeof wrapped === 'object' && typeof wrapped.data !== 'undefined') {
      try {
        event = typeof wrapped.data === 'string' ? JSON.parse(wrapped.data) : (wrapped.data as StreamMessage);
      } catch {
        event = null;
      }
    }
    if (!event || typeof event.event_type !== 'string') return;
    handlersRef.current.forEach((handler) => handler(event));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const config: DirectConfig = {
      videoElementId: 'remote-video',
      audioElementId: 'remote-audio',
      server: host,
      signalingPort,
      nativeTouchEvents: true,
      fps: 30,
      maxReconnects: 5,
      reconnectDelay: 3000,
      onStart: (message: { action?: string; status?: string; info?: unknown }) => {
        if (cancelled) return;
        if (message.action !== 'start') return;
        if (message.status === 'success') {
          connectedRef.current = true;
          setStatus('connected');
          setErrorMessage('');
          for (const id of ['remote-video', 'remote-audio']) {
            const element = document.getElementById(id) as HTMLMediaElement | null;
            if (!element) continue;
            element.muted = true;
            void element.play().catch(() => undefined);
          }
          document.getElementById('remote-video')?.focus();
          return;
        }
        if (message.status === 'error') {
          connectedRef.current = false;
          setStatus('failed');
          setErrorMessage(message.info instanceof Error ? message.info.message : String(message.info || 'WebRTC stream start failed'));
        }
      },
      onUpdate: () => undefined,
      onCustomEvent: routeEvent,
      onStop: () => {
        connectedRef.current = false;
        if (!cancelled) setStatus('connecting');
      },
      onTerminate: () => {
        connectedRef.current = false;
        if (!cancelled) setStatus('failed');
      },
    };

    setStatus('connecting');
    AppStreamer.connect({ streamSource: StreamType.DIRECT, streamConfig: config }).catch((error: unknown) => {
      if (cancelled) return;
      connectedRef.current = false;
      setStatus('failed');
      setErrorMessage(error instanceof Error ? error.message : String(error));
    });

    return () => {
      cancelled = true;
      connectedRef.current = false;
      void AppStreamer.terminate(false).catch(() => undefined);
    };
  }, [host, signalingPort, routeEvent]);

  const sendMessage = useCallback((message: StreamMessage) => {
    if (!connectedRef.current) return false;
    void AppStreamer.sendMessage(message).catch(() => undefined);
    return true;
  }, []);

  const onCustomEvent = useCallback((handler: Handler) => {
    handlersRef.current.add(handler);
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);

  const value = useMemo(() => ({ status, errorMessage, sendMessage, onCustomEvent, host, signalingPort }), [status, errorMessage, sendMessage, onCustomEvent, host, signalingPort]);
  return <StreamingContext.Provider value={value}>{children}</StreamingContext.Provider>;
}

export function useStreaming() {
  const value = useContext(StreamingContext);
  if (!value) throw new Error('useStreaming must be used inside StreamingProvider');
  return value;
}

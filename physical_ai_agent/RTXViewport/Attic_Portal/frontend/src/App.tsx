import { useCallback, useRef } from 'react';
import { R17SignalPanel } from './components/R17SignalPanel';
import { StreamingProvider, useStreaming } from './streaming/StreamingProvider';

function Portal() {
  const { errorMessage, sendMessage, status } = useStreaming();
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const focusVideo = useCallback(() => {
    videoRef.current?.focus();
  }, []);

  const setViewportInputActive = useCallback((active: boolean) => {
    sendMessage({ event_type: 'setViewportInputActive', payload: { active } });
    if (active) focusVideo();
  }, [focusVideo, sendMessage]);

  return (
    <main className="stream-shell">
      <div
        className="viewport-region"
        onPointerEnter={() => setViewportInputActive(true)}
        onPointerDown={() => setViewportInputActive(true)}
        onMouseEnter={focusVideo}
        onPointerLeave={() => setViewportInputActive(false)}
      >
        <video
          ref={videoRef}
          id="remote-video"
          autoPlay
          playsInline
          tabIndex={-1}
          onFocus={() => setViewportInputActive(true)}
          onMouseEnter={focusVideo}
        />
      </div>
      <audio id="remote-audio" autoPlay />
      <div
        className="r17-panel-region"
        onPointerEnter={() => setViewportInputActive(false)}
        onPointerDown={() => setViewportInputActive(false)}
        onWheel={() => setViewportInputActive(false)}
      >
        <R17SignalPanel />
      </div>
      <div className={`stream-status stream-status--${status}`}>{status}</div>
      {errorMessage ? <div className="error">{errorMessage}</div> : null}
    </main>
  );
}

export default function App() {
  return (
    <StreamingProvider>
      <Portal />
    </StreamingProvider>
  );
}

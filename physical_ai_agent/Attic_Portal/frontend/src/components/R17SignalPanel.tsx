import { useCallback, useEffect, useState } from 'react';
import { R17CommandButton } from './R17CommandButton';
import { useR17CommandSender } from '../hooks/useR17CommandSender';
import { useR17StateFeed, useR17StateSubscription } from '../hooks/useR17StateSubscription';
import { useStreaming } from '../streaming/StreamingProvider';
import type { R17LidarStatus, R17OffsetX, R17Pose, R17RenderMode, R17StatePayload, R17StateStatus, R17View } from '../types/r17';

const POSE_BUTTONS: Array<{ pose: R17Pose; label: string }> = [
  { pose: 'LEFT', label: 'LEFT POSE -15' },
  { pose: 'HOME', label: 'HOME' },
  { pose: 'RIGHT', label: 'RIGHT POSE +15' },
];

const VIEW_BUTTONS: Array<{ view: Exclude<R17View, 'CUSTOM'>; label: string }> = [
  { view: 'DEFAULT', label: 'DEFAULT VIEW' },
  { view: 'CUBE_FOCUS', label: 'CUBE FOCUS' },
];

const RENDER_BUTTONS: Array<{ mode: R17RenderMode; label: string }> = [
  { mode: 'BEAUTY', label: 'BEAUTY' },
  { mode: 'SEMANTIC', label: 'SEMANTIC' },
];

const LIDAR_BUTTONS: Array<{ enabled: boolean; label: string }> = [
  { enabled: true, label: 'LIDAR ON' },
  { enabled: false, label: 'LIDAR OFF' },
];

function offsetLabel(offsetX: R17OffsetX | null): string {
  if (offsetX === null) return 'offset pending';
  return `offsetX ${offsetX > 0 ? '+' : ''}${offsetX}`;
}

export function R17SignalPanel() {
  const [cubePath, setCubePath] = useState('');
  const [activePose, setActivePose] = useState<R17Pose | null>(null);
  const [offsetX, setOffsetX] = useState<R17OffsetX | null>(null);
  const [status, setStatus] = useState<R17StateStatus>('WAITING');
  const [statusText, setStatusText] = useState('Waiting for Memory Cube Link');
  const [transitionActive, setTransitionActive] = useState(false);
  const [activeView, setActiveView] = useState<R17View>('DEFAULT');
  const [focusCameraPath, setFocusCameraPath] = useState('');
  const [renderMode, setRenderMode] = useState<R17RenderMode>('BEAUTY');
  const [cubeSemanticClass, setCubeSemanticClass] = useState('');
  const [cubeSemanticLabel, setCubeSemanticLabel] = useState('');
  const [outputKeys, setOutputKeys] = useState<string[]>([]);
  const [lidarStatus, setLidarStatus] = useState<R17LidarStatus>('DISABLED');
  const [lidarSensorPath, setLidarSensorPath] = useState('');
  const [validPointCount, setValidPointCount] = useState<number | null>(null);
  const [nearestRange, setNearestRange] = useState<number | null>(null);
  const [nonvisualMaterialCount, setNonvisualMaterialCount] = useState<number | null>(null);
  const [inFlightRequestId, setInFlightRequestId] = useState<string | null>(null);
  const { sendR17Command } = useR17CommandSender();
  const { status: streamStatus } = useStreaming();

  useEffect(() => {
    if (streamStatus !== 'connected') return undefined;
    const timer = window.setTimeout(() => {
      sendR17Command('r17.getState', {});
    }, 250);
    return () => window.clearTimeout(timer);
  }, [sendR17Command, streamStatus]);

  // Server-authoritative panel readout. Button presentation stays correlated to
  // its own requestId; this only mirrors published state.
  const applyState = useCallback((state: R17StatePayload) => {
    if (state.cubePath) setCubePath(state.cubePath);
    if (state.requestedPose) setActivePose(state.requestedPose);
    if (typeof state.offsetX === 'number') setOffsetX(state.offsetX);
    if (state.activeView) setActiveView(state.activeView);
    if (state.focusCameraPath) setFocusCameraPath(state.focusCameraPath);
    if (state.renderMode) setRenderMode(state.renderMode);
    if (state.cubeSemanticClass) setCubeSemanticClass(state.cubeSemanticClass);
    if (state.cubeSemanticLabel) setCubeSemanticLabel(state.cubeSemanticLabel);
    if (Array.isArray(state.outputKeys)) setOutputKeys(state.outputKeys);
    if (state.lidarStatus) setLidarStatus(state.lidarStatus);
    if (state.lidarSensorPath) setLidarSensorPath(state.lidarSensorPath);
    if (typeof state.lidarNonvisualMaterialCount === 'number') setNonvisualMaterialCount(state.lidarNonvisualMaterialCount);
    // null is the server clearing stale telemetry on LIDAR OFF, so it is
    // applied rather than ignored like the other optional readouts.
    if (state.validPointCount !== undefined) setValidPointCount(state.validPointCount);
    if (state.nearestRange !== undefined) setNearestRange(state.nearestRange);
    setTransitionActive(Boolean(state.transitionActive));
    setStatus(state.status);
    setStatusText(state.error || state.message || state.status);
  }, []);

  useR17StateFeed(applyState);

  const handleCorrelatedState = useCallback((state: R17StatePayload) => {
    applyState(state);
    if (state.status === 'READY' || state.status === 'ERROR') {
      setInFlightRequestId(null);
    }
  }, [applyState]);

  useR17StateSubscription(inFlightRequestId, handleCorrelatedState);

  const controlsDisabled =
    !cubePath || Boolean(inFlightRequestId) || transitionActive || status === 'APPLYING' || status === 'WAITING';
  // Camera presets only move the viewer camera, so they stay available while a
  // cube pose is settling. They still wait on this panel's own in-flight request.
  const viewControlsDisabled = !cubePath || Boolean(inFlightRequestId) || status === 'WAITING';
  // Robot Vision only reselects the streamed ovrtx output, so it stays available
  // while a cube pose settles, on the same gate as the camera presets.
  const renderControlsDisabled = viewControlsDisabled;
  // The LiDAR Link recomposes the viewer-owned layers, so it waits for a
  // settled panel the same way the cube pose controls do.
  const lidarControlsDisabled = controlsDisabled;

  return (
    <aside className="r17-signal-panel" aria-label="R-17 Signal Panel">
      <header className="r17-panel-header">
        <div className="r17-panel-title">R-17 Signal Panel</div>
        <div className={`r17-status r17-status--${status.toLowerCase()}`}>{status}</div>
      </header>

      <section className="r17-cube-link" aria-label="Memory Cube Link">
        <div className="r17-section-label">Memory Cube Link</div>
        <div className="r17-cube-path">{cubePath || 'Resolving Memory Cube...'}</div>
        <div className="r17-pose-readout">
          <span>{activePose || 'HOME'}</span>
          <span>{offsetLabel(offsetX)}</span>
        </div>
      </section>

      <div className="r17-pose-controls" aria-label="Memory Cube pose controls">
        {POSE_BUTTONS.map(({ pose, label }) => (
          <R17CommandButton
            key={pose}
            command="cube.setPose"
            payload={{ pose }}
            disabled={controlsDisabled}
            onRequestStart={setInFlightRequestId}
            onRequestState={handleCorrelatedState}
          >
            {label}
          </R17CommandButton>
        ))}
      </div>

      <section className="r17-camera-link" aria-label="R-17 camera view">
        <div className="r17-section-label">Camera View</div>
        <div className="r17-cube-path">{focusCameraPath || 'Resolving focus camera...'}</div>
        <div className="r17-pose-readout">
          <span>{activeView}</span>
          <span>{activeView === 'CUSTOM' ? 'manual navigation' : 'preset'}</span>
        </div>
      </section>

      <div className="r17-view-controls" aria-label="R-17 camera view controls">
        {VIEW_BUTTONS.map(({ view, label }) => (
          <R17CommandButton
            key={view}
            command="camera.setView"
            payload={{ view }}
            disabled={viewControlsDisabled}
            onRequestStart={setInFlightRequestId}
            onRequestState={handleCorrelatedState}
          >
            {label}
          </R17CommandButton>
        ))}
      </div>

      <section className="r17-vision-link" aria-label="R-17 Robot Vision">
        <div className="r17-section-label">Robot Vision</div>
        <div className="r17-pose-readout">
          <span>{renderMode}</span>
          <span>{cubeSemanticClass || 'class pending'}</span>
        </div>
        <div className="r17-cube-path">{cubeSemanticLabel || 'Resolving semantic labels...'}</div>
        <div className="r17-cube-path">{outputKeys.length ? outputKeys.join(' | ') : 'Awaiting render outputs...'}</div>
      </section>

      <div className="r17-render-controls" aria-label="R-17 Robot Vision render controls">
        {RENDER_BUTTONS.map(({ mode, label }) => (
          <R17CommandButton
            key={mode}
            command="render.setMode"
            payload={{ mode }}
            disabled={renderControlsDisabled}
            onRequestStart={setInFlightRequestId}
            onRequestState={handleCorrelatedState}
          >
            {label}
          </R17CommandButton>
        ))}
      </div>

      <section className="r17-lidar-link" aria-label="R-17 LiDAR Link">
        <div className="r17-section-label">LiDAR Link</div>
        <div className="r17-pose-readout">
          <span>{lidarStatus}</span>
          <span>{validPointCount === null ? 'points --' : `points ${validPointCount}`}</span>
        </div>
        <div className="r17-cube-path">{lidarSensorPath || 'Resolving LiDAR sensor...'}</div>
        <div className="r17-pose-readout">
          <span>{nearestRange === null ? 'nearest --' : `nearest ${nearestRange.toFixed(2)} m`}</span>
          <span>{nonvisualMaterialCount === null ? 'materials --' : `materials ${nonvisualMaterialCount}`}</span>
        </div>
      </section>

      <div className="r17-lidar-controls" aria-label="R-17 LiDAR controls">
        {LIDAR_BUTTONS.map(({ enabled, label }) => (
          <R17CommandButton
            key={label}
            command="lidar.setEnabled"
            payload={{ enabled }}
            disabled={lidarControlsDisabled}
            onRequestStart={setInFlightRequestId}
            onRequestState={handleCorrelatedState}
          >
            {label}
          </R17CommandButton>
        ))}
      </div>

      <div className="r17-status-line">{statusText}</div>
    </aside>
  );
}

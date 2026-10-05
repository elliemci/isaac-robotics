import { useCallback, useEffect, useState } from 'react';
import { R17CommandButton } from './R17CommandButton';
import { useR17CommandSender } from '../hooks/useR17CommandSender';
import { useR17StateFeed, useR17StateSubscription } from '../hooks/useR17StateSubscription';
import { useStreaming } from '../streaming/StreamingProvider';
import type { R17LidarStatus, R17OffsetX, R17PhysicsState, R17Pose, R17SimReadyState, R17RenderMode, R17StatePayload, R17StateStatus, R17View } from '../types/r17';

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
  const [physics, setPhysics] = useState<R17PhysicsState | null>(null);
  const [simready, setSimready] = useState<R17SimReadyState | null>(null);
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
    if (state.physics) setPhysics(state.physics);
    if (state.simready) setSimready(state.simready);
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
  // The physics probe only reads state and never moves the scene, so it uses
  // the same gate as the camera presets.
  const physicsControlsDisabled = viewControlsDisabled;
  // SimReady Validate is read-only USD inspection; same gate as the physics probe.
  const simreadyControlsDisabled = viewControlsDisabled;
  // run fixes needs a current report with a repairable RB.MB.001 finding. The
  // server enforces the same rule (and the source hashes); this only explains it.
  const fixesReason = !simready?.report
    ? 'Run targets first: no current report.'
    : simready.fixes.status !== 'IDLE'
      ? ''
      : !simready.report.ruleIds.includes('RB.MB.001')
        ? 'No RB.MB.001 finding to fix.'
        : !simready.report.repairable
          ? 'RB.MB.001 is not repairable from the existing proxies.'
          : '';
  const fixesControlsDisabled =
    simreadyControlsDisabled || !simready?.report?.repairable || simready.fixes.status !== 'IDLE';

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

      <section className="r17-physics-link" aria-label="Run Physics Simluation">
        <div className="r17-section-label">Run Physics Simluation</div>
        <div className="r17-pose-readout">
          <span>{physics?.status ?? 'NOT_RUN'}</span>
          <span>{physics?.runtimeInstalled === false ? 'ovphysx missing' : `rigid bodies ${physics ? physics.rigidBodyCount : '--'}`}</span>
        </div>
        <div className="r17-cube-path">{physics?.stagePath || 'Resolving physical stage...'}</div>
        <div className="r17-pose-readout">
          <span>{`steps ${physics?.stepCount ?? 0}`}</span>
          <span>{`t ${(physics?.elapsedTime ?? 0).toFixed(4)} s`}</span>
        </div>
        <div className="r17-pose-readout">
          <span>{physics?.bridgeReady ? 'bridge READY' : 'bridge NOT READY'}</span>
          <span>{`plays ${physics?.playCount ?? 0}`}</span>
        </div>
      </section>

      <div className="r17-physics-controls" aria-label="R-17 physics controls">
        <R17CommandButton
          command="physics.play"
          disabled={physicsControlsDisabled}
          onRequestStart={setInFlightRequestId}
          onRequestState={handleCorrelatedState}
        >
          ▶ PLAY
        </R17CommandButton>
      </div>

      <section className="r17-simready-link" aria-label="SimReady Validate">
        <div className="r17-section-label">SimReady Validate</div>
        <div className="r17-pose-readout">
          <span>{simready?.status ?? 'IDLE'}</span>
          <span>{`missing ${simready?.missingCount ?? 0}`}</span>
        </div>
        <div className="r17-cube-path">{simready?.stagePath || 'Resolving Mission 2 stage...'}</div>
        {simready && simready.status === 'IDLE' ? <div className="r17-cube-path">Not run. Click run targets.</div> : null}
        {simready?.targets.map((target) => (
          <div className="r17-pose-readout" key={target.target}>
            <span>{target.target}</span>
            <span>{`${target.status} (${target.missingCount})`}</span>
          </div>
        ))}
        <div className="r17-pose-readout">
          <span>{`fixes ${simready?.fixes?.status ?? 'IDLE'}`}</span>
          <span>{`applied ${simready?.fixes?.appliedCount ?? 0}`}</span>
        </div>
        {fixesControlsDisabled && fixesReason ? <div className="r17-cube-path">{`run fixes disabled: ${fixesReason}`}</div> : null}
        {simready && simready.fixes.status !== 'IDLE' ? <div className="r17-cube-path">{simready.fixes.message}</div> : null}
        {simready?.fixes?.reason ? <div className="r17-simready-error">{simready.fixes.reason}</div> : null}
        {simready?.fixes?.outlineVisible ? <div className="r17-cube-path">outlines: CollisionAPI green, RigidBodyAPI orange</div> : null}
        {simready?.error ? <div className="r17-simready-error">{simready.error}</div> : null}
        {simready && simready.missing.length > 0 ? (
          <ul className="r17-simready-missing" aria-label="Missing requirements">
            {simready.missing.map((item, index) => (
              <li key={`${item.target}-${item.rule}-${item.prim}-${index}`}>
                <strong>{item.ruleId ? `${item.ruleId} ` : ''}{item.rule}</strong> {item.prim} — {item.detail}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <div className="r17-simready-controls" aria-label="SimReady Validate controls">
        <R17CommandButton
          command="simready.validateTargets"
          payload={{ userInitiated: true }}
          disabled={simreadyControlsDisabled}
          onRequestStart={setInFlightRequestId}
          onRequestState={handleCorrelatedState}
        >
          run targets
        </R17CommandButton>
        <R17CommandButton
          command="simready.fixTargets"
          payload={{ userInitiated: true }}
          disabled={fixesControlsDisabled}
          onRequestStart={setInFlightRequestId}
          onRequestState={handleCorrelatedState}
        >
          run fixes
        </R17CommandButton>
      </div>

      <div className="r17-status-line">{statusText}</div>
    </aside>
  );
}

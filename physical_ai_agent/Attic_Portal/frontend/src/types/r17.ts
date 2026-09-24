export const R17_COMMAND_EVENT = 'r17-command-v1' as const;
export const R17_STATE_EVENT = 'r17-state-v1' as const;

export type R17StateStatus = 'WAITING' | 'APPLYING' | 'READY' | 'ERROR';
export type R17Pose = 'LEFT' | 'HOME' | 'RIGHT';
export type R17OffsetX = -15 | 0 | 15;
/** DEFAULT and CUBE_FOCUS are authored presets; CUSTOM means the viewer navigated. */
export type R17View = 'DEFAULT' | 'CUBE_FOCUS' | 'CUSTOM';
/** BEAUTY streams LdrColor; SEMANTIC streams candy-colored ovrtx SemanticSegmentation. */
export type R17RenderMode = 'BEAUTY' | 'SEMANTIC';
/** Server-authoritative LiDAR Link state. DISABLED means the sensor is not stepped. */
export type R17LidarStatus = 'DISABLED' | 'WAITING' | 'READY' | 'ERROR';

export type R17CommandPayload = {
  requestId: string;
  command: string;
  payload: Record<string, unknown>;
};

export type R17StatePayload = {
  requestId: string;
  status: R17StateStatus;
  moduleInstalled: boolean;
  command?: string;
  cubePath?: string;
  requestedPose?: R17Pose;
  offsetX?: R17OffsetX;
  transitionActive?: boolean;
  activeView?: R17View;
  focusCameraPath?: string;
  cameraLayer?: string;
  renderMode?: R17RenderMode;
  availableOutputs?: string[];
  outputKeys?: string[];
  semanticsLayer?: string;
  semanticIdMap?: Record<string, string>;
  semanticUniqueIds?: number[];
  semanticNonzeroPixels?: number;
  cubeSemanticClass?: string;
  cubeSemanticLabel?: string;
  lidarEnabled?: boolean;
  lidarStatus?: R17LidarStatus;
  lidarSensorPath?: string;
  lidarRenderProduct?: string;
  lidarLayer?: string;
  lidarRequestedChannels?: string[];
  lidarNonvisualMaterialCount?: number;
  /** null clears stale telemetry when the LiDAR Link is disabled. */
  validPointCount?: number | null;
  nearestRange?: number | null;
  homeTransformRowMajor?: number[][];
  currentTransformRowMajor?: number[][];
  message?: string;
  error?: string;
  data?: Record<string, unknown>;
};

export type R17CommandEnvelope = {
  event_type: typeof R17_COMMAND_EVENT;
  payload: R17CommandPayload;
};

export type R17StateEnvelope = {
  event_type: typeof R17_STATE_EVENT;
  payload: R17StatePayload;
};

export const DEFAULT_VIEW_PRESET = Object.freeze({
  name: 'DEFAULT VIEW',
  cameraPath: '/OVCamera',
  transformRowMajor: [
    [1, -0, 0, 0],
    [0, 0.33348709214081446, 0.9427546655283462, 0],
    [-0, -0.9427546655283462, 0.33348709214081446, 0],
    [-620, -1553.9533728153974, 272.73662692407055, 1],
  ],
  orbit: {
    target: [-620, -1125, 121],
    distance: 455,
    azimuth: 0,
    elevation: 0.34,
    worldUp: [0, 0, 1],
  },
  lens: {
    focalLength: 24,
    horizontalAperture: 20.955,
    verticalAperture: 11.7871875,
    clippingRange: [1, 10000000],
    projection: 'perspective',
  },
} as const);

export function isNonemptyRequestId(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function isR17Pose(value: unknown): value is R17Pose {
  return value === 'LEFT' || value === 'HOME' || value === 'RIGHT';
}

export function isR17OffsetX(value: unknown): value is R17OffsetX {
  return value === -15 || value === 0 || value === 15;
}

export function isR17View(value: unknown): value is R17View {
  return value === 'DEFAULT' || value === 'CUBE_FOCUS' || value === 'CUSTOM';
}

export function isR17RenderMode(value: unknown): value is R17RenderMode {
  return value === 'BEAUTY' || value === 'SEMANTIC';
}

export function isR17LidarStatus(value: unknown): value is R17LidarStatus {
  return value === 'DISABLED' || value === 'WAITING' || value === 'READY' || value === 'ERROR';
}

export function isR17StatePayload(value: unknown): value is R17StatePayload {
  if (!value || typeof value !== 'object') return false;
  const payload = value as Partial<R17StatePayload>;
  const statusOk = payload.status === 'WAITING' || payload.status === 'APPLYING' || payload.status === 'READY' || payload.status === 'ERROR';
  const poseOk = payload.requestedPose === undefined || isR17Pose(payload.requestedPose);
  const offsetOk = payload.offsetX === undefined || isR17OffsetX(payload.offsetX);
  const viewOk = payload.activeView === undefined || isR17View(payload.activeView);
  const renderModeOk = payload.renderMode === undefined || isR17RenderMode(payload.renderMode);
  const lidarStatusOk = payload.lidarStatus === undefined || isR17LidarStatus(payload.lidarStatus);
  return isNonemptyRequestId(payload.requestId) && statusOk && typeof payload.moduleInstalled === 'boolean' && poseOk && offsetOk && viewOk && renderModeOk && lidarStatusOk;
}

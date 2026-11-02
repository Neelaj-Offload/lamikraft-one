/**
 * Orbit state for the material viewer: azimuth (around the vertical axis) and elevation (above
 * the slab), in radians. Pure functions so drag, keys and preset buttons share one model and
 * the scene only ever renders a state.
 */

export interface OrbitState {
  azimuth: number;
  elevation: number;
}

export type PresetId = "front" | "top" | "edge";

export const PRESETS: Record<PresetId, OrbitState> = {
  front: { azimuth: 0.55, elevation: 0.52 },
  top: { azimuth: 0.05, elevation: 1.42 },
  edge: { azimuth: 1.25, elevation: 0.1 },
};

const MIN_ELEVATION = 0.06;
const MAX_ELEVATION = 1.45;
const KEY_STEP = 0.12;
const DRAG_RATE = 0.008;

export function clampOrbit(state: OrbitState): OrbitState {
  return {
    azimuth: state.azimuth,
    elevation: Math.min(MAX_ELEVATION, Math.max(MIN_ELEVATION, state.elevation)),
  };
}

/** Arrow keys orbit by a fixed step; other keys are ignored (null). */
export function stepOrbit(state: OrbitState, key: string): OrbitState | null {
  switch (key) {
    case "ArrowLeft":
      return clampOrbit({ ...state, azimuth: state.azimuth - KEY_STEP });
    case "ArrowRight":
      return clampOrbit({ ...state, azimuth: state.azimuth + KEY_STEP });
    case "ArrowUp":
      return clampOrbit({ ...state, elevation: state.elevation + KEY_STEP });
    case "ArrowDown":
      return clampOrbit({ ...state, elevation: state.elevation - KEY_STEP });
    default:
      return null;
  }
}

/** Pointer drag in pixels → orbit (dragging right turns the slab right, dragging down tilts it up). */
export function dragOrbit(state: OrbitState, dx: number, dy: number): OrbitState {
  return clampOrbit({ azimuth: state.azimuth + dx * DRAG_RATE, elevation: state.elevation + dy * DRAG_RATE });
}

/** The preset the state currently matches, if any (for aria-pressed on the preset buttons). */
export function matchingPreset(state: OrbitState): PresetId | null {
  for (const [id, preset] of Object.entries(PRESETS) as [PresetId, OrbitState][]) {
    if (Math.abs(preset.azimuth - state.azimuth) < 1e-6 && Math.abs(preset.elevation - state.elevation) < 1e-6) return id;
  }
  return null;
}

/** Spherical → Cartesian camera position looking at the origin. */
export function cameraPosition(state: OrbitState, distance: number): [number, number, number] {
  const horizontal = Math.cos(state.elevation) * distance;
  return [Math.sin(state.azimuth) * horizontal, Math.sin(state.elevation) * distance, Math.cos(state.azimuth) * horizontal];
}

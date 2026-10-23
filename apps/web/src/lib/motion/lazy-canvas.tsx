"use client";

import type { CanvasProps } from "@react-three/fiber";
import dynamic from "next/dynamic";
import {
  Component,
  createContext,
  useContext,
  useSyncExternalStore,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { useIsMotionReduced } from "./use-motion-preference";

/**
 * Lazy three.js canvas for material viewers. three, R3F and any drei helpers the
 * scene imports load only when a LazyCanvas actually mounts in the browser.
 */

const FallbackContext = createContext<ReactNode>(null);

function CanvasLoading() {
  return <>{useContext(FallbackContext)}</>;
}

const Canvas = dynamic(() => import("@react-three/fiber").then((mod) => mod.Canvas), {
  ssr: false,
  loading: CanvasLoading,
});

let webglAvailable: boolean | undefined;

function isWebGLAvailable(): boolean {
  if (webglAvailable === undefined) {
    try {
      const probe = document.createElement("canvas");
      webglAvailable = Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
    } catch {
      webglAvailable = false;
    }
  }
  return webglAvailable;
}

const noopSubscribe = () => () => {};

interface BoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

class CanvasErrorBoundary extends Component<BoundaryProps, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // A lost or refused WebGL context must not take the surrounding screen down.
    console.warn("3D view unavailable; showing the static fallback.", error, info.componentStack);
  }

  override render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export interface LazyCanvasProps extends Omit<CanvasProps, "fallback"> {
  /** Accessible description of what the scene shows; the canvas itself is not readable. */
  label: string;
  /** Static content (for example the material photo) shown while loading, without WebGL, or on failure. */
  fallback: ReactNode;
}

export function LazyCanvas({
  label,
  fallback,
  frameloop,
  dpr = [1, 2],
  className,
  children,
  ...canvasProps
}: LazyCanvasProps) {
  const reduced = useIsMotionReduced();
  const webgl = useSyncExternalStore(noopSubscribe, isWebGLAvailable, () => false);

  return (
    <div role="img" aria-label={label} className={className}>
      {webgl ? (
        <FallbackContext value={fallback}>
          <CanvasErrorBoundary fallback={fallback}>
            <Canvas
              {...canvasProps}
              dpr={dpr}
              // With reduced motion the scene renders on demand (state changes) instead of every frame.
              frameloop={reduced ? "demand" : (frameloop ?? "always")}
              fallback={fallback}
            >
              {children}
            </Canvas>
          </CanvasErrorBoundary>
        </FallbackContext>
      ) : (
        fallback
      )}
    </div>
  );
}

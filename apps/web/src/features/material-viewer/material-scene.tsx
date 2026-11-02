"use client";

import { ContactShadows } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { framingDistance, textureRepeat, type SlabDimensions } from "./geometry";
import { cameraPosition, type OrbitState } from "./orbit";
import type { Swatch } from "./swatches";

/** Textures are loaded here, not through a shared cache, so unmount can dispose them for real. */
function useSwatchTextures(swatch: Swatch, repeat: [number, number]): { albedo: THREE.Texture; normal: THREE.Texture } | null {
  const [textures, setTextures] = useState<{ albedo: THREE.Texture; normal: THREE.Texture } | null>(null);
  const { gl, invalidate } = useThree();

  useEffect(() => {
    let cancelled = false;
    const loader = new THREE.TextureLoader();
    const maxAnisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy());
    const prepare = (texture: THREE.Texture, srgb: boolean) => {
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = maxAnisotropy;
      if (srgb) texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;
      return texture;
    };
    void Promise.all([loader.loadAsync(swatch.albedo), loader.loadAsync(swatch.normal)]).then(
      ([albedo, normal]) => {
        if (cancelled) {
          albedo.dispose();
          normal.dispose();
          return;
        }
        setTextures({ albedo: prepare(albedo, true), normal: prepare(normal, false) });
        invalidate();
      },
      () => undefined, // the static fallback image stays on screen when a texture fails
    );
    return () => {
      cancelled = true;
    };
  }, [swatch, gl, invalidate]);

  useEffect(() => {
    if (!textures) return;
    textures.albedo.repeat.set(repeat[0], repeat[1]);
    textures.normal.repeat.set(repeat[0], repeat[1]);
    invalidate();
  }, [textures, repeat, invalidate]);

  useEffect(() => () => {
    textures?.albedo.dispose();
    textures?.normal.dispose();
  }, [textures]);

  return textures;
}

function Slab({ swatch, dims }: { swatch: Swatch; dims: SlabDimensions }) {
  const repeat = useMemo(() => textureRepeat(dims), [dims]);
  const textures = useSwatchTextures(swatch, repeat);
  const edgeColor = swatch.tone === "light" ? "#3a2418" : "#8a6238";

  // Six materials in BoxGeometry order: +x, -x, +y (top), -y (bottom), +z, -z. Built imperatively
  // so unmount disposes exactly the two materials that exist.
  const materials = useMemo(() => {
    if (!textures) return null;
    const face = new THREE.MeshStandardMaterial({
      map: textures.albedo,
      normalMap: textures.normal,
      normalScale: new THREE.Vector2(0.35, 0.35),
      roughness: 0.55,
      metalness: 0,
    });
    const edge = new THREE.MeshStandardMaterial({ color: edgeColor, roughness: 0.8, metalness: 0 });
    return { face, edge, list: [edge, edge, face, face, edge, edge] };
  }, [textures, edgeColor]);

  useEffect(
    () => () => {
      materials?.face.dispose();
      materials?.edge.dispose();
    },
    [materials],
  );

  if (!materials) return null;
  return (
    <mesh castShadow receiveShadow material={materials.list}>
      <boxGeometry args={[dims.length, dims.thickness, dims.width]} />
    </mesh>
  );
}

/**
 * Eases the camera towards the orbit state (≤ 600 ms settle), rendering on demand only while it
 * moves; under reduced motion the camera jumps and a single frame is rendered.
 */
function CameraRig({ orbit, distance, reduced }: { orbit: OrbitState; distance: number; reduced: boolean }) {
  const { camera, invalidate } = useThree();
  const target = useMemo(() => new THREE.Vector3(...cameraPosition(orbit, distance)), [orbit, distance]);
  const settled = useRef(false);

  useEffect(() => {
    settled.current = false;
    if (reduced) {
      camera.position.copy(target);
      camera.lookAt(0, 0, 0);
      settled.current = true;
    }
    invalidate();
  }, [target, reduced, camera, invalidate]);

  useFrame((_, delta) => {
    if (settled.current) return;
    // Exponential approach: ~95 % of the way in 0.45 s, visually settled well inside 600 ms.
    camera.position.lerp(target, 1 - Math.exp(-delta * 6.5));
    camera.lookAt(0, 0, 0);
    if (camera.position.distanceToSquared(target) < 1e-7) {
      camera.position.copy(target);
      settled.current = true;
    } else {
      invalidate();
    }
  });
  return null;
}

export function MaterialScene({ swatch, dims, orbit, reduced }: { swatch: Swatch; dims: SlabDimensions; orbit: OrbitState; reduced: boolean }) {
  const distance = framingDistance(dims);
  return (
    <>
      <CameraRig orbit={orbit} distance={distance} reduced={reduced} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[1.6, 2.4, 1.4]} intensity={1.7} castShadow shadow-mapSize={[1024, 1024]} shadow-bias={-0.0004} />
      <directionalLight position={[-1.8, 1.2, -1.2]} intensity={0.45} />
      <Slab swatch={swatch} dims={dims} />
      <ContactShadows position={[0, -dims.thickness / 2 - 0.0005, 0]} opacity={0.5} scale={Math.max(dims.length, dims.width) * 2.4} blur={2.4} far={0.6} frames={1} />
    </>
  );
}

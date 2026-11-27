"use client";

import { animate } from "animejs";
import { useEffect, useRef } from "react";
import {
  BufferGeometry,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  Line,
  LineBasicMaterial,
  LineLoop,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
} from "three";

const INK = 0x14211e;
const SIGNAL = 0xe4570e;

function circle(radius: number, y = 0, segments = 128): BufferGeometry {
  const points: Vector3[] = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    points.push(new Vector3(Math.sin(a) * radius, y, -Math.cos(a) * radius));
  }
  return new BufferGeometry().setFromPoints(points);
}

function ticks(): BufferGeometry {
  const positions: number[] = [];
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    const inner = i % 6 === 0 ? 0.7 : 0.78;
    const outer = 0.86;
    positions.push(Math.sin(a) * inner, 0, -Math.cos(a) * inner);
    positions.push(Math.sin(a) * outer, 0, -Math.cos(a) * outer);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  return geometry;
}

function meridian(): BufferGeometry {
  const points: Vector3[] = [];
  for (let i = 0; i <= 48; i++) {
    const a = (i / 48) * Math.PI;
    points.push(new Vector3(0, Math.sin(a) * 0.55, -Math.cos(a) * 1.06));
  }
  return new BufferGeometry().setFromPoints(points);
}

/**
 * A compass seen at an angle, drawn in lines. It renders only when its heading changes:
 * no loop runs while it is still. Its needle turns to the heading in degrees.
 */
export default function CompassThree({
  heading,
  onReady,
  onFail,
}: {
  heading: number;
  onReady: () => void;
  onFail: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const turn = useRef<((deg: number) => void) | null>(null);
  const initial = useRef(heading);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      onFail();
      return;
    }

    const scene = new Scene();
    const camera = new PerspectiveCamera(30, 1, 0.1, 50);
    camera.position.set(0, 2.05, 2.3);
    camera.lookAt(0, 0.08, 0);

    const ink = new LineBasicMaterial({ color: INK, transparent: true, opacity: 0.78 });
    const faint = new LineBasicMaterial({ color: INK, transparent: true, opacity: 0.32 });
    const signalLine = new LineBasicMaterial({ color: SIGNAL });
    const signalFill = new MeshBasicMaterial({ color: SIGNAL, side: DoubleSide });

    const geometries: BufferGeometry[] = [];
    const keep = <T extends BufferGeometry>(geometry: T) => {
      geometries.push(geometry);
      return geometry;
    };

    scene.add(new LineLoop(keep(circle(1.0)), ink));
    scene.add(new LineLoop(keep(circle(0.86)), faint));
    scene.add(new LineSegments(keep(ticks()), ink));
    scene.add(new Line(keep(meridian()), faint));

    const north = keep(new BufferGeometry().setFromPoints([
      new Vector3(-0.07, 0, -1.04),
      new Vector3(0.07, 0, -1.04),
      new Vector3(0, 0, -1.17),
    ]));
    north.setIndex([0, 1, 2]);
    scene.add(new Mesh(north, signalFill));

    const needle = new Group();
    const head = keep(new BufferGeometry().setFromPoints([
      new Vector3(0, 0.03, -0.66),
      new Vector3(0.085, 0.03, 0),
      new Vector3(-0.085, 0.03, 0),
    ]));
    head.setIndex([0, 1, 2]);
    needle.add(new Mesh(head, signalFill));
    needle.add(new LineLoop(keep(new BufferGeometry().setFromPoints([
      new Vector3(0.085, 0.03, 0),
      new Vector3(0, 0.03, 0.66),
      new Vector3(-0.085, 0.03, 0),
    ])), ink));
    needle.add(new LineLoop(keep(circle(0.045, 0.035, 24)), signalLine));
    scene.add(needle);

    const render = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        renderer.setSize(width, height, false);
        camera.aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
        camera.updateProjectionMatrix();
      }
      renderer.render(scene, camera);
    };

    const state = { deg: initial.current };
    needle.rotation.y = -(state.deg * Math.PI) / 180;
    render();
    onReady();

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let tween: ReturnType<typeof animate> | null = null;
    turn.current = (deg: number) => {
      tween?.pause();
      const apply = () => {
        needle.rotation.y = -(state.deg * Math.PI) / 180;
        render();
      };
      if (reduce.matches) {
        state.deg = deg;
        apply();
        return;
      }
      tween = animate(state, { deg, duration: 520, ease: "out(3)", onUpdate: apply });
    };

    const resize = new ResizeObserver(render);
    resize.observe(canvas);

    return () => {
      tween?.pause();
      resize.disconnect();
      turn.current = null;
      geometries.forEach((geometry) => geometry.dispose());
      [ink, faint, signalLine, signalFill].forEach((material) => material.dispose());
      renderer.dispose();
    };
  }, [onReady, onFail]);

  useEffect(() => {
    turn.current?.(heading);
  }, [heading]);

  return <canvas ref={canvasRef} aria-hidden="true" className="block size-full" />;
}

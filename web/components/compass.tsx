"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

// The three.js compass is loaded after the page, in its own chunk. Until it is ready, and
// wherever WebGL is missing, this flat drawing stands in. Both show the same heading.
const CompassThree = dynamic(() => import("@/components/compass-three"), { ssr: false });

// Rounded so the server and the browser write identical numbers into the markup.
const round = (n: number) => Math.round(n * 1000) / 1000;
const ticks = Array.from({ length: 72 }, (_, i) => i);

export function CompassFlat({ heading }: { heading: number }) {
  return (
    <svg viewBox="-60 -60 120 120" className="size-full" aria-hidden="true">
      <circle r="52" fill="none" stroke="var(--ink)" strokeOpacity="0.78" strokeWidth="1.2" />
      <circle r="45" fill="none" stroke="var(--ink)" strokeOpacity="0.32" strokeWidth="1" />
      {ticks.map((i) => {
        const a = (i / 72) * Math.PI * 2;
        const inner = i % 6 === 0 ? 37 : 41;
        return (
          <line
            key={i}
            x1={round(Math.sin(a) * inner)}
            y1={round(-Math.cos(a) * inner)}
            x2={round(Math.sin(a) * 45)}
            y2={round(-Math.cos(a) * 45)}
            stroke="var(--ink)"
            strokeOpacity="0.78"
            strokeWidth="1"
          />
        );
      })}
      <path d="M-4 -54 L4 -54 L0 -60 Z" fill="var(--signal)" />
      <g
        style={{ transform: `rotate(${heading}deg)` }}
        className="transition-transform duration-500 ease-[var(--ease-out)] motion-reduce:transition-none"
      >
        <path d="M0 -34 L4.5 0 L-4.5 0 Z" fill="var(--signal)" />
        <path d="M4.5 0 L0 34 L-4.5 0" fill="none" stroke="var(--ink)" strokeWidth="1.2" />
        <circle r="2.4" fill="var(--sheet)" stroke="var(--signal)" strokeWidth="1.2" />
      </g>
    </svg>
  );
}

export function Compass({ heading, className = "" }: { heading: number; className?: string }) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const onReady = useCallback(() => setReady(true), []);
  const onFail = useCallback(() => setFailed(true), []);
  return (
    <div className={`relative ${className}`} aria-hidden="true">
      <div className={`absolute inset-0 transition-opacity duration-200 ${ready && !failed ? "opacity-0" : ""}`}>
        <CompassFlat heading={heading} />
      </div>
      {failed ? null : (
        <div className="absolute inset-0">
          <CompassThree heading={heading} onReady={onReady} onFail={onFail} />
        </div>
      )}
    </div>
  );
}

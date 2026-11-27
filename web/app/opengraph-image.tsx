import { ImageResponse } from "next/og";

// The picture shown when a TeleCompass link is shared: the site's own ground, ink and signal.
export const alt = "TeleCompass: a preflight check for telehealth visits";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const ticks = Array.from({ length: 72 }, (_, i) => i);
const round = (n: number) => Math.round(n * 1000) / 1000;

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "64px 72px",
          background: "#eef2f0",
          color: "#14211e",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", width: 720 }}>
          <div style={{ display: "flex", fontSize: 34, fontWeight: 600 }}>TeleCompass</div>
          <div
            style={{
              display: "flex",
              fontSize: 66,
              fontWeight: 500,
              lineHeight: 1.04,
              letterSpacing: -2,
              marginTop: 40,
            }}
          >
            Is this telehealth visit allowed, and will it be paid?
          </div>
          <div style={{ display: "flex", fontSize: 30, marginTop: 32, color: "#46554f" }}>
            Every answer comes with the exact words of the law.
          </div>
          <div style={{ display: "flex", fontSize: 24, marginTop: 40, color: "#a83b05" }}>
            Not legal advice.
          </div>
        </div>
        <svg width="300" height="300" viewBox="-60 -60 120 120">
          <circle r="52" fill="none" stroke="#14211e" strokeWidth="1.4" />
          <circle r="45" fill="none" stroke="#14211e" strokeOpacity="0.35" strokeWidth="1" />
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
                stroke="#14211e"
                strokeWidth="1"
              />
            );
          })}
          <path d="M-4 -54 L4 -54 L0 -60 Z" fill="#e4570e" />
          <g transform="rotate(330)">
            <path d="M0 -34 L4.5 0 L-4.5 0 Z" fill="#e4570e" />
            <path d="M4.5 0 L0 34 L-4.5 0" fill="none" stroke="#14211e" strokeWidth="1.2" />
          </g>
        </svg>
      </div>
    ),
    size,
  );
}

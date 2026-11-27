import { ImageResponse } from "next/og";

// The picture shown when a TeleCompass link is shared.
export const alt = "TeleCompass: a preflight check for telehealth visits";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "#0d3b4f",
          color: "#ffffff",
        }}
      >
        <div style={{ display: "flex", fontSize: 44, fontWeight: 600 }}>TeleCompass</div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 68, fontWeight: 700, lineHeight: 1.1 }}>
            Is this telehealth visit allowed, and will it be paid?
          </div>
          <div style={{ display: "flex", fontSize: 32, marginTop: 28, color: "#dcf1ed" }}>
            Every answer comes with the exact words of the law.
          </div>
        </div>
        <div style={{ display: "flex", fontSize: 26, color: "#dcf1ed" }}>Not legal advice.</div>
      </div>
    ),
    size,
  );
}

"use client";
import { useEffect, useRef } from "react";
export default function Pitch({
  points = null,
  shotKey = "idle",
  compact = false,
}: {
  points?: number | null;
  shotKey?: string;
  compact?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const g = ctx;
    let frame = 0;
    const begin = performance.now();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const W = 1000,
      H = 390;
    c.width = W * 2;
    c.height = H * 2;
    g.scale(2, 2);
    const rect = (
      x: number,
      y: number,
      w: number,
      h: number,
      color: string,
    ) => {
      g.fillStyle = color;
      g.fillRect(x, y, w, h);
    };
    const line = (
      x: number,
      y: number,
      x2: number,
      y2: number,
      color: string,
      width = 1,
    ) => {
      g.beginPath();
      g.moveTo(x, y);
      g.lineTo(x2, y2);
      g.strokeStyle = color;
      g.lineWidth = width;
      g.stroke();
    };
    const circle = (x: number, y: number, r: number, color: string) => {
      g.beginPath();
      g.arc(x, y, r, 0, Math.PI * 2);
      g.fillStyle = color;
      g.fill();
    };
    const poly = (ps: number[][], color: string) => {
      g.beginPath();
      ps.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
      g.closePath();
      g.fillStyle = color;
      g.fill();
    };
    function draw(t: number) {
      const sec = (t - begin) / 1000,
        phase = reduced ? 1 : Math.min(1, Math.max(0, (sec - 0.35) / 1.5));
      g.clearRect(0, 0, W, H);
      const sky = g.createLinearGradient(0, 0, 0, 270);
      sky.addColorStop(0, "#d9dcc5");
      sky.addColorStop(1, "#f0c5a0");
      g.fillStyle = sky;
      g.fillRect(0, 0, W, H);
      circle(715, 99, 38, "#f7e4b6");
      circle(715, 99, 47, "#f7e4b61a");
      // Distant town, rooftops and trees.
      for (let i = 0; i < 28; i++) {
        let x = i * 41,
          y = 167 - ((i * 17) % 35);
        rect(x, y, 36, 90, i % 2 ? "#8d9e8a" : "#a5ad94");
        poly(
          [
            [x - 3, y],
            [x + 18, y - 14],
            [x + 39, y],
          ],
          "#818f7d",
        );
        for (let j = 0; j < 3; j++) rect(x + 6 + j * 9, y + 9, 3, 5, "#c0bd9c");
      }
      for (const x of [18, 106, 341, 551, 956]) {
        rect(x, 151, 5, 75, "#536d5c");
        circle(x, 143, 25, "#7b9272");
        circle(x - 12, 155, 21, "#7b9272");
      }
      // Floodlights, with restrained evening glow.
      for (const x of [84, 930]) {
        line(x, 56, x - 8, 252, "#496353", 5);
        line(x - 12, 122, x + 17, 122, "#496353", 2);
        poly(
          [
            [x - 8, 65],
            [x + 220, 259],
            [x - 80, 259],
          ],
          "#f7e9bf0c",
        );
        rect(x - 29, 37, 62, 28, "#3c5749");
        for (let j = 0; j < 6; j++) rect(x - 24 + j * 9, 42, 6, 6, "#f9e8b8");
        for (let j = 0; j < 6; j++) rect(x - 24 + j * 9, 52, 6, 6, "#f9e8b8");
      }
      // Old terrace, stepped seats, hand-painted roof.
      poly(
        [
          [0, 186],
          [400, 178],
          [1000, 190],
          [1000, 205],
          [0, 200],
        ],
        "#274c3c",
      );
      rect(0, 202, 1000, 60, "#51654d");
      for (let j = 0; j < 4; j++) {
        rect(0, 208 + j * 13, 1000, 3, "#849178");
        for (let i = 0; i < 95; i++) {
          const x = i * 11 + (j % 2 ? 5 : 0),
            y = 205 + j * 13;
          const colors = [
            "#b1b496",
            "#e7d6ac",
            "#294d3b",
            "#8c9b7d",
            "#cb896c",
          ];
          circle(x, y, 2.1, colors[(i * 3 + j) % 5]);
          rect(x - 2, y + 2, 4, 5, colors[(i + j) % 5]);
        }
      }
      rect(0, 257, 1000, 27, "#294b3a");
      g.font = "bold 11px monospace";
      g.textAlign = "center";
      g.fillStyle = "#d9d9bb";
      g.fillText("THE STREETS REMEMBER", 180, 274);
      g.fillStyle = "#eeb189";
      g.fillText("GAFFER’S GAMBIT", 500, 274);
      g.fillStyle = "#d9d9bb";
      g.fillText("EST. 2026", 795, 274);
      // Striped playing surface.
      rect(0, 284, W, 106, "#6d9063");
      for (let i = 0; i < 9; i++)
        poly(
          [
            [i * 130, 284],
            [i * 130 + 60, 284],
            [i * 130 - 20, 390],
            [i * 130 - 100, 390],
          ],
          "#63865c",
        );
      line(0, 306, 1000, 306, "#c7d4ae", 1.2);
      line(0, 369, 1000, 369, "#dce3bc", 1.2);
      line(505, 284, 493, 390, "#c5d5ab", 1.1);
      g.strokeStyle = "#c5d5ab";
      g.lineWidth = 1.1;
      g.beginPath();
      g.ellipse(500, 335, 61, 28, 0, 0, Math.PI * 2);
      g.stroke();
      circle(500, 335, 2, "#dbe0bb");
      g.beginPath();
      g.moveTo(772, 306);
      g.lineTo(751, 369);
      g.lineTo(1000, 369);
      g.stroke();
      line(811, 306, 798, 351, "#c5d5ab");
      line(798, 351, 1000, 351, "#c5d5ab");
      // Goal and net: side elevation, enough depth to see the shot settle.
      poly(
        [
          [885, 237],
          [946, 250],
          [946, 330],
          [885, 324],
        ],
        "#f6eed41b",
      );
      poly(
        [
          [885, 237],
          [918, 232],
          [976, 246],
          [946, 250],
        ],
        "#fbf0cb30",
      );
      poly(
        [
          [946, 250],
          [976, 246],
          [978, 325],
          [946, 330],
        ],
        "#e6e2be22",
      );
      for (let j = 0; j < 10; j++) {
        line(
          885 + j * 6.1,
          237 + j * 1.3,
          885 + j * 6.1,
          324 + j * 0.6,
          "#e6e3c285",
        );
      }
      for (let j = 0; j < 10; j++)
        line(885, 237 + j * 8.6, 946, 250 + j * 8, "#e6e3c285");
      line(885, 324, 885, 237, "#f8efd5", 4);
      line(885, 237, 946, 250, "#f8efd5", 4);
      line(946, 250, 946, 330, "#f8efd5", 4);
      line(946, 250, 976, 246, "#f8efd5", 2);
      line(976, 246, 978, 325, "#f8efd5", 2);
      // Little number nine. A frame-driven kick, followed by a watchful stance.
      const kicking = points !== null && sec < 0.65 && !reduced;
      g.save();
      g.translate(139, 298);
      g.fillStyle = "#253f2b55";
      g.beginPath();
      g.ellipse(2, 31, 20, 5, 0, 0, 7);
      g.fill();
      line(-3, 10, -8, 27, "#f1d1a6", 7);
      line(-8, 27, -13, 31, "#1c382e", 6);
      line(5, 10, kicking ? 26 : 11, kicking ? 13 : 27, "#efd1a7", 7);
      line(
        kicking ? 26 : 11,
        kicking ? 13 : 27,
        kicking ? 34 : 18,
        kicking ? 12 : 31,
        "#203a2e",
        6,
      );
      poly(
        [
          [-11, -14],
          [10, -14],
          [14, 6],
          [6, 12],
          [-8, 10],
        ],
        "#ed9e76",
      );
      rect(-8, 6, 18, 8, "#f5e7c6");
      line(-11, -10, -19, 5, "#f0caa1", 5);
      line(11, -10, 19, kicking ? -18 : 1, "#f0caa1", 5);
      circle(0, -24, 9, "#e9c39a");
      poly(
        [
          [-9, -25],
          [-8, -32],
          [3, -34],
          [9, -29],
          [7, -23],
          [0, -28],
        ],
        "#284435",
      );
      g.fillStyle = "#234b37";
      g.font = "bold 15px Georgia";
      g.textAlign = "center";
      g.fillText("9", 1, 2);
      g.restore();
      let bx = 177,
        by = 321;
      const distance = points === null ? 0 : points === 0 ? 40 : points * 7.15;
      if (points !== null) {
        bx += distance * phase;
        const endY = points === 100 ? 258 : 321;
        by =
          321 +
          (endY - 321) * phase -
          Math.sin(phase * Math.PI) *
            (points === 100 ? 135 : 30 + (points ?? 0) * 0.9);
      }
      if (points !== null && phase < 1 && points > 0) {
        g.setLineDash([3, 7]);
        g.strokeStyle = "#fff7d887";
        g.lineWidth = 2;
        g.beginPath();
        for (let i = 0; i <= phase * 30; i++) {
          const p = i / 30,
            x = 177 + distance * p,
            y =
              321 +
              ((points === 100 ? 258 : 321) - 321) * p -
              Math.sin(p * Math.PI) *
                (points === 100 ? 135 : 30 + points * 0.9);
          i ? g.lineTo(x, y) : g.moveTo(x, y);
        }
        g.stroke();
        g.setLineDash([]);
      }
      g.fillStyle = "#244a3555";
      g.beginPath();
      g.ellipse(bx, 329, 9, 3, 0, 0, 7);
      g.fill();
      g.save();
      g.translate(bx, by);
      g.rotate(sec * (points !== null && phase < 1 ? 8 : 0));
      circle(0, 0, 7, "#fff5d9");
      poly(
        [
          [-2, -4],
          [3, -3],
          [4, 2],
          [0, 4],
          [-4, 1],
        ],
        "#284b3c",
      );
      g.restore();
      if (points === 100 && phase === 1) {
        g.textAlign = "center";
        g.fillStyle = "#203d2c";
        g.fillRect(390, 68, 220, 54);
        g.fillStyle = "#f7d59c";
        g.font = "italic bold 33px Georgia";
        g.fillText("Top bins.", 500, 106);
        if (!reduced)
          for (let i = 0; i < 22; i++) {
            let x = 820 + Math.sin(i * 9) * 100,
              y = 220 - ((sec * 45 + i * 17) % 130);
            rect(x, y, 3, 6, ["#f8d08c", "#f1a880", "#e8e5c9"][i % 3]);
          }
      }
      if (points !== null && points < 100 && phase === 1) {
        g.font = "bold 12px monospace";
        g.fillStyle = "#eff1d2";
        g.textAlign = "center";
        g.fillText(
          points === 0 ? "OFF TARGET" : `${points} METRES`,
          bx,
          by - 21,
        );
      }
      // Tiny pennant and drifting birds give the ground life without visual noise.
      line(18, 288, 18, 325, "#e9d7ae", 2);
      poly(
        [
          [18, 288],
          [37, 293 + Math.sin(sec * 2) * 2],
          [18, 299],
        ],
        "#eaa37a",
      );
      for (let i = 0; i < 3; i++) {
        let x = 390 + i * 20 + (reduced ? 0 : Math.sin(sec * 0.18) * 16),
          y = 66 + i * 8;
        line(x - 5, y, x, y + 2, "#687e69");
        line(x, y + 2, x + 5, y, "#687e69");
      }
      if (!reduced && document.visibilityState === "visible")
        frame = requestAnimationFrame(draw);
    }
    draw(document.visibilityState === "visible" ? begin : begin + 2000);
    const visibility = () => {
      cancelAnimationFrame(frame);
      if (document.visibilityState === "visible")
        frame = requestAnimationFrame(draw);
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [points, shotKey]);
  return (
    <div className={`pitch ${compact ? "pitch-compact" : ""}`}>
      <canvas
        ref={ref}
        role="img"
        aria-label={
          points === null
            ? "An illustrated football ground at dusk. A number nine lines up a shot."
            : points === 100
              ? "The ball flies into the top corner. Top bins!"
              : `The shot travels ${points} metres.`
        }
      />
      <div className="pitch-caption">
        <span>THE GAMBIT GROUND</span>
        <span>RARE KNOWLEDGE. LONG RANGE.</span>
      </div>
    </div>
  );
}

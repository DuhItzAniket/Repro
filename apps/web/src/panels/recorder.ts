// Test-only: a Canvas 2D stand-in that records what a panel draws, so panels get golden
// "screenshots" without a browser (pixel screenshots arrive with Playwright in B12).
import type { Ctx2D } from "./panel";

const r = (v: number) => Math.round(v * 10) / 10;

export class RecordingContext implements Ctx2D {
  readonly calls: string[] = [];
  fillStyle: string | CanvasGradient | CanvasPattern = "#000";
  strokeStyle: string | CanvasGradient | CanvasPattern = "#000";
  font = "";
  textBaseline: CanvasTextBaseline = "alphabetic";
  textAlign: CanvasTextAlign = "start";
  globalAlpha = 1;
  lineWidth = 1;

  private style(): string {
    return `${String(this.fillStyle)} a${r(this.globalAlpha)}`;
  }

  fillRect(x: number, y: number, w: number, h: number): void {
    this.calls.push(`rect ${r(x)},${r(y)} ${r(w)}x${r(h)} ${this.style()}`);
  }
  strokeRect(x: number, y: number, w: number, h: number): void {
    this.calls.push(`strokeRect ${r(x)},${r(y)} ${r(w)}x${r(h)} ${String(this.strokeStyle)}`);
  }
  clearRect(): void {}
  fillText(text: string, x: number, y: number): void {
    this.calls.push(
      `text "${text}" ${r(x)},${r(y)} ${this.font.split(" ").slice(0, 2).join(" ")} ${this.style()}`,
    );
  }
  beginPath(): void {}
  moveTo(x: number, y: number): void {
    this.calls.push(`moveTo ${r(x)},${r(y)}`);
  }
  lineTo(x: number, y: number): void {
    this.calls.push(`lineTo ${r(x)},${r(y)}`);
  }
  arc(x: number, y: number, radius: number): void {
    this.calls.push(`arc ${r(x)},${r(y)} r${r(radius)}`);
  }
  stroke(): void {
    this.calls.push(
      `stroke ${String(this.strokeStyle)} w${this.lineWidth} a${r(this.globalAlpha)}`,
    );
  }
  fill(): void {
    this.calls.push(`fill ${this.style()}`);
  }
  save(): void {}
  restore(): void {}

  text(): string {
    return `${this.calls.join("\n")}\n`;
  }
}

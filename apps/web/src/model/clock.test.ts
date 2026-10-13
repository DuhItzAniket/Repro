import { describe, expect, it } from "vitest";
import { PresentationClock } from "./clock";

function fakeClock(end = 10_000) {
  let wall = 1_000;
  const clock = new PresentationClock(() => wall);
  clock.setEnd(end);
  return {
    clock,
    advance: (ms: number) => {
      wall += ms;
    },
  };
}

describe("PresentationClock", () => {
  it("starts paused at 0 in replay mode", () => {
    const { clock, advance } = fakeClock();
    advance(500);
    expect(clock.status()).toEqual({ mode: "replay", speed: 1, paused: true, t: 0, end: 10_000 });
  });

  it("advances at the replay speed and keeps t continuous across speed changes", () => {
    const { clock, advance } = fakeClock();
    clock.play();
    advance(1_000);
    expect(clock.time()).toBe(1_000);
    clock.setSpeed(4);
    expect(clock.time()).toBe(1_000);
    advance(500);
    expect(clock.time()).toBe(3_000);
    clock.setSpeed(0.5);
    advance(1_000);
    expect(clock.time()).toBe(3_500);
  });

  it("pause freezes presentation while data keeps arriving (global pause)", () => {
    const { clock, advance } = fakeClock();
    clock.play();
    advance(2_000);
    clock.pause();
    advance(5_000);
    clock.setEnd(20_000);
    expect(clock.time()).toBe(2_000);
    clock.toggle();
    advance(100);
    expect(clock.time()).toBe(2_100);
  });

  it("waits at the end of the data without jumping when more arrives", () => {
    const { clock, advance } = fakeClock(1_000);
    clock.setSpeed(16);
    clock.play();
    advance(10_000);
    expect(clock.time()).toBe(1_000);
    clock.setEnd(5_000);
    expect(clock.time()).toBe(1_000); // no jump to where the wall clock "would" be
    advance(100);
    expect(clock.time()).toBe(2_600);
  });

  it("seeks within the data and keeps the play state", () => {
    const { clock, advance } = fakeClock();
    clock.seek(4_000);
    expect(clock.status()).toMatchObject({ t: 4_000, paused: true });
    clock.seek(-50);
    expect(clock.time()).toBe(0);
    clock.seek(99_999);
    expect(clock.time()).toBe(10_000);
    clock.seek(3_000);
    clock.play();
    advance(250);
    expect(clock.time()).toBe(3_250);
  });

  it("goes live at the data's edge and follows wall time at ×1", () => {
    const { clock, advance } = fakeClock(7_000);
    clock.setSpeed(16);
    clock.goLive();
    expect(clock.status()).toMatchObject({ mode: "live", paused: false, t: 7_000 });
    advance(300);
    expect(clock.time()).toBe(7_300); // ×1 in live, and not clamped to the data
  });

  it("pausing live drops to a ×1 replay behind the edge; goLive catches up", () => {
    const { clock, advance } = fakeClock(7_000);
    clock.goLive();
    advance(1_000);
    clock.pause();
    expect(clock.status()).toMatchObject({ mode: "replay", speed: 1, paused: true, t: 8_000 });
    clock.setEnd(12_000);
    clock.goLive();
    expect(clock.time()).toBe(12_000);
  });

  it("never moves its data edge backwards", () => {
    const { clock } = fakeClock(5_000);
    clock.setEnd(2_000);
    expect(clock.end).toBe(5_000);
  });
});

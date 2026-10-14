import { describe, expect, it } from "vitest";
import { latestRun, sourceFromQuery, streamUrl } from "./source";

const RUN = "run_01M4XFFGE7890FQMJMSM5RP3T9";

describe("sourceFromQuery", () => {
  it.each([
    [`?run=${RUN}`, { kind: "run", runId: RUN, replay: false }],
    [`?run=${RUN}&replay`, { kind: "run", runId: RUN, replay: true }],
    [`?run=${RUN}&test`, { kind: "run", runId: RUN, replay: false }],
    ["?log=stress", { kind: "fixture", name: "stress" }],
    ["?log=demo", { kind: "fixture", name: "demo" }],
    ["?log=/replay.jsonl", { kind: "log", url: "/replay.jsonl" }],
    ["?log=//elsewhere.example/x.jsonl", { kind: "fixture", name: "demo" }],
    ["?log=https://elsewhere.example/x.jsonl", { kind: "fixture", name: "demo" }],
    ["?run=run_not-an-id", { kind: "latest" }],
    ["?test", { kind: "fixture", name: "demo" }],
    ["", { kind: "latest" }],
  ])("%s", (search, expected) => {
    expect(sourceFromQuery(search)).toEqual(expected);
  });
});

describe("latestRun", () => {
  const respond = (body: string, status = 200) =>
    (async () => new Response(body, { status })) as unknown as typeof fetch;

  it("takes the newest run from the engine", async () => {
    expect(await latestRun(respond(JSON.stringify([{ id: RUN }])))).toBe(RUN);
  });

  it.each([
    ["no runs", respond("[]")],
    ["a dev server's page", respond("<!doctype html>")],
    ["an error", respond("{}", 503)],
    ["an unexpected id", respond(JSON.stringify([{ id: "../x" }]))],
    [
      "no server",
      (async () => Promise.reject(new TypeError("failed to fetch"))) as unknown as typeof fetch,
    ],
  ])("is null for %s", async (_what, fetcher) => {
    expect(await latestRun(fetcher)).toBeNull();
  });
});

it("builds the stream URL on the page's origin", () => {
  expect(streamUrl({ protocol: "http:", host: "127.0.0.1:8780" }, RUN, 12)).toBe(
    `ws://127.0.0.1:8780/runs/${RUN}/events?from=12`,
  );
  expect(streamUrl({ protocol: "https:", host: "h" }, RUN, 0)).toBe(
    `wss://h/runs/${RUN}/events?from=0`,
  );
});

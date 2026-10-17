import { describe, expect, it } from "vitest";
import { type TokenStorage, takeToken, withToken } from "./session";

const TOKEN = `${"t".repeat(40)}_-x`; // shaped like a token, plainly not one

function memory(): TokenStorage & { readonly items: Map<string, string> } {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => {
      items.set(key, value);
    },
  };
}

describe("takeToken", () => {
  it("takes the token from the fragment, keeps it and clears the address bar", () => {
    const storage = memory();
    const replaced: string[] = [];
    const place = { hash: `#token=${TOKEN}`, pathname: "/", search: "?run=x&test" };
    expect(takeToken(place, storage, (url) => replaced.push(url))).toBe(TOKEN);
    expect(replaced).toEqual(["/?run=x&test"]);
    expect(storage.items.get("repro.token")).toBe(TOKEN);
  });

  it("finds the kept token after a reload, and nothing without one", () => {
    const storage = memory();
    storage.setItem("repro.token", TOKEN);
    const place = { hash: "", pathname: "/", search: "" };
    expect(takeToken(place, storage, () => undefined)).toBe(TOKEN);
    expect(takeToken(place, memory(), () => undefined)).toBeNull();
    expect(takeToken(place, null, () => undefined)).toBeNull();
  });

  it("refuses what is not a token, and still clears it from the address bar", () => {
    const replaced: string[] = [];
    const place = { hash: "#token=<script>", pathname: "/", search: "" };
    expect(takeToken(place, memory(), (url) => replaced.push(url))).toBeNull();
    expect(replaced).toEqual(["/"]);
  });

  it("works when storage is blocked", () => {
    const blocked: TokenStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    const place = { hash: `#token=${TOKEN}`, pathname: "/", search: "" };
    expect(takeToken(place, blocked, () => undefined)).toBe(TOKEN);
    expect(takeToken({ ...place, hash: "" }, blocked, () => undefined)).toBeNull();
  });
});

describe("withToken", () => {
  it("adds the token as a bearer credential, keeping the other headers", async () => {
    const seen: Headers[] = [];
    const fetcher = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      seen.push(new Headers(init?.headers));
      return new Response("[]");
    }) as typeof fetch;
    await withToken(TOKEN, fetcher)("/runs", { headers: { Accept: "application/json" } });
    expect(seen[0]?.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(seen[0]?.get("Accept")).toBe("application/json");
    expect(withToken(null, fetcher)).toBe(fetcher);
  });
});

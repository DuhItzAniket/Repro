/**
 * The engine's per-session token (THREAT_MODEL T13, H03). `repro` prints the cockpit's URL with
 * the token in its fragment (`#token=…`), which a browser never sends to a server. The cockpit
 * takes it out of the address bar, keeps it in `sessionStorage` (one per tab and per origin,
 * port included), and sends it with each request for the engine's data: a header on fetches, a
 * query parameter on the event stream, whose handshake cannot carry headers.
 */

const KEY = "repro.token";
/** `secrets.token_urlsafe(32)`: 43 characters of URL-safe base64; anything else is refused. */
const TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

export interface Place {
  readonly hash: string;
  readonly pathname: string;
  readonly search: string;
}

export type TokenStorage = Pick<Storage, "getItem" | "setItem">;

/**
 * The session's token: from the URL's fragment, which `replace` then removes from the address
 * bar, else from this tab's storage (a reload); null when there is none.
 */
export function takeToken(
  place: Place,
  storage: TokenStorage | null,
  replace: (url: string) => void,
): string | null {
  const given = new URLSearchParams(place.hash.replace(/^#/, "")).get("token");
  if (given !== null) {
    replace(`${place.pathname}${place.search}`);
    if (!TOKEN.test(given)) return null;
    try {
      storage?.setItem(KEY, given);
    } catch {
      // blocked site data: this page load still has it
    }
    return given;
  }
  try {
    const kept = storage?.getItem(KEY) ?? null;
    return kept !== null && TOKEN.test(kept) ? kept : null;
  } catch {
    return null;
  }
}

/** `fetcher` sending the session's token, when there is one. */
export function withToken(token: string | null, fetcher: typeof fetch = fetch): typeof fetch {
  if (token === null) return fetcher;
  return (input, init) => {
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return fetcher(input, { ...init, headers });
  };
}

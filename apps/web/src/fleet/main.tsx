/**
 * The fleet view (K02): every run the engine serving this page holds, as tiles, refreshed every
 * two seconds from `/fleet`. A tile opens its run in the cockpit. The page shares the cockpit's
 * session token (sessionStorage, per origin) and its design tokens.
 */
import "@fontsource-variable/jetbrains-mono/wght.css";
import "../styles/tokens.css";
import "./fleet.css";
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { takeToken, withToken } from "../data/session";
import { LOCKED } from "../data/source";
import { counts, readFleet, type Tile, tiles } from "./model";

const POLL_MS = 2000;
const LIMIT = 64;

function tokenStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null; // blocked site data
  }
}

const token = takeToken(window.location, tokenStorage(), (url) =>
  window.history.replaceState(window.history.state, "", url),
);
const engineFetch = withToken(token);

const LABEL: Record<Tile["state"], string> = {
  running: "running",
  verified: "VERIFIED",
  flagged: "FLAGGED",
  unverifiable: "UNVERIFIABLE",
  failed: "failed",
};

function Fleet() {
  const [made, setMade] = useState<Tile[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let seen = new Map<string, number>();
    let stopped = false;
    async function poll(): Promise<void> {
      try {
        const response = await engineFetch(`/fleet?limit=${LIMIT}`, {
          headers: { Accept: "application/json" },
        });
        if (response.status === 401) {
          setProblem(LOCKED);
          return;
        }
        if (!response.ok) throw new Error(`the engine answered ${response.status}`);
        const next = tiles(readFleet(await response.json()), seen);
        seen = next.seen;
        if (!stopped) {
          setMade(next.tiles);
          setProblem(null);
        }
      } catch (error) {
        if (!stopped) setProblem(`No engine answers here (${String(error)}). Run repro serve.`);
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main class="fleet">
      <header>
        <h1>Fleet</h1>
        <p class="counts" aria-live="polite">
          {made.length} runs
          {counts(made)
            .filter(([, n]) => n > 0)
            .map(([state, n]) => (
              <span key={state} class={`count ${state}`}>
                {" "}
                · {n} {LABEL[state]}
              </span>
            ))}
        </p>
      </header>
      {problem !== null && <p class="problem">{problem}</p>}
      <ul class="tiles">
        {made.map((tile) => (
          <li key={tile.id}>
            <a
              class={`tile ${tile.state}${tile.pulse ? " pulse" : ""}`}
              href={`/?run=${tile.id}`}
              aria-label={`${tile.title}, ${tile.where}: ${LABEL[tile.state]}, ${tile.events} events`}
            >
              <span class="state">{LABEL[tile.state]}</span>
              <span class="title">{tile.title}</span>
              <span class="where">{tile.where}</span>
              <span class="events">{tile.events} events</span>
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}

const root = document.getElementById("app");
if (root === null) throw new Error("Repro: #app root element is missing from fleet.html");
render(<Fleet />, root);

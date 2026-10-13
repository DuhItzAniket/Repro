// Runs the force layout off the main thread (ARCHITECTURE §13: "layout.worker").
import { forceLayout } from "./force";

interface LayoutRequest {
  readonly id: number;
  readonly ids: readonly string[];
  readonly links: Int32Array;
  readonly containment: number;
}

// The app compiles against the DOM library; a worker's global scope only needs these two members.
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<LayoutRequest>) => void) | null;
  postMessage(message: unknown, transfer: Transferable[]): void;
};

scope.onmessage = (event) => {
  const { id, ids, links, containment } = event.data;
  const positions = forceLayout({ ids, links, containment });
  scope.postMessage({ id, positions }, [positions.buffer]);
};

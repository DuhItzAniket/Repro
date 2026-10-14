// Draws the card atlas off the main thread (ARCHITECTURE §13: "atlas.worker").
import { type AtlasCard, atlasLayout, cardUnits, drawAtlas } from "./atlas";

interface AtlasRequest {
  readonly id: number;
  readonly cards: readonly AtlasCard[];
}

// The app compiles against the DOM library; a worker's global scope only needs these members.
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<AtlasRequest>) => void) | null;
  postMessage(message: unknown, transfer: Transferable[]): void;
};

scope.onmessage = (event) => {
  const { id, cards } = event.data;
  const layout = atlasLayout(cards.map(cardUnits));
  const canvas = new OffscreenCanvas(layout.width, layout.height);
  const context = canvas.getContext("2d");
  if (context === null) {
    scope.postMessage({ id, bitmap: null, error: "no 2D context in worker" }, []);
    return;
  }
  drawAtlas(context, layout, cards);
  const bitmap = canvas.transferToImageBitmap();
  scope.postMessage({ id, bitmap }, [bitmap]);
};

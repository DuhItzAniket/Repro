/**
 * Builds the card atlas (in a worker when the browser can) and keeps the latest one. Layers
 * read `bitmap` and `version`; the host uploads the texture when `version` changes.
 */
import { type AtlasCard, atlasLayout, cardUnits, drawAtlas } from "./atlas";

export type AtlasBuild = (cards: readonly AtlasCard[]) => Promise<ImageBitmap | null>;

/** Main-thread fallback: an OffscreenCanvas or a detached canvas element. */
export const buildInline: AtlasBuild = async (cards) => {
  const layout = atlasLayout(cards.map(cardUnits));
  if (typeof OffscreenCanvas !== "undefined") {
    const canvas = new OffscreenCanvas(layout.width, layout.height);
    const context = canvas.getContext("2d");
    if (context === null) return null;
    drawAtlas(context, layout, cards);
    return canvas.transferToImageBitmap();
  }
  const canvas = document.createElement("canvas");
  canvas.width = layout.width;
  canvas.height = layout.height;
  const context = canvas.getContext("2d");
  if (context === null) return null;
  drawAtlas(context, layout, cards);
  return createImageBitmap(canvas);
};

/** Draws each atlas in a module worker (`atlas.worker.ts`). */
export function workerBuild(): AtlasBuild {
  let worker: Worker | null = null;
  let next = 0;
  const pending = new Map<number, (bitmap: ImageBitmap | null) => void>();
  return (cards) => {
    if (worker === null) {
      worker = new Worker(new URL("./atlas.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = (event: MessageEvent<{ id: number; bitmap: ImageBitmap | null }>) => {
        pending.get(event.data.id)?.(event.data.bitmap);
        pending.delete(event.data.id);
      };
    }
    const id = next++;
    // Only the drawn fields: a card's other fields need not cross to the worker.
    worker.postMessage({
      id,
      cards: cards.map(({ header, rows, dots, dotRows, meta }) => ({
        header,
        rows,
        dots,
        dotRows,
        meta,
      })),
    });
    return new Promise((resolve) => pending.set(id, resolve));
  };
}

/** Atlas builds can run in a worker when the browser has module workers and OffscreenCanvas. */
export function defaultAtlasBuild(): AtlasBuild {
  return typeof Worker !== "undefined" && typeof OffscreenCanvas !== "undefined"
    ? workerBuild()
    : buildInline;
}

export class AtlasService {
  private requested = "";
  private _bitmap: ImageBitmap | null = null;
  private _version = 0;

  constructor(private readonly build: AtlasBuild) {}

  get bitmap(): ImageBitmap | null {
    return this._bitmap;
  }

  get version(): number {
    return this._version;
  }

  /** Draws the atlas for `cards` unless the same `key` was already requested. */
  async request(key: string, cards: readonly AtlasCard[]): Promise<void> {
    if (key === this.requested) return;
    this.requested = key;
    const bitmap = await this.build(cards);
    if (this.requested !== key) {
      bitmap?.close();
      return;
    }
    this._bitmap?.close();
    this._bitmap = bitmap;
    this._version++;
  }
}

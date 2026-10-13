// Test-only helpers: load the JSON Schemas into Ajv (draft 2020-12) and read example files.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";

export const PKG = fileURLToPath(new URL("../..", import.meta.url));
export const SCHEMA_DIR = join(PKG, "schema");
export const EXAMPLES_DIR = join(PKG, "examples");
// In-memory base URI for resolving the schemas' relative $refs (.invalid is reserved, RFC 2606).
const BASE = "https://repro.invalid/schema/";

export const readJson = <T>(path: string): T => JSON.parse(readFileSync(path, "utf8")) as T;

export interface EventCases {
  valid: unknown[];
  invalid: { reason: string; event: unknown }[];
}

export interface ModelCases {
  valid: unknown[];
  invalid: { reason: string; value: unknown }[];
}

function buildAjv(): Ajv2020 {
  // ajv-formats is CommonJS; under ESM interop its function may sit on `.default`.
  const addFormats = ((addFormatsModule as unknown as { default?: unknown }).default ??
    addFormatsModule) as (ajv: Ajv2020) => void;
  const ajv = new Ajv2020({ strict: true, allErrors: true, allowUnionTypes: true });
  addFormats(ajv);
  for (const entry of readdirSync(SCHEMA_DIR, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".schema.json")) continue;
    const path = join(entry.parentPath, entry.name);
    const rel = relative(SCHEMA_DIR, path).split(sep).join("/");
    ajv.addSchema({ ...readJson<object>(path), $id: BASE + rel });
  }
  return ajv;
}

const ajv = buildAjv();

export function validator(rel: string): ValidateFunction {
  const validate = ajv.getSchema(BASE + rel);
  if (!validate) throw new Error(`schema not loaded: ${rel}`);
  return validate;
}

/** Parses a JSONL event log. Bad lines are reported, not thrown, so a damaged log still loads. */

export interface JsonlLineError {
  /** 1-based line number. */
  readonly line: number;
  readonly message: string;
}

export interface ParsedJsonl {
  readonly values: unknown[];
  readonly errors: JsonlLineError[];
}

export function parseJsonl(text: string): ParsedJsonl {
  const values: unknown[] = [];
  const errors: JsonlLineError[] = [];
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop(); // trailing newline
  lines.forEach((raw, i) => {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    if (line.trim() === "") {
      errors.push({ line: i + 1, message: "blank line" });
      return;
    }
    try {
      values.push(JSON.parse(line));
    } catch (error) {
      errors.push({ line: i + 1, message: error instanceof Error ? error.message : String(error) });
    }
  });
  return { values, errors };
}

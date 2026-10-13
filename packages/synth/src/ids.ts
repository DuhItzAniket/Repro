import type { Rng } from "./rng";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const MAX_ULID_TIME = 2 ** 48 - 1;

/**
 * A ULID (26 Crockford base32 characters): 48 bits of milliseconds, then 80 random bits.
 * The random part comes from a seeded stream, so ids are deterministic and, like real ULIDs,
 * sort by creation time.
 */
export function ulid(ms: number, rng: Rng): string {
  if (!Number.isInteger(ms) || ms < 0 || ms > MAX_ULID_TIME) {
    throw new RangeError(`ULID time out of range: ${ms}`);
  }
  let time = "";
  let rest = ms;
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD.charAt(rest % 32) + time;
    rest = Math.floor(rest / 32);
  }
  let random = "";
  for (let i = 0; i < 16; i++) random += CROCKFORD.charAt(rng.next() & 31);
  return time + random;
}

/** RFC 3339 UTC with milliseconds and a `Z` suffix, as the schema's Timestamp requires. */
export function isoTime(ms: number): string {
  return new Date(ms).toISOString();
}

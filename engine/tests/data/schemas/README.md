# Third-party schemas (H04)

`test_exports.py` validates Repro's exports against these files, kept here unmodified so that the
tests run offline and against the exact version named. Biome leaves this directory alone.

| File | What | Source (retrieved 2026-10-17) | SHA-256 | Terms |
|---|---|---|---|---|
| `sarif-schema-2.1.0.json` | SARIF 2.1.0 JSON Schema, OASIS Standard, Errata 01 | https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json | `c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e` | OASIS's notice, copied verbatim from the Errata 01 specification into `NOTICE-OASIS.txt`, as the notice itself requires |
| `JUnit.xsd` | XSD of Apache Ant's JUnit XML output (Windy Road Technology) | https://raw.githubusercontent.com/windyroad/JUnit-Schema/master/JUnit.xsd | `147ff89ef34a82f9a1b2951e7cad251b98c9a7a48a0e0c8e44937141791f57a8` | Apache License 2.0 (its notice is in the file; the licence's text is this repository's `LICENSE`) |

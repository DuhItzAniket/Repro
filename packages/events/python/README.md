# repro-events (Python)

Python tooling for the Repro event schema in [`../schema`](../schema):

- `repro_events.schemas`: loads the schema files into a `referencing` registry, lists the event
  kinds (from `event.schema.json`), and builds validators for events and models.
- `repro_events.agent_schema`: derives draft-07, `$ref`-free variants of schemas for LLM
  structured output (the Claude Agent SDK validates draft-07 only; ADR-0007).

Generated Pydantic models arrive in A05.

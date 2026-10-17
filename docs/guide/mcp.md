# Repro for agents: the MCP server

`repro mcp` serves Repro to a coding agent over the Model Context Protocol, on stdio. The
agent asks for its committed change to be verified, then reads the card and the evidence.
Repro stays the verifier: the agent names commits, and Repro decides what they do.

## Set it up
Add it to your agent host's MCP servers as a stdio command. In a project's `.mcp.json`
(Claude Code's format):

```json
{
  "mcpServers": {
    "repro": { "command": "repro", "args": ["mcp"] }
  }
}
```

It uses the same settings as every `repro` command: the data directory, the sandbox, the
agents. Its runs appear in the cockpit and in the fleet view (`repro serve`, then
`/fleet.html`).

## What the agent can do
| Tool | What it does |
|---|---|
| `start_verification(repo, base, head, claim)` | Starts a run on two commits of a local repository; `claim` is what the change says it does. Returns the run's ID |
| `verification_status(run_id)` | The run's status, its event count, and its card's status once it has one |
| `get_card(run_id, form)` | The card, as Markdown (`repro export --format md`) or JSON |
| `list_evidence(run_id)` / `get_evidence(run_id, evidence_id)` | The run's evidence, as the card cites it |
| `list_runs(limit)` | The most recent runs |

Every tool but `start_verification` only reads, and says so in its annotations.

## What the agent cannot do
- **Hand Repro a result.** Repro reads the two commits from git objects, never from the
  agent's working tree, and runs them in its own sandbox. Uncommitted changes are not seen:
  commit first.
- **Change a card or evidence.** The tools only read the store.

Starting a run runs that repository's code, in Repro's sandbox, exactly as `repro run` would.
Give the server to agents you would let run `repro run` on the same machine.

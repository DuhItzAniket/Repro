# ADR-0019: A GitHub App that runs Repro on the owner's machine

- **Status:** accepted by the owner (2026-10-21), with the App on the owner's machine through a
  relay for now
- **Date:** 2026-10-21
- **Phase:** I04

## Context
Repro reports to GitHub through its Action (I03). A repository adds a workflow, the run happens
on GitHub's runner, and the card comes back as a check run, a comment and a signed attestation.
The roadmap's I04, a GitHub App, adds what the Action cannot do:
- installation on an account or organization without a workflow file in each repository;
- a "Re-run Repro" button on the check run;
- one place for the settings of every repository it runs on.

It was deferred until users asked. The owner asked on 2026-10-21, and chose to run the App on
the owner's own machine, reached through a relay, for now.

What GitHub requires, read on 2026-10-21:
- **Credentials.** An App has an ID, a private key and a webhook secret
  [V docs.github.com, "Building a GitHub App that responds to webhook events"].
  - It authenticates as itself with a JWT signed with RS256. The JWT's `iat` is set "60
    seconds in the past", its `exp` "no more than 10 minutes into the future", and its `iss`
    is the App's client ID ("Use of the client ID is recommended")
    [V "Generating a JSON Web Token (JWT) for a GitHub App"].
  - It acts on a repository with an installation token from
    `POST /app/installations/{id}/access_tokens`. The token "will expire after 1 hour", and
    can be limited to some repositories and permissions. The webhook payload carries the
    installation's ID [V "Generating an installation access token for a GitHub App"].
- **Registration from a manifest.** A form posted to `https://github.com/settings/apps/new`
  (or an organization's) creates the App once the person clicks Create. GitHub then redirects
  to the manifest's `redirect_url` with a `code`. `POST /app-manifests/{code}/conversions`
  exchanges the code for the App's `id`, `pem` and `webhook_secret`, all "within one hour"
  [V "Registering a GitHub App from a manifest"].
  - Probot's local setup redirects to its own local server, and sends webhooks to a relay
    (`WEBHOOK_PROXY_URL`) [S probot/probot, `src/manifest-creation.ts`].
- **Deliveries.**
  - Each is signed in `X-Hub-Signature-256`: an HMAC-SHA256 of the payload with the webhook
    secret, compared in constant time ("Never use a plain `==` operator")
    [V "Validating webhook deliveries"].
  - A receiver should answer "within 10 seconds", and may queue the work.
  - `X-GitHub-Delivery` identifies a delivery and is kept on a redelivery, which guards
    against replays [V "Best practices for using webhooks"].
- **Checks.** Only an App can create check runs.
  - A check run takes at most three requested actions, each with a label of up to 20
    characters, a description of up to 40 and an identifier of up to 20
    [V REST "Check runs"].
  - Clicking one sends `check_run` `requested_action` to that App alone. "Re-run" sends
    `rerequested` to the App asked to re-run it [V "Webhook events and payloads", `check_run`].
- **Permissions** [V "Permissions required for GitHub Apps"]:
  - check runs need Checks (write);
  - comments on a pull request need Issues or Pull requests (write);
  - a pull request is read with Pull requests (read);
  - repository contents need Contents (read);
  - a user's role on a repository comes from `GET /repos/{owner}/{repo}/collaborators/{username}/permission`
    with Metadata (read). It answers `admin`, `write`, `read` or `none`
    [V REST "Collaborators"].
- **A relay for a machine GitHub cannot reach.** GitHub's guide uses smee.io for development,
  and says "You should not use Smee.io to forward your webhooks in production". The GitHub
  CLI's own forwarding "only works with repository and organization webhooks"
  [V "Using the GitHub CLI to forward webhooks for testing"].
  - smee.io's server parses each payload and relays JSON. Its client sends
    `JSON.stringify(data.body)` on to the local server, not GitHub's original bytes
    [V probot/smee.io `lib/server.js`; probot/smee-client `index.ts`, v4.4.3].
  - So a signature can only be checked against that re-serialization. GitHub's guide does
    exactly this, with the signature checked.

Repro already has what a run and its report need: `repro run --pr` (I01) and `report` (I02).
The Docker sandbox passes no host variable to a container (D02, H06), so a token given to
`repro run` never reaches the target's code. The threat model's T20 covers a fork's code
reaching a write token (I03).

## Decision
**1. Commands.** A command group `repro app`:
- **`repro app register [--org <name>]`** registers an App from a manifest:
  - Repro serves a page on a loopback port. The page posts the manifest to GitHub, the person
    clicks Create there, and GitHub redirects back to that port with the code and Repro's
    `state`;
  - Repro exchanges the code and writes the App's ID, client ID, slug, private key and
    webhook secret to Repro's data directory (`github-app/`). The key and secret are files
    readable by the user alone (on POSIX, mode 0600);
  - it prints the App's name and page, never a secret;
  - the manifest asks for the webhook URL (a new smee.io channel unless one is given), the
    events `pull_request` and `check_run`, and these permissions: Checks, Pull requests
    (write), Contents and Metadata (read);
  - the App is private to the account that registers it.
- **`repro app serve (--relay <url> | --listen <host:port>)`** receives deliveries:
  - from the relay, by reading its event stream, or on a port of its own, for a server behind
    the operator's proxy. Both go to the same handler;
  - it refuses to start without Docker: the App runs strangers' code only in containers (L3,
    L4 under gVisor, L5 under Kata).

**2. A delivery.**
1. Its signature is checked against the body before anything else reads it: the bytes
   received, or the relay's JSON in compact form. A delivery that fails is dropped and
   logged.
2. Its `X-GitHub-Delivery` is recorded in a SQLite table under `github-app/`. One already
   seen is dropped.
3. Then by event:
   - **`pull_request`** `opened`, `reopened` or `synchronize`, from the repository itself:
     queued;
   - **the same from a fork**: nothing runs. A check run `Repro` is set to `action_required`
     with a button "Run Repro";
   - **`check_run`** `rerequested`, or `requested_action` `run`, on a check run of this App's:
     queued only if the person who asked has `admin` or `write` on the repository. A fork's
     pull request runs only this way;
   - **anything else** (`ping`, installations): logged.
4. In `--listen` mode the answer is sent at once (`202`), and the work waits in the queue.

**3. A run.** One at a time by default (`app_concurrency`):
- an installation token limited to the one repository and the four permissions above;
- the check run set `in_progress`, so that the pull request shows it at once;
- `repro run --pr <url> --no-serve` with `REPRO_SANDBOX=docker` and the token as
  `GITHUB_TOKEN`, in the process's environment only;
- `report` (I02): the check run completed with the card and its annotations, and the comment.
  The comment is found as the App's own (`<slug>[bot]`). The check run gets the button
  "Re-run Repro".

**4. Settings.** In Repro's settings (`config.toml`, `REPRO_APP_*`):
- `app_repositories`: `owner/repo` patterns that narrow the repositories the installation
  gives. Unset means all of them;
- `app_concurrency`;
- the existing `docker_runtime`, which applies to the App's runs too.

Each repository's `.repro.yml` applies as it does today. The organization's configuration is
GitHub's installation itself: which repositories the App may see.

**5. Not in this ADR.**
- Signing: Sigstore's keyless signing in the Action rests on Actions' identity token, which
  the App does not have. Cards posted by the App are not signed.
- A hosted, shared service (a non-goal, PRODUCT.md).
- An organization-wide `.github` repository configuration.
- A Marketplace listing of the App.

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| Probot (Node.js) | Mature: manifest, JWT, webhooks and the relay built in | A second server runtime beside the Python engine; the run and report are Python | Repro's own receiver is small, and reuses I01 and I02 |
| A serverless receiver (a cloud function and a queue) that the owner's machine polls | Always on; GitHub's 10 s met by the function | A cloud account and its secrets; a queue to run | Later, if the App outgrows the relay |
| A Cloudflare quick tunnel in place of smee.io | Keeps GitHub's bytes, so every signature checks | A downloaded binary; a new URL on every start, so the App's webhook URL changes | smee.io is what GitHub's own guide uses; `--listen` is the path to a real server |
| Only the Action | No host to run | A workflow per repository; no re-run button | The owner asked for the App |

## Consequences
- **Easier:** Repro on many repositories without workflow files; a re-run from the check run;
  runs at L5 on a host with Kata (K10).
- **Harder:**
  - a machine must be on for pull requests to be checked;
  - a private key lives on it. It is limited to the four permissions above, never logged,
    never in an event, and never passed to `repro run`: only a one-repository, one-hour token
    is.
- **New threats** (THREAT_MODEL):
  - **forged or replayed deliveries:** checked by the signature and the delivery ID. The relay's
    channel URL is not a secret: whoever has it can read the payloads and post to it, but cannot
    sign;
  - **the key on the host:** a stolen key is all the App's permissions on every installation,
    until it is revoked on GitHub;
  - **through smee.io:** a third party sees each payload. For private repositories, use
    `--listen` behind the operator's own proxy.
- **T20 changes:**
  - a fork's code never runs without a click from someone with write access;
  - its token stays out of the containers, as in the Action.
- **Watch:** how many relayed deliveries fail their signature through re-serialization. The
  live trial counts them. If any fail, `--listen` (or a tunnel that keeps the bytes) is the
  answer, not a weaker check.
- **Revisit** when a server is available (switch to `--listen`), or when signing from the App
  is asked for.

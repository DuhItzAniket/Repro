# Repro as a GitHub App

Repro's GitHub App reproduces each pull request of the repositories it is installed on, on a
machine of yours, and puts its card on it: a check run named `Repro` with a **Re-run Repro**
button, and one comment that each run updates. Unlike the [Action](github-action.md), it needs
no workflow file in each repository. It runs on your machine, so it can run at L5 there
(Kata, K10). The design is ADR-0019.

The App is yours: you register it under your account or organization, and it runs only while
`repro app serve` does.

## Set it up
On a machine with Docker (Linux, or WSL2 on Windows), with Repro installed:

1. **Register it**:

   ```
   repro app register
   ```

   - It opens a page on this machine. Its button takes you to GitHub, with the App filled in.
   - Click **Create GitHub App** there. GitHub sends the App's private key and webhook secret
     back to Repro, which keeps them in its data directory (`~/.repro/github-app/`) and never
     shows them. You never copy them.
   - The App is private to your account. Add `--org <name>` to register it for an
     organization. Its name must be unused on GitHub; `--name` sets it, and GitHub's page lets
     you change it.
   - Deliveries go to a new [smee.io](https://smee.io) channel, unless you give
     `--webhook-url`.
   - In WSL2, open the page it prints in your Windows browser: WSL2 forwards `127.0.0.1` to
     it.
2. **Install it** on the repositories it should run on, at the link `register` prints
   (`https://github.com/apps/<slug>/installations/new`).
3. **Serve it**:

   ```
   repro app serve
   ```

   It reads the smee.io channel until you stop it with Ctrl+C. Pull requests opened or pushed
   to while it is stopped are not seen: a push, or the check run's **Re-run**, asks again.

## What it does
- **A pull request from the repository itself** (opened, reopened or pushed to) runs:
  1. its check run shows `in_progress` at once;
  2. Repro reproduces it (`repro run --pr`) in Docker;
  3. the check run gets the card, its conclusion (VERIFIED `success`, FLAGGED `failure`,
     UNVERIFIABLE `neutral`) and the **Re-run Repro** button, and the comment is written or
     updated.
- **A fork's pull request does not run by itself.** Its check run asks for action, with a
  **Run Repro** button. It runs when someone with write access to the repository clicks it. A
  click from anyone else is refused. The Action has the same rule for forks: a fork's code
  never runs where a write token is, unless a maintainer opts in.
- **A re-run** (the check's **Re-run** link, or **Re-run Repro**) runs again, under the same
  rule.
- **A run that fails** still completes its check run, `neutral`, with the reason and the
  button.

Only the latest of several pushes waiting for one pull request is run. Runs go one at a time,
unless you set `app_concurrency`.

## Settings
| Setting | Environment | Default | |
|---|---|---|---|
| `app_repositories` | `REPRO_APP_REPOSITORIES` | empty: all repositories the installation gives | `owner/repo` patterns, comma-separated (`acme/*`), that narrow it |
| `app_concurrency` | `REPRO_APP_CONCURRENCY` | 1 | Runs at once |
| `docker_runtime` | `REPRO_DOCKER_RUNTIME` | Docker's default | `kata` runs each container in a microVM (L5), `runsc` under gVisor (L4) |

Each repository's `.repro.yml` applies as it does to any run.

## Without a relay
`repro app serve --listen 127.0.0.1:8781` takes deliveries on a port of this machine. Put it
behind your own HTTPS reverse proxy, and set the App's webhook URL (on its GitHub page) to the
proxy's address. This is the way for a server, and for private repositories: smee.io, a third
party, sees each payload that passes through it.

## Security
- **Each delivery is checked** by its signature (`X-Hub-Signature-256`, with the webhook
  secret). One that does not check is dropped, never run. One already seen (by
  `X-GitHub-Delivery`) is dropped too, so a replay does nothing.
- **Through smee.io**, the payload arrives as JSON and is checked as written again compactly,
  as smee.io's own client does: GitHub's exact bytes are not passed on. A delivery that does
  not come out the same is dropped and logged. `--listen` keeps the bytes.
- **The private key stays on this machine.** Each run gets a token of its own, for one
  repository, for an hour, with four permissions: Checks and Pull requests (write), Contents
  and Metadata (read). It is passed to `repro run` alone, and never reaches the containers:
  Docker passes no host variable into them. `repro app serve` refuses to start without
  Docker.
- **A stolen key** acts as the App on every installation, until you revoke it on the App's
  GitHub page (**Private keys**). `register --replace` registers a new App in its place.
- **Not signed:** cards the App posts carry no attestation. Signing uses GitHub Actions'
  identity, so only the Action signs.

## Troubleshooting
| What you see | Why, and what to do |
|---|---|
| `no GitHub App is registered` | Run `repro app register` first, with the same data directory as `serve` |
| `Docker is needed` | Start Docker; the App runs other people's code in containers only |
| A pull request gets no check run | Is `serve` running, and the App installed on that repository? Is it among `app_repositories`? The log says what each delivery came to |
| `delivery dropped: its signature does not check` | A delivery not from GitHub, or one the relay changed in passing. Use `--listen` if it recurs |
| The page `register` opens is not reachable | Open the URL it prints in a browser on the same machine (WSL2: the Windows browser) |

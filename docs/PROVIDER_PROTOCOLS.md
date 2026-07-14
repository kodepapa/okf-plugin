# Provider protocols

OKFleet integrates with the locally installed `codex` and `claude` executables. It never reads or stores provider credentials.

## Codex

The default transport is the experimental Codex app-server over newline-delimited JSON-RPC on stdio. OKFleet performs an `initialize` handshake, starts or resumes a thread, starts a turn, and normalizes message, tool, file-change, usage, completion, and failure notifications. Threads use `read-only` for bundle/fleet reading and `workspace-write` only inside a staged snapshot. Approval policy is `never`; unexpected server approval requests are denied.

If app-server cannot initialize before emitting a turn event, OKFleet falls back to `codex exec --json`. Set `OKFLEET_CODEX_PROTOCOL=exec` to select that stable path explicitly. Provider-native thread IDs are kept in the local session database so `okfleet sessions resume` can continue them.

## Claude Code

Claude runs non-interactively with `--output-format stream-json` and partial-message events. The repository plugin is supplied with `--plugin-dir`, so the existing `okf-read` and `okf-author` skills remain available.

- Bundle read: plan permission mode with `Read,Glob,Grep`.
- Fleet read: plan permission mode with no filesystem tools; retrieved excerpts are included in the prompt.
- Staged work: edits are limited to `Read,Glob,Grep,Edit,Write` inside the snapshot. Shell access is not exposed.

Claude session IDs are stored for native `--resume` support.

## Normalized events

Both adapters emit the same lifecycle: session started, message delta/completed, tool started/completed, file changed, usage, turn completed/failed, and error. Consumers must tolerate unknown provider records. API keys and similar secrets in stderr are redacted before display.

Live model turns are optional tests because they can consume account quota. `okfleet doctor` checks binaries, versions, authentication where an official status command exists, and the Codex app-server handshake without starting a model turn.

# valkit

Personal utility scripts for day-to-day work, mostly in Python.

## Setup

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python version (see `.python-version`).

```sh
uv sync
```

## Utilities

| Command | Description |
| ------- | ----------- |
| `email-extractor <file.eml or pattern>... [-o out] [--by-topic] [--strict]` | Converts email threads into readable Markdown: one section per message, signatures stripped, secrets and wallet addresses redacted. By default writes `<input>.md` with participants in JSON frontmatter. With `--by-topic`, writes one file per topic (`YYYYMMDD-YYYYMMDD-<topic>.md`) next to the input and merges the folder's `metadata.json`. With `--strict`, keeps first names only, replaces emails, phones, links and dollar amounts, writes no metadata, and names files `….strict.md` so they never mix with normal output. Accepts several files or quoted wildcard patterns (`'~/mail/**/*.eml'`) and skips files that are not emails. Messages already converted into a folder are recorded in its `.email-extractor.json` and skipped next time; new messages are appended to the file that holds their thread or topic. |
| `mac-apps list [--manifest file\|-]`<br>`mac-apps plan --manifest file\|-`<br>`mac-apps apply --manifest file\|-` | Lists the installed Mac applications, largest first, with install channel (`cask`, `mas`, `manual`, `nix`, `system`), bundle size, and manifest key (cask token, App Store ID, or bundle ID). With `--manifest`, adds whether each `cask`, `mas`, and `manual` app is declared. `plan` shows what `apply` would remove, what is declared but not installed, what is installed but not declared, declared apps installed outside their declared directory, and Dock tiles with no app. `apply` removes only the entries that were in the previously applied manifest and are missing from the current one; undeclared apps are never removed, and the first run removes nothing. After the removals, `apply` exits 1 if a declared app is misplaced or a Dock tile has no app; it never moves apps. The applied manifest is kept in `~/.local/state/mac-apps/applied.json`. Removal uses `brew uninstall --zap --cask`, `sudo mas uninstall`, or `mo uninstall` (Trash). macOS only. Reads the app list from [Mole](https://github.com/tw93/Mole) (`mo`) and cask ownership from `brew`; both must be installed. Removing App Store apps also needs [mas](https://github.com/mas-cli/mas). The manifest format is below. |
| `mailkeeper plan --config file`<br>`mailkeeper apply --config file` | Keeps one IMAP mailbox clean of spam. `apply` returns each wanted email of the spam folder to the inbox and marks it: an email of a trusted sender, or one that a local model classes as `personal` or `transactional`. Other classes (`newsletter`, `marketing`, `cold_outreach`, `scam`) stay. A trusted sender is one whose domain the receiving server authenticates (DMARC pass, or a DKIM pass for the From domain when it publishes no DMARC record) and who is the owner, on an own domain, or an address the sent folder shows the owner wrote to; such email never reaches the model. Each email is judged once, and an email a run moved is never moved again, so a move undone by hand stays undone. A run that returned something writes a Markdown report into `report_dir`. `plan` judges the same and prints what `apply` would do, changing nothing and saving nothing. Reads never mark an email read; the only changes are the move and the mark (a Gmail label, or an IMAP keyword elsewhere). Needs a server with `MOVE` and `UIDPLUS`, and a model server with an OpenAI-compatible API that supports `json_schema` replies. State is kept in `~/.local/state/mailkeeper/state.json`. The configuration format is below. |

Run a utility with `uv run <command>`.

### mac-apps manifest

```json
{
  "casks": { "example-browser": { "dir": "~/Applications" } },
  "mas": { "Example Notes": 123456789 },
  "manual": {
    "Example Printer Utility": {
      "bundleId": "com.example.printer-utility",
      "url": "https://example.com/download",
      "dir": "/Applications"
    }
  },
  "dock": ["/System/Applications/Mail.app", "/Users/example/Applications/Example Browser.app"]
}
```

All four keys are required. Casks are keyed by cask token. App Store apps map a name to the App Store ID. Manual apps carry the bundle ID and a download URL, which `plan` shows for apps that are declared but not installed. `dir` is the directory the app must be installed in, and a leading `~` means the home folder. App Store apps have no `dir`, because the App Store always installs into `/Applications`. `dock` lists the absolute paths of the Dock's app tiles.

### mailkeeper configuration

```json
{
  "imap": { "host": "imap.example.com", "user": "alex@example.com", "password_env": "MAILKEEPER_IMAP_PASSWORD" },
  "model": { "base_url": "http://127.0.0.1:8080/v1", "name": "example-model" },
  "owner": { "name": "Alex", "description": "Alex (alex@example.com), a software founder" },
  "own_addresses": ["alex@example.com"],
  "own_domains": ["example.com"],
  "mark": "unspam",
  "report_dir": "~/notes/inbox",
  "authserv_id": "mx.example.com",
  "folders": { "spam": "Junk", "sent": "Sent" }
}
```

Every key except `folders` is required, and an unknown key is an error. The password is read from the environment variable that `password_env` names, never from the file. `owner` fills the detector's instructions: `description` follows "the mailbox owner," and `name` stands where the instructions name the owner. `authserv_id` is the receiving server's name in its own `Authentication-Results` header (`mx.google.com` on Gmail); only the topmost such header counts. `mark` may hold letters, digits, `-` and `_`. `folders` overrides the spam and sent folders that the server marks `\Junk` and `\Sent`.

## Nix

The flake builds every command as one nix package (`nix build`), with dependencies taken from `uv.lock`. It targets `aarch64-darwin` only.

## Development

```sh
uv run ruff check .    # lint
uv run ruff format .   # format
uv run pyright         # type-check
uv run pytest          # test
```

Agent instructions and conventions live in [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE). Third-party notices are in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

# Model-behavior evals

Automated tests for the **model layer** of the Timmy skill — the one layer the
332+ unit tests can't reach. The harness reproduces the Cowork loop headlessly:

- the plugin `SKILL.md` is the system prompt (the real assistant contract);
- the real MCP server supplies tool schemas and executes the model's tool
  calls, through `mcp_views` shaping — the model sees exactly the production
  payloads;
- a live Claude model plays Timmy against scripted operator turns.

Assertions are deterministic wherever possible: which tools were called with
which arguments (ordered subset match), which tools were *never* called, and
the final database state — the engine owns the math, so end states are exact.

## Running

The default driver runs conversations through **Claude Code headless mode**
(`claude -p`), which bills the local Claude subscription seat — no API key,
no Console credits. Claude Code must be installed and logged in (it is, if
you're reading this on the dev machine).

```bash
python3 evals/run.py                       # all scenarios, 3 runs each, Sonnet 5
python3 evals/run.py --list                # free, no model calls
python3 evals/run.py --scenario custom_rounding_increment --runs 1
python3 evals/run.py --model claude-haiku-4-5   # track Haiku's known failure modes
python3 evals/run.py --dump-dir /tmp/eval-transcripts   # save failing transcripts
```

Claude-code driver mechanics: the SKILL.md replaces Claude Code's system
prompt (`--system-prompt`), built-in tools are disabled (`--tools ""`), and
the real timeassist MCP server is loaded via `--mcp-config` +
`--strict-mcp-config`. Do **not** add `--settings` or `--safe-mode` to the
command — both silently prevent the `--mcp-config` server from connecting.
`claude -p` also sometimes starts the turn before the MCP server connects;
the driver detects that (pending server + zero calls) and retries the
conversation instead of scoring it against the model.

### The raw-API driver

`--driver api` posts straight to the Messages API — closer to the wire, a
bit faster, but metered against Console credits. Credentials, either flavor:

```bash
export ANTHROPIC_API_KEY=...               # static key
# or OAuth (no static key; one-time interactive login):
ant auth login
set -a; eval "$(ant auth print-credentials --env)"; set +a
python3 evals/run.py --driver api
```

The OAuth access token is short-lived: re-run the `print-credentials` line
before each session. Don't set both env vars — the API rejects requests
carrying both credentials, and the harness fails fast if it sees that.

Model output is stochastic, so each scenario runs N times (default 3) and is
scored as a pass rate against `--threshold` (default 67%). The default model
is `claude-sonnet-5` — the recommended pilot model tier.

## When to run

- Before any release that touches `SKILL.md`, MCP tool descriptions, or
  result shapes (`mcp_views.py`). The gate test checks that key phrases
  *exist*; these evals check that they *work*.
- Deliberately **not** part of `python3 -m unittest discover -s tests` or the
  tag build: needs an API key, costs tokens (~a few cents per full run), and
  is not fully deterministic. The harness itself (loop, matcher, executor,
  scenario seeds) *is* covered offline by `tests/test_evals.py`.

## Anatomy

| File | What it holds |
|---|---|
| `harness.py` | Messages-API loop (stdlib `urllib`), MCP executor bridge, SKILL.md loader |
| `scenarios.py` | Scenario definitions: seed → operator turns → expects/forbids/end-state |
| `run.py` | CLI runner: repetitions, pass-rate scoring, transcript dumps |

Adding a scenario = one `Scenario(...)` entry in `scenarios.py`: a `seed`
function (real engine calls with `{day}`-based timestamps), operator turns,
`Expect`/`Forbid` tool patterns, and an optional `check_state` that queries
the SQLite end state. `tests/test_evals.py` automatically smoke-tests every
seed against the real engine.

Note on dependencies: the harness is stdlib-only like the rest of the repo,
so there is nothing to install — but unlike the engine, `evals/` is never
packaged into the exe or plugin, so that constraint is convention here, not
load-bearing.

#!/usr/bin/env python3
"""Run the model-behavior evals against a live Claude model.

Usage:
    ANTHROPIC_API_KEY=... python3 evals/run.py                 # all scenarios, 3 runs each
    python3 evals/run.py --list                                # show scenarios, no API needed
    ANTHROPIC_API_KEY=... python3 evals/run.py --scenario custom_rounding_increment --runs 1
    ANTHROPIC_API_KEY=... python3 evals/run.py --model claude-haiku-4-5

Costs real API tokens and is stochastic — deliberately NOT part of
`python3 -m unittest discover -s tests` or the tag build. Run it before
releases that touch SKILL.md, tool descriptions, or MCP result shapes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import claude_code_driver as ccd  # noqa: E402
from evals import scenarios as scenario_defs  # noqa: E402
from evals.harness import (  # noqa: E402
    DEFAULT_MODEL, HarnessError, McpToolExecutor,
    http_transport, load_skill_system_prompt, run_conversation,
)


def _api_conversation(transport, model, max_steps, max_tokens):
    def play(system, turns, db, workdir):
        executor = McpToolExecutor(db)
        return run_conversation(
            system=system, tools=executor.list_tools(), turns=turns,
            executor=executor, transport=transport, model=model,
            max_steps=max_steps, max_tokens=max_tokens,
        )
    return play


def _claude_code_conversation(model):
    def play(system, turns, db, workdir):
        return ccd.run_conversation_via_claude_code(
            system=system, turns=turns, db_path=db, model=model, workdir=workdir,
        )
    return play


def run_once(scenario, *, day, system, play, dump_dir=None, run_index=0):
    """Returns a list of failure reasons ([] = pass)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "timeassist.sqlite"
        scenario.seed(db, day)
        turns = [turn.format(day=day) for turn in scenario.turns]
        try:
            calls, transcript = play(system, turns, db, Path(tmp))
        except HarnessError as exc:
            return [f"harness: {exc}"]
        errors = scenario_defs.match_expectations(calls, scenario.expects)
        errors += scenario_defs.match_forbidden(calls, scenario.forbids)
        if scenario.check_state:
            errors += scenario.check_state(db, day)
        if errors and dump_dir:
            dump_dir.mkdir(parents=True, exist_ok=True)
            out = dump_dir / f"{scenario.name}-run{run_index + 1}.json"
            out.write_text(json.dumps({
                "scenario": scenario.name,
                "errors": errors,
                "tool_calls": [
                    {"name": c.name, "arguments": c.arguments, "is_error": c.is_error}
                    for c in calls
                ],
                "transcript": transcript,
            }, indent=2, default=str))
        return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--driver", choices=("claude-code", "api"), default="claude-code",
        help="claude-code: headless `claude -p`, billed to your Claude subscription "
             "(default). api: raw Messages API, needs Console credits.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model ID (default {DEFAULT_MODEL})")
    parser.add_argument("--runs", type=int, default=3, help="repetitions per scenario (default 3)")
    parser.add_argument("--scenario", action="append", help="run only this scenario (repeatable)")
    parser.add_argument(
        "--threshold", type=float, default=0.66,
        help="required pass rate per scenario (default 0.66, i.e. 2 of 3 runs)",
    )
    parser.add_argument("--max-steps", type=int, default=14, help="API-call cap per conversation")
    parser.add_argument("--max-tokens", type=int, default=1500, help="max_tokens per response")
    parser.add_argument("--dump-dir", type=Path, help="write failing transcripts as JSON here")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = parser.parse_args()

    selected = scenario_defs.SCENARIOS
    if args.scenario:
        known = {s.name for s in selected}
        unknown = set(args.scenario) - known
        if unknown:
            parser.error(f"unknown scenario(s): {sorted(unknown)}; known: {sorted(known)}")
        selected = [s for s in selected if s.name in args.scenario]

    if args.list:
        for s in selected:
            print(f"{s.name:36} {s.description}")
        return 0

    if args.driver == "api":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not api_key and not auth_token:
            print(
                "No credentials — set ANTHROPIC_API_KEY, or for OAuth run\n"
                '  ant auth login   # once, interactive\n'
                '  set -a; eval "$(ant auth print-credentials --env)"; set +a',
                file=sys.stderr,
            )
            return 2
        transport = http_transport(api_key=api_key, auth_token=auth_token)
        play = _api_conversation(transport, args.model, args.max_steps, args.max_tokens)
    else:
        play = _claude_code_conversation(args.model)

    day = date.today().isoformat()
    system = load_skill_system_prompt()

    print(f"driver={args.driver}  model={args.model}  runs={args.runs}/scenario  "
          f"threshold={args.threshold:.0%}  day={day}\n")
    results = {}
    for scenario in selected:
        passes = 0
        for i in range(args.runs):
            errors = run_once(
                scenario, day=day, system=system, play=play,
                dump_dir=args.dump_dir, run_index=i,
            )
            if errors and all("MCP server never connected" in e for e in errors):
                # Pure infrastructure failure — the model never saw tools, so
                # this is not a behavioral datapoint. One fresh run replaces it.
                print(f"  … {scenario.name} (run {i + 1}/{args.runs}): "
                      f"MCP startup race, redoing the run", flush=True)
                errors = run_once(
                    scenario, day=day, system=system, play=play,
                    dump_dir=args.dump_dir, run_index=i,
                )
            if errors:
                print(f"  FAIL {scenario.name} (run {i + 1}/{args.runs})", flush=True)
                for error in errors:
                    print(f"       - {error}", flush=True)
            else:
                passes += 1
                print(f"  pass {scenario.name} (run {i + 1}/{args.runs})", flush=True)
        results[scenario.name] = passes / args.runs

    print("\n=== summary ===")
    worst_failures = []
    for name, rate in results.items():
        verdict = "OK  " if rate >= args.threshold else "FAIL"
        print(f"  {verdict} {name:36} {rate:.0%}")
        if rate < args.threshold:
            worst_failures.append(name)

    if worst_failures:
        print(f"\n{len(worst_failures)} scenario(s) below the {args.threshold:.0%} pass threshold.")
        return 1
    print("\nAll scenarios at or above threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

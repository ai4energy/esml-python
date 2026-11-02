#!/usr/bin/env python3
"""A faithful fake of the `esml` engine for client tests (no engine needed).

It implements two surfaces:

* the resident `esml session` protocol (`esml.session/v1`), and
* the one-shot command line (`check` / `check-units` / `tasks` / `inspect` /
  `dump` / `echo-argv`).

The JSON shapes mirror the real engine: `esml check --json` emits an array of
report objects (`file` / `well_formed` / `summary` / `findings`), and
`esml tasks --json` emits an `esml.tasks/v1` envelope.

Set ``FAKE_ESML_MODE`` to exercise failure modes:

* ``bad-version`` — the open envelope claims an unknown apiVersion
* ``crash``       — exits right after the open envelope
* ``silent``      — reads nothing and never answers (timeout test)
* ``garbage``     — answers each request with a non-JSON line
* ``error``       — the one-shot CLI fails loudly (stderr + exit 1)
* ``bad-json``    — the one-shot CLI exits 0 but prints no JSON
* ``timeout``     — the one-shot CLI never answers (alias of ``silent``)
* ``task-error``  — `esml tasks --json` answers `ok=false` with an error
* ``bad-api``     — `esml tasks --json` answers the wrong apiVersion
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time

API = "esml.session/v1"
TASKS_API = "esml.tasks/v1"
DOC_HASH = 42
MODE = os.environ.get("FAKE_ESML_MODE", "ok")

#: One-shot subcommands the fake answers.
CLI_COMMANDS = ("check", "check-units", "tasks", "inspect", "dump", "echo-argv")

#: Flags that consume the following token.
_VALUE_FLAGS = (
    "-L",
    "--libroot",
    "--system",
    "--source",
    "--jobs",
    "--tspan",
    "--steps",
    "--observe",
)


def envelope(**fields):
    out = {"apiVersion": API}
    out.update(fields)
    return out


def error(op, message):
    return envelope(op="error", request=op, error=message)


# ── the one-shot command line ────────────────────────────────────────────


def read_doc(path):
    """The document text, or ``None`` when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def positional(argv):
    """The first non-flag token of ``argv`` (flag values are skipped)."""
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in _VALUE_FLAGS:
            skip = True
            continue
        if tok.startswith("-"):
            continue
        return tok
    return None


def attributes(tag_text):
    """The attributes of one XML start tag as a dict."""
    out = {}
    for key, value in re.findall(r'([A-Za-z_:][\w.:-]*)\s*=\s*"([^"]*)"', tag_text):
        out[key] = value
    return out


def check_report(text, path):
    """The `esml check --json` report of one document."""
    well_formed = "</esml>" in text
    findings = []
    errors = 0
    if not well_formed:
        errors = 1
        findings.append(
            {
                "severity": "error",
                "code": "XML",
                "location": "document",
                "message": "XML well-formedness failed",
                "advice": "close every element that is opened",
                "count": 1,
            }
        )
    return {
        "file": path,
        "well_formed": well_formed,
        "summary": {
            "errors": errors,
            "warnings": 0,
            "models": len(re.findall(r"<modelType\b", text)),
            "systems": len(re.findall(r"<system\b", text)),
            "types": len(re.findall(r"<type\b", text)),
            "port_types": 0,
            "units": len(re.findall(r"<units\b", text)),
            "functions": 0,
            "use_libraries": [],
            "five_level_ok": well_formed,
            "connect_rules_total": 0,
        },
        "findings": findings,
    }


def check_units_report(text, path):
    """The `esml check-units --json` report of one document."""
    well_formed = "</esml>" in text
    findings = []
    errors = 0
    if not well_formed:
        errors = 1
        findings.append(
            {
                "severity": "error",
                "code": "XML",
                "location": "document",
                "message": "XML well-formedness failed",
                "advice": "close every element that is opened",
            }
        )
    return {
        "file": path,
        "well_formed": well_formed,
        "summary": {
            "errors": errors,
            "warnings": 0,
            "unit_block_rows": len(re.findall(r"<units\b", text)),
            "type_unit_decls": len(re.findall(r"<type\b", text)),
            "invalid_type_units": 0,
            "unknown_anchors": 0,
            "dimension_mismatches": 0,
        },
        "findings": findings,
    }


def render_report(report):
    """The human-readable form of one report (the `--json`-less output)."""
    lines = ["=== {}".format(report["file"])]
    if not report["well_formed"]:
        lines.append("    (XML well-formedness failed; engine-level checks skipped)")
    if not report["findings"]:
        lines.append("    ok")
    for finding in report["findings"]:
        lines.append(
            "    {} {}: {} ({})".format(
                finding["severity"],
                finding["code"],
                finding["message"],
                finding["location"],
            )
        )
    return "\n".join(lines) + "\n"


def tasks_envelope(text, path):
    """The `esml tasks --json` envelope of one document."""
    target = None
    for tag in re.findall(r"<computeTasks\b[^>]*>", text):
        target = attributes(tag).get("target", target)
    rows = []
    for tag in re.findall(r"<task\b[^>]*>", text):
        attrs = attributes(tag)
        name = attrs.get("name")
        if not name:
            continue
        kind = attrs.get("kind", "simulate")
        rows.append(
            {
                "name": name,
                "kind": kind,
                "target": target,
                "units": {},
                "meta": {"engineVersion": "9.9.9-fake", "docHash": DOC_HASH},
                "outcome": {"kind": kind, "status": "ok"},
            }
        )
    if not rows:
        return {
            "apiVersion": TASKS_API,
            "ok": False,
            "error": {
                "code": "tasks.empty",
                "message": "no matching task in {}".format(path),
            },
        }
    return {"apiVersion": TASKS_API, "ok": True, "system": target, "tasks": rows}


def inspect_text(text):
    """The `esml inspect` report (human text)."""
    systems = re.findall(r"<system\b[^>]*>", text)
    name = attributes(systems[0]).get("name", "?") if systems else "?"
    variables = len(re.findall(r"<variable\b", text))
    params = len(re.findall(r"<parameter\b", text))
    equations = len(re.findall(r"<equation\b", text))
    return (
        "document : {name} ({models} models)\n"
        "system   : {system} → {unknowns} unknowns, {equations} equations, "
        "{params} params\n"
    ).format(
        name=attributes(re.findall(r"<esml\b[^>]*>", text)[0]).get("name", "?"),
        models=len(re.findall(r"<modelType\b", text)),
        system=name,
        unknowns=variables,
        equations=equations,
        params=params,
    )


def dump_text(text):
    """The `esml dump` listing (human text)."""
    systems = re.findall(r"<system\b[^>]*>", text)
    name = attributes(systems[0]).get("name", "?") if systems else "?"
    lines = ["system : {}".format(name)]
    for tag in re.findall(r"<variable\b[^>]*>", text):
        attrs = attributes(tag)
        lines.append(
            "  {name} = {initial}".format(
                name=attrs.get("name", "?"), initial=attrs.get("initial", "0")
            )
        )
    return "\n".join(lines) + "\n"


def cli_main(cmd, argv):
    """The one-shot command line of the fake engine."""
    if MODE in ("silent", "timeout"):
        time.sleep(3600)
        return 0
    if MODE == "error":
        print("error: fake engine failure (mode=error)", file=sys.stderr)
        return 1
    if MODE == "bad-json":
        print("this is not a json document")
        return 0

    if cmd == "echo-argv":
        # A probe subcommand: it reports exactly what the client passed.
        print(json.dumps({"cmd": cmd, "args": argv, "stdin": sys.stdin.read()}))
        return 0

    path = positional(argv)
    if path is None:
        print("error: `{}` requires <file|dir>".format(cmd), file=sys.stderr)
        return 2
    text = read_doc(path)
    if text is None:
        print(
            "error: read {}: No such file or directory (os error 2)".format(path),
            file=sys.stderr,
        )
        return 1

    if cmd == "check":
        report = check_report(text, path)
        code = 1 if report["summary"]["errors"] else 0
    elif cmd == "check-units":
        report = check_units_report(text, path)
        # The engine propagates the exit code only on its *human* path; in
        # the `--json` path `check-units` always exits 0, even with errors.
        # The fake mirrors that quirk so the client cannot lean on the exit
        # code alone.
        code = 0 if "--json" in argv else (1 if report["summary"]["errors"] else 0)
    elif cmd == "tasks":
        if MODE == "task-error":
            print(
                json.dumps(
                    {
                        "apiVersion": TASKS_API,
                        "ok": False,
                        "error": {
                            "code": "task.failed",
                            "message": "task `sim1` failed",
                        },
                    }
                )
            )
            return 0
        if MODE == "bad-api":
            print(json.dumps({"apiVersion": "esml.tasks/v0", "ok": True, "tasks": []}))
            return 0
        envelope_out = tasks_envelope(text, path)
        if "--json" in argv:
            print(json.dumps(envelope_out, indent=2, sort_keys=True))
        else:
            for row in envelope_out.get("tasks", []):
                print(
                    "task {name} ({kind}) [{target}]: {kind}".format(
                        name=row["name"], kind=row["kind"], target=row["target"]
                    )
                )
        return 0
    elif cmd == "inspect":
        print(inspect_text(text), end="")
        return 0
    elif cmd == "dump":
        print(dump_text(text), end="")
        return 0
    else:  # pragma: no cover — the caller filters the command set
        print("fake esml: unknown subcommand `{}`".format(cmd), file=sys.stderr)
        return 2

    if "--json" in argv:
        print(json.dumps([report], indent=2, sort_keys=True))
    else:
        print(render_report(report), end="")
    return code


# ── the resident session protocol ─────────────────────────────────────────


class Fake:
    def __init__(self):
        self.params = {"m.lam": 0.5}
        self.variables = ["m.x", "m.y"]
        self.states = ["m.x"]
        self.state = {}
        self.sim_end = None  # [t, x]
        self.cold_solves = 0
        self.warm_solves = 0
        self.sim_calls = 0
        self.last_steps = 0

    def x0(self):
        if "m.x" in self.state:
            return self.state["m.x"]
        if self.sim_end is not None:
            return self.sim_end[1]
        return 1.0

    def values_at(self, t_rel):
        lam = self.params["m.lam"]
        x = self.x0() * math.exp(-lam * t_rel)
        return {"m.x": x, "m.y": lam * x}

    def solve(self):
        lam = self.params["m.lam"]
        x = self.x0() / (1.0 + lam)
        warm = self.cold_solves > 0
        if warm:
            self.warm_solves += 1
        else:
            self.cold_solves += 1
        return envelope(
            op="solve",
            iterations=3 if warm else 5,
            warm=warm,
            unknowns=len(self.variables),
            values=[
                {"path": "m.x", "value": x},
                {"path": "m.y", "value": lam * x},
            ],
            durationMs=1,
            docHash=DOC_HASH,
        )


def trajectory(sess, op, t0, t1, steps, observe):
    if steps < 1:
        return error(op, "steps must be >= 1")
    projected = observe if observe is not None else sess.variables
    if len(set(projected)) != len(projected):
        return error(op, "observe paths must be unique")
    t = [t0 + (t1 - t0) * i / steps for i in range(steps + 1)]
    rows = [sess.values_at(tt - t0) for tt in t]
    series = []
    for path in projected:
        if path not in sess.variables:
            return error(op, f"unknown observe path `{path}` (parameters are not observable)")
        series.append({"path": path, "values": [row[path] for row in rows]})
    continued = sess.sim_end is not None or bool(sess.state)
    if op == "simulate":
        sess.sim_end = [t1, rows[-1]["m.x"]]
        sess.state.clear()
        sess.sim_calls += 1
        sess.last_steps = steps
    return envelope(
        op=op,
        steps=steps,
        points=len(t),
        continued=continued,
        t=t,
        series=series,
        durationMs=1,
        docHash=DOC_HASH,
    )


def pairs_of(req, op):
    arr = req.get("values")
    if not isinstance(arr, list):
        return None, error(op, 'missing "values" array')
    rows = []
    for item in arr:
        path = item.get("path") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(path, str) or not isinstance(value, (int, float)):
            return None, error(op, 'each "values" item needs "path" (string) and "value" (number)')
        rows.append((path, float(value)))
    return rows, None


def observe_of(req):
    if "observe" not in req:
        return None, None
    arr = req["observe"]
    if not isinstance(arr, list) or not arr:
        return None, "observing needs a non-empty array"
    if any(not isinstance(p, str) for p in arr):
        return None, "each observe path must be a string"
    return arr, None


def handle(sess, req):
    op = req.get("op")
    if not isinstance(op, str):
        return error(None, 'missing "op" (string)')
    if op == "set_param":
        path, value = req.get("path"), req.get("value")
        if not isinstance(path, str) or not isinstance(value, (int, float)):
            return error(op, 'set_param requires "path" (string) and "value" (number)')
        if path not in sess.params:
            return error(op, f"`{path}` is not a declared parameter")
        sess.params[path] = float(value)
        return envelope(op=op, ok=True, path=path, value=float(value))
    if op == "set_state":
        path, value = req.get("path"), req.get("value")
        if not isinstance(path, str) or not isinstance(value, (int, float)):
            return error(op, 'set_state requires "path" (string) and "value" (number)')
        if path not in sess.states:
            return error(op, f"`{path}` is not a dynamic state")
        sess.state[path] = float(value)
        return envelope(op=op, ok=True, path=path, value=float(value))
    if op in ("set_params", "set_states"):
        rows, err = pairs_of(req, op)
        if err is not None:
            return err
        if op == "set_params":
            for path, _ in rows:
                if path not in sess.params:
                    return error(op, f"`{path}` is not a declared parameter")
            for path, value in rows:
                sess.params[path] = value
        else:
            for path, _ in rows:
                if path not in sess.states:
                    return error(op, f"`{path}` is not a dynamic state")
            for path, value in rows:
                sess.state[path] = value
        return envelope(op=op, ok=True, count=len(rows))
    if op == "clear_state":
        sess.state.clear()
        sess.sim_end = None
        return envelope(op=op, ok=True, pendingStates=0)
    if op == "solve":
        return sess.solve()
    if op in ("simulate", "predict"):
        steps = req.get("steps", 100)
        if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
            return error(op, '"steps" must be an integer >= 1')
        observe, err = observe_of(req)
        if err is not None:
            return error(op, err)
        if op == "predict":
            horizon = req.get("horizon")
            if not isinstance(horizon, (int, float)) or horizon <= 0:
                return error(op, 'predict requires "horizon" (number, > 0)')
            return trajectory(sess, op, 0.0, float(horizon), steps, observe)
        span = req.get("tspan")
        if not isinstance(span, list) or len(span) != 2 or any(
            not isinstance(v, (int, float)) for v in span
        ):
            return error(op, 'simulate requires "tspan": [t0, t1] (two numbers)')
        return trajectory(sess, op, float(span[0]), float(span[1]), steps, observe)
    if op == "snapshot":
        return envelope(
            op=op,
            docHash=DOC_HASH,
            snapshot={
                "docHash": DOC_HASH,
                "params": [[k, v] for k, v in sorted(sess.params.items())],
                "simEnd": sess.sim_end,
                "state": [[0, v] for _, v in sorted(sess.state.items())],
                "coldSolves": sess.cold_solves,
                "warmSolves": sess.warm_solves,
                "simCalls": sess.sim_calls,
                "lastSteps": sess.last_steps,
            },
        )
    if op == "restore":
        snap = req.get("snapshot")
        if not isinstance(snap, dict):
            return error(op, "restore requires \"snapshot\" (object)")
        if snap.get("docHash") != DOC_HASH:
            return error(op, "snapshot was taken from a different document")
        params = {}
        for row in snap.get("params", []):
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not isinstance(row[0], str)
                or not isinstance(row[1], (int, float))
            ):
                return error(op, "bad snapshot params")
            if row[0] not in sess.params:
                return error(op, f"snapshot parameter `{row[0]}` is not declared")
            params[row[0]] = float(row[1])
        sess.params.update(params)
        sim_end = snap.get("simEnd")
        if sim_end is not None:
            if (
                not isinstance(sim_end, list)
                or len(sim_end) != 2
                or any(not isinstance(v, (int, float)) for v in sim_end)
            ):
                return error(op, "bad snapshot simEnd")
            sess.sim_end = [float(sim_end[0]), float(sim_end[1])]
        else:
            sess.sim_end = None
        state = {}
        for row in snap.get("state", []):
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not isinstance(row[0], int)
                or not isinstance(row[1], (int, float))
            ):
                return error(op, "bad snapshot state")
            if not 0 <= row[0] < len(sess.states):
                return error(op, "snapshot state index out of range")
            state[sess.states[row[0]]] = float(row[1])
        sess.state = state
        sess.cold_solves = int(snap.get("coldSolves", 0))
        sess.warm_solves = int(snap.get("warmSolves", 0))
        sess.sim_calls = int(snap.get("simCalls", 0))
        sess.last_steps = int(snap.get("lastSteps", 0))
        return envelope(op=op, ok=True, docHash=DOC_HASH)
    if op == "info":
        return envelope(
            op=op,
            docHash=DOC_HASH,
            unknowns=len(sess.variables),
            coldSolves=sess.cold_solves,
            warmSolves=sess.warm_solves,
            lastIters=5,
            closed=False,
            dynamic=True,
            pendingStates=len(sess.state),
            simCalls=sess.sim_calls,
            lastSteps=sess.last_steps,
        )
    if op in ("close", "quit"):
        return envelope(
            op="close",
            ok=True,
            coldSolves=sess.cold_solves,
            warmSolves=sess.warm_solves,
            simCalls=sess.sim_calls,
        )
    return error(
        op,
        f"unknown op `{op}` (expected set_param / set_state / set_params / "
        "set_states / clear_state / solve / simulate / predict / snapshot / "
        "restore / info / close)",
    )


def session_main(argv):
    """The resident `esml session <file>` protocol."""
    sess = Fake()
    version = "esml.session/v0" if MODE == "bad-version" else API
    print(
        json.dumps(
            {
                "apiVersion": version,
                "op": "open",
                "system": "Fake",
                "unknowns": len(sess.variables),
                "docHash": DOC_HASH,
                "dynamic": True,
            }
        ),
        flush=True,
    )
    if MODE == "crash":
        return 3
    if MODE == "silent":
        while True:
            time.sleep(30)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if MODE == "garbage":
            print("this is not a json envelope", flush=True)
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps(error(None, f"bad JSON: {exc}")), flush=True)
            continue
        if not isinstance(req, dict):
            print(json.dumps(error(None, "request must be an object")), flush=True)
            continue
        out = handle(sess, req)
        print(json.dumps(out), flush=True)
        if out.get("op") == "close":
            return 0
    return 0


def main(argv):
    if "--version" in argv:
        print("ESML v9.9.9-fake · fake engine for client tests")
        return 0
    if not argv:
        print("fake esml: expected a subcommand", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "session":
        return session_main(rest)
    if cmd in CLI_COMMANDS:
        return cli_main(cmd, rest)
    print(f"fake esml: unknown subcommand `{cmd}`", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

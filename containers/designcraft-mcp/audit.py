"""Compare the installed designcraft-cli with the reviewed snapshot (bin/designcraft-audit).

The gateway policy (src/mcp_oauth_gateway/policy_designcraft.py and the DESIGNCRAFT defaults
in config.py) was reviewed against one DesignCraft version. This script lists what changed
since: tools, commands, the parameters that carry paths, and the commands that mention
printing, the clipboard, URLs, scripts or programs. Stdlib only; run it with ``python3 -I``.

    audit.py CLI SNAPSHOT POLICY_SOURCE [--update]
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile

PATH_PARAM = re.compile(
    r"\b(path|paths|dir|directory|file|folder|[a-z]+(?:Path|Dir|Image|File|Folder))\??\s*:"
)
RISK = re.compile(
    r"(?i)\b(print|printer|spooler|clipboard|https?|url|network|download|upload|lp|lpr|"
    r"launch|browser|shell|script|command line|process|program|external|socket)\b"
)


def run_mcp(cli: str) -> list[str]:
    """Tool names, from the real MCP server (headless, confined to an empty folder)."""
    with tempfile.TemporaryDirectory() as empty:
        args = [cli, "mcp", "--automation-read-root", empty, "--automation-write-root", empty]
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": empty},
            cwd=empty,
        )
        init = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "a"}}
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": init},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        out, _ = proc.communicate("".join(json.dumps(m) + "\n" for m in messages), timeout=60)
    for line in out.splitlines():
        reply = json.loads(line)
        if reply.get("id") == 2:
            return sorted(tool["name"] for tool in reply["result"]["tools"])
    raise SystemExit("designcraft-cli mcp did not answer tools/list")


def current(cli: str) -> dict:
    version = subprocess.run([cli, "--version"], capture_output=True, text=True, check=True)
    commands = json.loads(
        subprocess.run([cli, "commands"], capture_output=True, text=True, check=True).stdout
    )
    found = {}
    for command in commands:
        text = f"{command.get('label', '')} {command.get('params') or ''}"
        found[command["id"]] = {
            "paths": sorted(set(PATH_PARAM.findall(command.get("params") or ""))),
            "risk": sorted({m.lower() for m in RISK.findall(text)}),
        }
    return {"version": version.stdout.split()[-1], "tools": run_mcp(cli), "commands": found}


def path_keys(policy_source: str) -> set[str]:
    tree = ast.parse(open(policy_source, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PATH_KEYS":
            return set(ast.literal_eval(node.value.args[0]))
    raise SystemExit(f"PATH_KEYS not found in {policy_source}")


def main() -> int:
    cli, snapshot_path, policy_source, *flags = sys.argv[1:]
    now = current(cli)
    if "--update" in flags:
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            json.dump(now, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"snapshot updated for designcraft {now['version']}: {snapshot_path}")
        return 0
    with open(snapshot_path, encoding="utf-8") as fh:
        reviewed = json.load(fh)

    problems: list[str] = []
    print(f"designcraft-cli {now['version']} (reviewed: {reviewed['version']})")
    for tool in sorted(set(now["tools"]) - set(reviewed["tools"])):
        problems.append(f"new tool {tool}: hidden by the gateway until added to the allow-list")
    for tool in sorted(set(reviewed["tools"]) - set(now["tools"])):
        problems.append(f"tool {tool} is gone")
    old, new = reviewed["commands"], now["commands"]
    for cid in sorted(set(new) - set(old)):
        spec = new[cid]
        problems.append(f"new command {cid} paths={spec['paths']} mentions={spec['risk']}")
    for cid in sorted(set(old) - set(new)):
        problems.append(f"command {cid} is gone")
    for cid in sorted(set(new) & set(old)):
        if new[cid] != old[cid]:
            problems.append(f"command {cid} changed: {old[cid]} -> {new[cid]}")
    known = path_keys(policy_source)
    seen = {key for spec in new.values() for key in spec["paths"]}
    for key in sorted(seen - known - {"file", "folder", "directory", "paths"}):
        problems.append(f"parameter '{key}' looks like a path but is not in PATH_KEYS")

    for line in problems:
        print(f"  - {line}")
    if problems:
        print(
            "\nReview each line (docs/designcraft.md, 'Upgrading DesignCraft'), adjust the policy,"
            "\nthen record the review: bin/designcraft-audit --update"
        )
        return 1
    print("no change since the reviewed snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())

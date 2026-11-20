"""Tool policy for the DesignCraft resource (``/designcraft/mcp``).

DesignCraft's MCP server (``designcraft-cli mcp``, headless) has a few tools, and two of
them, ``execute`` and ``batch``, run any of its ~550 commands by id. The engine itself
confines every file it reads or writes to ``EDITORIAL_ROOT`` (``--automation-read-root`` /
``--automation-write-root``). This policy adds what those roots don't cover, and fails
closed on anything that hasn't been reviewed:

- tools: an allow-list. A tool that a new release adds stays hidden until reviewed.
- commands: ids must look like ``namespace.name``, match an allow pattern and no deny
  pattern (printing, the system clipboard, opaque scripts).
- shapes: ``execute`` is exactly ``{command, params?}`` and ``batch`` exactly
  ``{commands}``. Batch ``script`` text is refused, since the gateway can't see the
  commands inside it.
- paths: ``path``, ``dir`` and ``coverImage`` (at any depth) go through the gateway's path
  jail and must be literal. A batch reference such as ``$0.path`` is resolved by the
  upstream after the check, so it is refused in those arguments.
- JSON-RPC: no batches (arrays), only the reviewed methods, and ``resources/read`` only for
  ``designcraft://`` URIs.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .config import Settings
from .policy import Policy, PolicyError

COMMAND_ID = re.compile(r"^[a-z][A-Za-z0-9]*(\.[A-Za-z0-9]+)+$")
# Every parameter of 0.20.1 that carries a path (bin/designcraft-audit lists them). Exact and
# case-sensitive: `fileName` (an export name template) is not a path.
PATH_KEYS = frozenset({"path", "dir", "coverImage"})
METHODS = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "logging/setLevel",
    }
)
RESOURCE_SCHEME = "designcraft://"


@dataclass(frozen=True)
class DesignCraftPolicy(Policy):
    tools: frozenset[str] = frozenset()
    allow_commands: tuple[str, ...] = ()
    deny_commands: tuple[str, ...] = ()
    images_dir: str = ""

    strict = True

    @classmethod
    def from_settings(cls, settings: Settings) -> DesignCraftPolicy:
        root = settings.policy_root
        return cls(
            root=root,
            scopes=settings.scopes,
            tools=frozenset(settings.designcraft_allow_tools),
            allow_commands=tuple(settings.designcraft_allow_commands),
            deny_commands=tuple(settings.designcraft_deny_commands),
            images_dir=posixpath.join(root, settings.assets_subdir) if root else "",
        )

    # ----------------------------------------------------------------- tools
    def tool_allowed(self, name: str) -> bool:
        return name in self.tools

    def check_command(self, command: Any) -> str:
        if not isinstance(command, str) or not COMMAND_ID.match(command):
            raise PolicyError("'command' must be a DesignCraft command id such as frame.create")
        if any(fnmatchcase(command, pattern) for pattern in self.deny_commands):
            raise PolicyError(f"command '{command}' is disabled by the gateway policy")
        if not any(fnmatchcase(command, pattern) for pattern in self.allow_commands):
            raise PolicyError(f"command '{command}' is not in the gateway's reviewed command list")
        return command

    def _steps(self, name: str, arguments: dict) -> list[dict]:
        if name == "execute":
            return [arguments]
        if name != "batch":
            return []
        if "script" in arguments:
            raise PolicyError(
                "batch 'script' text is refused by the gateway: pass the steps as "
                '\'commands\': [{"command": …, "params": {…}}]'
            )
        extra = sorted(set(arguments) - {"commands"})
        if extra:
            raise PolicyError(f"batch takes only 'commands' (got {', '.join(extra)})")
        steps = arguments.get("commands")
        if not isinstance(steps, list) or not steps:
            raise PolicyError("batch needs a non-empty 'commands' list")
        return steps

    def commands(self, params: dict) -> list[str]:
        """Validate the commands an ``execute`` / ``batch`` call runs and return their ids."""
        name, arguments = params["name"], params["arguments"]
        ids = []
        for step in self._steps(name, arguments):
            where = "execute" if name == "execute" else "each batch step"
            if not isinstance(step, dict):
                raise PolicyError(f"{where} must be an object {{command, params}}")
            extra = sorted(set(step) - {"command", "params"})
            if extra:
                raise PolicyError(
                    f"{where} takes only 'command' and 'params' (got {', '.join(extra)})"
                )
            if "params" in step and not isinstance(step["params"], dict):
                raise PolicyError(f"{where}: 'params' must be an object")
            ids.append(self.check_command(step.get("command")))
        return ids

    def apply_call(self, params: Any) -> tuple[dict, list[str]]:
        new_params, paths = super().apply_call(params)
        self.commands(new_params)
        return new_params, paths

    def audit_detail(self, params: dict) -> str:
        ids = self.commands(params)
        return f" commands={ids}" if ids else ""

    # ----------------------------------------------------------------- paths
    def path_key(self, key: str) -> bool:
        return key in PATH_KEYS

    def check_path(self, value: str, key: str = "path") -> str:
        if "$" in value:
            raise PolicyError(
                f"argument '{key}' must be a literal path: batch references such as $0.path "
                "are not accepted in path arguments"
            )
        return super().check_path(value, key)

    # -------------------------------------------------------------- messages
    def check_message(self, method: Any, params: Any) -> None:
        if method is None:  # a response to a server request
            return
        if not isinstance(method, str):
            raise PolicyError("malformed JSON-RPC method")
        if method.startswith("notifications/"):
            return
        if method not in METHODS:
            raise PolicyError(f"method '{method}' is not accepted on this resource")
        if method == "resources/read":
            uri = params.get("uri") if isinstance(params, dict) else None
            if not isinstance(uri, str) or not uri.startswith(RESOURCE_SCHEME):
                raise PolicyError(f"only {RESOURCE_SCHEME} resources can be read")

    def instructions_note(self) -> str:
        if not self.root:
            return ""
        return (
            "\n\nThis DesignCraft runs headless behind a gateway. Every path argument must be "
            f"an absolute path under {self.root} (images saved by Editorial Assets: "
            f"{self.images_dir}); save documents there as .designcraft files and preview pages "
            "with render_page. Use batch with 'commands' (script text is refused) and pass "
            "literal paths ($N references are refused in path arguments). Printing, the "
            "system clipboard, keyboard shortcuts and the window/dialog tools are disabled."
        )

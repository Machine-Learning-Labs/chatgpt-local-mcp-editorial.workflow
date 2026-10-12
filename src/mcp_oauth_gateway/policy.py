"""Tool policy enforced on MCP JSON-RPC traffic before it reaches scribus-mcp.

- deny/allow lists: denied tools disappear from ``tools/list`` and ``tools/call`` is refused
- path jail: every path-like argument must resolve inside ``POLICY_ROOT``
  (symlinks resolved, so the root must be mounted at the same path in the gateway)
- ``tools/list`` results get ``securitySchemes`` (OpenAI Apps SDK) for the oauth2 scope
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from typing import Any

from .config import DEFAULT_SCOPE, Settings

# Argument names that carry filesystem paths in scribus-mcp (path, image_path,
# font_path, target_dir…) plus generic spellings other MCPs use.
PATH_ARG = re.compile(r"(^|_)(path|paths|dir|directory|file|filename|folder)$", re.IGNORECASE)


class PolicyError(Exception):
    """A tool call that must not reach the upstream MCP."""


@dataclass(frozen=True)
class Policy:
    root: str = ""
    deny: frozenset[str] = frozenset()
    allow: frozenset[str] = frozenset()
    scopes: tuple[str, ...] = (DEFAULT_SCOPE,)

    @classmethod
    def from_settings(cls, settings: Settings) -> Policy:
        return cls(
            root=settings.policy_root,
            deny=frozenset(settings.deny_tools),
            allow=frozenset(settings.allow_tools),
            scopes=settings.scopes,
        )

    # ----------------------------------------------------------------- tools
    def tool_allowed(self, name: str) -> bool:
        if name in self.deny:
            return False
        return not self.allow or name in self.allow

    def apply_call(self, params: Any) -> tuple[dict, list[str]]:
        """Validate a ``tools/call`` params object.

        Returns the params to forward (path arguments rewritten to their resolved
        absolute form, so the upstream acts on exactly what was checked) and the
        list of paths for the audit log.
        """
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise PolicyError("malformed tools/call request")
        name = params["name"]
        if not self.tool_allowed(name):
            raise PolicyError(f"tool '{name}' is disabled by the gateway policy")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise PolicyError("tool arguments must be an object")
        paths: list[str] = []
        rewritten = self._rewrite(arguments, paths)
        return {**params, "arguments": rewritten}, paths

    def _rewrite(self, obj: Any, paths: list[str], key: str = "") -> Any:
        if isinstance(obj, dict):
            return {k: self._rewrite(v, paths, str(k)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._rewrite(v, paths, key) for v in obj]
        if isinstance(obj, str) and obj and PATH_ARG.search(key):
            resolved = self.check_path(obj, key)
            paths.append(resolved)
            return resolved
        return obj

    def check_path(self, value: str, key: str = "path") -> str:
        if not self.root:
            return value
        if "\x00" in value:
            raise PolicyError(f"argument '{key}' contains a NUL byte")
        if value.startswith("~") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
            raise PolicyError(f"argument '{key}' must be an absolute path under {self.root}")
        candidate = value if value.startswith("/") else posixpath.join(self.root, value)
        resolved = os.path.realpath(candidate)
        root = os.path.realpath(self.root)
        if resolved != root and not resolved.startswith(root.rstrip("/") + "/"):
            raise PolicyError(
                f"argument '{key}' points outside the editorial folder: use paths under {self.root}"
            )
        return resolved

    # ---------------------------------------------------------------- results
    def filter_tools_result(self, result: Any) -> Any:
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return result
        schemes = [{"type": "oauth2", "scopes": list(self.scopes)}]
        tools = []
        for tool in result["tools"]:
            if not isinstance(tool, dict) or not self.tool_allowed(str(tool.get("name"))):
                continue
            tool = {**tool, "securitySchemes": schemes}
            tool["_meta"] = {**(tool.get("_meta") or {}), "securitySchemes": schemes}
            tools.append(tool)
        return {**result, "tools": tools}

    def instructions_note(self) -> str:
        if not self.root:
            return ""
        return (
            f"\n\nFile access is restricted by the gateway: every path argument must be an "
            f"absolute path under {self.root} (images to place: {self.root}/inbox)."
        )

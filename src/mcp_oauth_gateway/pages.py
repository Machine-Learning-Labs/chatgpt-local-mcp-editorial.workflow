"""Minimal HTML for the consent screen (no template engine needed)."""

from __future__ import annotations

from html import escape

_STYLE = """
:root{color-scheme:light dark;--bg:#f6f5f2;--fg:#1d1d1b;--card:#fff;--muted:#6b6a66;--accent:#b4462b}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--card:#22211e;--muted:#a3a19a}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;
background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;padding:16px}
main{background:var(--card);max-width:420px;width:100%;padding:28px;border-radius:12px;
box-shadow:0 1px 3px #0002}h1{font-size:1.25rem;margin:0 0 12px}p{margin:0 0 12px}
.muted{color:var(--muted);font-size:.9rem;word-break:break-all}
input{width:100%;padding:10px;font:inherit;border:1px solid var(--muted);border-radius:8px;
background:transparent;color:inherit;margin:4px 0 16px}
.row{display:flex;gap:8px}button{flex:1;padding:10px;font:inherit;border-radius:8px;
border:1px solid var(--accent);cursor:pointer}
.approve{background:var(--accent);color:#fff}.deny{background:transparent;color:inherit}
.error{color:var(--accent)}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def consent_page(
    *, client_name: str, redirect_uri: str, scope: str, request_token: str, error: str | None = None
) -> str:
    err = f"<p class=error>{escape(error)}</p>" if error else ""
    body = f"""
<h1>Authorize access to Scribus MCP</h1>
<p><strong>{escape(client_name)}</strong> wants to use this MCP server.</p>
<p class=muted>Redirect: {escape(redirect_uri)}<br>Scope: {escape(scope)}</p>
<p class=muted>Anyone can register a client under this name.
If you did not start this connection yourself a moment ago, deny it.</p>
{err}
<form method=post action=/authorize>
  <input type=hidden name=request value="{escape(request_token)}">
  <label for=password>Owner password</label>
  <input id=password name=password type=password autocomplete=current-password autofocus>
  <div class=row>
    <button class=deny name=decision value=deny type=submit>Deny</button>
    <button class=approve name=decision value=approve type=submit>Approve</button>
  </div>
</form>"""
    return _page("Authorize · Scribus MCP", body)


def error_page(message: str) -> str:
    return _page("OAuth error", f"<h1>Cannot authorize</h1><p class=error>{escape(message)}</p>")

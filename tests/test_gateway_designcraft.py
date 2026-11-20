"""DesignCraft resource (/designcraft/mcp): routing, audience and the fail-closed policy."""

import json
import logging
import secrets

import httpx
import pytest
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.config import Settings
from mcp_oauth_gateway.policy import PolicyError
from mcp_oauth_gateway.policy_designcraft import DesignCraftPolicy
from mcp_oauth_gateway.tokens import pkce_s256

from .conftest import BASE, REDIRECT, SECRET, _stream, make_settings, register, token_for

PATH = "/designcraft/mcp"
DESIGNCRAFT = f"{BASE}{PATH}"
# The 26 tools of designcraft-cli 0.20.1.
TOOLS = [
    "list_commands",
    "execute",
    "batch",
    "inspect_document",
    "get_story",
    "set_story_text",
    "new_document",
    "open_document",
    "save_document",
    "place_image",
    "render_page",
    "export_png",
    "screenshot",
    "select_tool",
    "pointer",
    "key",
    "type_text",
    "ime",
    "click",
    "drag",
    "menu_list",
    "ui_inspect",
    "ui_set",
    "dialog_set",
    "dialog_confirm",
    "dialog_cancel",
]


class Upstreams:
    """Fake Scribus and DesignCraft (mcp-proxy) upstreams."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content or b"{}")
        method = body.get("method") if isinstance(body, dict) else None
        if method == "tools/list":
            result = {"tools": [{"name": n, "inputSchema": {}} for n in TOOLS]}
        elif method == "initialize":
            result = {"serverInfo": {"name": "designcraft"}, "instructions": "DesignCraft."}
        else:
            result = {"echo": method, "params": body.get("params")}
        payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result})
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_stream(payload.encode())
        )


@pytest.fixture
def upstreams():
    return Upstreams()


@pytest.fixture
def root(tmp_path):
    (tmp_path / "libro" / "assets").mkdir(parents=True)
    return str(tmp_path.resolve())


@pytest.fixture
def client(upstreams, root):
    settings = make_settings(
        policy_root=root,
        designcraft_upstream_url="http://127.0.0.1:8767/mcp",
        designcraft_upstream_host_header="localhost:8767",
    )
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstreams))
    with TestClient(app, base_url=BASE) as test_client:
        yield test_client


def auth(app, path=PATH):
    return {"authorization": f"Bearer {token_for(app, audience=BASE + path)}"}


def rpc(client, method, params=None, id_=1):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return client.post(PATH, json=message, headers=auth(client.app))


def call(client, name, arguments):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments})


def refused(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is True
    return result["content"][0]["text"]


def forwarded(upstreams) -> dict:
    return json.loads(upstreams.requests[-1].content)


# ---------------------------------------------------------------- resource wiring
def test_designcraft_disabled_by_default():
    with TestClient(create_app(make_settings()), base_url=BASE) as client:
        assert client.get(f"/.well-known/oauth-protected-resource{PATH}").status_code == 404
        assert client.post(PATH, json={}).status_code == 404
        assert client.get("/").json()["designcraft"] is None


def test_protected_resource_metadata_and_challenge(client):
    meta = client.get(f"/.well-known/oauth-protected-resource{PATH}").json()
    assert meta["resource"] == DESIGNCRAFT and meta["resource_name"] == "DesignCraft"
    assert client.get(f"/.well-known/oauth-authorization-server{PATH}").status_code == 200
    response = client.post(PATH, json={})
    assert response.status_code == 401
    assert f"oauth-protected-resource{PATH}" in response.headers["www-authenticate"]
    assert client.get("/").json()["designcraft"] == PATH


def test_tokens_are_not_interchangeable(client, upstreams):
    assert client.post(PATH, json={}, headers=auth(client.app, "/editor/mcp")).status_code == 401
    assert client.post("/editor/mcp", json={}, headers=auth(client.app)).status_code == 401
    assert upstreams.requests == []


def test_authorize_accepts_designcraft_resource(client):
    reg = register(client)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": pkce_s256(secrets.token_urlsafe(48)),
            "code_challenge_method": "S256",
            "resource": DESIGNCRAFT,
        },
    )
    assert response.status_code == 200  # consent page, not invalid_target


def test_allowed_call_is_forwarded_reserialized(client, upstreams):
    params = {"command": "frame.create", "params": {"rect": [36, 36, 300, 200], "text": "Hi"}}
    response = call(client, "execute", params)
    assert response.json()["result"]["echo"] == "tools/call"
    request = upstreams.requests[-1]
    assert str(request.url) == "http://127.0.0.1:8767/mcp"
    assert request.headers["host"] == "localhost:8767"
    assert "authorization" not in request.headers
    assert request.content == json.dumps(forwarded(upstreams)).encode()
    assert forwarded(upstreams)["params"]["arguments"] == params


def test_editor_policy_is_unchanged(client, upstreams):
    # The Scribus resource keeps its own deny list and accepts its tools as before.
    response = client.post(
        "/editor/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "key"}},
        headers=auth(client.app, "/editor/mcp"),
    )
    assert response.json()["result"]["echo"] == "tools/call"


# --------------------------------------------------------------------- listing
def test_tools_list_only_shows_reviewed_tools(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == set(Settings.__dataclass_fields__["designcraft_allow_tools"].default)
    assert not names & {"key", "screenshot", "click", "dialog_set", "pointer", "type_text"}
    assert all(t["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}] for t in tools)


def test_initialize_note_names_root_and_images(client, root):
    instructions = rpc(client, "initialize", {}).json()["result"]["instructions"]
    assert instructions.startswith("DesignCraft.")
    assert f"under {root}" in instructions and f"{root}/libro/assets" in instructions


# ------------------------------------------------------------------- refusals
@pytest.mark.parametrize("tool", ["key", "screenshot", "dialog_set", "type_text", "Execute"])
def test_unreviewed_tools_are_refused(client, upstreams, tool):
    assert "disabled by the gateway policy" in refused(call(client, tool, {}))
    assert upstreams.requests == []


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("file.print", "disabled"),
        ("file.printers", "disabled"),
        ("edit.paste", "disabled"),
        ("edit.pasteWithoutFormatting", "disabled"),
        ("script.run", "disabled"),
        ("app.quit", "disabled"),
        ("file.recentFiles", "disabled"),
        ("network.fetch", "not in the gateway's reviewed command list"),
        ("file.upload", "not in the gateway's reviewed command list"),
        ("FILE.PRINT", "command id"),
        ("file", "command id"),
        (7, "command id"),
        (None, "command id"),
    ],
)
def test_execute_command_policy(client, upstreams, command, reason):
    assert reason in refused(call(client, "execute", {"command": command}))
    assert upstreams.requests == []


def test_batch_is_refused_whole_when_one_step_is_denied(client, upstreams):
    steps = [{"command": "frame.create", "params": {}}, {"command": "file.print"}]
    assert "file.print" in refused(call(client, "batch", {"commands": steps}))
    assert upstreams.requests == []


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"script": "file.print {}"}, "'script' text is refused"),
        ({"commands": [{"command": "frame.create"}], "script": "x"}, "'script' text"),
        ({"commands": [], "extra": 1}, "only 'commands'"),
        ({"commands": []}, "non-empty 'commands'"),
        ({"commands": "file.print"}, "non-empty 'commands'"),
        ({"commands": ["file.print"]}, "must be an object"),
        ({"commands": [{"command": "frame.create", "id": 2}]}, "only 'command' and 'params'"),
        ({"commands": [{"command": "frame.create", "params": "[]"}]}, "must be an object"),
    ],
)
def test_batch_shape_is_enforced(client, upstreams, arguments, reason):
    assert reason in refused(call(client, "batch", arguments))
    assert upstreams.requests == []


def test_execute_shape_is_enforced(client, upstreams):
    assert "'params' must be an object" in refused(
        call(client, "execute", {"command": "frame.create", "params": "{}"})
    )
    assert "only 'command' and 'params'" in refused(
        call(client, "execute", {"command": "frame.create", "script": "x"})
    )
    assert upstreams.requests == []


# ------------------------------------------------------------------------ paths
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_document", {"path": "/etc/passwd"}),
        ("execute", {"command": "file.open", "params": {"path": "/etc/passwd"}}),
        ("execute", {"command": "file.package", "params": {"dir": "/var/out"}}),
        ("execute", {"command": "file.exportEpub", "params": {"coverImage": "/etc/x.png"}}),
        ("batch", {"commands": [{"command": "file.save", "params": {"path": "../../x"}}]}),
    ],
)
def test_paths_outside_the_root_are_refused(client, upstreams, tool, arguments):
    assert "outside the editorial folder" in refused(call(client, tool, arguments))
    assert upstreams.requests == []


def test_relative_paths_are_rewritten_inside_the_root(client, upstreams, root):
    call(client, "execute", {"command": "file.save", "params": {"path": "libro/doc"}})
    params = forwarded(upstreams)["params"]["arguments"]["params"]
    assert params["path"] == f"{root}/libro/doc"


@pytest.mark.parametrize("value", ["$0.path", "${0.path}", "libro/${last.name}.png"])
def test_batch_references_are_refused_in_path_arguments(client, upstreams, value):
    steps = [{"command": "file.saveACopy", "params": {"path": value}}]
    assert "literal path" in refused(call(client, "batch", {"commands": steps}))
    assert upstreams.requests == []


def test_references_and_templates_pass_in_other_arguments(client, upstreams):
    steps = [
        {"command": "frame.create", "params": {"rect": [0, 0, 9, 9]}},
        {"command": "story.get", "params": {"story": "$0.story"}},
        {"command": "file.exportBatch", "params": {"job": {"fileName": "{document} - {layout}"}}},
    ]
    call(client, "batch", {"commands": steps})
    sent = forwarded(upstreams)["params"]["arguments"]["commands"]
    assert sent == steps


# ---------------------------------------------------------------------- JSON-RPC
def test_jsonrpc_batches_are_refused(client, upstreams):
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    response = client.post(PATH, json=[message], headers=auth(client.app))
    assert response.status_code == 400 and response.json()["error"]["code"] == -32600
    assert upstreams.requests == []


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("prompts/list", {}),
        ("sampling/createMessage", {}),
        ("resources/read", {"uri": "file:///etc/passwd"}),
        ("resources/read", {}),
    ],
)
def test_unreviewed_methods_are_refused(client, upstreams, method, params):
    response = rpc(client, method, params)
    assert response.status_code == 400 and response.json()["error"]["code"] == -32601
    assert upstreams.requests == []


def test_reviewed_methods_and_notifications_pass(client, upstreams):
    rpc(client, "resources/read", {"uri": "designcraft://document"})
    rpc(client, "ping")
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    client.post(PATH, json=note, headers=auth(client.app))
    assert len(upstreams.requests) == 3


def test_audit_log_names_the_commands(client, caplog):
    steps = [{"command": "frame.create"}, {"command": "type.char", "params": {"size": 24}}]
    with caplog.at_level(logging.INFO, logger="mcp_oauth_gateway.audit"):
        call(client, "batch", {"commands": steps})
        call(client, "execute", {"command": "file.print"})
    text = caplog.text
    assert "tool=batch" in text and "commands=['frame.create', 'type.char']" in text
    assert "deny" in text and "file.print" in text


# ------------------------------------------------------------------ configuration
def test_empty_allow_lists_fail_closed(root):
    settings = Settings.from_env(
        {
            "GATEWAY_SECRET": SECRET,
            "GATEWAY_OWNER_PASSWORD": "pw",
            "POLICY_ROOT": root,
            "DESIGNCRAFT_ALLOW_TOOLS": "none",
            "DESIGNCRAFT_ALLOW_COMMANDS": "none",
        }
    )
    policy = DesignCraftPolicy.from_settings(settings)
    assert not policy.tool_allowed("execute")
    with pytest.raises(PolicyError):
        policy.check_command("frame.create")


def test_env_overrides(root):
    settings = Settings.from_env(
        {
            "GATEWAY_SECRET": SECRET,
            "GATEWAY_OWNER_PASSWORD": "pw",
            "POLICY_ROOT": root,
            "ASSETS_SUBDIR": "/fotos/",
            "DESIGNCRAFT_UPSTREAM_URL": "http://127.0.0.1:9999/mcp/",
            "DESIGNCRAFT_UPSTREAM_HOST_HEADER": "localhost:9999",
            "DESIGNCRAFT_ALLOW_TOOLS": "execute,render_page",
            "DESIGNCRAFT_ALLOW_COMMANDS": "frame.*",
            "DESIGNCRAFT_DENY_COMMANDS": "frame.delete",
        }
    )
    assert settings.designcraft_upstream_url == "http://127.0.0.1:9999/mcp"
    assert settings.designcraft_upstream_host_header == "localhost:9999"
    policy = DesignCraftPolicy.from_settings(settings)
    assert policy.images_dir == f"{root}/fotos"
    assert policy.tool_allowed("render_page") and not policy.tool_allowed("batch")
    assert policy.check_command("frame.create") == "frame.create"
    with pytest.raises(PolicyError, match="disabled"):
        policy.check_command("frame.delete")
    with pytest.raises(PolicyError, match="reviewed"):
        policy.check_command("type.char")


def test_defaults_cover_every_reviewed_namespace():
    defaults = Settings(secret=SECRET, owner_password="pw")
    policy = DesignCraftPolicy.from_settings(defaults)
    for command in ("frame.create", "file.exportPdf", "file.package", "edit.undo", "table.insert"):
        assert policy.check_command(command) == command
    assert policy.instructions_note() == ""  # no root, no note

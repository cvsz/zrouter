"""Command-line interface for zrouter."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from typing import Any

from zrouter_application import FreeRouter
from zrouter_bot import (
    BotHealth,
    CalendarManager,
    CartManager,
    CloudAgentManager,
    EmailManager,
    FileHandler,
    MediaManager,
    MeetingManager,
    NetworkManager,
    PageManager,
    Routine,
    RoutineScheduler,
    SkillLibrary,
    get_bot,
)
from zrouter_bot_models import VaultEntry
from zrouter_catalog import CATALOG
from zrouter_config import CFG, PROVIDERS, read_secret_file
from zrouter_contracts import RouterError
from zrouter_http import serve as _serve_http
from zrouter_runtime import Stats


def serve(router: FreeRouter, host: str, port: int, token: str | None) -> None:
    """Call the HTTP adapter using the current route configuration."""
    _serve_http(router, host, port, token, CFG.routes)


# --------------------------------------------------------------------------- CLI

HELP_TOPICS: dict[str, str] = {
    "quickstart": """\
QUICKSTART
  1. Get free key(s) at https://build.nvidia.com  (keys start with nvapi-)
  2. export NVIDIA_API_KEYS="nvapi-aaa,nvapi-bbb"
  3. python zrouter.py list              # which allowlisted models exist
  4. python zrouter.py chat "hello"      # auto-routed chat
  5. python zrouter.py serve             # OpenAI-compatible proxy on :8000
""",
    "keys": """\
API KEYS
  Sources (merged, de-duplicated):
    NVIDIA_API_KEY      one key
    NVIDIA_API_KEYS     comma / space / newline separated
    --keys-file FILE    one key per line, '#' comments allowed
  On HTTP 429 the key is benched (Retry-After honoured) and the SAME model is
  retried on the next key. 401/403 marks a key dead. Keys are always masked in
  output. Use only keys that belong to you or your team.
  Check state with:  python zrouter.py keys
""",
    "routes": """\
ROUTES  (free-only allowlist; exact IDs or explicit glob patterns, first available match wins)
  auto       classify the prompt automatically (default for `chat` and the proxy)
  general    everyday questions
  code       code / debugging / regex / SQL / git
  reasoning  maths, logic, step-by-step analysis, very long prompts
  fast       short prompts, smallest models
  vision     messages containing images
  Model names accepted by `chat --model` and the proxy:
    auto | free-<route> | route:<route> | exact allowlisted model ID (e.g. glm-4.7)
    Config route patterns may use explicit glob syntax such as "nvidia/*-vision"
  Anything not on the allowlist is refused (HTTP 404), so paid models are never called.
  Edit routes with a config file (see: help config). See what resolves: `list`.
""",
    "serve": """\
PROXY SERVER
  python zrouter.py serve [--host 127.0.0.1] [--port 8000] [--token SECRET]
  Endpoints:
    POST /v1/chat/completions   (stream and non-stream, tools, images)
    POST /v1/embeddings
    GET  /v1/models   GET /health   GET /stats
  Client example:
    from openai import OpenAI
    c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="SECRET")
    c.chat.completions.create(model="auto", messages=[{"role": "user", "content": "hi"}])
  Response headers: X-Router-Model, X-Router-Key (masked), X-Router-Cache.
  Binds to localhost by default. If you use --host 0.0.0.0, ALWAYS set --token / ROUTER_TOKEN.
""",
    "config": """\
CONFIG FILE  (--config router.json  or  NVIDIA_ROUTER_CONFIG=router.json)
  {
    "routes": {"code": ["glm-4.7", "deepseek-v3.2"]},   // replaces only the routes you list
    "deny": ["embed", "guard", "safety"],                // never route chat to ids containing these
    "embed_allow": ["nv-embed"],
    "rpm": 30,            // per-key requests/minute (free tier is about 40)
    "max_wait": 30,       // seconds to wait if every key is rate limited
    "cache_ttl": 600,     // seconds; 0 disables (cache only applies when temperature == 0)
    "timeout": 90,
    "base_url": "https://integrate.api.nvidia.com/v1"
  }
  (Remove the // comments in the real file; JSON does not allow them.)
""",
    "env": """\
ENVIRONMENT VARIABLES
  NVIDIA_API_KEY / NVIDIA_API_KEYS   API key(s)
  NVIDIA_BASE_URL                    default https://integrate.api.nvidia.com/v1
  NVIDIA_RPM                         per-key requests per minute (default 35)
  NVIDIA_MAX_WAIT                    max seconds to wait when all keys are limited (default 60)
  NVIDIA_CACHE_TTL                   cache seconds (default 3600, 0 = off)
  NVIDIA_ROUTER_CONFIG               path to router.json
  NVIDIA_ROUTER_HOME                 stats dir (default ~/.nvidia_free_router)
  ROUTER_TOKEN                       bearer token required by the proxy
""",
    "troubleshooting": """\
TROUBLESHOOTING
  "No API key"                      set NVIDIA_API_KEY(S) or --keys-file
  "no allowlisted model available"  run `list`; edit routes so the substrings match real ids
  429 / "all keys rate-limited"     add more keys, lower NVIDIA_RPM, or raise NVIDIA_MAX_WAIT
  401/403                           key invalid/expired; check `keys` (shows DEAD)
  404 on a model                    it is not on the allowlist (by design: free-only)
  Unsure what is happening          add -v for logs, or run `probe` to test each model
""",
}

MAIN_EPILOG = """\
examples:
  %(prog)s chat "write a regex for emails"        auto-routed
  %(prog)s chat "hi" --route fast --stream        pick a route, stream output
  %(prog)s serve --port 8000 --token secret       OpenAI-compatible proxy
  %(prog)s keys | list | probe | stats            diagnostics

more help:  %(prog)s help [quickstart|keys|routes|serve|config|env|troubleshooting]
"""


def print_help_topic(parser: argparse.ArgumentParser, topic: str | None) -> None:
    if topic in (None, "all"):
        parser.print_help()
        print()
        for t in HELP_TOPICS.values():
            print(t)
    elif topic in HELP_TOPICS:
        print(HELP_TOPICS[topic])
    else:
        sys.exit(
            f"unknown help topic '{topic}'. Topics: all, " + ", ".join(HELP_TOPICS)
        )


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    ap = argparse.ArgumentParser(
        prog="zrouter.py",
        formatter_class=fmt,
        epilog=MAIN_EPILOG,
        description="Free-only router for NVIDIA hosted NIM endpoints: model fallback, multi-key "
        "rotation on 429, auto routing, streaming, cache, stats and an OpenAI-compatible proxy.",
    )
    ap.add_argument(
        "--keys-file", metavar="FILE", help="file with one API key per line"
    )
    ap.add_argument(
        "--providers-file",
        metavar="FILE",
        default=os.environ.get("NVIDIA_PROVIDERS_FILE"),
        help="provider.json with per-provider API keys and base URLs (or NVIDIA_PROVIDERS_FILE)",
    )
    ap.add_argument(
        "--config",
        metavar="FILE",
        default=os.environ.get("NVIDIA_ROUTER_CONFIG"),
        help="JSON config overriding routes/limits (or NVIDIA_ROUTER_CONFIG)",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="show routing/rate-limit logs"
    )
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name: str, help_: str, **kw: Any) -> argparse.ArgumentParser:
        return sub.add_parser(
            name, help=help_, description=help_, formatter_class=fmt, **kw
        )

    add(
        "keys",
        "show each API key (masked): ready / limited / dead, success and 429 counts",
    )
    add("list", "list allowlisted models that currently exist, grouped by route")
    m = add(
        "models",
        "list catalog models with free/paid/provider metadata (no API key needed)",
    )
    m.add_argument(
        "--provider",
        metavar="PROVIDER",
        help="filter by provider (e.g. NVIDIA, Google)",
    )
    m.add_argument("--free", action="store_true", help="show only free models")
    m.add_argument("--paid", action="store_true", help="show only paid models")
    d = add(
        "discover",
        "auto-discover models from the NVIDIA API and update models.json",
    )
    d.add_argument("--keys-file", metavar="FILE", help="file with one API key per line")
    d.add_argument(
        "--output",
        metavar="FILE",
        default="models.json",
        help="output catalog path (default: models.json)",
    )
    p = add(
        "providers",
        "list configured providers with API key counts and base URLs (no API key needed)",
    )
    p.add_argument(
        "--file",
        metavar="FILE",
        default=None,
        help="provider.json path (default: provider.json or NVIDIA_PROVIDERS_FILE)",
    )
    add(
        "probe",
        "send a tiny request to every allowlisted model and report status + latency",
    )
    add("stats", "show saved per-model and per-key statistics (no API key needed)")
    c = add(
        "chat",
        "send one prompt through the router",
        epilog='example:  %(prog)s "explain TCP slow start" --route reasoning --stream',
    )
    c.add_argument("prompt", help="the user message")
    c.add_argument(
        "--route",
        help="force a route (default: auto-classify). Any route name defined in "
        "routes (default or config); validated at request time.",
    )
    c.add_argument(
        "--model",
        help="specific allowlisted model, any substring of its id (e.g. glm-4.7)",
    )
    c.add_argument("--system", help="optional system prompt")
    c.add_argument(
        "--max-tokens", type=int, default=1024, metavar="N", help="default 1024"
    )
    c.add_argument("--stream", action="store_true", help="print tokens as they arrive")
    s = add(
        "serve",
        "run a local OpenAI-compatible proxy (chat, embeddings, models, health, stats)",
        epilog="client base_url: http://HOST:PORT/v1   model: auto | free-code | glm-4.7 ...",
    )
    s.add_argument(
        "--host", default="127.0.0.1", help="default 127.0.0.1 (localhost only)"
    )
    s.add_argument("--port", type=int, default=8000, help="default 8000")
    s.add_argument(
        "--token",
        default=os.environ.get("ROUTER_TOKEN") or read_secret_file(
            os.environ.get("ROUTER_TOKEN_FILE")
        ),
        help="require 'Authorization: Bearer TOKEN' (or ROUTER_TOKEN); "
        "strongly advised if host is not 127.0.0.1",
    )
    b = add(
        "bot",
        "bot framework: status, vault, memory, approvals, routines, skills, files, meetings",
    )
    b.add_argument(
        "subcmd",
        help="subcommand: status, vault, memory, approval, approve, deny, routine, skill, file, meeting, page, agent, email, calendar, media, cart, network, health",
    )
    b.add_argument(
        "arg",
        nargs="?",
        help="subcommand argument (e.g. card id, skill id, file name, memory key)",
    )
    b.add_argument(
        "arg2",
        nargs="?",
        help="second subcommand argument (e.g. vault id, memory key, value)",
    )
    b.add_argument(
        "arg3",
        nargs="?",
        help="third subcommand argument",
    )
    b.add_argument(
        "arg4",
        nargs="?",
        help="fourth subcommand argument",
    )
    b.add_argument("--value", help="value for memory set or vault update")
    b.add_argument("--value2", help="second value for cart items (quantity)")
    b.add_argument("--details", help="details for approval card creation")
    b.add_argument(
        "--schedule", help="schedule for routine (e.g. daily 09:00, every 1 hour)"
    )
    b.add_argument("--title", help="meeting/page title")
    b.add_argument(
        "--platform", help="meeting platform (zoom, google_meet, microsoft_teams)"
    )
    b.add_argument("--link", help="meeting link URL")
    b.add_argument("--at", type=float, help="meeting scheduled time (unix timestamp)")
    b.add_argument("--mode", help="agent mode (code, research, analysis, writing)")
    b.add_argument("--task", help="cloud agent task description")
    b.add_argument("--from", dest="from_addr", help="email from address")
    b.add_argument("--to", dest="to_addr", help="email to address")
    b.add_argument("--subject", help="email subject")
    b.add_argument("--body", help="email/message body")
    h = add(
        "help",
        "detailed help: quickstart, keys, routes, serve, config, env, troubleshooting",
    )
    h.add_argument(
        "topic", nargs="?", default="all", help="all (default) or one topic name"
    )
    return ap


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    if a.cmd is None:
        ap.print_help()
        print("\nNew here? run:  python zrouter.py help quickstart")
        return
    if a.cmd == "help":
        return print_help_topic(ap, a.topic)

    if a.cmd == "bot":
        _bot_cmd(a)
        return

    logging.basicConfig(
        level=logging.INFO if a.verbose or a.cmd == "serve" else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if a.config:
        CFG.load(a.config)

    if a.cmd == "stats":
        data = Stats().data
        print(f"{'model':<48}{'ok':>6}{'fail':>6}{'429':>6}{'avg s':>8}")
        for m, v in sorted(data["models"].items()):
            avg = v["lat_sum"] / v["ok"] if v["ok"] else 0
            print(f"{m:<48}{v['ok']:>6}{v['fail']:>6}{v['429']:>6}{avg:>8.2f}")
        print(f"\n{'key':<24}{'ok':>6}{'fail':>6}{'429':>6}")
        for k, v in data["keys"].items():
            print(f"{k:<24}{v['ok']:>6}{v['fail']:>6}{v['429']:>6}")
        return

    if a.cmd == "models":
        models = CATALOG.models
        if a.provider:
            models = CATALOG.by_provider(a.provider)
        if a.free:
            models = CATALOG.list_free()
        if a.paid:
            models = CATALOG.list_paid()
        if not models:
            print("No models match the given filters.")
            return
        print(f"{'model':<40}{'provider':<16}{'tier':<8}{'routes':<24}{'description'}")
        print("-" * 110)
        for m in sorted(models, key=lambda x: str(x.get("id", ""))):
            mid = str(m.get("id", ""))
            prov = str(m.get("provider", "unknown"))
            tier = "free" if m.get("free") else "paid"
            routes = ",".join(m.get("routes", []))
            desc = str(m.get("description", ""))
            print(f"{mid:<40}{prov:<16}{tier:<8}{routes:<24}{desc}")
        return

    if a.cmd == "providers":
        print(f"{'provider':<16}{'base_url':<45}{'keys':>6}{'env_var':<20}")
        print("-" * 90)
        for p in PROVIDERS.list_providers():
            name = str(p["name"])
            base = str(p["base_url"])
            nkeys = str(p["key_count"])
            env = str(p["env_var"])
            print(f"{name:<16}{base:<45}{nkeys:>6}{env:<20}")
        return

    try:
        r = FreeRouter(keys_file=a.keys_file, providers_file=a.providers_file)
    except RouterError as e:
        sys.exit(f"error {e.status}: {e.message}")
    try:
        if a.cmd == "keys":
            for label, prov, st, ok, n429 in r.key_status():
                print(f"{label:<22} {prov:<16} {st:<16} ok={ok} 429s={n429}")
        elif a.cmd == "list":
            for route, pats in CFG.routes.items():
                print(f"[{route}]")
                for m in r.allowed(pats):
                    print("  ", m)
        elif a.cmd == "probe":
            for m, (status, secs) in r.probe().items():
                print(f"{status!s:>6}  {secs:>6}s  {m}")
        elif a.cmd == "chat":
            msgs = ([{"role": "system", "content": a.system}] if a.system else []) + [
                {"role": "user", "content": a.prompt}
            ]
            if a.stream:
                for d in r.chat_stream(
                    msgs, route=a.route, model=a.model, max_tokens=a.max_tokens
                ):
                    print(d, end="", flush=True)
                print()
            else:
                out = r.chat(
                    msgs, route=a.route, model=a.model, max_tokens=a.max_tokens
                )
                print(f"# model: {out['model']}  key: {out['key']}\n{out['text']}")
        elif a.cmd == "serve":
            serve(r, a.host, a.port, a.token)
        elif a.cmd == "discover":
            count = CATALOG.update_from_router(r)
            CATALOG.save(a.output)
            free = len(CATALOG.list_free())
            paid = len(CATALOG.list_paid())
            print(f"Discovered {count} model(s) from NVIDIA API -> {a.output}")
            print(f"  free: {free}  paid: {paid}")
            providers = sorted({m.get("provider", "unknown") for m in CATALOG.models})
            print(f"  providers: {', '.join(providers)}")
    except RouterError as e:
        sys.exit(f"error {e.status}: {e.message}")
    finally:
        if r.stats:
            r.stats.flush()


def _bot_cmd(a: Any) -> None:
    """Handle bot subcommands."""
    bot = get_bot()

    if a.subcmd == "status":
        d = bot.to_dict()
        print(f"Bot: {d['name']} (id={d['id']})")
        print(f"  Status: {d['status_phrase']} ({d['status']})")
        print(f"  Vault entries: {d['vault_entries']}")
        print(f"  Memory keys: {d['memory_keys']}")
        print(f"  Pending approvals: {d['pending_approvals']}")

    elif a.subcmd == "health":
        report = BotHealth(bot).report()
        for k, v in report.items():
            print(f"  {k}: {v}")

    elif a.subcmd == "vault":
        if a.arg == "list":
            entries = bot.vault_list()
            if not entries:
                print("  No vault entries.")
            for e in entries:
                print(f"  {e.id[:8]}  {e.kind:<12} {e.name}")
        elif a.arg == "get" and a.arg2:
            e = bot.vault_get(a.arg2)
            if e:
                print(f"  {e.name} ({e.kind}): {e.value}")
            else:
                print(f"  Vault entry {a.arg2} not found.")
        elif a.arg == "add" and a.arg2 and a.value:
            import json as _json

            try:
                val = _json.loads(a.value)
            except (ValueError, TypeError):
                val = {"raw": a.value}
            e = VaultEntry(id=str(uuid.uuid4()), name=a.arg2, kind="secret", value=val)
            bot.vault_add(e)
            print(f"  Added vault entry {e.id[:8]}: {e.name}")
        elif a.arg == "delete" and a.arg2:
            ok = bot.vault_delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot vault list | get <id> | add <name> <value> | delete <id>"
            )

    elif a.subcmd == "memory":
        if a.arg == "list":
            mem = bot.all_memory()
            if not mem:
                print("  No memory entries.")
            for k, v in mem.items():
                print(f"  {k}: {v}")
        elif a.arg == "get" and a.arg2:
            print(f"  {a.arg2}: {bot.recall(a.arg2)}")
        elif a.arg == "set" and a.arg2 and a.value:
            bot.remember(a.arg2, a.value)
            print(f"  Set {a.arg2} = {a.value}")
        elif a.arg == "delete" and a.arg2:
            ok = bot.forget(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot memory list | get <key> | set <key> --value <value> | delete <key>"
            )

    elif a.subcmd == "approval":
        cards = bot.pending_approvals()
        if not cards:
            print("  No pending approvals.")
        for c in cards:
            print(f"  {c.id[:8]}  {c.action:<20} {c.status.value:<12} {c.details}")

    elif a.subcmd == "approve" and a.arg:
        card = bot.approve_card(a.arg, decided_by="cli")
        if card:
            print(f"  Approved: {card.action}")
        else:
            print(f"  Card {a.arg} not found or already decided.")

    elif a.subcmd == "deny" and a.arg:
        card = bot.deny_card(a.arg, decided_by="cli")
        if card:
            print(f"  Denied: {card.action}")
        else:
            print(f"  Card {a.arg} not found or already decided.")

    elif a.subcmd == "routine":
        scheduler = RoutineScheduler()
        if a.arg == "list":
            routines = scheduler.list()
            if not routines:
                print("  No routines.")
            for r in routines:
                print(f"  {r.id[:8]}  {r.name:<20} {r.status.value:<12} {r.schedule}")
        elif a.arg == "add" and a.arg2:
            routine = Routine(
                id=str(uuid.uuid4()),
                name=a.arg2,
                action="chat",
                params={"prompt": a.value or ""},
                schedule=a.schedule or "daily 09:00",
            )
            scheduler.add(routine)
            print(f"  Added routine {routine.id[:8]}: {routine.name}")
        else:
            print("  Usage: zrouter bot routine list | add <name> [schedule]")

    elif a.subcmd == "skill":
        library = SkillLibrary()
        if a.arg == "list":
            skills = library.list()
            if not skills:
                print("  No skills.")
            for s in skills:
                print(
                    f"  {s.id[:8]}  {s.name:<20} {s.category:<12} params={','.join(s.parameters)}"
                )
        elif a.arg == "use" and a.arg2 and a.value:
            import json as _json

            try:
                params = _json.loads(a.value)
            except (ValueError, TypeError):
                params = {"text": a.value}
            result = library.use(a.arg2, params)
            print(f"  {result}")
        else:
            print("  Usage: zrouter bot skill list | use <id> --value <json>")

    elif a.subcmd == "file":
        fh = FileHandler()
        if a.arg == "list":
            files = fh.list_files()
            if not files:
                print("  No files.")
            for f in files:
                print(f"  {f['name']:<40} {f['size']:>10} bytes  {f['extension']}")
        elif a.arg == "upload" and a.arg2:
            from pathlib import Path as _Path

            p = _Path(a.arg2)
            if p.exists():
                meta = fh.save_file(p.name, p.read_bytes())
                print(
                    f"  Uploaded: {meta['id'][:8]}  {meta['original_name']} ({meta['size']} bytes)"
                )
            else:
                print(f"  File not found: {a.arg2}")
        else:
            print("  Usage: zrouter bot file list | upload <path>")

    elif a.subcmd == "meeting":
        mm = MeetingManager()
        if a.arg == "list":
            meetings = mm.list()
            if not meetings:
                print("  No meetings.")
            for m in meetings:
                print(f"  {m.id[:8]}  {m.title:<25} {m.platform:<15} {m.status}")
        elif a.arg == "add" and a.title and a.platform and a.link and a.at is not None:
            m = mm.schedule(a.title, a.platform, a.link, a.at)
            print(f"  Scheduled: {m.title} ({m.platform}) id={m.id[:8]}")
        elif a.arg == "join" and a.arg2:
            m = mm.join(a.arg2)
            if m:
                print(f"  Joined: {m.title} ({m.platform})")
            else:
                print(f"  Meeting {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot meeting list | add --title <t> --platform <p> --link <url> --at <ts> | join <id>"
            )

    elif a.subcmd == "page":
        pm = PageManager()
        if a.arg == "list":
            pages = pm.list_for_bot(bot.id)
            if not pages:
                print("  No pages.")
            for p in pages:
                print(
                    f"  {p.id[:8]}  {p.title:<25} {'owner' if p.owner_bot_id == bot.id else 'shared'}"
                )
        elif a.arg == "create" and a.arg2 and a.value:
            page = pm.create(a.arg2, a.value, bot.id)
            print(f"  Created page: {page.title} id={page.id[:8]}")
        elif a.arg == "get" and a.arg2:
            p = pm.get(a.arg2)
            if p:
                print(f"  {p.title}: {p.content[:100]}...")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "update" and a.arg2 and a.value:
            p = pm.update(a.arg2, a.value)
            if p:
                print(f"  Updated page: {p.title}")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "share" and a.arg2:
            p = pm.share_with(a.arg2, bot.id)
            if p:
                print(f"  Shared page: {p.title}")
            else:
                print(f"  Page {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = pm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot page list | create <title> --value <content> | get <id> | update <id> --value <content> | share <id> | delete <id>"
            )

    elif a.subcmd == "agent":
        cam = CloudAgentManager()
        if a.arg2 == "list":
            agents = cam.list()
            if not agents:
                print("  No agents.")
            for ag in agents:
                print(f"  {ag.id[:8]}  {ag.name:<20} {ag.mode:<12} {ag.status}")
        elif a.arg == "create" and a.arg2 and a.mode and a.task:
            agent = cam.create(a.arg2, a.mode, a.task)
            print(f"  Created agent: {agent.name} ({agent.mode}) id={agent.id[:8]}")
        elif a.arg == "start" and a.arg2:
            agent = cam.start(a.arg3)
            if agent:
                print(f"  Started agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "complete" and a.arg2 and a.value:
            agent = cam.complete(a.arg2, a.value)
            if agent:
                print(f"  Completed agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "fail" and a.arg2 and a.value:
            agent = cam.fail(a.arg2, a.value)
            if agent:
                print(f"  Failed agent: {agent.name}")
            else:
                print(f"  Agent {a.arg3} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = cam.delete(a.arg3)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot agent list | create <name> --mode <m> --task <t> | start <id> | complete <id> --value <result> | fail <id> --value <error> | delete <id>"
            )

    elif a.subcmd == "email":
        em = EmailManager()
        if a.arg == "list":
            emails = em.list()
            if not emails:
                print("  No emails.")
            for e in emails:
                print(
                    f"  {e.id[:8]}  {e.subject:<30} {e.from_addr:<20} -> {e.to_addr:<20} {e.status}"
                )
        elif a.arg == "draft" and a.from_addr and a.to_addr and a.subject and a.body:
            email = em.draft(a.from_addr, a.to_addr, a.subject, a.body)
            print(f"  Drafted email: {email.subject} id={email.id[:8]}")
        elif a.arg == "send" and a.arg2:
            email = em.send(a.arg2)
            if email:
                print(f"  Sent email: {email.subject}")
            else:
                print(f"  Email {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = em.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot email list | draft --from <f> --to <t> --subject <s> --body <b> | send <id> | delete <id>"
            )

    elif a.subcmd == "calendar":
        cal = CalendarManager()
        if a.arg == "list":
            events = cal.list()
            if not events:
                print("  No events.")
            for e in events:
                print(f"  {e.id[:8]}  {e.title:<25} {e.status}")
        elif a.arg == "create" and a.arg2 and a.at is not None and a.value:
            event = cal.create(a.title, a.at, a.at + 3600, a.value)
            print(f"  Created event: {event.title} id={event.id[:8]}")
        elif a.arg == "cancel" and a.arg2:
            event = cal.cancel(a.arg2)
            if event:
                print(f"  Cancelled event: {event.title}")
            else:
                print(f"  Event {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot calendar list | create <title> --at <ts> --value <desc> | cancel <id>"
            )

    elif a.subcmd == "media":
        mm = MediaManager()
        if a.arg == "list":
            assets = mm.list()
            if not assets:
                print("  No media assets.")
            for a_ in assets:
                print(
                    f"  {a_.id[:8]}  {a_.title:<25} {a_.media_type:<8} {a_.size_bytes} bytes"
                )
        elif a.arg == "create" and a.arg2 and a.mode and a.value:
            asset = mm.create(
                a.title, a.media_type, a.value, a.value, len(a.value.encode())
            )
            print(
                f"  Created media: {asset.title} ({asset.media_type}) id={asset.id[:8]}"
            )
        elif a.arg == "delete" and a.arg2:
            ok = mm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot media list | create <title> --mode <image|video> --value <prompt|path> | delete <id>"
            )

    elif a.subcmd == "cart":
        cm = CartManager()
        if a.arg == "list":
            carts = cm.list_for_bot(bot.id)
            if not carts:
                print("  No carts.")
            for c in carts:
                print(
                    f"  {c.id[:8]}  {c.status:<12} total=${c.total():.2f} items={len(c.items)}"
                )
        elif a.arg == "add-item" and a.arg2 and a.value and a.value2:
            try:
                price = float(a.value)
                quantity = int(a.value2)
            except (ValueError, TypeError):
                print(
                    "  Error: price must be a number and quantity must be an integer."
                )
            else:
                carts = cm.list_for_bot(bot.id)
                if carts:
                    cart = carts[0]
                else:
                    cart = cm.create(bot.id)
                cart = cm.add_item(cart.id, a.arg2, price, quantity, a.arg3 or "")
                print(f"  Added item to cart: {a.arg2}")
        elif a.arg == "checkout" and a.arg2:
            cart = cm.checkout(a.arg2)
            if cart:
                print(f"  Checked out cart: total=${cart.total():.2f}")
            else:
                print(f"  Cart {a.arg2} not found.")
        else:
            print(
                "  Usage: zrouter bot cart list | add-item <name> --value <price> --value2 <qty> [url] | checkout <id>"
            )

    elif a.subcmd == "network":
        nm = NetworkManager()
        if a.arg == "list":
            peers = nm.list()
            if not peers:
                print("  No peers.")
            for p in peers:
                print(f"  {p.id[:8]}  {p.name:<20} {p.ip:<20} {p.status}")
        elif a.arg == "add" and a.arg2 and a.arg3:
            peer = nm.add_peer(a.arg2, a.arg3)
            print(f"  Added peer: {peer.name} ({peer.ip})")
        elif a.arg == "status" and a.arg2:
            peer = nm.update_status(a.arg2, a.arg3 or "online")
            if peer:
                print(f"  Peer status: {peer.status}")
            else:
                print(f"  Peer {a.arg2} not found.")
        elif a.arg == "delete" and a.arg2:
            ok = nm.delete(a.arg2)
            print(f"  Deleted: {ok}")
        else:
            print(
                "  Usage: zrouter bot network list | add <name> <ip> | status <id> <online|offline> | delete <id>"
            )

    else:
        print(
            "  Unknown bot subcommand. Use: status, health, vault, memory, approval, approve, deny, routine, skill, file, meeting, page, agent, email, calendar, media, cart, network"
        )

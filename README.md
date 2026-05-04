# llm-relay

> Use Codex CLI with any LLM backend — DeepSeek, Mistral, and more.

**llm-relay** is a local proxy that translates the [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses) into requests any OpenAI-compatible backend can understand. It runs silently in the background so tools like [Codex CLI](https://github.com/openai/codex) can use DeepSeek (or other providers) without any code changes.

```
Codex CLI  →  llm-relay (local proxy)  →  DeepSeek API
              http://127.0.0.1:8080         api.deepseek.com
```

---

## Why llm-relay?

Codex CLI speaks the **OpenAI Responses API** — a format that most alternative providers do not support. llm-relay bridges the gap:

- **No code changes** in Codex — it never knows it's talking to a different backend.
- **One command** to install, one command to start.
- **Auto-configures** `~/.codex/config.toml` — no manual editing required.
- **Pure Python** — zero external dependencies, works on macOS and Linux.

---

## Requirements

- **Python 3.9 or higher** — check with `python3 --version`
- **A DeepSeek API key** — get one at [platform.deepseek.com](https://platform.deepseek.com/api_keys)

---

## Installation

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/thatsbass/llm-relay/main/install.sh | bash
```

> **Notes:**
> - Use `bash`, not `sh`. On Ubuntu/Debian, `sh` is `dash` and will fail.
> - Do **not** use `sudo`. The installer runs as your user and installs into `~/.llm-relay/`. If a step needs elevated privileges (e.g. installing `python3-venv`), the script will call `sudo` itself and ask for your password.

The installer will:
1. Check that Python 3.9+ is available
2. Create a virtual environment in `~/.llm-relay/venv/`
3. Install llm-relay into the venv
4. Create the `llm-relay` command in `~/.local/bin/`
5. Add `~/.local/bin` to your PATH (in `.zshrc`, `.zprofile`, `.bashrc`, or `.bash_profile` — whichever your shell uses)
6. Launch the setup wizard automatically

After the installer finishes, **open a new terminal** (or run `source ~/.zshrc`) for the `llm-relay` command to be available.

### Manual install

```bash
git clone https://github.com/thatsbass/llm-relay.git
cd llm-relay
python3 -m pip install .
```

---

## Quick start

```
Step 1 — Run the setup wizard (once)

  $ llm-relay setup

  ╔══════════════════════════════╗
  ║      llm-relay  setup        ║
  ╚══════════════════════════════╝

  Port [8080]:
  Provider (deepseek) [deepseek]:
  DEEPSEEK_API_KEY: ****

  ✓ Config saved       → ~/.llm-relay/config.json
  ✓ Codex config updated → ~/.codex/config.toml
  ✓ .env written       → ~/.llm-relay/.env


Step 2 — Start the proxy

  $ llm-relay start

  ✓ Proxy running  →  http://127.0.0.1:8080
  ✓ Backend        →  DeepSeek

  Press Ctrl+C to stop.


Step 3 — Use Codex normally (in another terminal)

  $ codex "Write a Python function that reverses a string"
```

That's it. llm-relay automatically updates `~/.codex/config.toml` during setup so Codex routes all requests through the proxy.

---

## Commands

| Command | Description |
|---|---|
| `llm-relay` | Start the proxy (runs setup first if not configured) |
| `llm-relay start` | Start the proxy in the foreground |
| `llm-relay stop` | Stop the proxy from another terminal |
| `llm-relay status` | Show running state and active configuration |
| `llm-relay setup` | Re-run the setup wizard (change port, provider, or API key) |
| `llm-relay update` | Upgrade to the latest version from GitHub |
| `llm-relay config port 9000` | Change the port without re-running setup |
| `llm-relay config key sk-xxx` | Update the API key without re-running setup |
| `llm-relay --version` | Print the version and exit |

### Examples

```bash
# Check if the proxy is running
llm-relay status

# Change port and restart
llm-relay config port 9000
llm-relay stop && llm-relay start

# Update your API key
llm-relay config key sk-your-new-key

# Run the setup wizard again (e.g. to switch provider)
llm-relay setup
```

---

## What gets configured automatically

Running `llm-relay setup` writes or updates the following files:

### `~/.llm-relay/config.json`
The proxy's own configuration (source of truth).
```json
{
  "port": 8080,
  "provider": "deepseek",
  "api_key": "sk-your-key"
}
```

### `~/.codex/config.toml`
Codex CLI's configuration — updated automatically. Your existing projects and settings are preserved.
```toml
model = "gpt-5.5"
model_provider = "deepseek"

[model_providers.deepseek]
name = "DeepSeek"
base_url = "http://127.0.0.1:8080"
env_key = "DEEPSEEK_API_KEY"
wire_api = "responses"
...

# Your existing project trust levels are untouched:
[projects."/your/project"]
trust_level = "trusted"
```

### `~/.llm-relay/.env`
Optional — source this file if you want the env vars in your shell session:
```bash
source ~/.llm-relay/.env
```

---

## How it works

```
┌─────────────┐     OpenAI         ┌─────────────┐     DeepSeek       ┌──────────────┐
│  Codex CLI  │  Responses API  →  │  llm-relay  │  Chat Completions  │  DeepSeek    │
│             │  POST /responses   │  :8080      │  POST /v1/chat/... │  API         │
└─────────────┘                    └─────────────┘                     └──────────────┘
                                         │
                                   ┌─────┴──────┐
                                   │ Translates │
                                   │ • messages │
                                   │ • tools    │
                                   │ • SSE      │
                                   └────────────┘
```

llm-relay handles the format differences between the two APIs:

- **Message format** — converts Responses API `input[]` items to Chat Completions `messages[]`
- **Tool calls** — translates function definitions and results in both directions
- **Streaming** — simulates Server-Sent Events (the real API streams; the proxy buffers then replays)
- **XML tool calls** — some backends return tool calls as XML instead of JSON; llm-relay parses both

---

## Supported backends

| Backend | Key | Status |
|---|---|---|
| [DeepSeek](https://platform.deepseek.com) | `deepseek` | ✅ Supported |
| More coming | — | 🔜 Planned |

---

## Adding a new backend

llm-relay uses a **Factory pattern** — adding a backend requires only two files:

**1. Create `llm_relay/translators/my_provider.py`:**
```python
from llm_relay.translators.base import AbstractTranslator, ParsedResponse

class MyProviderTranslator(AbstractTranslator):
    @property
    def base_url(self): return "https://api.myprovider.com"

    @property
    def chat_endpoint(self): return "/v1/chat/completions"

    def build_request(self, messages, tools, max_output_tokens, tc_count, **kw):
        return {"model": "my-model", "messages": messages, "stream": False}

    def parse_response(self, raw_body, req_id):
        # translate the response to Responses API format
        ...
```

**2. Register it in `llm_relay/translators/factory.py`:**
```python
from llm_relay.translators.my_provider import MyProviderTranslator
TranslatorFactory.register("myprovider", MyProviderTranslator)
```

**3. Add it to the provider list in `llm_relay/cli/config_manager.py`:**
```python
PROVIDERS = {
    "deepseek":   {"display": "DeepSeek",    "env_key": "DEEPSEEK_API_KEY"},
    "myprovider": {"display": "My Provider", "env_key": "MYPROVIDER_API_KEY"},
}
```

No other file needs to change. The wizard and factory pick it up automatically.

---

## Troubleshooting

### `llm-relay: command not found`
The `~/.local/bin` directory is not in your PATH yet.
```bash
# For zsh
source ~/.zprofile   # or ~/.zshrc

# For bash
source ~/.bashrc     # or ~/.bash_profile
```
Or open a new terminal window.

### `Cannot bind to port 8080`
Another process is using that port.
```bash
llm-relay config port 9000
llm-relay start
```

### `DEEPSEEK_API_KEY not set`
```bash
llm-relay config key sk-your-key
```

### `502 Upstream error`
The proxy cannot reach the DeepSeek API.
- Check your internet connection.
- Verify your API key is valid at [platform.deepseek.com](https://platform.deepseek.com).
- Check your API quota / billing.

### Proxy crashes and leaves a stale PID file
```bash
llm-relay stop    # detects and cleans up the stale PID file automatically
llm-relay start
```

### Health check
```bash
curl http://127.0.0.1:8080/health
# Expected: {"status": "ok"}
```

---

## Project structure

```
llm-relay/
├── install.sh                     # One-line installer
├── llm_relay/
│   ├── cli/
│   │   ├── config_manager.py      # ~/.llm-relay/config.json R/W
│   │   ├── codex_writer.py        # Smart merge of ~/.codex/config.toml
│   │   ├── pid.py                 # PID file (start/stop between terminals)
│   │   ├── wizard.py              # Interactive setup wizard
│   │   └── commands.py            # start / stop / status / config
│   ├── parsers/
│   │   ├── messages.py            # Responses API → Chat Completions format
│   │   └── xml_tools.py           # XML/DSML tool-call parser
│   ├── translators/
│   │   ├── base.py                # AbstractTranslator interface
│   │   ├── factory.py             # TranslatorFactory (registry pattern)
│   │   └── deepseek.py            # DeepSeek implementation
│   ├── session/
│   │   └── store.py               # Thread-safe LRU conversation store
│   └── server/
│       ├── handler.py             # HTTP request handler
│       └── app.py                 # Application factory
└── tests/                         # 82 unit tests
```

---

## Stargazers over time
[![Stargazers over time](https://starchart.cc/thatsbass/llm-relay.svg?background=%23070707&axis=%23ffffff&line=%23ffffff)](https://starchart.cc/thatsbass/llm-relay)

---

## Contributing

Contributions are welcome — especially new backend translators!

```bash
git clone https://github.com/thatsbass/llm-relay.git
cd llm-relay
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
python3 -m pytest tests/ -v

# Or without pytest
python3 -m unittest discover -s tests -v
```

Please open an issue before starting work on a large change.

---

## License

MIT — see [LICENSE](LICENSE).

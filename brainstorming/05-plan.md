# 05 — Plan d'implémentation

## Arbre des fichiers cible

```
llm_relay/
├── __init__.py                        # (modifié) version → 0.2.0
├── __main__.py                        # (modifié) description mise à jour
├── config.py                          # (modifié) + api_base_url, fallback, protocoles
│
├── parsers/
│   ├── __init__.py
│   ├── messages.py                    # (inchangé) Responses → messages[]
│   ├── anthropic_messages.py          # (NOUVEAU) Anthropic → messages[]
│   └── xml_tools.py                   # (inchangé) extraction XML tool calls
│
├── translators/
│   ├── __init__.py
│   ├── base.py                        # (modifié) + build_anthropic_request, + FIM
│   ├── factory.py                     # (modifié) register nouveaux translators
│   ├── deepseek.py                    # (modifié) → config pour chat_completions
│   ├── chat_completions.py            # (NOUVEAU) translator Chat générique
│   ├── anthropic_pass.py              # (NOUVEAU) pass-through Anthropic
│   └── anthropic_to_chat.py           # (NOUVEAU) traduction Anthropic↔Chat
│
├── server/
│   ├── __init__.py
│   ├── app.py                         # (modifié) injection routing engine
│   ├── handler.py                     # (modifié) + /v1/messages, /v1/models, FIM
│   ├── sse_anthropic.py               # (NOUVEAU) streaming SSE Anthropic
│   └── models_handler.py              # (NOUVEAU) GET /v1/models
│
├── routing/
│   ├── __init__.py
│   ├── engine.py                      # (NOUVEAU) routing engine
│   ├── rate_limiter.py                # (NOUVEAU) token bucket
│   ├── circuit_breaker.py             # (NOUVEAU) circuit breaker
│   └── fallback.py                    # (NOUVEAU) fallback chain
│
├── context/
│   ├── __init__.py
│   └── injector.py                    # (NOUVEAU) context injection
│
├── session/
│   ├── __init__.py
│   └── store.py                       # (modifié) session enrichie
│
└── cli/
    ├── __init__.py
    ├── commands.py                    # (modifié) banner multi-endpoint
    ├── wizard.py                      # (modifié) multi-provider + base_url
    ├── config_manager.py              # (modifié) PROVIDERS enrichi
    ├── codex_writer.py                # (inchangé) config Codex
    ├── claude_writer.py               # (NOUVEAU) guide config Claude Desktop 3P
    └── pid.py                         # (inchangé)

tests/
├── test_parsers.py                    # (modifié) + tests anthropic
├── test_translators.py               # (modifié) + tests nouveaux translators
├── test_session.py                    # (inchangé)
├── test_anthropic_messages.py         # (NOUVEAU)
├── test_anthropic_streaming.py        # (NOUVEAU)
├── test_routing.py                    # (NOUVEAU)
└── test_fim.py                        # (NOUVEAU)
```

---

## Phase 0 : Refactor Chat Completions Translator

**Objectif** : Extraire le code DeepSeek en un translator générique `chat_completions.py`.

**Fichiers** :
- `translators/chat_completions.py` (NOUVEAU) — translator générique avec `base_url`, `model` configurables
- `translators/deepseek.py` (MODIFIÉ) — devient une fine couche config : `base_url="https://api.deepseek.com"`, `model="deepseek-v4-pro"`
- `translators/factory.py` (MODIFIÉ) — `register("deepseek", DeepSeekTranslator)` continue de fonctionner

**Détail** :
- Le `ChatCompletionsTranslator` accepte `base_url`, `model`, `api_key` dans son constructeur
- `DeepSeekTranslator` hérite de `ChatCompletionsTranslator` avec les valeurs DeepSeek
- Zéro changement fonctionnel pour le chemin existant

---

## Phase 1 : Northbound Anthropic Messages API

**Objectif** : Accepter les requêtes `POST /v1/messages` et les router.

**Fichiers** :
- `parsers/anthropic_messages.py` (NOUVEAU)
- `server/handler.py` (MODIFIÉ — ajout `POST /v1/messages`)
- `server/models_handler.py` (NOUVEAU — `GET /v1/models`)

### 1a. Parser Anthropic → format interne

```python
# parsers/anthropic_messages.py

def anthropic_to_messages(anthropic_request: dict) -> dict:
    """
    Convertit une requête Anthropic Messages API en format interne.
    
    Retourne : {
        "messages": [...],     # format Chat Completions
        "tools": [...],        # format Chat Completions
        "system": "...",       # system prompt extrait
        "stream": bool,
        "max_tokens": int,
        "temperature": float,
        "top_p": float,
        "thinking": {...},     # préservé pour le pass-through
    }
    """
```

Étapes de traduction :
1. Extraire `system` → `messages[0] = {role: "system", content: ...}`
2. Parcourir `messages[]` :
   - `role: "user"` + `content` string → `{role: "user", content: ...}`
   - `role: "user"` + `content[{type: "tool_result", ...}]` → `{role: "tool", tool_call_id: ..., content: ...}`
   - `role: "assistant"` + `content[{type: "text", ...}]` → `{role: "assistant", content: ...}`
   - `role: "assistant"` + `content[{type: "tool_use", ...}]` → `{role: "assistant", tool_calls: [...]}`
   - `role: "assistant"` + `content[{type: "thinking", ...}]` → préservé pour pass-through
3. Traduire `tools[]` : `{name, description, input_schema}` → `{type: "function", function: {name, description, parameters}}`
4. Extraire `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`

### 1b. Handler POST /v1/messages

```python
# Dans handler.py

def do_POST(self):
    if self.path in ("/responses", "/v1/responses"):
        self._handle_responses()  # existant
    elif self.path == "/v1/messages":
        self._handle_anthropic()  # nouveau
    elif self.path == "/v1/fim/completions":
        self._handle_fim()        # nouveau (phase 6)
    else:
        self.send_error(404)

def _handle_anthropic(self):
    # 1. Parse requête Anthropic → format interne
    # 2. Déterminer stratégie (pass-through ou traduction)
    # 3. Router vers le backend
    # 4. Parse réponse → format Anthropic
    # 5. Si stream: SSE Anthropic, sinon JSON
```

### 1c. GET /v1/models

```python
# server/models_handler.py

def handle_models():
    """
    Retourne la liste des modèles disponibles au format Anthropic.
    
    Réponse :
    {
      "data": [
        {"id": "deepseek-v4-pro", "object": "model", ...},
        {"id": "deepseek-v4-flash", "object": "model", ...},
      ]
    }
    """
```

---

## Phase 2 : Pass-through Anthropic

**Objectif** : Forwarder les requêtes Anthropic vers DeepSeek `/anthropic` sans traduction.

**Fichiers** :
- `translators/anthropic_pass.py` (NOUVEAU)
- `server/sse_anthropic.py` (NOUVEAU)

### Pass-through translator

```python
class AnthropicPassThroughTranslator(AbstractTranslator):
    """
    Forwarde les requêtes Anthropic vers un backend qui parle Anthropic nativement.
    Utilisé pour DeepSeek /anthropic.
    """
    
    @property
    def base_url(self) -> str:
        return "https://api.deepseek.com/anthropic"
    
    def build_request(self, original_request: dict) -> dict:
        # Passe la requête telle quelle (ou avec modifications mineures)
        return original_request
    
    def forward_anthropic(self, payload: bytes) -> bytes:
        # POST vers le backend Anthropic
        ...
    
    def parse_response(self, raw_body: bytes, req_id: str) -> ParsedResponse:
        # Parse la réponse Anthropic → format interne
        ...
```

### Streaming Anthropic SSE

```python
# server/sse_anthropic.py

def stream_anthropic_response(raw_stream, wfile):
    """
    Lit le stream SSE du backend Anthropic et le forwarde vers le client.
    Version simple : relay pur des événements SSE.
    Version enrichie : interception + modification des événements.
    """
```

---

## Phase 3 : Traduction Anthropic ↔ Chat Completions

**Objectif** : Traduire les requêtes Anthropic en Chat Completions (pour OpenCode Go Chat).

**Fichiers** :
- `translators/anthropic_to_chat.py` (NOUVEAU)

### Requête : Anthropic → Chat

```
Anthropic                              Chat Completions
─────────────────────────────────────────────────────────
system: "..."                          messages[0]: {role:"system", content:"..."}
messages[n].role: "user"              messages[n].role: "user"
messages[n].content: "text"           messages[n].content: "text"
messages[n].content: [{type:"text"}]  messages[n].content: block.text
messages[n].content: [{type:"tool_use"}]  messages[n].role: "assistant"
                                           messages[n].tool_calls: [{id, function:{name, arguments: json.dumps(input)}}]
messages[n].content: [{type:"tool_result"}]  messages[n].role: "tool"
                                              messages[n].tool_call_id: block.tool_use_id
                                              messages[n].content: block.content
tools: [{name, input_schema}]         tools: [{type:"function", function:{name, parameters: input_schema}}]
tool_choice: {type:"auto"}            tool_choice: "auto"
thinking: {type:"enabled"}            thinking: {type:"enabled"} (si supporté)
                                       ou reasoning_effort: "high" (DeepSeek)
max_tokens: N                         max_tokens: N
```

### Réponse : Chat → Anthropic

```
Chat Completions                       Anthropic
─────────────────────────────────────────────────────────
choices[0].message.content             content: [{type:"text", text: ...}]
choices[0].message.tool_calls[]        content: [{type:"tool_use", id, name, input}]
choices[0].message.reasoning_content   content: [{type:"thinking", thinking: ..., signature: ...}]
usage.prompt_tokens                    usage.input_tokens
usage.completion_tokens                usage.output_tokens
```

### Points d'attention

1. **Thinking** : DeepSeek Chat renvoie le reasoning dans `reasoning_content`. Il faut le wrapper dans un bloc `thinking` Anthropic avec une signature factice.
2. **Streaming** : Le streaming Chat (delta chunks) doit être converti en streaming Anthropic (named events). C'est le plus complexe.
3. **Tool calls** : Les `tool_calls` Chat sont dans un champ séparé, il faut les réintégrer dans le `content[]` Anthropic.
4. **Stop reason** : `finish_reason: "stop"` → `stop_reason: "end_turn"`, `finish_reason: "tool_calls"` → `stop_reason: "tool_use"`

---

## Phase 4 : Routing Engine

**Objectif** : Sélectionner le bon backend selon la config et la disponibilité.

**Fichiers** :
- `routing/engine.py` (NOUVEAU)
- `routing/fallback.py` (NOUVEAU)
- `routing/circuit_breaker.py` (NOUVEAU)
- `routing/rate_limiter.py` (NOUVEAU)

### Routing engine

```python
class RoutingEngine:
    def __init__(self, primary: Translator, fallback_chain: list[Translator]):
        self.primary = primary
        self.fallback_chain = fallback_chain
        self.circuit_breakers = {}
    
    def route(self, request: dict, protocol: str) -> ParsedResponse:
        """Route la requête vers le backend approprié."""
        # 1. Essayer le backend primaire
        # 2. Si échec, essayer la chaîne de fallback
        # 3. Circuit breaker par backend
        # 4. Retry avec backoff
```

### Circuit breaker

```python
class CircuitBreaker:
    STATE_CLOSED = "closed"       # fonctionne normalement
    STATE_OPEN = "open"           # bloqué, refuse les appels
    STATE_HALF_OPEN = "half_open" # teste si le backend est revenu
    
    def __init__(self, failure_threshold=5, reset_timeout=30):
        ...
```

### Fallback chain

```python
FALLBACK_CHAINS = {
    "deepseek": [
        {"provider": "deepseek", "protocol": "anthropic_messages", "timeout": 30},
        {"provider": "deepseek", "protocol": "chat_completions", "timeout": 20},
        {"provider": "opencode", "protocol": "chat_completions", "timeout": 45},
    ],
}
```

---

## Phase 5 : CLI & Wizard

**Objectif** : Mettre à jour l'interface CLI pour le multi-provider.

**Fichiers** :
- `cli/config_manager.py` (MODIFIÉ)
- `cli/wizard.py` (MODIFIÉ)
- `cli/commands.py` (MODIFIÉ)
- `cli/claude_writer.py` (NOUVEAU)

### Nouveau wizard

```
╔══════════════════════════════════╗
║      llm-relay  v0.2  setup      ║
╚══════════════════════════════════╝

  Primary provider (deepseek/opencode) [deepseek]: 
  DeepSeek API key [current ends in …abcd]: 
  Fallback provider (none/deepseek/opencode) [none]: opencode
  OpenCode Go API key: 
  Port [8080]: 

  ✓ Config saved         → ~/.llm-relay/config.json
  ✓ Codex config updated → ~/.codex/config.toml
  ✓ .env written         → ~/.llm-relay/.env

  ── Claude Desktop 3P configuration ──
  To use with Claude Desktop in gateway mode:
    1. Open Claude Desktop → Developer → Configure third-party inference
    2. Set inferenceProvider: gateway
    3. Set inferenceGatewayBaseUrl: https://127.0.0.1:8080
    4. Set inferenceGatewayApiKey: (any value, proxy handles auth)
    5. Apply and relaunch

  ── Claude Code configuration ──
  export ANTHROPIC_BASE_URL=http://127.0.0.1:8080
  export ANTHROPIC_AUTH_TOKEN=any-value
  
  Next steps:
    1. Reload your shell: source ~/.zshrc
    2. Start the proxy:    llm-relay start
```

### Banner mis à jour

```
  ✓ Proxy running  →  http://127.0.0.1:8080
  ✓ Backend        →  DeepSeek (primary)
  ✓ Fallback       →  OpenCode Go

  Endpoints:
    http://127.0.0.1:8080/responses       (Codex CLI)
    http://127.0.0.1:8080/v1/responses    (Codex CLI)
    http://127.0.0.1:8080/v1/messages     (Claude Code, Claude Desktop)
    http://127.0.0.1:8080/v1/models       (auto-discovery)

  Press Ctrl+C to stop.
```

---

## Phase 6 : FIM (Fill-in-the-Middle)

**Objectif** : Supporter le mode complétion pour les plugins Copilot.

**Fichiers** :
- `server/handler.py` (MODIFIÉ — ajout `POST /v1/fim/completions`)

### Stratégie

```
Si le backend supporte FIM (DeepSeek) :
  → Pass-through vers /v1/fim/completions

Sinon (OpenCode Go, autres) :
  → Transformation FIM → Chat :
    system_prompt = "Complete le code entre <prefix> et <suffix>"
    user_message = f"<prefix>{prefix}</prefix>\n<suffix>{suffix}</suffix>"
```

---

## Phase 7 : HTTPS/TLS

**Objectif** : Supporter HTTPS pour la compatibilité Claude Desktop 3P.

**Fichiers** :
- `server/app.py` (MODIFIÉ) — option TLS
- `server/tls.py` (NOUVEAU) — génération certificat auto-signé

### Implémentation

```python
# server/tls.py
def generate_self_signed_cert():
    """Génère un certificat auto-signé pour 127.0.0.1."""
    from cryptography import x509
    # ou utiliser openssl en subprocess
    ...

# server/app.py
def create_server(config: Config) -> HTTPServer:
    if config.tls:
        cert_path, key_path = ensure_certificate()
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert_path, key_path)
        # wrapper TLS autour du socket
    ...
```

### Solution de fallback si pas de HTTPS natif

Documenter l'utilisation de Caddy comme reverse proxy TLS local :
```bash
caddy reverse-proxy --from https://127.0.0.1:8443 --to http://127.0.0.1:8080
```

---

## Phase 8 : Context Injection

**Objectif** : Enrichir les requêtes avec le contexte du projet.

**Fichiers** :
- `context/injector.py` (NOUVEAU)
- `session/store.py` (MODIFIÉ)

### Exemple d'injection

```
SYSTEM PROMPT ORIGINAL :
  "You are an AI coding assistant..."

SYSTEM PROMPT ENRICHI :
  """
  # PROJECT CONTEXT (injected by llm-relay)
  Project root: /Users/alice/my-app
  Git branch: feature/new-auth
  File tree:
    src/
    ├── auth.ts          (234 lines)
    ├── middleware.ts    (89 lines)
    └── types.ts         (45 lines)
  package.json: typescript@5.4, express@4.19
  
  # ORIGINAL SYSTEM PROMPT
  You are an AI coding assistant...
  """
```

---

## Phase 9 : Tests

**Objectif** : Couvrir tout le nouveau code.

| Classe de test | Fichier | Nombre estimé |
|----------------|---------|---------------|
| Anthropic parser | `test_anthropic_messages.py` | ~15 |
| Anthropic SSE streaming | `test_anthropic_streaming.py` | ~10 |
| Traduction Anthropic↔Chat | `test_translators.py` (étendu) | ~15 |
| Routing engine | `test_routing.py` | ~10 |
| Circuit breaker | `test_routing.py` | ~5 |
| Fallback chain | `test_routing.py` | ~5 |
| FIM handler | `test_fim.py` | ~8 |
| Context injection | `test_parsers.py` (étendu) | ~5 |
| Config multi-provider | `test_translators.py` (étendu) | ~5 |

---

## Ordre d'exécution

```
Phase 0 (refactor) ──→ Phase 1 (northbound) ──→ Phase 2 (pass-through)
                                                    │
                                                    ▼
                                              Phase 3 (traduction)
                                                    │
                                                    ▼
                                              Phase 4 (routing)
                                                    │
                                        ┌───────────┼───────────┐
                                        ▼           ▼           ▼
                                  Phase 5 (CLI) Phase 6 (FIM) Phase 7 (TLS)
                                        │           │           │
                                        └───────────┼───────────┘
                                                    ▼
                                              Phase 8 (context)
                                                    │
                                                    ▼
                                              Phase 9 (tests)

Les phases 5, 6, 7 sont indépendantes et peuvent être faites en parallèle après la phase 4.

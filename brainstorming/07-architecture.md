# 07 — Architecture cible

## Diagramme global

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          llm-relay v0.2                                  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    HTTP SERVER (port 8080)                        │   │
│  │                                                                    │   │
│  │  GET  /health          →  {"status": "ok"}                        │   │
│  │  GET  /v1/models       →  Liste des modèles (Anthropic format)   │   │
│  │  POST /responses       →  Handler Responses API                  │   │
│  │  POST /v1/responses    →  (alias)                                 │   │
│  │  POST /v1/messages     →  Handler Anthropic Messages API         │   │
│  │  POST /v1/fim/*        →  Handler FIM                             │   │
│  └──────────────────────────────┬───────────────────────────────────┘   │
│                                 │                                        │
│  ┌──────────────────────────────▼───────────────────────────────────┐   │
│  │                      REQUEST DISPATCHER                           │   │
│  │                                                                    │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐          │   │
│  │  │ Responses    │   │ Anthropic    │   │ FIM          │          │   │
│  │  │ Parser       │   │ Parser       │   │ Parser       │          │   │
│  │  │ messages.py  │   │ anthropic_   │   │ fim_parser   │          │   │
│  │  │              │   │ messages.py  │   │              │          │   │
│  │  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘          │   │
│  │         │                  │                  │                   │   │
│  │         └──────────────────┼──────────────────┘                   │   │
│  │                            │                                      │   │
│  │                   FORMAT INTERNE                                  │   │
│  │              {messages[], tools[], params}                        │   │
│  └────────────────────────────┬──────────────────────────────────────┘   │
│                               │                                          │
│  ┌────────────────────────────▼──────────────────────────────────────┐   │
│  │                      ROUTING ENGINE                                │   │
│  │                                                                    │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐          │   │
│  │  │ Rate Limiter │──→│ Circuit Brkr │──→│ Fallback     │          │   │
│  │  │ (token       │   │ (par backend)│   │ Chain        │          │   │
│  │  │  bucket)     │   │              │   │              │          │   │
│  │  └──────────────┘   └──────────────┘   └──────┬───────┘          │   │
│  │                                               │                   │   │
│  │                    Backend sélectionné         │                   │   │
│  └───────────────────────────────────────────────┬───────────────────┘   │
│                                                  │                       │
│  ┌───────────────────────────────────────────────▼───────────────────┐   │
│  │                    SOUTHBOUND TRANSLATORS                          │   │
│  │                                                                    │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐        │   │
│  │  │ Chat           │ │ Anthropic      │ │ FIM            │        │   │
│  │  │ Completions    │ │ Pass-through   │ │ Translator     │        │   │
│  │  │ Translator     │ │ Translator     │ │                │        │   │
│  │  │                │ │                │ │                │        │   │
│  │  │ DeepSeek Chat  │ │ DeepSeek       │ │ DeepSeek FIM   │        │   │
│  │  │ OpenCode Go    │ │ /anthropic     │ │                │        │   │
│  │  │ Generic        │ │ OpenCode Go    │ │                │        │   │
│  │  └────────────────┘ └────────────────┘ └────────────────┘        │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    CROSS-CUTTING CONCERNS                         │   │
│  │                                                                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │   │
│  │  │ Context    │  │ Session    │  │ Post-      │  │ Debug      │ │   │
│  │  │ Injector   │  │ Store      │  │ Processor  │  │ Logger     │ │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Flux d'une requête Anthropic (Claude Code → DeepSeek /anthropic)

```
ÉTAPE 1 : RÉCEPTION
─────────────────────────────────────────────────────────────
Client (Claude Code) envoie :
  POST /v1/messages
  {
    "model": "claude-sonnet-4-6",
    "max_tokens": 4096,
    "system": "You are a coding assistant...",
    "messages": [
      {"role": "user", "content": "Fix the bug in auth.ts"}
    ],
    "tools": [
      {"name": "bash", "input_schema": {...}},
      {"name": "read", "input_schema": {...}}
    ],
    "thinking": {"type": "enabled", "budget_tokens": 2000}
  }

ÉTAPE 2 : PARSING (parsers/anthropic_messages.py)
─────────────────────────────────────────────────────────────
→ anthropic_to_messages(request)
→ Format interne :
  {
    "messages": [
      {"role": "system", "content": "You are a coding assistant..."},
      {"role": "user", "content": "Fix the bug in auth.ts"}
    ],
    "tools": [
      {"type": "function", "function": {"name": "bash", "parameters": {...}}},
      {"type": "function", "function": {"name": "read", "parameters": {...}}}
    ],
    "stream": false,
    "max_tokens": 4096,
    "thinking": {"type": "enabled", "budget_tokens": 2000},
    "_original_anthropic": {...}  // préservé pour pass-through
  }

ÉTAPE 3 : ROUTING (routing/engine.py)
─────────────────────────────────────────────────────────────
→ Backend primaire = deepseek, protocole = anthropic_messages
→ Le backend parle Anthropic nativement → stratégie = PASS_THROUGH
→ Circuit breaker : closed → OK
→ Rate limiter : token disponible → OK

ÉTAPE 4 : FORWARDING (translators/anthropic_pass.py)
─────────────────────────────────────────────────────────────
→ POST https://api.deepseek.com/anthropic/v1/messages
→ Body : la requête Anthropic originale (presque inchangée)
→ Auth : Bearer <DEEPSEEK_API_KEY>
→ Streaming : activé si demandé par le client

ÉTAPE 5 : RÉPONSE
─────────────────────────────────────────────────────────────
← DeepSeek répond en Anthropic Messages format
→ Parse la réponse
→ Si streaming : relay des événements SSE
→ Si non-streaming : parse → forward JSON

ÉTAPE 6 : POST-PROCESSING
─────────────────────────────────────────────────────────────
→ Sauvegarde session
→ Logging
→ Réponse forwardée au client (Claude Code)
```

---

## Flux d'une requête Anthropic (Claude Code → OpenCode Go Chat)

```
ÉTAPES 1-2 : Identiques (réception + parsing)

ÉTAPE 3 : ROUTING
─────────────────────────────────────────────────────────────
→ Backend = opencode, protocole = chat_completions
→ Le backend parle Chat Completions → stratégie = TRANSLATION
→ Si primary (DeepSeek) est down, routing via fallback chain

ÉTAPE 4 : TRADUCTION (translators/anthropic_to_chat.py)
─────────────────────────────────────────────────────────────
→ anthropic_request_to_chat(request_interne)
→ Transforme :
    system: "You are a coding assistant..."
    → messages[0] = {role: "system", content: "You are a coding assistant..."}
    
    messages: [{role: "user", content: "Fix the bug"}]
    → messages: [{role: "user", content: "Fix the bug"}]
    
    tools: [{name: "bash", input_schema: {...}}]
    → tools: [{type: "function", function: {name: "bash", parameters: {...}}}]
    
    thinking: {type: "enabled", budget_tokens: 2000}
    → thinking: {type: "enabled"} (si supporté) ou reasoning_effort: "high"

→ POST https://opencode.ai/zen/go/v1/chat/completions

ÉTAPE 5 : RÉPONSE + TRADUCTION INVERSE
─────────────────────────────────────────────────────────────
← OpenCode Go répond en Chat Completions
→ chat_response_to_anthropic(response)
→ Transforme :
    choices[0].message.content
    → content: [{type: "text", text: "..."}]
    
    choices[0].message.tool_calls[]
    → content: [{type: "tool_use", id, name, input: JSON.parse(args)}]
    
    usage.prompt_tokens → usage.input_tokens
    usage.completion_tokens → usage.output_tokens

→ Si streaming : chat_sse_to_anthropic_sse(stream)
    Les delta chunks Chat sont convertis en événements Anthropic SSE
```

---

## Flux d'une requête Responses (Codex CLI → DeepSeek Chat)

```
Ce chemin est inchangé par rapport à v0.1.

ÉTAPE 1 : POST /responses
ÉTAPE 2 : input_to_messages() (parsers/messages.py)
ÉTAPE 3 : translate_tools()
ÉTAPE 4 : DeepSeekTranslator.build_request()
ÉTAPE 5 : forward → https://api.deepseek.com/v1/chat/completions
ÉTAPE 6 : parse_response() → Responses API format
ÉTAPE 7 : SSE simulé si stream=true
```

---

## Structure du format interne

Le format interne est la représentation canonique utilisée entre le parsing northbound et le forwarding southbound.

```python
@dataclass
class InternalRequest:
    """Requête normalisée, indépendante du protocole d'origine."""
    messages: list[dict]          # Format Chat Completions
    tools: list[dict] | None      # Format Chat Completions
    stream: bool
    max_tokens: int
    temperature: float | None
    top_p: float | None
    stop_sequences: list[str] | None
    tool_choice: str | dict | None
    
    # Préservé pour pass-through (non modifié par la traduction)
    original_request: dict | None  # Requête originale Anthropic (si applicable)
    original_protocol: str         # "anthropic" | "responses" | "fim"
    thinking_config: dict | None   # Config thinking Anthropic
    model_requested: str           # Modèle demandé par le client
    
    # Métadonnées de session
    session_id: str | None
    working_dir: str | None
```

---

## Stratégie de décision du translator

```python
def select_translator(protocol: str, backend: str) -> Translator:
    """
    Sélectionne le translator approprié selon le protocole client
    et les capacités du backend.
    """
    backend_caps = PROVIDERS[backend]["protocols"]
    
    if protocol == "anthropic":
        if "anthropic_messages" in backend_caps:
            return AnthropicPassThroughTranslator(backend)
        elif "chat_completions" in backend_caps:
            return AnthropicToChatTranslator(backend)
        else:
            raise UnsupportedProtocolError(backend, protocol)
    
    elif protocol == "responses":
        if "chat_completions" in backend_caps:
            return ChatCompletionsTranslator(backend)
        else:
            raise UnsupportedProtocolError(backend, protocol)
    
    elif protocol == "fim":
        if "fim" in backend_caps:
            return FimPassThroughTranslator(backend)
        elif "chat_completions" in backend_caps:
            return FimToChatTranslator(backend)
        else:
            raise UnsupportedProtocolError(backend, protocol)
```

---

## Gestion du streaming Anthropic → Chat → Anthropic

C'est la partie la plus complexe. Le flux :

```
Client (Claude Code)     llm-relay              Backend (DeepSeek Chat)
─────────────────────────────────────────────────────────────────────
stream=true              traduit Anthropic→Chat  ne supporte pas
                         stream Anthropic
                                                  ↓
                         désactive stream         stream=false
                         pour le backend
                                                  ↓
                         reçoit réponse complète  réponse complète
                                                  ↓
                         simule SSE Anthropic     
                         depuis la réponse Chat   
                                                  ↓
envoie événements SSE    ←──────────────────────
(event: message_start,
 event: content_block_*,
 event: message_delta,
 event: message_stop)
```

Quand le backend supporte le streaming (ex: DeepSeek /anthropic), c'est du pur relay SSE :

```
Client (Claude Code)     llm-relay              Backend (DeepSeek /anthropic)
─────────────────────────────────────────────────────────────────────────────
stream=true              forward                stream=true
                         ↓                      ↓
                  ┌───── relay SSE ─────┐
                  │  (passe à travers)   │
                  └──────────────────────┘
                         ↓                      ↓
reçoit SSE                ←──────────────────  envoie SSE
```

---

## Contrainte HTTPS (Claude Desktop 3P)

La documentation Claude Desktop 3P exige que `inferenceGatewayBaseUrl` soit en `https://`. llm-relay écoute par défaut en HTTP sur `127.0.0.1`.

### Solutions envisagées

```
┌─────────────────────────────────────────────────────────────────────┐
│ Option A : Tester http://127.0.0.1                                  │
│   Vérifier si Claude Desktop accepte HTTP pour localhost            │
│   (la doc dit "must be https" mais une exception est possible)      │
├─────────────────────────────────────────────────────────────────────┤
│ Option B : TLS natif dans llm-relay                                 │
│   Flag --tls ou --https                                             │
│   Génération certificat auto-signé pour 127.0.0.1                   │
│   Server: HTTPServer → wrap_socket(ssl_context)                     │
│   URL: https://127.0.0.1:8443                                       │
├─────────────────────────────────────────────────────────────────────┤
│ Option C : Reverse proxy Caddy                                      │
│   caddy reverse-proxy --from https://127.0.0.1:8443 \               │
│                        --to http://127.0.0.1:8080                   │
│   Caddy génère et gère le certificat auto-signé automatiquement     │
├─────────────────────────────────────────────────────────────────────┤
│ Option D : Tunnel public (ngrok, cloudflared)                       │
│   ngrok http 8080 → https://xxx.ngrok.io                            │
│   Cloudflared tunnel → https://xxx.trycloudflare.com                │
└─────────────────────────────────────────────────────────────────────┘
```

### Recommandation

1. Test A (coût nul)
2. Si échec → B (intégré, pas de dépendance externe)
3. Documenter C comme alternative simple

---

## Gestion de session

```python
@dataclass
class AgentSession:
    """Session enrichie pour les agents de code."""
    
    # Identité
    response_id: str           # ID OpenAI (pour Codex) ou message_id (pour Anthropic)
    protocol: str              # "responses" ou "anthropic"
    
    # Historique
    messages: list[dict]       # Messages au format interne
    
    # Contexte projet (injecté)
    working_dir: str           # Répertoire de travail
    project_map: dict          # Arborescence + métadonnées
    git_branch: str | None     # Branche git active
    active_tools: set[str]     # Outils actifs dans cette session
    
    # Budget
    token_budget: int          # Tokens restants
    tool_call_count: int       # Compteur de tool calls (détection boucle)
    
    # Timestamps
    created_at: float
    last_access: float
    
    # Anthropic-specific
    thinking_blocks: list[dict] # Thinking blocks préservés (signatures)
```

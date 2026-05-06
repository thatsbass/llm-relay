# 02 — Analyse des 3 formats d'API

Ce document détaille le fonctionnement des trois formats d'API que le proxy doit gérer.

---

## 1. OpenAI Chat Completions API

**Endpoint** : `POST /v1/chat/completions`
**Docs** : https://platform.openai.com/docs/api-reference/chat/create

### Concept

Format le plus répandu. **Stateless** : chaque requête contient l'intégralité de l'historique de conversation.

### Requête type

```json
{
  "model": "deepseek-v4-pro",
  "messages": [
    {"role": "system", "content": "Tu es un assistant de codage."},
    {"role": "user", "content": "Crée un fichier hello.py"},
    {"role": "assistant", "content": null, "tool_calls": [
      {"id": "call_1", "type": "function",
       "function": {"name": "exec_command", "arguments": "{\"command\":\"touch hello.py\"}"}}
    ]},
    {"role": "tool", "tool_call_id": "call_1", "content": "Fichier créé."}
  ],
  "tools": [
    {"type": "function", "function": {
      "name": "exec_command",
      "description": "Exécute une commande shell",
      "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}
    }}
  ],
  "stream": false,
  "max_tokens": 4096,
  "temperature": 0.7
}
```

### Réponse type

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Le fichier hello.py a été créé avec succès !"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 20,
    "total_tokens": 170
  }
}
```

### Structure des tool calls

```
message.role = "assistant"
message.tool_calls = [
  {id: "call_1", type: "function", function: {name: "bash", arguments: "{...}"}}
]
```

### Structure des tool results

```
message.role = "tool"
message.tool_call_id = "call_1"
message.content = "résultat de la commande"
```

### Streaming

Format SSE standard OpenAI : `data: {json}\n\n`, terminé par `data: [DONE]`.

### Supporté par

- **DeepSeek** (natif, endpoint `/v1/chat/completions`)
- **OpenCode Go** (endpoint `/zen/go/v1/chat/completions`)
- OpenAI, Mistral, Groq, Together AI, etc.

---

## 2. Anthropic Messages API

**Endpoint** : `POST /v1/messages`
**Docs** : https://docs.anthropic.com/en/api/messages

### Concept

Format propriétaire Anthropic. **Stateless** mais avec des fonctionnalités avancées (cache, thinking, content blocks).

### Requête type

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 4096,
  "system": "Tu es un assistant de codage.",
  "messages": [
    {"role": "user", "content": "Crée un fichier hello.py"},
    {"role": "assistant", "content": [
      {"type": "tool_use", "id": "toolu_01", "name": "bash",
       "input": {"command": "touch hello.py"}}
    ]},
    {"role": "user", "content": [
      {"type": "tool_result", "tool_use_id": "toolu_01",
       "content": "Fichier créé."}
    ]}
  ],
  "tools": [
    {"name": "bash", "description": "Exécute une commande shell",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}
  ],
  "thinking": {"type": "enabled", "budget_tokens": 2000},
  "stream": true
}
```

### Points clés

1. **System prompt** : champ top-level `system` (string ou array de content blocks), PAS dans `messages[]`
2. **Content blocks** : chaque message a `content` qui est soit une string, soit un array de blocs typés (`text`, `tool_use`, `tool_result`, `thinking`, `image`, `document`)
3. **Tool use** : l'assistant répond avec des blocs `tool_use` dans `content[]`, pas dans un champ `tool_calls` séparé
4. **Tool result** : envoyé comme un message `user` contenant un bloc `tool_result`
5. **Thinking** : blocs `thinking` dans la réponse, avec `signature` cryptographique

### Réponse type

```json
{
  "id": "msg_xxx",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-4-6",
  "content": [
    {"type": "thinking", "thinking": "L'utilisateur veut créer un fichier...",
     "signature": "WaUjzkypQ2mUEVM36O2TxuC06KN8xyfbJwyem2dw3URv..."},
    {"type": "text", "text": "Le fichier hello.py a été créé avec succès !"}
  ],
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 150,
    "output_tokens": 45,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0
  }
}
```

### Structure des tool calls (dans la réponse)

```
content = [
  {type: "thinking", thinking: "...", signature: "..."},
  {type: "tool_use", id: "toolu_01", name: "bash", input: {command: "touch hello.py"}}
]
```

### Structure des tool results (dans la requête)

```
{role: "user", content: [
  {type: "tool_result", tool_use_id: "toolu_01", content: "Fichier créé."}
]}
```

### Streaming Anthropic

Format SSE avec événements nommés :

```
event: message_start
data: {"type":"message_start","message":{...}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking",...}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"..."}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"text",...}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"..."}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{...}}

event: message_stop
data: {"type":"message_stop"}
```

Événements supplémentaires : `ping` (keepalive).

### Fonctionnalités avancées

| Fonctionnalité | Description |
|----------------|-------------|
| `cache_control` | Prompt caching : cache le system prompt et l'historique entre les appels. Lectures à 10% du prix. |
| `thinking` | Extended thinking : le modèle raisonne avant de répondre. Blocs `thinking` avec `signature`. |
| `tool_choice` | `auto`, `any`, `tool`, `none` + `disable_parallel_tool_use` |
| Images | Blocs `image` (base64 ou URL) dans les messages utilisateur |
| Documents | Blocs `document` (PDF, texte) |
| Server tools | `web_search`, `code_execution`, `web_fetch` exécutés côté Anthropic |
| Beta headers | `anthropic-beta: ...` pour activer des features en preview |
| Context awareness | Le modèle reçoit des balises `<budget:token_budget>` pour connaître l'espace restant |

### Claude Desktop 3P Gateway — clés de connexion

Quand Claude Desktop est configuré en mode 3P avec `inferenceProvider: "gateway"`, il envoie des requêtes Anthropic Messages API à l'URL configurée. Les clés obligatoires :

| Clé | Requis | Description |
|-----|--------|-------------|
| `inferenceProvider` | OUI | `"gateway"` (parmi `gateway`, `vertex`, `bedrock`, `foundry`) |
| `inferenceGatewayBaseUrl` | OUI | URL du gateway. **⚠️ Doit être `https://`** |
| `inferenceGatewayApiKey` | OUI* | Clé API (ou placeholder ; le proxy peut l'ignorer) |
| `inferenceGatewayAuthScheme` | NON | `"bearer"` (défaut, envoie `Authorization: Bearer <key>`) ou `"x-api-key"` |

\* Sauf si `inferenceGatewayAuthScheme: "sso"` ou `inferenceCredentialHelper` configuré.

**Auto-discovery des modèles** : si `inferenceModels` n'est pas défini dans la config 3P, Claude Desktop appelle `GET /v1/models` sur le gateway pour découvrir les modèles disponibles. Le proxy doit donc implémenter cet endpoint.

### Supporté par

- Anthropic (natif)
- **DeepSeek** (compatible via `/anthropic`, voir `03-gap-analysis.md`)
- OpenCode Go (partiel, uniquement pour les modèles MiniMax)
- **Claude Desktop en mode 3P gateway** (envoie des requêtes Anthropic Messages API)

---

## 3. OpenAI Responses API

**Endpoint** : `POST /v1/responses`
**Docs** : https://platform.openai.com/docs/api-reference/responses

### Concept

Format **stateful** conçu pour les agents. Le serveur garde l'historique de conversation. L'agent envoie seulement les nouveaux événements.

### Requête type

```json
{
  "model": "gpt-5",
  "instructions": "Tu es un assistant de codage.",
  "input": [
    {"type": "message", "role": "user", "content": "Crée un fichier"},
    {"type": "function_call", "call_id": "abc", "name": "exec_command",
     "arguments": "{\"command\":\"touch hello.py\"}"},
    {"type": "function_call_output", "call_id": "abc", "output": "OK"}
  ],
  "previous_response_id": "resp_123",
  "tools": [
    {"type": "function", "name": "exec_command",
     "description": "Exécute une commande shell",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}
  ],
  "stream": true
}
```

### Points clés

1. **Stateful** : `previous_response_id` remplace l'envoi de tout l'historique. Le serveur se souvient.
2. **Instructions** : champ top-level (équivalent du system prompt)
3. **Input items** : un array de typed items (pas de messages avec role/content simples)
4. **Types d'items** : `message`, `function_call`, `function_call_output`, `reasoning`, `item_reference`, `computer_call`
5. **Built-in tools** : `web_search`, `file_search`, `code_interpreter` (outils natifs OpenAI)

### Réponse type

```json
{
  "id": "resp_456",
  "object": "response",
  "status": "completed",
  "model": "gpt-5",
  "output": [
    {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
     "content": [{"type": "output_text", "text": "Fichier créé !", "annotations": []}]}
  ],
  "parallel_tool_calls": true,
  "usage": {
    "input_tokens": 80,
    "output_tokens": 15,
    "total_tokens": 95,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 0}
  }
}
```

### Structure des items

```
input = [
  {type: "message", role: "user", content: "..."},
  {type: "function_call", call_id: "abc", name: "exec_command", arguments: "{...}"},
  {type: "function_call_output", call_id: "abc", output: "résultat"},
  {type: "reasoning", summary: [{type: "summary_text", text: "..."}]},
  {type: "item_reference", id: "msg_1"}
]

output = [
  {type: "message", role: "assistant", content: [{type: "output_text", text: "..."}]},
  {type: "function_call", call_id: "xyz", name: "exec_command", arguments: "{...}"}
]
```

### Streaming

Format SSE avec événements spécifiques :

```
event: response.created
event: response.output_item.added
event: response.content_part.added
event: response.output_text.delta
event: response.output_text.done
event: response.content_part.done
event: response.function_call_arguments.delta
event: response.function_call_arguments.done
event: response.output_item.done
event: response.completed
```

### Fonctionnalités uniques (absentes de Chat Completions)

| Fonctionnalité | Description |
|----------------|-------------|
| Stateful | Le serveur gère l'historique via `previous_response_id` |
| Built-in tools | `web_search`, `file_search`, `code_interpreter` exécutés par OpenAI |
| Reasoning items | Tours de raisonnement dédiés dans la conversation |
| Item references | Références à des items précédents par ID |
| Truncation | Gestion automatique du context window |
| Computer use | Contrôle d'interface graphique (type `computer_call`) |

### Supporté par

- OpenAI (natif)
- Personne d'autre — ce format est propriétaire et **n'est implémenté par aucun autre fournisseur**

---

## Tableau comparatif synthétique

```
┌────────────────────┬──────────────────┬──────────────────┬──────────────────┐
│                    │ CHAT COMPLETIONS │ ANTHROPIC MSGS   │ RESPONSES API    │
├────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Créé par           │ OpenAI           │ Anthropic        │ OpenAI           │
│ Standard ouvert    │ De facto         │ Non              │ Non              │
│ Stateful           │ Non              │ Non              │ OUI              │
│ System prompt      │ messages[0]      │ Champ top-level  │ Champ top-level  │
│                    │ role:"system"    │ "system"         │ "instructions"   │
│ Messages           │ messages[]       │ messages[]       │ input[]          │
│                    │ (role+content)   │ (role+content)   │ (typed items)    │
│ Tool calls         │ message.         │ content[{        │ input[{          │
│                    │ tool_calls[]     │  type:"tool_use" │  type:           │
│                    │                  │ }]               │  function_call}] │
│ Tool results       │ role:"tool"      │ content[{        │ input[{          │
│                    │ + tool_call_id   │  type:           │  type:function_  │
│                    │                  │  tool_result}]   │  call_output}]   │
│ Thinking           │ reasoning_content│ content[{        │ output[{         │
│                    │ (propriétaire)   │  type:"thinking" │  type:reasoning}]│
│                    │                  │  + signature]    │                  │
│ Streaming          │ SSE delta        │ SSE named events │ SSE named events │
│ Prompt caching     │ Non standard     │ cache_control    │ Non              │
│ Images             │ OUI (vision)     │ OUI              │ Non              │
│ Documents          │ Non              │ OUI (PDF)        │ Non              │
│ Supporté par       │ Tout le monde    │ Anthropic        │ OpenAI seulement │
│                    │ (DeepSeek, etc.) │ DeepSeek (partiel│                  │
│                    │                  │ via /anthropic)  │                  │
└────────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

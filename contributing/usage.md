# llm-relay v0.2 — Guide d'utilisation

## Ce qui a changé depuis la v0.1

La v0.1 ne supportait qu'un seul chemin : **Codex CLI → OpenAI Responses API → DeepSeek Chat Completions**.

La v0.2 transforme llm-relay en **routeur multi-protocole**. Le proxy accepte désormais deux formats d'API en entrée et peut router vers trois types de backends :

```
AVANT (v0.1) :
  Codex CLI ──Responses API──→ llm-relay ──Chat Completions──→ DeepSeek

APRÈS (v0.2) :
  Codex CLI ──Responses API──→ llm-relay ──┬── Chat Completions ──→ DeepSeek
                                            ├── Anthropic API ────→ DeepSeek /anthropic
                                            └── Chat Completions ──→ OpenCode Go

  Claude Code ──Anthropic API──→ llm-relay ─┤ (mêmes backends)
  Claude Desktop ──Anthropic API─→          │
```

### Nouveautés

| Fonctionnalité | Statut v0.1 | Statut v0.2 |
|---------------|-------------|-------------|
| Support Claude Code | ❌ | ✅ via `POST /v1/messages` |
| Support Claude Desktop 3P | ❌ | ✅ mode gateway |
| Auto-discovery modèles | ❌ | ✅ `GET /v1/models` |
| DeepSeek Anthropic API | ❌ | ✅ pass-through `/anthropic` |
| OpenCode Go | ❌ | ✅ nouveau backend |
| Fallback automatique | ❌ | ✅ circuit breaker + retry |
| TLS/HTTPS | ❌ | ✅ certificat auto-signé |
| Multi-provider wizard | ❌ | ✅ fallback configurable |

---

## Démarrage rapide

### 1. Installation (inchangée)

```bash
# Première installation
curl -fsSL https://raw.githubusercontent.com/thatsbass/llm-relay/main/install.sh | bash

# Ou mise à jour depuis une version existante
llm-relay update
```

### 2. Setup interactif

```bash
llm-relay setup
```

Le wizard demande :
- Port
- Provider (deepseek, deepseek-anthropic, opencode)
- API key
- Fallback (optionnel)

**Tout est automatique** : le setup écrit la config Codex CLI, le fichier d'environnement Claude Code, et la config Claude Desktop 3P.

### 3. Démarrer en tâche de fond (daemon)

```bash
llm-relay start --daemon
llm-relay start --daemon --tls --port 8443   # avec HTTPS
```

```
  ✓ Proxy started (daemon) → PID 12345
  ✓ Listening on https://127.0.0.1:8443
  ✓ Backend: DeepSeek
  ✓ Logs: llm-relay logs -f
```

Le proxy tourne en arrière-plan. Pour l'arrêter : `llm-relay stop`.

### 4. Logs

```bash
llm-relay logs               # 20 dernières lignes
llm-relay logs -n 100         # 100 lignes
llm-relay logs -f             # suivre en direct (Ctrl+C pour quitter)
```

Fichier : `~/.llm-relay/proxy.log`

### 5. État

```bash
llm-relay status
```

```
  ✓ Status    : running  (PID 12345)
  ✓ Provider  : DeepSeek
  ✓ Port      : 8443
  ✓ URL       : https://127.0.0.1:8443
  ✓ API key   : …abcd
```

---

## Switching de backend

```bash
# Voir les backends disponibles
llm-relay backend list

# Changer de backend (met à jour toutes les configs automatiquement)
llm-relay config backend deepseek-anthropic
llm-relay config backend opencode

# Si le proxy tourne, le redémarrer pour appliquer
llm-relay stop && llm-relay start --daemon
```

---

## Utilisation avec Claude Code CLI

### Via le proxy (mode par défaut)

```bash
llm-relay claude proxy
source ~/.llm-relay/claude-code.env
claude
```

Le proxy route vers le backend configuré (DeepSeek, OpenCode Go, etc.).

### Directement vers ton abonnement Anthropic

```bash
llm-relay claude direct
# → demande ta clé API Anthropic
source ~/.llm-relay/claude-code.env
claude
```

### Fichier d'environnement généré

`~/.llm-relay/claude-code.env` contient toutes les variables nécessaires :

```bash
export ANTHROPIC_BASE_URL="https://127.0.0.1:8443"
export ANTHROPIC_AUTH_TOKEN="llm-relay"
export ANTHROPIC_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_EFFORT_LEVEL="max"
```

Le fichier est sourcé automatiquement dans ton shell profile (`.zshrc`/`.bashrc`) lors du `llm-relay setup`.

---

## Utilisation avec Claude Desktop en mode 3P

Le `llm-relay setup` écrit automatiquement la config dans :

```
~/Library/Application Support/Claude-3p/configLibrary/<id>.json
```

Si tu as besoin de la regénérer :

```bash
llm-relay config backend deepseek-anthropic    # regénère le fichier 3P
```

Puis quitter et relancer Claude Desktop. L'écran de connexion affiche :
- **"Continuer avec Passerelle"** → Claude Desktop + llm-relay (DeepSeek)
- **"Se connecter à Anthropic"** → Claude Desktop standard

### Si le sélecteur de modèles n'affiche pas DeepSeek

Quitter complètement Claude Desktop (⌘Q) et relancer. La config `inferenceModels` force l'affichage des modèles DeepSeek.

---

## Résumé des commandes

| Commande | Action |
|----------|--------|
| `llm-relay start --daemon` | Démarrer en arrière-plan |
| `llm-relay stop` | Arrêter |
| `llm-relay status` | État du proxy |
| `llm-relay logs [-f]` | Voir les logs |
| `llm-relay setup` | Reconfigurer |
| `llm-relay config port N` | Changer le port |
| `llm-relay config key sk-xxx` | Changer la clé API |
| `llm-relay config backend <name>` | Changer de provider |
| `llm-relay backend list` | Lister les providers |
| `llm-relay claude proxy` | Claude Code → proxy |
| `llm-relay claude direct` | Claude Code → Anthropic |
| `llm-relay trust-ca` | Installer le certificat HTTPS |
| `llm-relay update` | Mettre à jour |

### Étape 1 : Configurer le proxy

S'assurer que le proxy tourne (HTTP ou HTTPS).

### Étape 2 : Activer le mode développeur dans Claude Desktop

1. Lancer Claude Desktop — **ne pas se connecter**
2. macOS : **Help → Troubleshooting → Enable Developer Mode**
3. Windows : **☰ → Help → Troubleshooting → Enable Developer Mode**

### Étape 3 : Configurer le gateway 3P

1. Aller dans **Developer → Configure third-party inference**
2. Onglet **Connection** :
   - **Inference provider** : `Gateway`
   - **Gateway base URL** : `https://127.0.0.1:8080` (ou `http://127.0.0.1:8080` si accepté)
   - **API key** : n'importe quelle valeur (le proxy gère l'auth)
   - **Auth scheme** : `bearer`
3. Cliquer **Apply locally** → l'appli redémarre

### Étape 4 : Choisir le mode au lancement

L'écran de connexion affiche deux options :
- **"Continuer avec Passerelle"** → Claude Desktop utilise ton proxy → DeepSeek / OpenCode Go
- **"Se connecter à Anthropic"** → Claude Desktop standard avec ton abonnement Anthropic

### Dépannage

Si l'écran de choix n'apparaît pas (forcer le mode 3P) :

```bash
# Éditer le fichier de config 3P
# macOS : ~/Library/Application Support/Claude-3p/configLibrary/<id>.json
# Windows : %LOCALAPPDATA%\Claude-3p\configLibrary\<id>.json

# Changer :
"disableDeploymentModeChooser": true   →   "disableDeploymentModeChooser": false
```

Puis quitter et relancer Claude Desktop.

---

## Endpoints de l'API

### `GET /health`

```bash
curl http://127.0.0.1:8080/health
# → {"status": "ok"}
```

### `GET /v1/models`

```bash
curl http://127.0.0.1:8080/v1/models
# → {"object": "list", "data": [
#     {"id": "deepseek-v4-pro", "object": "model", ...},
#     {"id": "deepseek-v4-flash", "object": "model", ...},
#     {"id": "deepseek-chat", "object": "model", ...}
#   ]}
```

Claude Desktop 3P appelle cet endpoint pour l'auto-discovery des modèles.

### `POST /v1/messages` (Anthropic Messages API)

```bash
curl http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: any-value" \
  -d '{
    "model": "claude-sonnet-4",
    "max_tokens": 1024,
    "system": "Tu es un assistant.",
    "messages": [{"role": "user", "content": "Bonjour"}]
  }'
```

### `POST /responses` (OpenAI Responses API)

```bash
curl http://127.0.0.1:8080/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5",
    "instructions": "Tu es un assistant.",
    "input": [{"type": "message", "role": "user", "content": "Bonjour"}]
  }'
```

### `POST /v1/responses` (alias)

Identique à `/responses` — pour la compatibilité avec le SDK OpenAI.

---

## Variables d'environnement

### Obligatoires

| Variable | Description |
|----------|-------------|
| `DEEPSEEK_API_KEY` | Clé API DeepSeek |
| `OPENCODE_API_KEY` | Clé API OpenCode Go (si utilisé) |

### Configuration du proxy

| Variable | Défaut | Description |
|----------|--------|-------------|
| `LLM_RELAY_PORT` | `8080` | Port d'écoute |
| `LLM_RELAY_BACKEND` | `deepseek` | Backend principal (`deepseek`, `deepseek-anthropic`, `opencode`) |
| `LLM_RELAY_FALLBACK_BACKEND` | — | Backend de fallback |
| `LLM_RELAY_DEBUG` | `false` | Logs détaillés (`1`, `true`, `yes`) |
| `LLM_RELAY_MAX_TOKENS` | `4096` | Max tokens par réponse |
| `LLM_RELAY_TLS` | `false` | Active HTTPS avec certificat auto-signé |
| `LLM_RELAY_API_BASE_URL` | — | Override l'URL de base du backend |
| `LLM_RELAY_MODEL` | — | Override le modèle par défaut |

---

## Commandes CLI

| Commande | Description |
|----------|-------------|
| `llm-relay` ou `llm-relay start` | Démarrer le proxy |
| `llm-relay stop` | Arrêter le proxy |
| `llm-relay status` | État et configuration |
| `llm-relay setup` | Ré-exécuter le wizard |
| `llm-relay update` | Mettre à jour depuis GitHub |
| `llm-relay config port <N>` | Changer le port |
| `llm-relay config key <sk-...>` | Changer la clé API |

---

## Résilience : circuit breaker et fallback

Le proxy intègre un mécanisme de résilience automatique :

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  Requête ──→ DeepSeek (primary)                              │
│                │                                             │
│                ├─ succès → réponse                           │
│                └─ échec → CircuitBreaker (5 échecs = open)   │
│                              │                               │
│                              └─ Fallback → OpenCode Go       │
│                                 │                            │
│                                 ├─ succès → réponse          │
│                                 └─ échec → erreur 502        │
│                                                              │
│  CircuitBreaker : après 30s, passe en half_open              │
│  → un appel test est tenté sur DeepSeek                      │
│  → si OK : circuit repasse en closed                         │
│  → si KO : circuit reste open                                │
└──────────────────────────────────────────────────────────────┘
```

Configurable via :

```bash
export LLM_RELAY_FALLBACK_BACKEND="opencode"
export OPENCODE_API_KEY="oc-votre-cle"
```

---

## Architecture interne (pour les contributeurs)

Le proxy est organisé en couches :

```
┌─────────────────────────────────────────────────────────────┐
│  SERVER (handler.py)                                        │
│  ├── do_GET:  /health, /v1/models                          │
│  └── do_POST: /responses, /v1/messages                      │
│                                                             │
│  PARSERS                                                    │
│  ├── messages.py          : Responses API → format interne  │
│  └── anthropic_messages.py: Anthropic API → format interne  │
│                                                             │
│  ROUTING (routing/)                                         │
│  ├── engine.py            : RoutingEngine                   │
│  ├── circuit_breaker.py   : CircuitBreaker (par backend)    │
│  └── fallback.py          : FallbackChain                   │
│                                                             │
│  TRANSLATORS                                                │
│  ├── chat_completions.py  : Générique Chat Completions      │
│  ├── deepseek.py          : DeepSeek (étend Chat)           │
│  ├── opencode.py          : OpenCode Go (étend Chat)        │
│  └── anthropic_pass.py    : Pass-through Anthropic          │
│                                                             │
│  SESSION (session/store.py)                                 │
│  └── Stocke l'historique pour Codex CLI (stateful → stateless)│
└─────────────────────────────────────────────────────────────┘
```

### Ajouter un nouveau backend

1. Créer une classe dans `translators/` qui étend `ChatCompletionsTranslator` ou `AnthropicPassThroughTranslator`
2. Définir `DEFAULT_BASE_URL`, `DEFAULT_CHAT_ENDPOINT`, `DEFAULT_MODEL`
3. L'enregistrer dans `translators/factory.py`
4. L'ajouter au `PROVIDERS` dict dans `cli/config_manager.py`

Exemple pour un backend hypothétique "MyLLM" :

```python
# translators/myllm.py
from llm_relay.translators.chat_completions import ChatCompletionsTranslator

class MyLLMTranslator(ChatCompletionsTranslator):
    DEFAULT_BASE_URL = "https://api.myllm.com"
    DEFAULT_CHAT_ENDPOINT = "/v1/chat/completions"
    DEFAULT_MODEL = "myllm-pro"
```

```python
# translators/factory.py
from llm_relay.translators.myllm import MyLLMTranslator
TranslatorFactory.register("myllm", MyLLMTranslator)
```

```python
# cli/config_manager.py
PROVIDERS = {
    ...
    "myllm": {
        "display": "MyLLM",
        "env_key": "MYLLM_API_KEY",
    },
}
```

---

## Fichiers et emplacements

```
~/.llm-relay/
├── config.json          ← Configuration (port, provider, api_key, fallback)
├── .env                 ← Variables d'environnement exportables
├── proxy.pid            ← PID du proxy en cours
├── tls/                 ← Certificats TLS (si HTTPS activé)
│   ├── cert.pem
│   └── key.pem
└── venv/                ← Environnement virtuel Python

~/.codex/
└── config.toml          ← Configuration Codex CLI (mise à jour auto par setup)
```

---

## FAQ

**Pourquoi le proxy est nécessaire si DeepSeek a une API Anthropic ?**

DeepSeek `/anthropic` ne supporte pas `cache_control` (pas de prompt caching), ignore `thinking.budget_tokens`, et ne supporte pas les images. Le proxy compense ces gaps et offre un point de configuration unique pour tous tes agents.

**Quelle config pour utiliser ton abonnement Anthropic ET DeepSeek ?**

Deux options :
- Option A (simple) : Claude Desktop → 3P gateway → proxy → DeepSeek. Claude Code CLI → direct Anthropic (env vars séparées).
- Option B (unifié) : Tout passe par le proxy. Configurer le fallback DeepSeek → OpenCode Go (ton abonnement).

**Le proxy ajoute-t-il de la latence ?**

En mode pass-through (DeepSeek `/anthropic`) : < 10ms (juste un forward). En mode traduction (Anthropic ↔ Chat) : < 50ms (parsing + conversion). Le streaming est relayé ou simulé sans accumulation complète.

**Pourquoi HTTPS est nécessaire pour Claude Desktop 3P ?**

La doc Claude Desktop exige `https://` pour `inferenceGatewayBaseUrl`. Active avec `LLM_RELAY_TLS=1`. Le proxy génère un certificat auto-signé automatiquement.

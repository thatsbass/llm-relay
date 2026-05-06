# 04 — Product Requirements Document (PRD)

## Résumé exécutif

**llm-relay v0.2** étend le proxy local existant pour supporter Claude Code et Claude Desktop (mode 3P gateway) comme clients northbound, et DeepSeek (Anthropic API + Chat Completions) et OpenCode Go comme backends southbound. L'architecture devient un **routeur multi-protocole** avec fallback automatique.

---

## Objectifs produit

1. **Supporter Claude Code et Claude Desktop** comme clients via l'Anthropic Messages API
2. **Supporter OpenCode Go** comme backend (Chat Completions + Anthropic Messages)
3. **Routing intelligent** : choisir le bon backend selon la configuration et la disponibilité
4. **Résilience** : retry, circuit breaker, fallback automatique entre backends
5. **Enrichissement** : injection de contexte projet, post-processing du reasoning
6. **Conserver le zéro-dépendance** : Python stdlib uniquement
7. **Rétrocompatibilité** : le chemin Codex CLI → DeepSeek Chat continue de fonctionner

---

## Périmètre fonctionnel

### Northbound (endpoints entrants)

| Endpoint | Protocole | Client | Priorité |
|----------|-----------|--------|----------|
| `POST /responses` | OpenAI Responses API | Codex CLI | Existant |
| `POST /v1/responses` | OpenAI Responses API (alias) | Codex CLI | Existant |
| `POST /v1/messages` | Anthropic Messages API | Claude Code, Claude Desktop 3P | **Nouveau P0** |
| `GET /v1/models` | Anthropic Models API | Claude Desktop (auto-discovery) | **Nouveau P1** |
| `POST /v1/fim/completions` | FIM (Fill-in-the-Middle) | Plugins Copilot | **Nouveau P2** |
| `GET /health` | Liveness probe | Tous | Existant |

### Southbound (backends sortants)

| Backend | Protocole | Endpoint | Priorité |
|---------|-----------|----------|----------|
| DeepSeek Chat | Chat Completions | `https://api.deepseek.com/v1/chat/completions` | Existant |
| DeepSeek Anthropic | Anthropic Messages | `https://api.deepseek.com/anthropic/v1/messages` | **Nouveau P0** |
| DeepSeek FIM | FIM Completions | `https://api.deepseek.com/v1/fim/completions` | **Nouveau P2** |
| OpenCode Go Chat | Chat Completions | `https://opencode.ai/zen/go/v1/chat/completions` | **Nouveau P1** |
| OpenCode Go Anthropic | Anthropic Messages | `https://opencode.ai/zen/go/v1/messages` | **Nouveau P1** |
| Generic Chat | Chat Completions | Configurable | **Nouveau P2** |

### Fonctions transverses

| Fonction | Description | Priorité |
|----------|-------------|----------|
| **Routing engine** | Sélection du backend selon config + modèle demandé | P0 |
| **Fallback chain** | Chaîne de fallback configurable (ex: DeepSeek → OpenCode Go) | P1 |
| **Retry + backoff** | Retry avec exponential backoff (max 3 tentatives) | P1 |
| **Circuit breaker** | Désactive un backend après N échecs, réessaye après timeout | P1 |
| **Rate limiter** | Token bucket par backend, respecte les limites du provider | P2 |
| **Context injection** | Enrichit le system prompt avec le contexte projet (arborescence, git branch) | P2 |
| **Post-processing** | Nettoie les réponses (balises `<think>`, tool calls XML, normalisation) | Existant |
| **Session store enrichi** | Stocke working_dir, project_map, token_budget en plus de l'historique | P1 |

---

## Exigences non-fonctionnelles

| Exigence | Cible |
|----------|-------|
| **Latence ajoutée** | < 50ms pour le pass-through, < 200ms pour la traduction |
| **Zéro dépendance** | Python stdlib uniquement (pas de `pip install`) |
| **Python** | ≥ 3.10 |
| **Port** | Configurable (8080 par défaut) |
| **Sécurité** | Écoute uniquement sur 127.0.0.1 (localhost) |
| **TLS/HTTPS** | Optionnel : certificat auto-signé pour compatibilité Claude Desktop 3P (`inferenceGatewayBaseUrl` exige `https://`) |
| **Tests** | ≥ 80% de couverture sur le nouveau code |
| **Rétrocompatibilité** | Les configurations v0.1 doivent fonctionner sans changement |

---

## Stratégie de traduction

### Règle de décision

```
Le backend cible parle-t-il le même protocole que le client ?

  OUI → Pass-through avec enrichissement (ex: Claude → DeepSeek /anthropic)
  NON → Traduction complète (ex: Claude → OpenCode Go Chat)
```

### Matrice de décision

```
CLIENT (northbound)     BACKEND (southbound)       STRATÉGIE
─────────────────────────────────────────────────────────────────
Responses API           Chat Completions          Traduction (existant)
Responses API           Anthropic Messages        Non applicable (pas de backend
                                                   Anthropic utilisé par Codex)
Anthropic Messages      Anthropic Messages        Pass-through
Anthropic Messages      Chat Completions          Traduction Anthropic↔Chat
FIM                     FIM                       Pass-through
FIM                     Chat Completions          Transformation FIM→Chat
```

---

## Configuration

### Format config.json (étendu)

```json
{
  "port": 8080,
  "provider": "deepseek",
  "api_key": "sk-xxx",
  "fallback_provider": "opencode",
  "fallback_api_key": "oc-xxx",
  "custom_base_url": null
}
```

### Providers supportés

```python
PROVIDERS = {
    "deepseek": {
        "display": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "protocols": ["chat_completions", "anthropic_messages", "fim"],
        "base_url": "https://api.deepseek.com",
        "anthropic_base_url": "https://api.deepseek.com/anthropic",
    },
    "opencode": {
        "display": "OpenCode Go",
        "env_key": "OPENCODE_API_KEY",
        "protocols": ["chat_completions", "anthropic_messages"],
        "base_url": "https://opencode.ai/zen/go",
    },
}
```

### Variables d'environnement

```bash
# DeepSeek
export DEEPSEEK_API_KEY="sk-xxx"

# OpenCode Go
export OPENCODE_API_KEY="oc-xxx"

# Proxy
export LLM_RELAY_PORT="8080"
export LLM_RELAY_DEBUG="1"
export LLM_RELAY_BACKEND="deepseek"
export LLM_RELAY_FALLBACK_BACKEND="opencode"
```

---

## Phases

| Phase | Contenu | Effort estimé |
|-------|---------|---------------|
| **Phase 0** | Refactor : génériciser le translator Chat Completions (extraire de deepseek.py) | Petit |
| **Phase 1** | Northbound Anthropic Messages API (POST /v1/messages, GET /v1/models) | Moyen |
| **Phase 2** | Streaming Anthropic SSE + pass-through DeepSeek /anthropic | Moyen |
| **Phase 3** | Traduction Anthropic↔Chat Completions (pour OpenCode Go Chat) | Grand |
| **Phase 4** | Routing engine + fallback + retry + circuit breaker | Moyen |
| **Phase 5** | CLI & wizard mis à jour (multi-provider) | Petit |
| **Phase 6** | FIM (Fill-in-the-Middle) | Petit |
| **Phase 7** | HTTPS/TLS (certificat auto-signé pour Claude Desktop 3P) | Moyen |
| **Phase 8** | Context injection + session store enrichi | Moyen |
| **Phase 9** | Tests + documentation | Moyen |

---

## Succès mesurable

1. **Claude Code fonctionne** avec DeepSeek via `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`
2. **Claude Desktop 3P** fonctionne avec le proxy comme gateway (HTTP ou HTTPS selon solution)
3. **Switching 3P ↔ Standard** fonctionne : `disableDeploymentModeChooser: false` permet de choisir au lancement
4. **Codex CLI continue** de fonctionner (rétrocompatibilité)
4. **Fallback fonctionnel** : si DeepSeek est down, bascule vers OpenCode Go
5. **Tests passent** : ≥ 80% de couverture
6. **Zéro régression** : les 82 tests existants passent toujours

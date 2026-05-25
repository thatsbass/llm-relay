# 03 — Gap Analysis : écarts entre APIs et backends

Ce document analyse ce que chaque API supporte, ce que les agents de code utilisent réellement, et les écarts que le proxy doit combler.

---

## 1. Compatibilité DeepSeek Anthropic API

DeepSeek expose une API Anthropic-compatible à `https://api.deepseek.com/anthropic`.
Source : https://api-docs.deepseek.com/guides/anthropic_api

### Matrice de compatibilité

```
FONCTIONNALITÉ                    SUPPORT     IMPACT
──────────────────────────────────────────────────────────────
🟢 system                         OUI         —
🟢 messages (text)                OUI         —
🟢 tool_use / tool_result         OUI         —
🟢 tools (name, input_schema)     OUI         —
🟢 tool_choice (auto/any/tool)    OUI         —
🟢 streaming                      OUI         —
🟢 stop_sequences                 OUI         —
🟢 temperature / top_p            OUI         —
🟢 thinking (basique)             OUI         —
🟢 output_config.effort           OUI         —
🟢 max_tokens                     OUI         —
🟢 x-api-key auth                 OUI         —
──────────────────────────────────────────────────────────────
🟠 thinking.budget_tokens         IGNORÉ      Pas de budget
🟠 thinking.display               ?           Non documenté
🟠 disable_parallel_tool_use      IGNORÉ      Pas de contrôle
🟠 cache_control (auto+explicit)  IGNORÉ      ⚠️ PAS DE CACHE
🟠 anthropic-beta header          IGNORÉ      Features beta ignorées
🟠 anthropic-version header       IGNORÉ      —
🟠 top_k                          IGNORÉ      Peu utilisé
🟠 citations                      IGNORÉ      —
🟠 is_error (tool_result)         IGNORÉ      Erreurs outils ignorées
──────────────────────────────────────────────────────────────
🔴 image (type="image")           NON         Screenshots impossibles
🔴 document (type="document")     NON         PDF impossibles
🔴 search_result                  NON         Pas de RAG via API
🔴 server_tool_use                NON         web_search côté serveur
🔴 redacted_thinking              NON         Thinking omis non dispo
🔴 web_search_tool_result         NON         —
🔴 code_execution_tool_result     NON         —
🔴 mcp_tool_use/result            NON         —
🔴 container_upload               NON         —
🔴 mcp_servers                    IGNORÉ      —
🔴 metadata                       IGNORÉ      —
🔴 service_tier                   IGNORÉ      —
```

### Gaps critiques pour Claude Code

#### Gap 1 : `cache_control` ignoré — PAS DE PROMPT CACHING

C'est le gap le plus impactant. Sans cache, chaque appel API re-traite l'intégralité du system prompt et de l'historique.

```
Impact financier (session type de 50 appels, system prompt de 10k tokens) :

Avec cache (Anthropic natif) :
  Appel 1  : 10k tokens (cache write, 1.25x prix) = 12.5k équivalent
  Appels 2-50 : 10k × 49 (cache read, 0.1x prix) = 49k équivalent
  Total équivalent : ~61.5k tokens facturés

Sans cache (DeepSeek /anthropic) :
  Appels 1-50 : 10k × 50 (full input, 1x prix) = 500k tokens facturés

→ 8x plus de tokens input facturés avec DeepSeek
→ Latence plus élevée à chaque appel (re-traitement du system prompt)
→ Impact rate limit (plus de tokens = plafond atteint plus vite)
```

**Ce que le proxy peut faire** : Limiter la taille de l'historique et tronquer le system prompt (déjà partiellement fait dans `config.py`). Mais le proxy ne peut PAS simuler le cache côté serveur.

#### Gap 2 : `thinking.budget_tokens` ignoré

Claude Code configure le budget de réflexion via `ANTHROPIC_THINKING_BUDGET` ou `effortLevel`. DeepSeek ignore cette valeur.

**Ce que le proxy peut faire** : Mapper le budget thinking Anthropic vers le paramètre `reasoning_effort` ou `thinking` de DeepSeek Chat Completions.

#### Gap 3 : `disable_parallel_tool_use` ignoré

L'agent ne peut pas forcer l'exécution séquentielle des outils. Problème si les outils ont des dépendances.

**Ce que le proxy peut faire** : Intercepter les tool calls parallèles et les re-séquencer

---

## 2. Compatibilité Claude Desktop 3P (Feature Matrix)

Source : https://claude.com/docs/cowork/3p/feature-matrix

```
FONCTIONNALITÉ                         STANDARD    3P GATEWAY
──────────────────────────────────────────────────────────────
✅ Cowork tab (agent principal)           ✓         ✓
✅ Code tab (Claude Code intégré)         ✓         ✓
✅ Projets                                ✓         ✓
✅ Fichiers (accès, upload)               ✓         ✓
✅ MCP local                              ✓         ✓
✅ MCP distant                            ✓         ✓
✅ Skills, plugins, hooks                 ✓         ✓
✅ Artifacts                              ✓         ✓
✅ Mémoire (stockée localement)           ✓         ✓
✅ Scheduled tasks                        ✓         ✓
❌ Chat tab                               ✓         —
❌ Voice mode                             ✓         —
❌ Computer use                           —         —
❌ Connecteurs Anthropic 1P               ✓         —
❌ Dispatch / mobile                      ✓         —
```

### Remarques importantes

- **Code tab en 3P** : certains paramètres 3P ne se propagent pas encore au Code tab. Configurer via `managed-settings.json` si nécessaire (voir https://code.claude.com/docs/en/desktop#managed-settings).
- **Sandbox Cowork** : le Cowork tab a un bac à sable réseau (`coworkEgressAllowedHosts`). Le proxy doit être dans cette liste si elle est restreinte.
- **Code tab** : s'exécute sur l'hôte avec l'accès réseau normal. Non restreint par `coworkEgressAllowedHosts`.

### Contrainte HTTPS

La doc spécifie que `inferenceGatewayBaseUrl` **doit être `https://`**. Si Claude Desktop refuse `http://127.0.0.1`, il faudra ajouter le support TLS à llm-relay (voir [08-claude-desktop-3p.md](./08-claude-desktop-3p.md)).

---

## 3. Gap OpenAI Responses API → Chat Completions

C'est le chemin que llm-relay gère déjà (v0.1). État actuel :

```
FONCTIONNALITÉ RESPONSES        ÉQUIVALENT CHAT        STATUT
────────────────────────────────────────────────────────────────
✅ Stateful (prev_response_id)  Stateless               Géré (SessionStore)
✅ instructions                 role:system             Géré (input_to_messages)
✅ function_call                tool_calls[]            Géré
✅ function_call_output         role:tool               Géré
✅ message items                role:user/assistant     Géré
⚠️ reasoning items              Pas d'équivalent        Partiel (summary→content)
✅ item_reference               Pas d'équivalent        Ignoré (non nécessaire)
✅ computer_call                Pas d'équivalent        Ignoré
❌ Built-in tools               Pas d'équivalent        NON GÉRÉ
   (web_search, file_search,                            (erreur si utilisé)
    code_interpreter)
⚠️ truncation strategy          Manuel                  Partiel (trim config.py)
✅ parallel_tool_calls          Pas de contrôle         Accepté/forwardé
⚠️ Streaming simulé             Pas de vrai streaming   Géré (SSE simulé)
```

### Gap à combler : Built-in tools

Codex CLI peut utiliser `web_search`, `file_search`, `code_interpreter` qui sont des outils internes OpenAI. Aucun équivalent dans Chat Completions.

**Ce que le proxy peut faire** :
- `web_search` → le proxy fait lui-même la recherche web et renvoie le résultat comme un `function_call_output` normal
- `code_interpreter` → le proxy exécute le code Python localement
- `file_search` → le proxy fait une recherche dans les fichiers du projet

---

## 4. Ce que Claude Code utilise vraiment

Basé sur la documentation de Claude Code settings et les variables d'environnement.

| Feature API | Requis ? | Critique ? | Détail |
|-------------|----------|------------|--------|
| **Tool use** (bash, read, write, edit, glob, grep, task...) | OUI | ⚠️ CRITIQUE | L'agent ne peut pas agir sans |
| **Streaming** | OUI | ⚠️ CRITIQUE | Affichage temps réel dans le terminal |
| **System prompt** | OUI | ⚠️ CRITIQUE | Règles agent, contexte projet, permissions |
| **Multi-turn** | OUI | ⚠️ CRITIQUE | Conversations longues avec tool calls |
| **Extended thinking** | OUI | 🔶 IMPORTANT | Via `ANTHROPIC_THINKING_BUDGET` ou `effortLevel` |
| **Thinking blocks** dans la réponse | OUI | 🔶 IMPORTANT | Affichés dans l'UI |
| **Cache control** | OUI | 🔶 IMPORTANT | `ANTHROPIC_CACHE_CONTROL` - cache le system prompt |
| **Tool choice** | OUI | ◽ SECONDAIRE | `auto` par défaut, parfois `any` |
| **Parallel tool calls** | OUI | ◽ SECONDAIRE | Exécution parallèle |
| **Stop sequences** | OUI | ◽ SECONDAIRE | Rarement utilisé |
| **Images** (screenshots) | RARE | ◽ SECONDAIRE | Support expérimental |
| **Documents/PDFs** | NON | — | Pas utilisé en codage |
| **Server tools** | NON | — | Claude Code a ses propres outils |
| **MCP tools** | NON via API | — | Géré localement par Claude Code |

---

## 5. Ce que Codex CLI utilise vraiment

| Feature API | Requis ? | Critique ? | Détail |
|-------------|----------|------------|--------|
| **Stateful sessions** | OUI | ⚠️ CRITIQUE | `previous_response_id` |
| **Tool use** (exec_command...) | OUI | ⚠️ CRITIQUE | Via `function_call` dans `input[]` |
| **Streaming** (simulé) | OUI | 🔶 IMPORTANT | llm-relay simule déjà |
| **Instructions** | OUI | ⚠️ CRITIQUE | System prompt |
| **Built-in tools** | OUI | 🔶 IMPORTANT | `web_search`, `file_search`, `code_interpreter` |
| **Reasoning** | OUI | 🔶 IMPORTANT | `type:reasoning` items |
| **Truncation** | OUI | ◽ SECONDAIRE | Gestion auto du context window |

---

## 6. Résumé des actions pour le proxy

```
┌─────────────────────────────────────────────────────────────────┐
│ CHEMIN                          GAPS À COMBLER    PRIORITÉ     │
├─────────────────────────────────────────────────────────────────┤
│ Claude Code → Anthropic →       cache_control      IMPORTANT   │
│   DeepSeek /anthropic           (limiter historique)            │
│                                 thinking.budget    SECONDAIRE   │
│                                 (mapper → effort)               │
│                                 images non dispo   FAIBLE       │
│                                 (filtrer/warning)               │
├─────────────────────────────────────────────────────────────────┤
│ Claude Code → Anthropic →       Traduction         CRITIQUE    │
│   OpenCode Go Chat              Anthropic↔Chat                 │
│                                 Streaming Anthropic             │
│                                 SSE simulé                      │
├─────────────────────────────────────────────────────────────────┤
│ Codex CLI → Responses →         Built-in tools      IMPORTANT   │
│   DeepSeek Chat                 (web_search...)                 │
│                                 Reasoning→thinking  SECONDAIRE   │
├─────────────────────────────────────────────────────────────────┤
│ TOUS                             Routing multi-      CRITIQUE   │
│                                  backend                        │
│                                  Fallback + retry   IMPORTANT   │
│                                  Rate limiting      SECONDAIRE  │
│                                  FIM                SECONDAIRE  │
└─────────────────────────────────────────────────────────────────┘
```

# 01 — Problématique

## Contexte

Les agents de codage (Claude Code, Codex CLI, GitHub Copilot) sont devenus des outils incontournables pour les développeurs. Cependant, chaque agent est conçu pour fonctionner avec un fournisseur de modèles spécifique :

- **Codex CLI** (OpenAI) → parle exclusivement l'OpenAI Responses API → ne fonctionne qu'avec OpenAI
- **Claude Code** (Anthropic) → parle exclusivement l'Anthropic Messages API → ne fonctionne qu'avec Anthropic
- **Claude Desktop en mode 3P gateway** → parle l'Anthropic Messages API → nécessite un gateway HTTPS

Pendant ce temps, les modèles alternatifs (DeepSeek, GLM-4, Qwen, Kimi) offrent des performances comparables pour une fraction du prix :

| Modèle | Prix input (par M tokens) | Prix output (par M tokens) |
|--------|--------------------------|----------------------------|
| GPT-5 Pro | $5.00 | $30.00 |
| Claude Opus 4 | $15.00 | $75.00 |
| DeepSeek V4 Pro | $0.14 | $0.42 |
| DeepSeek V4 Flash | $0.10 | $0.30 |
| GLM-5 (via OpenCode Go) | ~$0.15 | ~$0.60 |
| Qwen3.5 Plus (via OpenCode Go) | ~$0.08 | ~$0.30 |

**Facteur de prix : 50x à 100x moins cher.**

## Le problème

Les agents de code et les modèles ne parlent pas la même langue :

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  Claude Code ──→ Anthropic Messages API ──✗── DeepSeek       │
│  (format non supporté par DeepSeek natif)                    │
│                                                              │
│  Codex CLI ──→ OpenAI Responses API ──✗── DeepSeek           │
│  (format non supporté par DeepSeek)                          │
│                                                              │
│  Claude Desktop ──→ Anthropic Messages API ──✗── OpenCode Go │
│  (format non supporté par OpenCode Go Chat)                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Une nuance importante : DeepSeek parle Anthropic

Depuis 2025, DeepSeek expose une API Anthropic-compatible à `https://api.deepseek.com/anthropic`. Cela signifie que **Claude Code peut parler directement à DeepSeek** sans proxy, en configurant :

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=sk-votre-cle
claude  # fonctionne directement !
```

Cependant, cette compatibilité est **partielle** (voir [03-gap-analysis.md](./03-gap-analysis.md)). Plusieurs fonctionnalités critiques sont ignorées ou non supportées :

- `cache_control` (prompt caching) → **ignoré** → pas d'optimisation de cache
- `thinking.budget_tokens` → **ignoré** → pas de contrôle du budget de raisonnement
- `disable_parallel_tool_use` → **ignoré** → pas de contrôle d'exécution parallèle
- Images, documents, server tools → **non supportés**

## Pourquoi un proxy reste nécessaire

Même avec la compatibilité Anthropic de DeepSeek, un proxy apporte :

| Bénéfice | Sans proxy | Avec proxy |
|----------|-----------|------------|
| **Routing unifié** | Chaque agent configuré séparément | Un seul point de configuration |
| **Multi-backend** | Un seul backend à la fois | Fallback automatique (DeepSeek → OpenCode Go) |
| **Codex CLI** | Impossible avec DeepSeek | Fonctionnel (traduction Responses → Chat) |
| **Résilience** | Aucune (erreur = échec) | Retry, circuit breaker, fallback |
| **Enrichissement** | Aucun | Injection de contexte projet, post-processing |
| **Observabilité** | Logs éparpillés | Traces centralisées, debug |
| **Compensation des gaps** | Les gaps cassent l'agent | Le proxy compense (ex: simuler le FIM, filtrer les images) |

## La vision

Faire de llm-relay une **couche d'abstraction universelle** entre les agents de code et les fournisseurs de modèles :

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  AGENTS (northbound)              BACKENDS (southbound)          │
│                                                                  │
│  Codex CLI ──→ Responses API ──┐                                 │
│                                │      ┌──→ DeepSeek Chat         │
│  Claude Code ─→ Messages API ──┤──────┤                          │
│                                │      ├──→ DeepSeek /anthropic   │
│  Claude Desktop ─→ Messages ───┘      │                          │
│  (mode 3P gateway)                    ├──→ OpenCode Go Chat      │
│                                       │                          │
│  Plugins Copilot ─→ FIM ─────────────┤──→ DeepSeek FIM          │
│                                       │                          │
│                                       └──→ GLM-4 / autres        │
│                                                                  │
│              llm-relay : traduire, router, enrichir              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Objectifs clés

1. **Transparence** : L'agent ne sait pas quel backend est utilisé
2. **Fiabilité** : Fallback automatique en cas d'échec
3. **Performance** : Pass-through quand c'est possible, traduction quand c'est nécessaire
4. **Extensibilité** : Ajouter un nouveau backend = une classe + une entrée dans la config
5. **Zéro dépendance externe** : Python stdlib uniquement (principe conservé)

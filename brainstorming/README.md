# Brainstorming — Extension llm-relay v0.2

Ce dossier contient la documentation de conception pour l'extension de llm-relay afin de supporter Claude Code, Claude Desktop (mode 3P gateway), et des backends multiples (DeepSeek, OpenCode Go).

## Contenu

| Fichier | Description |
|---------|-------------|
| [`01-problematique.md`](./01-problematique.md) | Énoncé du problème : pourquoi un proxy est nécessaire pour brancher des agents de code sur des modèles alternatifs |
| [`02-formats-api.md`](./02-formats-api.md) | Analyse détaillée des 3 formats d'API (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses) |
| [`03-gap-analysis.md`](./03-gap-analysis.md) | Analyse des écarts : ce que chaque API supporte, ce qui manque, impact sur les agents |
| [`04-PRD.md`](./04-PRD.md) | Product Requirements Document : exigences fonctionnelles et non-fonctionnelles |
| [`05-plan.md`](./05-plan.md) | Plan d'implémentation : phases, fichiers, dépendances |
| [`06-references.md`](./06-references.md) | Références de documentation (APIs, agents, providers) |
| [`07-architecture.md`](./07-architecture.md) | Architecture cible : diagrammes, flux, décisions techniques |
| [`08-claude-desktop-3p.md`](./08-claude-desktop-3p.md) | Guide de configuration Claude Desktop en mode 3P gateway |

## Périmètre

- **Northbound (clients entrants)** : OpenAI Responses API (Codex CLI) + Anthropic Messages API (Claude Code, Claude Desktop 3P)
- **Southbound (backends sortants)** : Chat Completions (DeepSeek, OpenCode Go) + Anthropic Messages API (DeepSeek /anthropic, OpenCode Go)
- **Fonctions transverses** : Routing, fallback, rate limiting, circuit breaker, context injection, post-processing

## Statut

Phase de conception — pas encore d'implémentation.

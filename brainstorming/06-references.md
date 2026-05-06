# 06 — Références de documentation

## APIs LLM

### Anthropic Messages API
- **Référence complète** : https://docs.anthropic.com/en/api/messages
- **Tool use** : https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- **Prompt caching** : https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- **Extended thinking** : https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
- **Streaming** : https://docs.anthropic.com/en/api/streaming
- **Context windows** : https://docs.anthropic.com/en/docs/build-with-claude/context-windows
- **Token counting** : https://docs.anthropic.com/en/docs/build-with-claude/token-counting
- **Error codes** : https://docs.anthropic.com/en/api/errors
- **Beta headers** : https://docs.anthropic.com/en/api/beta-headers
- **Models overview** : https://docs.anthropic.com/en/docs/about-claude/models/overview

### OpenAI Chat Completions API
- **Référence** : https://platform.openai.com/docs/api-reference/chat/create
- **Tool calling** : https://platform.openai.com/docs/guides/function-calling
- **Streaming** : https://platform.openai.com/docs/api-reference/streaming
- **Structured outputs** : https://platform.openai.com/docs/guides/structured-outputs

### OpenAI Responses API
- **Référence** : https://platform.openai.com/docs/api-reference/responses
- **Guide** : https://platform.openai.com/docs/guides/responses

### DeepSeek API
- **Docs générales** : https://api-docs.deepseek.com/
- **Anthropic API compatibilité** : https://api-docs.deepseek.com/guides/anthropic_api
- **Chat Completions** : https://api-docs.deepseek.com/api/deepseek-api
- **FIM (Fill-in-the-Middle)** : https://api-docs.deepseek.com/guides/fim_completion
- **Thinking mode** : https://api-docs.deepseek.com/guides/thinking_mode
- **Tool calls** : https://api-docs.deepseek.com/guides/tool_calls
- **Context caching (KV cache)** : https://api-docs.deepseek.com/guides/kv_cache
- **Pricing** : https://api-docs.deepseek.com/quick_start/pricing
- **Rate limits** : https://api-docs.deepseek.com/quick_start/rate_limit
- **Error codes** : https://api-docs.deepseek.com/quick_start/error_codes

### OpenCode Go
- **Docs** : https://opencode.ai/docs/go/
- **Models disponibles** : https://opencode.ai/zen/go/v1/models
- **API endpoints** :
  - Chat Completions : `https://opencode.ai/zen/go/v1/chat/completions`
  - Messages (Anthropic) : `https://opencode.ai/zen/go/v1/messages`
- **AI SDK packages** :
  - `@ai-sdk/openai-compatible` (la plupart des modèles)
  - `@ai-sdk/anthropic` (MiniMax M2.5/M2.7)
  - `@ai-sdk/alibaba` (Qwen3.5/3.6)

---

## Agents de code

### Claude Code
- **Settings** : https://docs.anthropic.com/en/docs/claude-code/settings
- **Modèle** : https://docs.anthropic.com/en/docs/claude-code/model-config
- **Permissions** : https://docs.anthropic.com/en/docs/claude-code/permissions
- **Sub-agents** : https://docs.anthropic.com/en/docs/claude-code/sub-agents
- **MCP** : https://docs.anthropic.com/en/docs/claude-code/mcp
- **Hooks** : https://docs.anthropic.com/en/docs/claude-code/hooks
- **Variables d'environnement** : https://docs.anthropic.com/en/docs/claude-code/env-vars

### Claude Desktop 3P (Third-Party)
- **Overview** : https://claude.com/docs/cowork/3p/overview
- **Installation** : https://claude.com/docs/cowork/3p/installation
- **Configuration** : https://claude.com/docs/cowork/3p/configuration
- **Feature Matrix** : https://claude.com/docs/cowork/3p/feature-matrix
- **Gateway** : https://claude.com/docs/cowork/3p/gateway
- **Code tab** : https://claude.com/docs/cowork/3p/code
- **Extensions** : https://claude.com/docs/cowork/3p/extensions
- **Telemetry** : https://claude.com/docs/cowork/3p/telemetry
- **Data storage** : https://claude.com/docs/cowork/3p/data-storage

### Codex CLI (OpenAI)
- **GitHub** : https://github.com/openai/codex
- **Configuration** : Codex utilise `~/.codex/config.toml`
- **API** : Utilise l'OpenAI Responses API

### Claude Code avec DeepSeek
- **Guide officiel DeepSeek** : https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code
- **Variables d'environnement** :
  ```bash
  ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
  ANTHROPIC_AUTH_TOKEN=<api-key>
  ANTHROPIC_MODEL=deepseek-v4-pro[1m]
  ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
  ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
  ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
  CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
  CLAUDE_CODE_EFFORT_LEVEL=max
  ```

---

## Standards et protocoles

- **Server-Sent Events (SSE)** : https://html.spec.whatwg.org/multipage/server-sent-events.html
- **JSON Schema** : https://json-schema.org/
- **TOML spec** : https://toml.io/

---

## Architecture de référence

### LiteLLM (proxy LLM open-source)
- **GitHub** : https://github.com/BerriAI/litellm
- **Fonctionnalités** : Multi-provider, load balancing, rate limiting, spend tracking
- **Format** : OpenAI Chat Completions en entrée, traduction vers 100+ backends

### OpenRouter
- **Site** : https://openrouter.ai/
- **Fonctionnalités** : Proxy LLM avec fallback automatique
- **Format** : Chat Completions standardisé

---

## Projets similaires

- **one-api** : https://github.com/songquanpeng/one-api — proxy OpenAI vers multiples backends
- **LobeChat Gateway** : https://github.com/lobehub/lobe-chat — interface + proxy
- **Portkey** : https://portkey.ai/ — gateway LLM managé

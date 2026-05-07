# Troubleshooting

Problèmes courants et leurs solutions pour llm-relay.

---

## Claude Desktop 3P

### "Gateway was unreachable: net::ERR_CERT_AUTHORITY_INVALID"

Le certificat HTTPS auto-signé n'est pas reconnu par Claude Desktop (Electron).

```bash
llm-relay trust-ca
```

Si le dialogue admin n'apparaît pas :

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.llm-relay/tls/ca-cert.pem
```

Puis quitter et relancer Claude Desktop.

### "Gateway returned HTTP 404"

Claude Desktop appelle `/v1/models?limit=1` et le proxy ne gère pas les query strings. Mettre à jour llm-relay (`llm-relay update`).

### "API Error: Error response" — HTTP 400 (tool_calls)

```
An assistant message with 'tool_calls' must be followed by tool messages...
```

Cause : l'ordre des messages Chat Completions est incorrect. Les `tool_result` doivent être placés avant le texte utilisateur. Mettre à jour llm-relay.

### Le sélecteur de modèles n'affiche pas DeepSeek

Claude Desktop garde en cache la liste des modèles. Vérifier la config 3P :

```bash
cat ~/Library/Application\ Support/Claude-3p/configLibrary/*.json | grep inferenceModels
```

Doit contenir :
```json
"inferenceModels": [
  {"name": "deepseek-v4-pro", "supports1m": true},
  {"name": "deepseek-v4-flash"}
]
```

Si absent, relancer `llm-relay setup` pour regénérer.

Si présent, quitter complètement Claude Desktop (⌘Q) et relancer.

### Le spinner tourne indéfiniment après une réponse

Le stream SSE ne se termine pas correctement. Mettre à jour llm-relay.

---

## Claude Code CLI

### "Unable to connect to API (ConnectionRefused)"

Le proxy n'est pas démarré ou le port est incorrect.

```bash
llm-relay status                    # Vérifier si le proxy tourne
llm-relay start --daemon --tls      # Le démarrer si arrêté
source ~/.llm-relay/claude-code.env # Recharger les vars
```

### Claude Code utilise Anthropic au lieu du proxy

```bash
llm-relay claude proxy
source ~/.llm-relay/claude-code.env
```

### Claude Code utilise le proxy au lieu d'Anthropic

```bash
llm-relay claude direct
# Entrer ta clé API Anthropic
source ~/.llm-relay/claude-code.env
```

### Le proxy ne répond pas / timeout

```bash
llm-relay logs -f                    # Voir les logs en direct
```

Chercher les erreurs `Upstream HTTP` ou `Connection error`.

---

## HTTPS / TLS

### SSL certificate verification failed

Même cause que `ERR_CERT_AUTHORITY_INVALID`. Voir section Claude Desktop 3P.

### "openssl: command not found"

```bash
brew install openssl     # macOS
apt install openssl      # Linux
```

### "sudo: a terminal is required"

Le `sudo` ne fonctionne pas en subprocess. Exécuter la commande manuellement :

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.llm-relay/tls/ca-cert.pem
```

---

## Port déjà utilisé

### "Address already in use"

Un autre processus occupe le port.

```bash
llm-relay stop
# ou forcer :
lsof -ti:8080 | xargs kill -9
```

Changer de port :
```bash
llm-relay config port 8081
llm-relay start --daemon --port 8081
```

---

## Backend / Provider

### "DEEPSEEK_API_KEY environment variable is not set"

La clé API n'est pas configurée.

```bash
llm-relay setup           # Ré-exécuter le wizard
# ou :
llm-relay config key sk-xxx
```

### "Upstream HTTP 401"

La clé API est invalide. Vérifier sur [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).

### "Upstream HTTP 429"

Rate limit atteint. Attendre ou configurer un fallback :

```bash
llm-relay setup           # Ajouter un fallback provider
```

### Changer de backend

```bash
llm-relay config backend deepseek-anthropic
llm-relay config backend opencode
llm-relay backend list
```

---

## Logs

### Où sont les logs ?

```bash
llm-relay logs            # Dernières 20 lignes
llm-relay logs -n 100     # 100 dernières lignes
llm-relay logs -f         # Suivre en direct (Ctrl+C pour quitter)
```

Fichier : `~/.llm-relay/proxy.log`

---

## Diagnostic rapide

```bash
# État complet du proxy
llm-relay status

# Vérifier que le proxy répond
curl -sk https://127.0.0.1:8443/health

# Tester le endpoint models
curl -sk https://127.0.0.1:8443/v1/models | python3 -m json.tool

# Tester le endpoint messages
curl -sk https://127.0.0.1:8443/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"x","max_tokens":5,"messages":[{"role":"user","content":"hi"}]}'
```

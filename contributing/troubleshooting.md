# Troubleshooting

Problèmes courants et leurs solutions pour llm-relay.

---

## Claude Desktop 3P

### "inferenceModels: configured model X is not an Anthropic model"

```
Invalid custom3p enterprise config: inferenceModels: configured model "glm-5.1" is not
an Anthropic model. Gateway deployments require an Anthropic model from the provider catalog.
```

Claude Desktop valide que chaque entrée dans `inferenceModels` est un modèle Anthropic reconnu. Les noms de modèles backend (DeepSeek, OpenCode) ne sont pas acceptés dans ce champ.

Regénérer la config (corrigée depuis la v0.2.3) :

```bash
llm-relay setup
# ou :
llm-relay config backend deepseek-anthropic
```

Puis quitter et relancer Claude Desktop (⌘Q). La config générée contiendra uniquement des noms Anthropic (`claude-sonnet-4-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`) — le proxy route vers le vrai backend automatiquement.

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

### Le sélecteur de modèles n'affiche pas les modèles

Claude Desktop garde en cache la liste des modèles. Vérifier la config 3P :

```bash
cat ~/Library/Application\ Support/Claude-3p/configLibrary/*.json | grep inferenceModels
```

Doit contenir des noms de modèles Anthropic :
```json
"inferenceModels": [
  "claude-sonnet-4-5",
  "claude-sonnet-4-6",
  "claude-haiku-4-5"
]
```

> Claude Desktop valide que chaque entrée est un modèle Anthropic — ne pas y mettre des noms DeepSeek/OpenCode. Le proxy route vers le vrai backend automatiquement.

Si absent, relancer `llm-relay setup` pour regénérer.

Si présent, quitter complètement Claude Desktop (⌘Q) et relancer.

### Le spinner tourne indéfiniment après une réponse

Le stream SSE ne se termine pas correctement. Mettre à jour llm-relay.

---

## Claude Code CLI

### "Unable to connect to API (ConnectionRefused)"

Le proxy n'est pas démarré, le port est incorrect, ou `claude-code.env` pointe vers la mauvaise URL.

```bash
# 1. Vérifier l'état du proxy (affiche aussi les divergences d'URL)
llm-relay status

# 2. Si le proxy est arrêté, le démarrer
llm-relay start --daemon

# 3. Si status affiche un avertissement URL (⚠), redémarrer suffit
llm-relay stop && llm-relay start --daemon
```

> **Note** : le wrapper `~/.llm-relay/bin/claude` source `claude-code.env` automatiquement. Pas besoin de `source` manuel — s'assurer que `which claude` renvoie `~/.llm-relay/bin/claude`.

### `claude-code.env` pointe vers `https://` mais le proxy est HTTP

`llm-relay status` détecte et signale cette divergence :

```
  ⚠  claude-code.env → https://127.0.0.1:8080
     Proxy is on     → http://127.0.0.1:8080
     Restart to resync:  llm-relay stop && llm-relay start
```

Solution : redémarrer le proxy — `cmd_start` réécrit le fichier avec le bon schéma.

### Le modèle change entre les requêtes (ex. glm-5.1 → minimax-m2.5)

Claude Code utilise cinq slots de modèles différents selon la tâche (tour principal, sous-agents, etc.). Si les slots pointent vers des modèles différents, les logs montrent des modèles qui alternent.

**Diagnostic :**
```bash
cat ~/.llm-relay/claude-code.env   # vérifier que tous les slots sont identiques
llm-relay logs                     # chercher les lignes [req] model=...
```

**Solution :** redémarrer — `llm-relay start` réécrit le fichier en alignant tous les slots sur le modèle primaire :
```bash
llm-relay stop && llm-relay start --daemon
```

### Claude Code utilise Anthropic au lieu du proxy

```bash
llm-relay claude proxy
# Le wrapper source l'env automatiquement — pas besoin de `source`
```

### Claude Code utilise le proxy au lieu d'Anthropic

```bash
llm-relay claude direct
```

### Le proxy ne répond pas / timeout

```bash
llm-relay logs -f                    # Voir les logs en direct (Ctrl+C pour quitter)
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

Depuis la v0.2, llm-relay choisit **automatiquement** un port libre si le port configuré est occupé — pas besoin d'intervention manuelle. `llm-relay status` affiche le port effectif.

Si tu veux fixer un port permanent :
```bash
llm-relay config port 8081
llm-relay stop && llm-relay start --daemon
```

Pour forcer le kill d'un ancien processus bloquant :
```bash
llm-relay start --force   # kill l'ancien processus puis redémarre
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
llm-relay logs -f         # Suivre en direct — Ctrl+C quitte proprement (pas de traceback)
```

Fichier : `~/.llm-relay/proxy.log` — tronqué à chaque démarrage.

### `llm-relay logs -f` affiche un traceback sur Ctrl+C

Comportement corrigé depuis la v0.2.2. Mettre à jour :
```bash
llm-relay update
```

---

## Modèles

### Les modèles ne s'affichent pas

```bash
# Voir les modèles disponibles pour le backend actif
llm-relay models

# Voir les modèles d'un backend spécifique
llm-relay models --backend opencode
llm-relay models --backend deepseek

# Rafraîchir depuis l'API
llm-relay models --refresh
```

Le cache est valide 1 heure. Les modèles statiques (DeepSeek) n'ont pas besoin de cache.

---

## Backend / Upstream

### "Upstream HTTP 403: error code: 1010" (OpenCode Go)

Cloudflare WAF bloque le User-Agent par défaut de Python urllib. Corrigé depuis la v0.2.2 — le proxy envoie `User-Agent: curl/8.7.1`.

```bash
llm-relay update
llm-relay stop && llm-relay start --daemon
```

### Le daemon crashe silencieusement après le premier appel (macOS)

Symptôme : le daemon démarre, répond au `/health`, puis disparaît dès la première requête. macOS affiche une popup "Python s'est arrêté".

Cause : `os.fork()` après l'import de `ssl`/OpenSSL laisse des mutex internes dans un état incohérent dans le processus enfant — le premier `urlopen()` déclenche un `SIGABRT`.

Corrigé depuis la v0.2.2 : le daemon utilise désormais `subprocess.Popen(..., start_new_session=True)` au lieu de `os.fork()`.

```bash
llm-relay update
llm-relay stop && llm-relay start --daemon
```

---

## Diagnostic rapide

```bash
# État complet du proxy (port, modèle, avertissement URL)
llm-relay status

# Vérifier que le proxy répond
curl http://127.0.0.1:8080/health
# → {"status": "ok"}

# Tester le endpoint models
curl http://127.0.0.1:8080/v1/models | python3 -m json.tool

# Tester le endpoint messages (Anthropic format)
curl http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: test" \
  -d '{"model":"glm-5.1","max_tokens":20,"messages":[{"role":"user","content":"say: ok"}]}'

# Voir les logs en direct
llm-relay logs -f

# Tuer proprement si bloqué
pkill -f "llm_relay _serve"
rm -f ~/.llm-relay/proxy.pid ~/.llm-relay/effective_port
llm-relay start --daemon
```

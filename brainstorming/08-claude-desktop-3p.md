# 08 — Claude Desktop 3P Gateway Mode

Ce document explique comment configurer Claude Desktop pour qu'il utilise llm-relay comme gateway en mode 3P (third-party inference).

---

## 1. Principe

Claude Desktop en mode 3P peut utiliser un **gateway LLM personnalisé** qui implémente l'Anthropic Messages API. llm-relay expose exactement cette API sur `POST /v1/messages` et `GET /v1/models`.

```
Claude Desktop ──gateway HTTPS──→ llm-relay ──→ DeepSeek / OpenCode Go / ...
```

---

## 2. Configuration locale (mode développeur)

Les fichiers de configuration 3P sont stockés dans :

```
macOS : ~/Library/Application Support/Claude-3p/configLibrary/
Windows : %LOCALAPPDATA%\Claude-3p\configLibrary\
```

Structure :
```
configLibrary/
├── _meta.json                          ← référence la config active
└── <uuid>.json                         ← chaque config est un fichier JSON
```

### 2a. Créer une configuration

1. Lancer Claude Desktop — **ne pas se connecter**
2. Activer le mode développeur :
   - macOS : **Help → Troubleshooting → Enable Developer Mode**
   - Windows : **☰ → Help → Troubleshooting → Enable Developer Mode**
3. Ouvrir la fenêtre de config : **Developer → Configure third-party inference**
4. Remplir les champs (voir section 3)
5. Cliquer **Apply locally** → l'appli relance

### 2b. Fichier de config type pour llm-relay

```json
{
  "inferenceProvider": "gateway",
  "inferenceGatewayBaseUrl": "https://127.0.0.1:8443",
  "inferenceGatewayApiKey": "llm-relay",
  "inferenceGatewayAuthScheme": "bearer",
  "disableDeploymentModeChooser": false
}
```

**Notes** :
- `inferenceGatewayApiKey` peut être n'importe quelle valeur : le proxy ne vérifie pas l'auth (par défaut) ou utilise sa propre clé API
- `disableDeploymentModeChooser: false` permet de voir l'écran de choix (3P vs Anthropic) au lancement
- Si configuré via l'UI, changer `disableDeploymentModeChooser` nécessite d'éditer le fichier JSON directement

### 2c. Modèles

Quand `inferenceModels` n'est pas défini, le mode gateway fait du **auto-discovery** via `GET /v1/models`. llm-relay doit donc implémenter cet endpoint qui retourne la liste des modèles disponibles au format Anthropic.

Réponse attendue par Claude Desktop :
```json
{
  "data": [
    {
      "id": "deepseek-v4-pro",
      "object": "model",
      "created": 1700000000,
      "owned_by": "deepseek"
    },
    {
      "id": "deepseek-v4-flash",
      "object": "model",
      "created": 1700000000,
      "owned_by": "deepseek"
    }
  ]
}
```

Si on veut restreindre les modèles visibles, on peut définir `inferenceModels` explicitement dans la config 3P :
```json
{
  "inferenceModels": ["deepseek-v4-pro", "deepseek-v4-flash"]
}
```

---

## 3. Clés de configuration gateway obligatoires

| Clé | Type | Requis | Description |
|-----|------|--------|-------------|
| `inferenceProvider` | string | **OUI** | `"gateway"` |
| `inferenceGatewayBaseUrl` | string | **OUI** | URL du gateway. **⚠️ Doit être `https://`** |
| `inferenceGatewayApiKey` | string | OUI* | Clé API envoyée au gateway |

\* Sauf si `inferenceGatewayAuthScheme: "sso"` ou si un `inferenceCredentialHelper` est configuré.

### Clés optionnelles gateway

| Clé | Type | Défaut | Description |
|-----|------|--------|-------------|
| `inferenceGatewayAuthScheme` | string | `"bearer"` | `"bearer"` (Authorization: Bearer) ou `"x-api-key"` |
| `inferenceGatewayHeaders` | JSON string array | — | Headers HTTP supplémentaires : `["X-Org-Id: team1"]` |
| `inferenceCredentialHelper` | string | — | Chemin absolu vers un exécutable qui retourne un token |
| `inferenceCredentialHelperTtlSec` | integer | `3600` | Cache TTL pour le credential helper |

---

## 4. Clés d'activation et de switching

| Clé | Type | Défaut | Description |
|-----|------|--------|-------------|
| `inferenceProvider` | string | — | Active le mode 3P. Sans cette clé (et les credentials), l'appli démarre en mode standard. |
| `disableDeploymentModeChooser` | boolean | `false` | `true` = force le mode 3P sans choix. `false` = affiche l'écran de choix au lancement. |
| `deploymentOrganizationUuid` | string | — | UUID d'identification du déploiement (pour le support Anthropic) |

### Switching entre modes

Une fois la config 3P créée avec `disableDeploymentModeChooser: false` :

1. Quitter et relancer Claude Desktop
2. L'écran de connexion affiche deux options :
   - **"Continuer avec Passerelle"** → mode 3P (ton gateway llm-relay)
   - **"Se connecter à Anthropic"** → mode standard (ton abonnement Anthropic)
3. Choisir l'un ou l'autre → les données de chaque mode restent isolées dans leurs dossiers respectifs

**Données 3P** → `~/Library/Application Support/Claude-3p/`
**Données standard** → `~/Library/Application Support/Claude/`

---

## 5. Contrainte HTTPS

```
⚠️  inferenceGatewayBaseUrl: "Must be https://"
```

La documentation officielle exige HTTPS. llm-relay écoute en HTTP par défaut.

### Solutions

| Solution | Effort | Description |
|----------|--------|-------------|
| **A)** Tester `http://127.0.0.1` | Nul | Il est possible que Claude Desktop fasse une exception pour localhost. À tester en premier. |
| **B)** TLS natif llm-relay | Moyen | Ajouter un flag `--tls` qui génère un certificat auto-signé pour `127.0.0.1` et configure le serveur en HTTPS |
| **C)** Reverse proxy Caddy | Faible | `caddy reverse-proxy --from https://127.0.0.1:8443 --to http://127.0.0.1:8080` (Caddy gère le TLS auto-signé automatiquement) |
| **D)** Tunnel public | Faible | ngrok, cloudflared, localhost.run exposent en HTTPS |

### Recommandation

Commencer par **A** (test). Si échec → **B** directement dans llm-relay (flag `--tls` ou `--https`).

---

## 6. Sandbox et onglets Cowork / Code

### Onglet Cowork

Le Cowork tab (l'agent principal) opère dans un **bac à sable réseau** gouverné par `coworkEgressAllowedHosts`. Par défaut, seul l'endpoint d'inférence est autorisé. Si le proxy est utilisé, il doit être dans la liste :

```json
{
  "coworkEgressAllowedHosts": ["127.0.0.1:8443", "*.example.com"]
}
```

Si `coworkEgressAllowedHosts` n'est pas défini, tout le trafic réseau du Cowork tab (hors inference) est bloqué (403).

### Onglet Code (Claude Code intégré)

Le Code tab s'exécute **sur l'hôte avec l'accès réseau normal de l'utilisateur** — il n'est PAS restreint par `coworkEgressAllowedHosts`.

**Config du Code tab en 3P** : certains paramètres 3P ne se propagent pas encore au Code tab. Pour configurer le Code tab directement, déployer un `managed-settings.json` (voir [Claude Code managed settings](https://code.claude.com/docs/en/desktop#managed-settings)).

Pour désactiver le Code tab : `isClaudeCodeForDesktopEnabled: false`.

### Outils désactivables

```json
{
  "disabledBuiltinTools": ["WebSearch", "WebFetch"]
}
```

Noms valides : `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `NotebookEdit`, `WebFetch`, `WebSearch`, `Task`, `TodoWrite`, `TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`, `TaskStop`, `Skill`, `REPL`, `JavaScript`, `AskUserQuestion`, `ToolSearch`, `SendUserMessage`.

---

## 7. Fonctionnalités disponibles en 3P

```
FONCTIONNALITÉ                         STANDARD    3P
──────────────────────────────────────────────────────
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

---

## 8. Checklist de déploiement

- [ ] llm-relay en écoute (HTTP ou HTTPS selon solution choisie)
- [ ] `GET /v1/models` répond correctement
- [ ] `POST /v1/messages` accepte les requêtes Anthropic
- [ ] Config 3P créée dans `configLibrary/` avec les bonnes valeurs
- [ ] `disableDeploymentModeChooser: false` (pour pouvoir switcher)
- [ ] `coworkEgressAllowedHosts` inclut l'adresse du proxy (si restreint)
- [ ] Test : **Help → Troubleshooting → Copy Managed Configuration Report** → vérifier que tout est vert
- [ ] Logs si problème : `~/Library/Logs/Claude/main.log`

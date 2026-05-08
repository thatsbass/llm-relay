# Dev Setup — tester depuis une branche

Pour contribuer ou tester une branche avant merge, ne pas utiliser `install.sh` (qui pointe vers `main`). Utiliser un virtualenv local à la place.

## 1. Cloner et checkout la branche

```bash
git clone https://github.com/thatsbass/llm-relay.git
cd llm-relay
git checkout feature/claude-code-desktop-gateway
```

Ou si le repo est déjà cloné :

```bash
git fetch origin
git checkout feature/claude-code-desktop-gateway
```

## 2. Créer le virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

## 3. Installer en mode éditable

```bash
pip install -e .
```

Le mode `-e` (editable) fait que les modifications du code source sont prises en compte immédiatement — pas besoin de réinstaller après chaque changement.

Vérifier :

```bash
llm-relay --help
```

## 4. Configurer

```bash
llm-relay setup
```

Le wizard demande le port, le provider, et la clé API. La config est écrite dans `~/.llm-relay/`.

## 5. Démarrer le proxy

```bash
# Foreground (utile pour voir les logs)
llm-relay start

# Daemon (arrière-plan)
llm-relay start --daemon
llm-relay logs -f    # suivre les logs
```

## 6. Développer

Les fichiers sources sont dans `llm_relay/`. Comme le package est installé en mode éditable, il suffit de sauvegarder le fichier et de redémarrer le proxy :

```bash
llm-relay stop && llm-relay start --daemon
```

## 7. Tests unitaires

```bash
pip install -e ".[dev]"
pytest
```

## Désactiver le virtualenv

```bash
deactivate
```

## Notes

- Le `.venv/` est ignoré par git (`.gitignore`).
- La config (`~/.llm-relay/`) est partagée entre toutes les installations — même le dev local écrit dans `~/.llm-relay/`.
- Pour isoler complètement, passer `LLM_RELAY_PORT=8081` avant de démarrer.

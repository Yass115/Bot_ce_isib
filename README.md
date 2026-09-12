# Bot ISIB — Discord Étudiant ISIB

Bot Discord (Python / [discord.py](https://discordpy.readthedocs.io/)) pour
le Conseil Étudiant ISIB - HE2B : authentification des étudiant·e·s via
leur adresse `@etu.he2b.be` (code envoyé par mail via Brevo) et gestion des
inscriptions académiques (cursus / niveau / orientation) avec validation
interne.

## Fichiers du projet

- `bot.py` — code du bot
- `requirements.txt` — dépendances Python
- `.env.example` — liste des variables d'environnement attendues (à copier
  en `.env` pour un lancement en local — **ne jamais commit `.env`**)
- `render.yaml` — Blueprint Render (déploiement automatique du bot en
  *Background Worker*, avec disque persistant pour la base SQLite)

La base `bot_isib.db` (SQLite) et le fichier `.env` sont volontairement
exclus du dépôt via `.gitignore` : ce sont des données sensibles /
générées, jamais du code.

## Lancer le bot en local

```bash
python -m venv .venv
source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # puis remplis les valeurs
python bot.py
```

## Déploiement 24h/24 - 7j/7 sur Render

Render ne propose pas de plan gratuit pour un **Background Worker** (le
type de service adapté à un bot Discord, qui n'écoute aucune requête HTTP
entrante). Il faut donc un plan payant (**Starter**, ~7 $/mois) pour que
le bot tourne en continu sans jamais s'éteindre. C'est volontairement ce
que configure `render.yaml`, avec en plus un petit disque persistant
(1 Go, quelques centimes/mois) pour que `bot_isib.db` ne soit **pas**
effacée à chaque redéploiement.

### 1. Créer le compte Render et connecter GitHub

1. Va sur [render.com](https://render.com) et crée un compte (tu peux te
   connecter directement avec GitHub).
2. Dans **Account Settings → GitHub**, autorise Render à accéder au
   dépôt `yass115/bot_ce_isib` (accès à ce seul repo, ou à tous — au choix).

### 2. Déployer via le Blueprint (`render.yaml`)

1. Sur le dashboard Render, clique **New → Blueprint**.
2. Sélectionne le dépôt `yass115/bot_ce_isib` et la branche `main`.
3. Render détecte automatiquement `render.yaml` et propose de créer le
   service `bot-isib` (Background Worker + disque persistant).
4. Avant de valider, Render te demande de renseigner les variables
   marquées `sync: false` (elles ne sont **jamais** stockées dans le
   dépôt) :

   | Variable | Valeur |
   |---|---|
   | `DISCORD_TOKEN` | Token de ton bot (Discord Developer Portal) |
   | `GUILD_ID` | ID du serveur Discord |
   | `BREVO_API_KEY` | Clé API Brevo |
   | `EMAIL_SENDER` | Adresse d'envoi (ex. `isib-ce@he2b.be`) |
   | `EMAIL_SENDER_NAME` | Nom affiché de l'expéditeur |
   | `AUDIT_CHANNEL_ID` | ID du salon d'audit |
   | `VALIDATION_CHANNEL_ID` | ID du salon de validation interne |

   `DB_PATH` et `PYTHON_VERSION` sont déjà définies dans `render.yaml`,
   inutile d'y toucher.

5. Clique **Apply** — Render installe les dépendances (`pip install -r
   requirements.txt`) puis lance `python bot.py`. Le bot doit apparaître
   en ligne sur Discord au bout de 1 à 2 minutes.

### 3. Déploiement continu

Une fois branché, **chaque `git push` sur `main`** déclenche
automatiquement un nouveau déploiement (`autoDeploy: true`). Tu n'as
plus rien à faire manuellement ensuite.

### Sans Blueprint (méthode manuelle, alternative)

Si tu préfères ne pas utiliser `render.yaml` :

1. **New → Background Worker**, connecte le repo `yass115/bot_ce_isib`,
   branche `main`.
2. **Build command** : `pip install -r requirements.txt`
3. **Start command** : `python bot.py`
4. Plan : **Starter** minimum (pas de gratuit pour un Background Worker).
5. Ajoute un disque : **Disks → Add Disk**, mount path `/var/data`,
   1 Go.
6. Renseigne les mêmes variables d'environnement que ci-dessus, plus
   `DB_PATH=/var/data/bot_isib.db`.

## ⚠️ Sécurité — token et clé API

Le token Discord et la clé API Brevo échangés dans la conversation qui a
servi à préparer ce dépôt **ne sont plus considérés comme secrets** (ils
ont transité en clair dans un chat). Avant la mise en production, il est
fortement recommandé de :

- régénérer le token du bot dans le
  [Discord Developer Portal](https://discord.com/developers/applications)
  (onglet **Bot → Reset Token**) ;
- régénérer la clé API Brevo dans **Brevo → SMTP & API → API Keys** ;

puis de renseigner uniquement les **nouvelles** valeurs dans Render.

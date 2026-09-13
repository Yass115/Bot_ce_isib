# Bot ISIB — Discord Étudiant ISIB

Bot Discord (Python / [discord.py](https://discordpy.readthedocs.io/)) pour
le Conseil Étudiant ISIB - HE2B : authentification des étudiant·e·s via
leur adresse `@etu.he2b.be` (code envoyé par mail via Brevo) et gestion des
inscriptions académiques (cursus / niveau / orientation) avec validation
interne.

## Architecture

```mermaid
flowchart LR
    Dev["Toi (ou Claude)"] -- "git push main" --> GH["GitHub\nyass115/bot_ce_isib"]
    GH -- "auto-deploy\n(render.yaml)" --> Render["Render\nWeb Service, plan Free"]
    Cron["Ping externe\n(cron-job.org, /10 min)"] -- "GET /" --> Render
    Render -- "discord.py" --> Discord["API Discord"]
    Render -- "envoi des codes" --> Brevo["API Brevo"]
    Render -- "psycopg2" --> Neon[("Neon PostgreSQL\ndonnées persistantes")]
```

Le principe : **GitHub est la seule source de vérité du code**, et Render
redéploie automatiquement à chaque `git push` sur `main`. Le bot
lui-même tourne en continu sur Render (maintenu éveillé par le ping
externe), et toutes ses données persistantes vivent hors de Render, sur
Neon — donc rien n'est perdu si Render redémarre le service.

| Composant | Rôle |
|---|---|
| **GitHub** | Héberge le code (`bot.py`). Toute mise à jour part d'ici. |
| **Render** | Fait tourner le bot 24h/24 (Web Service gratuit). Redéploie automatiquement à chaque push sur `main`. |
| **Ping externe** (cron-job.org) | Empêche Render de mettre le service en veille (plan Free = veille après 15 min d'inactivité). |
| **Neon** | Base PostgreSQL externe et persistante : étudiant·e·s authentifié·e·s, demandes académiques. Indépendante des redémarrages de Render. |
| **Discord / Brevo** | APIs externes utilisées par le bot (connexion Discord, envoi des mails de code). |

## Fichiers du projet

- `bot.py` — code du bot
- `requirements.txt` — dépendances Python
- `.env.example` — liste des variables d'environnement attendues (à copier
  en `.env` pour un lancement en local — **ne jamais commit `.env`**)
- `render.yaml` — Blueprint Render (déploiement automatique du bot en
  Web Service, plan gratuit)

Le bot stocke ses données (étudiant·e·s authentifié·e·s, demandes
académiques) dans une base **PostgreSQL externe (Neon, gratuit)** plutôt
que dans un fichier SQLite local — voir la section suivante. Le fichier
`.env` est volontairement exclu du dépôt via `.gitignore`.

## Lancer le bot en local

```bash
python -m venv .venv
source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # puis remplis les valeurs (dont PGHOST/PGUSER/...)
python bot.py
```

## Base de données persistante (Neon PostgreSQL, gratuit)

Le plan gratuit de Render n'a pas de disque persistant : sans base
externe, toute donnée écrite localement (un fichier SQLite par exemple)
serait perdue au moindre redémarrage du service. Ce dépôt utilise donc
**Neon**, un PostgreSQL managé gratuit à vie, dont le calcul se
"réveille" automatiquement et instantanément à la première requête —
aucune intervention manuelle après une période d'inactivité.

1. Crée un compte gratuit sur [neon.tech](https://neon.tech) (connexion
   possible avec GitHub).
2. Crée un nouveau projet (ex. nommé `bot-isib`), région Frankfurt.
3. Sur la page du projet, section **Connect** / **Connection string** :
   clique le petit menu déroulant à côté (souvent "Connection string" /
   *Parameters only*) et choisis l'affichage en **paramètres séparés**
   plutôt que l'URL complète. Tu obtiens alors individuellement :
   `Host`, `Database`, `User`, `Password`.

   Si seule l'URL complète est disponible, elle a ce format —
   les parties correspondent aux variables ci-dessous :
   ```
   postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
   ```
4. Reporte chaque valeur dans les variables Render correspondantes
   (`PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` — voir tableau
   plus bas). **On utilise des variables séparées plutôt qu'une seule
   URL** : coller une longue chaîne `postgresql://user:pass@host/db`
   dans un champ se corrompt facilement (retour à la ligne, espace
   ajouté par le copier-coller) et fait planter la connexion.
5. **N'envoie jamais le mot de passe dans un chat** : colle-le
   uniquement dans le champ `PGPASSWORD` de Render, ou dans ton `.env`
   local.
6. Les tables (`verified_students`, `academic_requests`) sont créées
   automatiquement par le bot à son premier démarrage — rien à faire
   côté Neon.

## Déploiement 24h/24 - 7j/7 sur Render, **gratuitement**

Render ne propose pas de plan gratuit pour un *Background Worker* (le
type de service normalement adapté à un bot Discord). Pour rester à
0 €/mois, ce dépôt déploie donc le bot comme un **Web Service**
(qui a un plan **Free**), avec un tout petit serveur web (`aiohttp`,
déjà présent dans `bot.py`) qui ne fait que répondre "OK" sur `/` — cela
sert uniquement à satisfaire Render (qui exige qu'un Web Service écoute
sur un port) et à permettre à un service externe de le "réveiller"
régulièrement.

**Le piège du plan gratuit :** un Web Service Render gratuit se met en
veille après **15 minutes sans requête HTTP entrante**, et redémarre
dès qu'une requête arrive (ou dans les ~30 secondes qui suivent). Pour
empêcher ça, on branche un service de "ping" gratuit qui appelle l'URL
du bot toutes les 10 minutes, 24h/24.

### 1. Créer le compte Render et connecter GitHub

1. Va sur [render.com](https://render.com), crée un compte (connexion
   directe avec GitHub possible).
2. Dans **Account Settings → GitHub**, autorise Render à accéder au
   dépôt `yass115/bot_ce_isib`.

### 2. Déployer via le Blueprint (`render.yaml`)

1. Sur le dashboard Render, clique **New → Blueprint**.
2. Sélectionne le dépôt `yass115/bot_ce_isib`, branche `main`.
3. Render détecte `render.yaml` et propose de créer le service `bot-isib`
   (Web Service, plan **Free**).
4. Renseigne les variables marquées `sync: false` (jamais stockées dans
   le dépôt) :

   | Variable | Valeur |
   |---|---|
   | `DISCORD_TOKEN` | Token de ton bot (Discord Developer Portal) |
   | `GUILD_ID` | ID du serveur Discord |
   | `BREVO_API_KEY` | Clé API Brevo |
   | `EMAIL_SENDER` | Adresse d'envoi (ex. `isib-ce@he2b.be`) |
   | `EMAIL_SENDER_NAME` | Nom affiché de l'expéditeur |
   | `AUDIT_CHANNEL_ID` | ID du salon d'audit |
   | `VALIDATION_CHANNEL_ID` | ID du salon de validation interne |
   | `PGHOST` | Host Neon (voir section précédente) |
   | `PGDATABASE` | Nom de la base Neon (souvent `neondb`) |
   | `PGUSER` | Utilisateur Neon (souvent `neondb_owner`) |
   | `PGPASSWORD` | Mot de passe Neon |

   `PGPORT` (`5432`) et `PGSSLMODE` (`require`) sont déjà définies dans
   `render.yaml`, inutile d'y toucher.

5. Clique **Apply**. Render installe les dépendances puis lance
   `python bot.py`. Une fois déployé, note l'URL publique du service
   (ex. `https://bot-isib.onrender.com`) — Render l'affiche en haut de
   la page du service.

### 3. Empêcher la mise en veille (ping externe gratuit)

Utilise un service de cron gratuit, par exemple
[cron-job.org](https://cron-job.org) ou
[UptimeRobot](https://uptimerobot.com) :

1. Crée un compte gratuit.
2. Ajoute un nouveau job/moniteur :
   - URL : `https://bot-isib.onrender.com` (ton URL Render)
   - Intervalle : **toutes les 10 minutes** (moins que les 15 min de
     seuil de mise en veille de Render)
3. Sauvegarde. C'est tout — tant que ce ping tourne, le service Render
   reste éveillé en continu et le bot Discord reste connecté 24h/24.

### 4. Déploiement continu

Une fois branché, **chaque `git push` sur `main`** déclenche
automatiquement un nouveau déploiement (`autoDeploy: true`).

### Les données survivent-elles aux redémarrages ?

Oui. Le service Render lui-même reste sans disque persistant (plan
Free oblige), mais ça n'a plus d'importance : toutes les données du bot
(étudiant·e·s authentifié·e·s, demandes académiques) vivent dans la
base Neon externe, pas sur le disque de Render. Que le service Render
redémarre pour cause d'inactivité, de redéploiement, ou de maintenance,
la base Neon n'est pas affectée et le bot la retrouve intacte à chaque
démarrage.

### Sans Blueprint (méthode manuelle, alternative)

Si tu préfères ne pas utiliser `render.yaml` :

1. **New → Web Service**, connecte le repo `yass115/bot_ce_isib`,
   branche `main`.
2. **Build command** : `pip install -r requirements.txt`
3. **Start command** : `python bot.py`
4. Plan : **Free**.
5. Renseigne les mêmes variables d'environnement que ci-dessus, dont
   `PGHOST`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` (connexion Neon).
6. Configure le ping externe comme à l'étape 3 ci-dessus.

## Mettre à jour le bot

Le service Render est connecté à la branche `main` avec le déploiement
automatique activé (`autoDeploy: true`). **Chaque `git push` sur `main`
déclenche un redéploiement automatique** — rien à faire côté Render.

Deux façons de modifier le code :

1. **Demander à Claude** de faire le changement (commande, texte,
   comportement...) — il modifie `bot.py`, commit et push sur `main`,
   Render redéploie tout seul en 1-2 minutes.
2. **Modifier soi-même** :
   - directement sur GitHub : ouvre `bot.py` sur
     `github.com/yass115/bot_ce_isib`, clique l'icône crayon, puis
     **Commit changes** sur `main` ;
   - ou en local :
     ```bash
     git add .
     git commit -m "description du changement"
     git push origin main
     ```

Suis le déploiement dans l'onglet **Deploys** du service Render.

 `initialiser_base_de_donnees()` ne fait que **créer** les tables si
elles n'existent pas (`CREATE TABLE IF NOT EXISTS`) — elle ne modifie
pas une table déjà existante sur Neon. Un changement de structure sur
une base contenant déjà des données nécessite une vraie migration.

## Sécurité — token et clé API

Le token Discord et la clé API Brevo échangés dans la conversation qui a
servi à préparer ce dépôt **ne sont plus considérés comme secrets** (ils
ont transité en clair dans un chat). Avant la mise en production, il est
fortement recommandé de :

- régénérer le token du bot dans le
  [Discord Developer Portal](https://discord.com/developers/applications)
  (onglet **Bot → Reset Token**) ;
- régénérer la clé API Brevo dans **Brevo → SMTP & API → API Keys** ;

puis de renseigner uniquement les **nouvelles** valeurs dans Render.

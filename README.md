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

### ⚠️ Limite du plan gratuit : pas de stockage persistant

Le plan **Free** de Render ne permet pas d'attacher de disque
persistant. Résultat : à chaque redémarrage du service (redéploiement,
ou un redémarrage imposé par Render), le fichier `bot_isib.db` repart
de zéro — **les étudiant·e·s déjà authentifié·e·s et l'historique des
demandes académiques sont perdus**. Le ping externe limite les
redémarrages liés à l'inactivité, mais ne les supprime pas totalement
(maintenance Render, déploiements, etc.).

Si la conservation durable de ces données est importante (ce qui est
probablement le cas ici), les options sont :

1. **Passer le service en Background Worker + disque persistant**
   (~7 $/mois) — solution la plus simple et la plus fiable, voir
   git history de ce fichier pour la configuration correspondante.
2. **Utiliser une base de données externe gratuite** (ex. Postgres
   gratuit chez [Supabase](https://supabase.com) ou
   [Neon](https://neon.tech), ou SQLite distant via
   [Turso](https://turso.tech)) à la place du fichier SQLite local —
   demande une petite adaptation du code de `bot.py`.

Dis-moi si tu veux que je mette en place l'une de ces deux options.

### Sans Blueprint (méthode manuelle, alternative)

Si tu préfères ne pas utiliser `render.yaml` :

1. **New → Web Service**, connecte le repo `yass115/bot_ce_isib`,
   branche `main`.
2. **Build command** : `pip install -r requirements.txt`
3. **Start command** : `python bot.py`
4. Plan : **Free**.
5. Renseigne les mêmes variables d'environnement que ci-dessus.
6. Configure le ping externe comme à l'étape 3 ci-dessus.

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

# ============================================================
# BOT ISIB - DISCORD ÉTUDIANT ISIB
# ============================================================
#
# TABLE DES MATIÈRES
#
# 0. IMPORTS
#
# 1. CONFIGURATION
#    1.1 Variables d'environnement
#    1.2 Paramètres de l'authentification
#    1.3 Paramètres des inscriptions académiques
#    1.4 Permissions internes du bot
#    1.5 Intents Discord
#
# 2. BASE DE DONNÉES (POSTGRESQL - NEON)
#    2.1 Connexion
#    2.2 Initialisation
#    2.3 Étudiants authentifiés
#    2.4 Demandes académiques
#
# 3. OUTILS GÉNÉRAUX
#    3.1 Permissions
#    3.2 Salons
#    3.3 Rôles
#
# 4. AUTHENTIFICATION ÉTUDIANTE
#    4.1 Brevo
#    4.2 Stockage temporaire des codes
#    4.3 Audit
#    4.4 Vérification du code
#    4.5 Formulaire initial
#    4.6 Bouton permanent
#
# 5. PANNEAU D'AUTHENTIFICATION
#
# 6. INSCRIPTIONS ACADÉMIQUES — SÉLECTION MULTI-RÔLES
#    6.1 Registre des rôles académiques
#    6.2 Lecture / formatage des rôles
#    6.3 Interface de sélection multi-rôles
#    6.4 Récapitulatif étudiant
#    6.5 Création sécurisée de la demande
#
# 7. VALIDATION INTERNE CE ISIB
#    7.1 Fiche de validation
#    7.2 Application exacte des rôles
#    7.3 Validation et notification
#    7.4 Boutons Valider / Modifier / Refuser
#    7.5 Modification CE par sélection multi-rôles
#    7.6 Refus
#
# 8. PANNEAU D'INSCRIPTION ACADÉMIQUE
#
# 9. BOT DISCORD
#
# 10. COMMANDES
#     10.1 /ping
#     10.2 /test_audit
#     10.3 /installer_verification
#     10.4 /installer_inscription
#     10.5 /statut_inscription
#
# 11. DÉMARRAGE
#
# ============================================================


# ============================================================
# 0. IMPORTS
# ============================================================

import os
import time
import secrets
import asyncio
import html
import json
import traceback

from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

import discord
from discord import app_commands
from dotenv import load_dotenv

from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)


# ============================================================
# 1. CONFIGURATION
# ============================================================


# ============================================================
# 1.1 VARIABLES D'ENVIRONNEMENT
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_SENDER_NAME = os.getenv("EMAIL_SENDER_NAME")

AUDIT_CHANNEL_ID = os.getenv("AUDIT_CHANNEL_ID")
VALIDATION_CHANNEL_ID = os.getenv("VALIDATION_CHANNEL_ID")

# --------------------------------------------------------------
# Connexion PostgreSQL (Neon) en paramètres séparés plutôt
# qu'une seule URL : plus robuste, un simple copier-coller
# d'une longue chaîne "postgresql://user:pass@host/db?..."
# se corrompt trop facilement (retour à la ligne, espace...).
# --------------------------------------------------------------

PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT", "5432")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
PGSSLMODE = os.getenv("PGSSLMODE", "require")


VARIABLES_OBLIGATOIRES = {
    "DISCORD_TOKEN": TOKEN,
    "GUILD_ID": GUILD_ID,
    "BREVO_API_KEY": BREVO_API_KEY,
    "EMAIL_SENDER": EMAIL_SENDER,
    "EMAIL_SENDER_NAME": EMAIL_SENDER_NAME,
    "AUDIT_CHANNEL_ID": AUDIT_CHANNEL_ID,
    "VALIDATION_CHANNEL_ID": VALIDATION_CHANNEL_ID,
    "PGHOST": PGHOST,
    "PGDATABASE": PGDATABASE,
    "PGUSER": PGUSER,
    "PGPASSWORD": PGPASSWORD,
}


for nom_variable, valeur in VARIABLES_OBLIGATOIRES.items():

    if not valeur:

        raise RuntimeError(
            f"{nom_variable} absent du fichier .env"
        )


GUILD_ID = int(GUILD_ID)
AUDIT_CHANNEL_ID = int(AUDIT_CHANNEL_ID)
VALIDATION_CHANNEL_ID = int(VALIDATION_CHANNEL_ID)


# ============================================================
# 1.2 PARAMÈTRES DE L'AUTHENTIFICATION
# ============================================================

NOM_ROLE_ETUDIANT_VERIFIE = (
    "ÉTUDIANT ISIB - HE2B VÉRIFIÉ"
)

DUREE_CODE_SECONDES = 5 * 60

NOMBRE_MAX_TENTATIVES = 5

DELAI_NOUVEL_ENVOI = 60

TITRE_PANNEAU_VERIFICATION = (
    "🔐 AUTHENTIFICATION ÉTUDIANT.E.S ISIB - HE2B"
)


# ============================================================
# 1.3 PARAMÈTRES DES INSCRIPTIONS ACADÉMIQUES
# ============================================================

TITRE_PANNEAU_INSCRIPTION = (
    "🎓 INSCRIPTIONS ACADÉMIQUES"
)


# ============================================================
# 1.4 PERMISSIONS INTERNES DU BOT
# ============================================================

ROLES_ADMIN_BOT = {
    "ADMIN DISCORD",
    "COORDINATION CE ISIB",
}

ROLES_VALIDATION_INSCRIPTION = {
    "ADMIN DISCORD",
    "COORDINATION CE ISIB",
}


# ============================================================
# 1.5 INTENTS DISCORD
# ============================================================

intents = discord.Intents.default()

# Nécessaire pour lire les membres et gérer leurs rôles.
intents.members = True


# ============================================================
# 2. BASE DE DONNÉES (POSTGRESQL - NEON)
# ============================================================
#
# Base externe persistante (gratuite chez Neon) : les données
# survivent aux redémarrages du service Render, contrairement
# à un fichier SQLite local sur le plan Free (pas de disque
# persistant).
#
# RealDictCursor fait en sorte que chaque ligne se comporte
# comme un dict (row["colonne"]), exactement comme le faisait
# sqlite3.Row auparavant : le reste du code n'a pas à changer.
# ============================================================


# ============================================================
# 2.1 CONNEXION
# ============================================================

def connexion_db():

    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
        sslmode=PGSSLMODE,
        cursor_factory=RealDictCursor
    )


# ============================================================
# 2.2 INITIALISATION
# ============================================================

def initialiser_base_de_donnees():

    connexion = connexion_db()
    curseur = connexion.cursor()

    # --------------------------------------------------------
    # Étudiants authentifiés via leur adresse @etu.he2b.be.
    #
    # Cette table appartient à la PARTIE AUTHENTIFICATION.
    # Sa structure reste inchangée.
    #
    # BIGINT : les identifiants Discord (snowflakes) dépassent
    # la capacité d'un INTEGER Postgres classique (32 bits).
    # --------------------------------------------------------

    curseur.execute(
        """
        CREATE TABLE IF NOT EXISTS verified_students (
            discord_user_id BIGINT PRIMARY KEY,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            email TEXT NOT NULL,
            verified_at DOUBLE PRECISION NOT NULL
        )
        """
    )

    # --------------------------------------------------------
    # Historique des demandes académiques.
    #
    # Les anciennes colonnes requested_profile_key et
    # final_profile_key sont conservées afin de ne pas casser
    # l'historique déjà présent dans la base.
    #
    # Le nouveau système utilise :
    #
    # requested_roles_json = liste exacte des rôles demandés
    # final_roles_json     = liste exacte validée par le CE
    # --------------------------------------------------------

    curseur.execute(
        """
        CREATE TABLE IF NOT EXISTS academic_requests (
            id SERIAL PRIMARY KEY,

            discord_user_id BIGINT NOT NULL,

            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            email TEXT NOT NULL,

            current_roles_json TEXT NOT NULL,

            requested_profile_key TEXT NOT NULL,
            final_profile_key TEXT,

            requested_roles_json TEXT,
            final_roles_json TEXT,

            status TEXT NOT NULL,

            created_at DOUBLE PRECISION NOT NULL,

            reviewer_id BIGINT,
            reviewed_at DOUBLE PRECISION,

            refusal_reason TEXT,

            validation_channel_id BIGINT,
            validation_message_id BIGINT
        )
        """
    )

    # --------------------------------------------------------
    # MIGRATION AUTOMATIQUE D'UNE ANCIENNE BASE
    #
    # Contrairement à SQLite, PostgreSQL sait ajouter une
    # colonne uniquement si elle n'existe pas déjà : ces deux
    # instructions ne font rien si les colonnes sont déjà
    # présentes (base déjà migrée, ou table nouvellement créée
    # ci-dessus avec ces colonnes incluses).
    # --------------------------------------------------------

    curseur.execute(
        "ALTER TABLE academic_requests "
        "ADD COLUMN IF NOT EXISTS requested_roles_json TEXT"
    )

    curseur.execute(
        "ALTER TABLE academic_requests "
        "ADD COLUMN IF NOT EXISTS final_roles_json TEXT"
    )

    connexion.commit()
    connexion.close()


# ============================================================
# 2.3 ÉTUDIANTS AUTHENTIFIÉS
# ============================================================

def enregistrer_etudiant_authentifie(
    discord_user_id: int,
    nom: str,
    prenom: str,
    email: str
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        INSERT INTO verified_students (
            discord_user_id,
            nom,
            prenom,
            email,
            verified_at
        )

        VALUES (%s, %s, %s, %s, %s)

        ON CONFLICT (discord_user_id)
        DO UPDATE SET

            nom = EXCLUDED.nom,
            prenom = EXCLUDED.prenom,
            email = EXCLUDED.email,
            verified_at = EXCLUDED.verified_at
        """,
        (
            discord_user_id,
            nom,
            prenom,
            email,
            time.time()
        )
    )

    connexion.commit()
    connexion.close()


def recuperer_etudiant_authentifie(
    discord_user_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM verified_students
        WHERE discord_user_id = %s
        """,
        (
            discord_user_id,
        )
    )

    resultat = curseur.fetchone()

    connexion.close()

    return resultat


def recuperer_etudiant_par_email(
    email: str
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM verified_students
        WHERE LOWER(email) = LOWER(%s)
        """,
        (
            email,
        )
    )

    resultat = curseur.fetchone()

    connexion.close()

    return resultat


# ============================================================
# 2.4 DEMANDES ACADÉMIQUES
# ============================================================

def creer_demande_academique(
    discord_user_id: int,
    nom: str,
    prenom: str,
    email: str,
    roles_actuels: list[str],
    roles_demandes: list[str]
) -> int:

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        INSERT INTO academic_requests (
            discord_user_id,
            nom,
            prenom,
            email,
            current_roles_json,
            requested_profile_key,
            final_profile_key,
            requested_roles_json,
            final_roles_json,
            status,
            created_at
        )

        VALUES (
            %s, %s, %s, %s, %s,
            'multi_roles', NULL, %s, NULL, 'pending', %s
        )

        RETURNING id
        """,
        (
            discord_user_id,
            nom,
            prenom,
            email,
            json.dumps(
                roles_actuels,
                ensure_ascii=False
            ),
            json.dumps(
                roles_demandes,
                ensure_ascii=False
            ),
            time.time()
        )
    )

    request_id = curseur.fetchone()["id"]

    connexion.commit()
    connexion.close()

    return request_id


def recuperer_demande(
    request_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM academic_requests
        WHERE id = %s
        """,
        (
            request_id,
        )
    )

    resultat = curseur.fetchone()

    connexion.close()

    return resultat


def recuperer_derniere_demande_etudiant(
    discord_user_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM academic_requests

        WHERE discord_user_id = %s

        ORDER BY id DESC
        LIMIT 1
        """,
        (
            discord_user_id,
        )
    )

    resultat = curseur.fetchone()

    connexion.close()

    return resultat


def recuperer_demandes_en_attente():

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM academic_requests
        WHERE status = 'pending'
        """
    )

    resultats = curseur.fetchall()

    connexion.close()

    return resultats


def enregistrer_message_validation(
    request_id: int,
    channel_id: int,
    message_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        UPDATE academic_requests

        SET
            validation_channel_id = %s,
            validation_message_id = %s

        WHERE id = %s
        """,
        (
            channel_id,
            message_id,
            request_id
        )
    )

    connexion.commit()
    connexion.close()



def supprimer_demande_academique(
    request_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        DELETE FROM academic_requests
        WHERE id = %s
        """,
        (
            request_id,
        )
    )

    connexion.commit()
    connexion.close()


def nettoyer_demandes_orphelines():

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        DELETE FROM academic_requests

        WHERE status = 'pending'
        AND validation_message_id IS NULL
        """
    )

    nombre = curseur.rowcount

    connexion.commit()
    connexion.close()

    if nombre > 0:

        print(
            f"🧹 {nombre} demande(s) académique(s) "
            "orpheline(s) supprimée(s)."
        )


def enregistrer_decision(
    request_id: int,
    statut: str,
    reviewer_id: int,
    final_roles: list[str] | None = None,
    refusal_reason=None
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    final_roles_json = (
        json.dumps(
            final_roles,
            ensure_ascii=False
        )
        if final_roles is not None
        else None
    )

    curseur.execute(
        """
        UPDATE academic_requests

        SET
            status = %s,
            reviewer_id = %s,
            reviewed_at = %s,
            final_profile_key = NULL,
            final_roles_json = %s,
            refusal_reason = %s

        WHERE id = %s
        """,
        (
            statut,
            reviewer_id,
            time.time(),
            final_roles_json,
            refusal_reason,
            request_id
        )
    )

    connexion.commit()
    connexion.close()


# ============================================================
# 3. OUTILS GÉNÉRAUX
# ============================================================


# ============================================================
# 3.1 PERMISSIONS
# ============================================================

def utilisateur_est_admin_bot(
    member: discord.Member
) -> bool:

    noms_roles = {
        role.name
        for role in member.roles
    }

    return bool(
        ROLES_ADMIN_BOT.intersection(
            noms_roles
        )
    )


def utilisateur_peut_valider_inscription(
    member: discord.Member
) -> bool:

    noms_roles = {
        role.name
        for role in member.roles
    }

    return bool(
        ROLES_VALIDATION_INSCRIPTION.intersection(
            noms_roles
        )
    )


# ============================================================
# 3.2 SALONS
# ============================================================

async def recuperer_salon(
    client: discord.Client,
    channel_id: int
):

    salon = client.get_channel(
        channel_id
    )

    if salon is not None:
        return salon

    try:

        return await client.fetch_channel(
            channel_id
        )

    except discord.HTTPException as erreur:

        print(
            f"❌ Impossible de récupérer "
            f"le salon {channel_id} :",
            erreur
        )

        return None


async def recuperer_salon_audit(
    client: discord.Client
):

    return await recuperer_salon(
        client,
        AUDIT_CHANNEL_ID
    )


async def recuperer_salon_validation(
    client: discord.Client
):

    return await recuperer_salon(
        client,
        VALIDATION_CHANNEL_ID
    )


async def epingler_panneau(
    message: discord.Message
) -> bool:
    """
    Épingle un panneau public sans empêcher son installation
    si le bot ne possède pas la permission de gérer les messages.
    """

    if message.pinned:

        return True

    try:

        await message.pin(
            reason="Panneau permanent du Bot ISIB"
        )

        return True

    except (
        discord.Forbidden,
        discord.HTTPException
    ) as erreur:

        print(
            "⚠️ Impossible d'épingler automatiquement "
            f"le panneau {message.id} :",
            erreur
        )

        return False


# ============================================================
# 3.3 RÔLES
# ============================================================

def trouver_role_etudiant_verifie(
    guild: discord.Guild
):

    return discord.utils.get(
        guild.roles,
        name=NOM_ROLE_ETUDIANT_VERIFIE
    )


# ============================================================
# PARTIE A — AUTHENTIFICATION ÉTUDIANTE
# ============================================================
#
# Cette partie gère :
# - l'adresse @etu.he2b.be ;
# - le code Brevo ;
# - le rôle ÉTUDIANT ISIB - HE2B VÉRIFIÉ ;
# - l'audit des authentifications.
#
# IMPORTANT : logique conservée telle quelle.
#
# ============================================================


# ============================================================
# 4. AUTHENTIFICATION ÉTUDIANTE
# ============================================================


# ============================================================
# 4.1 BREVO
# ============================================================

brevo_client = Brevo(
    api_key=BREVO_API_KEY,
    timeout=15.0
)


def envoyer_email_code(
    destinataire: str,
    prenom: str,
    code: str
) -> str:

    prenom_html = html.escape(
        prenom
    )

    code_html = html.escape(
        code
    )

    result = (
        brevo_client
        .transactional_emails
        .send_transac_email(

            subject=(
                "Votre code d'authentification "
                "- Discord Étudiant ISIB"
            ),

            html_content=(
                "<html>"

                "<body style='"
                "font-family: Arial, sans-serif;"
                "font-size: 16px;"
                "color: #222222;"
                "line-height: 1.5;"
                "'>"

                f"<p>Bonjour {prenom_html},</p>"

                "<p>"
                "Voici votre code d'authentification :"
                "</p>"

                "<p style='"
                "font-size: 32px;"
                "font-weight: bold;"
                "letter-spacing: 8px;"
                "'>"

                f"{code_html}"

                "</p>"

                "<p>"
                "Ce code est valable pendant 5 minutes."
                "</p>"

                "<p>"
                "Ceci afin de pouvoir accéder à la "
                "communauté étudiante de l'ISIB - HE2B."
                "</p>"

                "<p>"
                "En cas de souci, veuillez contacter "
                "<a href='mailto:isib-ce@he2b.be'>"
                "isib-ce@he2b.be"
                "</a>."
                "</p>"

                "<br>"

                "<p>"
                "CE ISIB | Conseil Étudiant ISIB"
                "<br>"
                "ISIB - HE2B"
                "<br>"
                "isib-ce@he2b.be"
                "</p>"

                "</body>"
                "</html>"
            ),

            sender=(
                SendTransacEmailRequestSender(
                    name=EMAIL_SENDER_NAME,
                    email=EMAIL_SENDER
                )
            ),

            to=[
                SendTransacEmailRequestToItem(
                    email=destinataire,
                    name=prenom
                )
            ]
        )
    )

    return result.message_id


# ============================================================
# 4.2 STOCKAGE TEMPORAIRE DES CODES
# ============================================================

codes_authentification = {}

derniers_envois_code = {}


# ============================================================
# 4.3 AUDIT
# ============================================================

async def envoyer_fiche_audit(
    interaction: discord.Interaction,
    nom: str,
    prenom: str,
    email: str
):

    salon = await recuperer_salon_audit(
        interaction.client
    )

    if not isinstance(
        salon,
        discord.TextChannel
    ):

        print(
            "⚠️ Salon d'audit introuvable."
        )

        return

    membre = interaction.user

    embed = discord.Embed(
        title=(
            "✅ AUTHENTIFICATION ÉTUDIANTE RÉUSSIE"
        ),

        description=(
            "Une nouvelle authentification "
            "a été validée automatiquement."
        ),

        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="Nom",
        value=nom,
        inline=True
    )

    embed.add_field(
        name="Prénom",
        value=prenom,
        inline=True
    )

    embed.add_field(
        name="Adresse mail HE2B",
        value=email,
        inline=False
    )

    embed.add_field(
        name="Compte Discord",
        value=membre.mention,
        inline=True
    )

    embed.add_field(
        name="Nom Discord",
        value=str(membre),
        inline=True
    )

    embed.add_field(
        name="ID Discord",
        value=str(membre.id),
        inline=False
    )

    embed.add_field(
        name="Statut",
        value=(
            "✅ Adresse `@etu.he2b.be` authentifiée\n"
            f"✅ Rôle `{NOM_ROLE_ETUDIANT_VERIFIE}` attribué"
        ),
        inline=False
    )

    embed.set_thumbnail(
        url=membre.display_avatar.url
    )

    embed.set_footer(
        text=(
            "Discord Étudiant ISIB | "
            "Audit des authentifications"
        )
    )

    try:

        await salon.send(
            embed=embed
        )

    except discord.HTTPException as erreur:

        print(
            "❌ Erreur audit :",
            erreur
        )


# ============================================================
# 4.4 VÉRIFICATION DU CODE
# ============================================================

class CodeVerificationModal(
    discord.ui.Modal,
    title="Code d'authentification"
):

    code = discord.ui.TextInput(
        label="Code reçu par mail",
        placeholder="Ex. 483921",
        required=True,
        min_length=6,
        max_length=6
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        user_id = interaction.user.id

        donnees = codes_authentification.get(
            user_id
        )

        if not donnees:

            await interaction.response.send_message(
                "❌ **AUCUNE AUTHENTIFICATION EN COURS**\n\n"
                "Recommencez depuis le panneau.",
                ephemeral=True
            )

            return

        if time.time() > donnees["expiration"]:

            codes_authentification.pop(
                user_id,
                None
            )

            await interaction.response.send_message(
                "⌛ **CODE EXPIRÉ**\n\n"
                "Recommencez votre authentification.",
                ephemeral=True
            )

            return

        code_saisi = self.code.value.strip()

        if (
            len(code_saisi) != 6
            or not code_saisi.isdigit()
        ):

            await interaction.response.send_message(
                "❌ Le code doit contenir exactement "
                "**6 chiffres**.",
                ephemeral=True
            )

            return

        if not secrets.compare_digest(
            code_saisi,
            donnees["code"]
        ):

            donnees["tentatives"] += 1

            restantes = (
                NOMBRE_MAX_TENTATIVES
                - donnees["tentatives"]
            )

            if restantes <= 0:

                codes_authentification.pop(
                    user_id,
                    None
                )

                await interaction.response.send_message(
                    "❌ **TROP DE TENTATIVES**\n\n"
                    "Le code a été invalidé.",
                    ephemeral=True
                )

                return

            await interaction.response.send_message(
                "❌ **CODE INCORRECT**\n\n"
                f"Tentatives restantes : "
                f"**{restantes}**.",
                view=CodeVerificationView(),
                ephemeral=True
            )

            return

        if not (
            interaction.guild
            and isinstance(
                interaction.user,
                discord.Member
            )
        ):

            await interaction.response.send_message(
                "❌ Impossible d'identifier "
                "votre compte Discord.",
                ephemeral=True
            )

            return

        role_verifie = trouver_role_etudiant_verifie(
            interaction.guild
        )

        if role_verifie is None:

            await interaction.response.send_message(
                "❌ Rôle étudiant vérifié introuvable.",
                ephemeral=True
            )

            return

        try:

            if role_verifie not in interaction.user.roles:

                await interaction.user.add_roles(
                    role_verifie,
                    reason=(
                        "Authentification via "
                        "adresse @etu.he2b.be"
                    )
                )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Le bot ne peut pas attribuer "
                "le rôle étudiant vérifié.",
                ephemeral=True
            )

            return

        nom = donnees["nom"]
        prenom = donnees["prenom"]
        email = donnees["email"]

        codes_authentification.pop(
            user_id,
            None
        )

        enregistrer_etudiant_authentifie(
            discord_user_id=user_id,
            nom=nom,
            prenom=prenom,
            email=email
        )

        await interaction.response.send_message(
            "✅ **AUTHENTIFICATION RÉUSSIE**\n\n"
            "Votre adresse mail étudiante "
            "a été authentifiée.\n\n"
            f"Le rôle `{NOM_ROLE_ETUDIANT_VERIFIE}` "
            "vous a été attribué.\n\n"
            "Bienvenue dans la communauté étudiante "
            "de l'ISIB - HE2B !",
            ephemeral=True
        )

        await envoyer_fiche_audit(
            interaction,
            nom,
            prenom,
            email
        )

        # Le panneau public reste fixe.
        # Toute l'authentification de l'étudiant est éphémère :
        # aucun nouveau panneau n'est renvoyé aux autres membres.


class CodeVerificationView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )

    @discord.ui.button(
        label="ENTRER MON CODE",
        emoji="🔢",
        style=discord.ButtonStyle.primary
    )
    async def entrer_code(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            CodeVerificationModal()
        )


# ============================================================
# 4.5 FORMULAIRE INITIAL
# ============================================================

class VerificationModal(
    discord.ui.Modal,
    title="Authentification étudiant.e.s ISIB - HE2B"
):

    nom = discord.ui.TextInput(
        label="Nom de famille",
        placeholder="Ex. Dupont",
        required=True,
        max_length=100
    )

    prenom = discord.ui.TextInput(
        label="Prénom",
        placeholder="Ex. Jean",
        required=True,
        max_length=100
    )

    email = discord.ui.TextInput(
        label="Adresse mail HE2B",
        placeholder="Ex. 55117@etu.he2b.be ou alias@etu.he2b.be",
        required=True,
        max_length=150
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        nom = self.nom.value.strip()
        prenom = self.prenom.value.strip()

        email = (
            self.email.value
            .strip()
            .lower()
        )

        # ----------------------------------------------------
        # Si rôle + identité déjà présente en DB :
        # authentification réellement déjà terminée.
        # ----------------------------------------------------

        if (
            interaction.guild
            and isinstance(
                interaction.user,
                discord.Member
            )
        ):

            role_verifie = trouver_role_etudiant_verifie(
                interaction.guild
            )

            identite_existante = (
                recuperer_etudiant_authentifie(
                    interaction.user.id
                )
            )

            if (
                role_verifie
                and role_verifie in interaction.user.roles
                and identite_existante
            ):

                await interaction.response.send_message(
                    "✅ **VOUS ÊTES DÉJÀ AUTHENTIFIÉ.E**",
                    ephemeral=True
                )

                return

        # ----------------------------------------------------
        # Le domaine doit être exactement étudiant HE2B.
        #
        # La partie avant @ est libre : un matricule comme
        # 55117@etu.he2b.be ou un alias comme
        # cesakwa@etu.he2b.be sont tous les deux acceptés.
        # ----------------------------------------------------

        adresse_valide = False

        if email.count("@") == 1:

            identifiant_mail, domaine_mail = email.split(
                "@",
                1
            )

            adresse_valide = bool(
                identifiant_mail
                and domaine_mail == "etu.he2b.be"
                and not any(
                    caractere.isspace()
                    for caractere in identifiant_mail
                )
            )

        if not adresse_valide:

            await interaction.response.send_message(
                "❌ **ADRESSE MAIL NON VALIDE**\n\n"
                "Utilisez une adresse étudiante se terminant "
                "exactement par `@etu.he2b.be`.\n\n"
                "Exemples : `55117@etu.he2b.be` ou "
                "`alias@etu.he2b.be`.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Empêche une même adresse mail d'être rattachée
        # à plusieurs comptes Discord.
        # ----------------------------------------------------

        proprietaire_email = (
            recuperer_etudiant_par_email(
                email
            )
        )

        if (
            proprietaire_email
            and proprietaire_email[
                "discord_user_id"
            ] != interaction.user.id
        ):

            await interaction.response.send_message(
                "❌ **ADRESSE DÉJÀ UTILISÉE**\n\n"
                "Cette adresse étudiante est déjà "
                "associée à un autre compte Discord.\n\n"
                "Contactez `isib-ce@he2b.be` "
                "si vous avez changé de compte.",
                ephemeral=True
            )

            return

        maintenant = time.time()

        dernier_envoi = derniers_envois_code.get(
            interaction.user.id
        )

        if dernier_envoi:

            ecoule = (
                maintenant
                - dernier_envoi
            )

            if ecoule < DELAI_NOUVEL_ENVOI:

                attente = int(
                    DELAI_NOUVEL_ENVOI
                    - ecoule
                )

                await interaction.response.send_message(
                    "⏳ **VEUILLEZ PATIENTER**\n\n"
                    f"Nouveau code disponible dans "
                    f"environ **{attente} secondes**.",
                    ephemeral=True
                )

                return

        code = (
            f"{secrets.randbelow(1_000_000):06d}"
        )

        expiration = (
            time.time()
            + DUREE_CODE_SECONDES
        )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        try:

            message_id = await asyncio.to_thread(
                envoyer_email_code,
                email,
                prenom,
                code
            )

        except Exception as erreur:

            print(
                "❌ ERREUR BREVO :",
                erreur
            )

            await interaction.followup.send(
                "❌ **L'ENVOI DU CODE A ÉCHOUÉ**\n\n"
                "Veuillez réessayer dans quelques instants.\n\n"
                "Contact : `isib-ce@he2b.be`.",
                ephemeral=True
            )

            return

        derniers_envois_code[
            interaction.user.id
        ] = time.time()

        codes_authentification[
            interaction.user.id
        ] = {
            "code": code,
            "expiration": expiration,
            "tentatives": 0,
            "nom": nom,
            "prenom": prenom,
            "email": email
        }

        print(
            "✅ Code d'authentification envoyé"
        )

        print(
            f"Destinataire : {email}"
        )

        print(
            f"Message ID : {message_id}"
        )

        await interaction.followup.send(
            "📩 **CODE D'AUTHENTIFICATION ENVOYÉ**\n\n"
            f"Un code à 6 chiffres vient "
            f"d'être envoyé à `{email}`.\n\n"
            "Le code est valable pendant "
            "**5 minutes**.\n\n"
            "Pensez également à vérifier "
            "vos courriers indésirables.",
            view=CodeVerificationView(),
            ephemeral=True
        )


# ============================================================
# 4.6 BOUTON PERMANENT
# ============================================================

class VerificationView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="COMMENCER MON AUTHENTIFICATION",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="isib_authentification_start"
    )
    async def start_verification(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if (
            interaction.guild
            and isinstance(
                interaction.user,
                discord.Member
            )
        ):

            role_verifie = trouver_role_etudiant_verifie(
                interaction.guild
            )

            identite = recuperer_etudiant_authentifie(
                interaction.user.id
            )

            if (
                role_verifie
                and role_verifie in interaction.user.roles
                and identite
            ):

                await interaction.response.send_message(
                    "✅ **VOUS ÊTES DÉJÀ AUTHENTIFIÉ.E**\n\n"
                    "Aucune nouvelle authentification "
                    "n'est nécessaire.",
                    ephemeral=True
                )

                return

        await interaction.response.send_modal(
            VerificationModal()
        )


# ============================================================
# 5. PANNEAU D'AUTHENTIFICATION
# ============================================================

def creer_embed_verification():

    embed = discord.Embed(
        title=TITRE_PANNEAU_VERIFICATION,

        description=(
            "Avant d'accéder aux divers espaces étudiants, "
            "vérifiez d'abord votre identité :\n\n"

            "1. Commencez votre authentification\n"
            "2. Indiquez nom, prénom et adresse mail "
            "`@etu.he2b.be`\n"
            "3. Un code temporaire sera envoyé par mail "
            "(vérifiez vos spams), entrez ensuite le code reçu.\n"
            "4. Bienvenue dans la communauté étudiante "
            "de l'ISIB - HE2B !\n\n"

            "🔵 CE ISIB | Conseil Étudiant ISIB\n"
            "📩 isib-ce@he2b.be\n"
            "💻 ISIBnet : Conseil Étudiant ISIB\n"
            "📸 Instagram : @cehe2b_isib\n"
            "🌐 https://www.cehe2b.be"
        )
    )

    embed.set_footer(
        text=(
            "Discord Étudiant ISIB | "
            "Conseil Étudiant ISIB - HE2B"
        )
    )

    return embed


async def publier_panneau_verification(
    channel: discord.TextChannel
):

    message = await channel.send(
        embed=creer_embed_verification(),
        view=VerificationView()
    )

    await epingler_panneau(
        message
    )

    return message


async def replacer_panneau_verification(
    channel: discord.TextChannel
):

    messages_a_supprimer = []

    async for message in channel.history(
        limit=100
    ):

        if not (
            bot.user
            and message.author.id == bot.user.id
        ):

            continue

        for embed in message.embeds:

            if (
                embed.title
                == TITRE_PANNEAU_VERIFICATION
            ):

                messages_a_supprimer.append(
                    message
                )

                break

    for message in messages_a_supprimer:

        try:

            await message.delete()

        except discord.HTTPException:

            pass

    nouveau = await publier_panneau_verification(
        channel
    )

    print(
        "✅ Panneau d'authentification "
        "replacé en bas."
    )

    return nouveau


# ============================================================
# PARTIE B — INSCRIPTIONS ACADÉMIQUES / ACCÈS AUX COURS
# ============================================================
#
# Cette partie est volontairement séparée de l'authentification.
#
# PRINCIPE :
#
# 1. L'étudiant doit déjà être authentifié.
# 2. Ses rôles académiques actuels sont pré-cochés en vert.
# 3. Il peut sélectionner PLUSIEURS rôles académiques via
#    des boutons cochables répartis sur plusieurs pages.
# 4. Chaque envoi crée une demande indépendante contenant la
#    liste complète des rôles qu'il souhaite conserver / obtenir.
#    Plusieurs demandes successives peuvent rester en attente.
# 5. Le CE ISIB peut traiter chaque demande séparément :
#       ✅ VALIDER
#       ✏️ MODIFIER
#       ❌ REFUSER
# 6. Une validation applique EXACTEMENT la liste retenue :
#       - rôles cochés     => conservés / ajoutés
#       - rôles décochés   => retirés
# 7. Le rôle de vérification n'est JAMAIS modifiable ici.
#
# ============================================================


# ============================================================
# 6. INSCRIPTIONS ACADÉMIQUES
# ============================================================


# ============================================================
# 6.1 REGISTRE DES RÔLES ACADÉMIQUES
# ============================================================
#
# Les noms ci-dessous doivent correspondre EXACTEMENT aux noms
# de rôles présents sur Discord.
#
# Les rôles sont répartis en 6 onglets visuels.
# Chaque rôle est représenté par un bouton :
#     ✅ vert = sélectionné
#     ⬜ gris = non sélectionné
#
# Cela simule des cases à cocher de façon plus intuitive
# que plusieurs menus déroulants.
#
# Le rôle :
#     ÉTUDIANT ISIB - HE2B VÉRIFIÉ
# n'est volontairement PAS dans cette liste.
#
# Il reste géré uniquement par la PARTIE AUTHENTIFICATION.
# ============================================================

GROUPES_ROLES_ACADEMIQUES = [

    # --------------------------------------------------------
    # ONGLET 1 — BAPSIE
    # --------------------------------------------------------
    {
        "key": "bapsie",
        "label": "BAPSIE",
        "tab_label": "BAPSIE",
        "general_role": None,
        "roles": [
            "B1 BAPSIE",
            "B2 BAPSIE",
            "B3 BAPSIE",
        ],
    },

    # --------------------------------------------------------
    # ONGLET 2 — B1 INGÉNIERIE
    # --------------------------------------------------------
    {
        "key": "b1_ing",
        "label": "B1 Ingénierie",
        "tab_label": "B1 ING",
        "general_role": "B1 INGÉNIERIE",
        "roles": [
            "B1 INGÉNIERIE",
        ],
    },

    # --------------------------------------------------------
    # ONGLET 3 — B2 INGÉNIERIE
    # Rôle général + options
    # --------------------------------------------------------
    {
        "key": "b2_ing",
        "label": "B2 Ingénierie",
        "tab_label": "B2 ING",
        "general_role": "B2 INGÉNIERIE",
        "roles": [
            "B2 INGÉNIERIE",
            "B2 CHIMIE",
            "B2 PHYSIQUE",
            "B2 MÉCANIQUE",
            "B2 ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE",
        ],
    },

    # --------------------------------------------------------
    # ONGLET 4 — B3 & BC INGÉNIERIE
    # Rôle général + options
    # --------------------------------------------------------
    {
        "key": "b3bc_ing",
        "label": "B3 & BC Ingénierie",
        "tab_label": "B3 & BC ING",
        "general_role": "B3 & BC INGÉNIERIE",
        "roles": [
            "B3 & BC INGÉNIERIE",
            "B3 & BC CHIMIE",
            "B3 & BC PHYSIQUE",
            "B3 & BC MÉCANIQUE",
            "B3 & BC ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE",
        ],
    },

    # --------------------------------------------------------
    # ONGLET 5 — M1 INGÉNIERIE
    # Rôle général + options
    # --------------------------------------------------------
    {
        "key": "m1_ing",
        "label": "M1 Ingénierie",
        "tab_label": "M1 ING",
        "general_role": "M1 INGÉNIERIE",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 CHIMIE",
            "M1 PHYSIQUE",
            "M1 MÉCANIQUE",
            "M1 ÉLECTRICITÉ",
            "M1 ÉLECTRONIQUE",
            "M1 INFORMATIQUE",
        ],
    },

    # --------------------------------------------------------
    # ONGLET 6 — M2 INGÉNIERIE
    # Rôle général + options
    # --------------------------------------------------------
    {
        "key": "m2_ing",
        "label": "M2 Ingénierie",
        "tab_label": "M2 ING",
        "general_role": "M2 INGÉNIERIE",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 CHIMIE",
            "M2 PHYSIQUE",
            "M2 MÉCANIQUE",
            "M2 ÉLECTRICITÉ",
            "M2 ÉLECTRONIQUE",
            "M2 INFORMATIQUE",
        ],
    },
]

# ------------------------------------------------------------
# Compatibilité avec les anciennes demandes déjà enregistrées
# avant le passage au système multi-rôles.
#
# Ce dictionnaire n'est PLUS utilisé pour créer les nouvelles
# demandes. Il sert uniquement à relire l'ancien historique.
# ------------------------------------------------------------

PROFILS_ACADEMIQUES_LEGACY = {

    "bapsie_b1": [
        "B1 BAPSIE"
    ],

    "bapsie_b2": [
        "B2 BAPSIE"
    ],

    "bapsie_b3": [
        "B3 BAPSIE"
    ],

    "ing_b1": [
        "B1 INGÉNIERIE"
    ],

    "ing_b2_chimie": [
        "B2 INGÉNIERIE",
        "B2 CHIMIE"
    ],

    "ing_b2_physique": [
        "B2 INGÉNIERIE",
        "B2 PHYSIQUE"
    ],

    "ing_b2_mecanique": [
        "B2 INGÉNIERIE",
        "B2 MÉCANIQUE"
    ],

    "ing_b2_eei": [
        "B2 INGÉNIERIE",
        "B2 ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE"
    ],

    "ing_b3bc_chimie": [
        "B3 & BC INGÉNIERIE",
        "B3 & BC CHIMIE"
    ],

    "ing_b3bc_physique": [
        "B3 & BC INGÉNIERIE",
        "B3 & BC PHYSIQUE"
    ],

    "ing_b3bc_mecanique": [
        "B3 & BC INGÉNIERIE",
        "B3 & BC MÉCANIQUE"
    ],

    "ing_b3bc_eei": [
        "B3 & BC INGÉNIERIE",
        "B3 & BC ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE"
    ],

    "ing_m1_chimie": [
        "M1 INGÉNIERIE",
        "M1 CHIMIE"
    ],

    "ing_m1_physique": [
        "M1 INGÉNIERIE",
        "M1 PHYSIQUE"
    ],

    "ing_m1_mecanique": [
        "M1 INGÉNIERIE",
        "M1 MÉCANIQUE"
    ],

    "ing_m1_electricite": [
        "M1 INGÉNIERIE",
        "M1 ÉLECTRICITÉ"
    ],

    "ing_m1_electronique": [
        "M1 INGÉNIERIE",
        "M1 ÉLECTRONIQUE"
    ],

    "ing_m1_informatique": [
        "M1 INGÉNIERIE",
        "M1 INFORMATIQUE"
    ],

    "ing_m2_chimie": [
        "M2 INGÉNIERIE",
        "M2 CHIMIE"
    ],

    "ing_m2_physique": [
        "M2 INGÉNIERIE",
        "M2 PHYSIQUE"
    ],

    "ing_m2_mecanique": [
        "M2 INGÉNIERIE",
        "M2 MÉCANIQUE"
    ],

    "ing_m2_electricite": [
        "M2 INGÉNIERIE",
        "M2 ÉLECTRICITÉ"
    ],

    "ing_m2_electronique": [
        "M2 INGÉNIERIE",
        "M2 ÉLECTRONIQUE"
    ],

    "ing_m2_informatique": [
        "M2 INGÉNIERIE",
        "M2 INFORMATIQUE"
    ],
}


# ============================================================
# 6.2 LECTURE / FORMATAGE DES RÔLES
# ============================================================

def obtenir_tous_noms_roles_academiques() -> list[str]:

    roles = []

    for groupe in GROUPES_ROLES_ACADEMIQUES:

        for nom_role in groupe["roles"]:

            if nom_role not in roles:

                roles.append(
                    nom_role
                )

    return roles


def normaliser_roles_academiques(
    roles: list[str] | set[str]
) -> list[str]:

    demandes = set(
        roles
    )

    return [
        nom_role
        for nom_role in obtenir_tous_noms_roles_academiques()
        if nom_role in demandes
    ]


def lire_roles_academiques_membre(
    member: discord.Member
) -> list[str]:

    noms_roles = set(
        obtenir_tous_noms_roles_academiques()
    )

    roles_membre = {
        role.name
        for role in member.roles
        if role.name in noms_roles
    }

    return normaliser_roles_academiques(
        roles_membre
    )


def formater_roles(
    roles: list[str] | set[str],
    vide="• Aucun rôle académique"
) -> str:

    roles_ordonnes = normaliser_roles_academiques(
        roles
    )

    if not roles_ordonnes:

        return vide

    return "\n".join(
        f"• `{role}`"
        for role in roles_ordonnes
    )


def calculer_modifications_roles(
    roles_actuels: list[str],
    roles_finaux: list[str]
):

    actuels = set(
        roles_actuels
    )

    finaux = set(
        roles_finaux
    )

    a_retirer = normaliser_roles_academiques(
        actuels - finaux
    )

    a_ajouter = normaliser_roles_academiques(
        finaux - actuels
    )

    conserves = normaliser_roles_academiques(
        actuels & finaux
    )

    return (
        a_retirer,
        a_ajouter,
        conserves
    )


def roles_demandes_depuis_demande(
    demande
) -> list[str]:

    if not demande:

        return []

    colonnes = set(
        demande.keys()
    )

    if (
        "requested_roles_json" in colonnes
        and demande["requested_roles_json"]
    ):

        try:

            return normaliser_roles_academiques(
                json.loads(
                    demande["requested_roles_json"]
                )
            )

        except (
            json.JSONDecodeError,
            TypeError
        ):

            pass

    # --------------------------------------------------------
    # Ancienne demande basée sur un profil.
    # --------------------------------------------------------

    profile_key = (
        demande["requested_profile_key"]
        if "requested_profile_key" in colonnes
        else None
    )

    return normaliser_roles_academiques(
        PROFILS_ACADEMIQUES_LEGACY.get(
            profile_key,
            []
        )
    )


def roles_finaux_depuis_demande(
    demande
) -> list[str]:

    if not demande:

        return []

    colonnes = set(
        demande.keys()
    )

    if (
        "final_roles_json" in colonnes
        and demande["final_roles_json"]
    ):

        try:

            return normaliser_roles_academiques(
                json.loads(
                    demande["final_roles_json"]
                )
            )

        except (
            json.JSONDecodeError,
            TypeError
        ):

            pass

    # --------------------------------------------------------
    # Compatibilité avec l'ancien système.
    # --------------------------------------------------------

    if (
        "final_profile_key" in colonnes
        and demande["final_profile_key"]
    ):

        return normaliser_roles_academiques(
            PROFILS_ACADEMIQUES_LEGACY.get(
                demande["final_profile_key"],
                []
            )
        )

    if demande["status"] in {
        "approved",
        "corrected"
    }:

        return roles_demandes_depuis_demande(
            demande
        )

    return []


# ============================================================
# 6.3 INTERFACE PAGINÉE PAR BOUTONS COCHABLES
# ============================================================
#
# Discord ne propose pas de vraie grille de cases à cocher.
# On simule donc ce fonctionnement avec des boutons :
#
#     ✅ bouton vert  = rôle sélectionné
#     ⬜ bouton gris  = rôle non sélectionné
#
# Les rôles sont répartis sur 6 onglets :
#
#     1. BAPSIE
#     2. B1 ING
#     3. B2 ING
#     4. B3 & BC ING
#     5. M1 ING
#     6. M2 ING
#
# Les choix restent mémorisés lorsqu'on change de page.
# ============================================================


class EtatSelectionRoles:

    def __init__(
        self,
        roles_selectionnes=None,
        roles_actuels=None
    ):

        selection_normalisee = (
            normaliser_roles_academiques(
                roles_selectionnes or []
            )
        )

        actuels_normalises = (
            normaliser_roles_academiques(
                roles_actuels
                if roles_actuels is not None
                else selection_normalisee
            )
        )

        # Liste que l'utilisateur est en train de préparer.
        self.roles = set(
            selection_normalisee
        )

        # État initial de la sélection.
        # Le bouton RÉINITIALISER revient exactement ici.
        self.roles_depart = set(
            selection_normalisee
        )

        # Situation académique réellement détenue au moment
        # où l'interface est ouverte.
        self.roles_actuels = set(
            actuels_normalises
        )


def formater_roles_compact(
    roles,
    vide="Aucun"
) -> str:

    roles_ordonnes = (
        normaliser_roles_academiques(
            roles
        )
    )

    if not roles_ordonnes:

        return vide

    return " • ".join(
        f"`{role}`"
        for role in roles_ordonnes
    )


def trouver_page_selection(
    roles_selectionnes
) -> int:

    roles_selectionnes = set(
        normaliser_roles_academiques(
            roles_selectionnes
        )
    )

    # Ouvre automatiquement l'onglet contenant le plus
    # de rôles déjà sélectionnés.
    meilleur_index = 0
    meilleur_score = 0

    for index, groupe in enumerate(
        GROUPES_ROLES_ACADEMIQUES
    ):

        score = sum(
            1
            for nom_role in groupe["roles"]
            if nom_role in roles_selectionnes
        )

        if score > meilleur_score:

            meilleur_index = index
            meilleur_score = score

    return meilleur_index


def titre_mode_selection(
    mode: str
) -> str:

    if mode == "student":

        return (
            "🎓 **SÉLECTION DE VOS RÔLES ACADÉMIQUES**"
        )

    return (
        "✏️ **MODIFICATION DE LA DEMANDE PAR LE CE ISIB**"
    )


def texte_interface_selection(
    etat: EtatSelectionRoles,
    titre: str,
    page_index=None
) -> str:

    if page_index is None:

        page_index = trouver_page_selection(
            etat.roles
        )

    page_index = max(
        0,
        min(
            page_index,
            len(GROUPES_ROLES_ACADEMIQUES) - 1
        )
    )

    groupe = GROUPES_ROLES_ACADEMIQUES[
        page_index
    ]

    nombre_page = sum(
        1
        for nom_role in groupe["roles"]
        if nom_role in etat.roles
    )

    roles_actuels = formater_roles_compact(
        etat.roles_actuels,
        vide="Aucun rôle académique"
    )

    roles_demandes = formater_roles_compact(
        etat.roles,
        vide="Aucun rôle sélectionné"
    )

    return (
        f"{titre}\n\n"

        f"📄 **Page {page_index + 1}/"
        f"{len(GROUPES_ROLES_ACADEMIQUES)} — "
        f"{groupe['label']}**\n"

        f"**{nombre_page} rôle(s) sélectionné(s) "
        "sur cet onglet**\n\n"

        "📌 **Rôles actuels :**\n"
        f"{roles_actuels}\n\n"

        "📝 **Rôles demandés :**\n"
        f"{roles_demandes}\n\n"

        "Cliquez sur un rôle pour le cocher ou le décocher.\n"
        "✅ **vert = sélectionné**   "
        "⬜ **gris = non sélectionné**\n\n"

        "Vous pouvez changer d'onglet sans perdre vos choix. "
        "Un rôle actuel non sélectionné dans la demande "
        "sera retiré uniquement si le CE valide la demande."
    )


def utilisateur_autorise_interface_ce(
    interaction: discord.Interaction
) -> bool:

    return (
        isinstance(
            interaction.user,
            discord.Member
        )
        and utilisateur_peut_valider_inscription(
            interaction.user
        )
    )


def libelle_role_bouton(
    groupe: dict,
    nom_role: str
) -> str:

    if (
        groupe.get("general_role")
        and nom_role == groupe["general_role"]
    ):

        return (
            f"GÉNÉRAL · {nom_role}"
        )[:80]

    if groupe.get("general_role"):

        return (
            f"OPTION · {nom_role}"
        )[:80]

    return nom_role[:80]


class RoleToggleButton(
    discord.ui.Button
):

    def __init__(
        self,
        etat: EtatSelectionRoles,
        groupe: dict,
        nom_role: str,
        mode: str,
        page_index: int,
        request_id=None,
        row=0
    ):

        self.etat = etat
        self.groupe = groupe
        self.nom_role = nom_role
        self.mode = mode
        self.page_index = page_index
        self.request_id = request_id

        selectionne = (
            nom_role in etat.roles
        )

        super().__init__(
            label=libelle_role_bouton(
                groupe,
                nom_role
            ),
            emoji=(
                "✅"
                if selectionne
                else "⬜"
            ),
            style=(
                discord.ButtonStyle.success
                if selectionne
                else discord.ButtonStyle.secondary
            ),
            row=row
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if (
            self.mode == "ce"
            and not utilisateur_autorise_interface_ce(
                interaction
            )
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # On acquitte immédiatement l'interaction.
        #
        # C'est plus robuste sur un hébergement distant
        # (Render, latence réseau, etc.) et évite que Discord
        # affiche "Le bot n'a pas répondu à temps" pendant
        # que le message est reconstruit.
        # ----------------------------------------------------

        await interaction.response.defer()

        if self.nom_role in self.etat.roles:

            self.etat.roles.discard(
                self.nom_role
            )

        else:

            self.etat.roles.add(
                self.nom_role
            )

        await interaction.edit_original_response(
            content=texte_interface_selection(
                self.etat,
                titre_mode_selection(
                    self.mode
                ),
                self.page_index
            ),
            view=SelectionRolesView(
                etat=self.etat,
                mode=self.mode,
                request_id=self.request_id,
                page_index=self.page_index
            )
        )


class PageRolesButton(
    discord.ui.Button
):

    def __init__(
        self,
        etat: EtatSelectionRoles,
        mode: str,
        page_cible: int,
        page_actuelle: int,
        request_id=None,
        row=2
    ):

        self.etat = etat
        self.mode = mode
        self.page_cible = page_cible
        self.request_id = request_id

        est_page_actuelle = (
            page_cible == page_actuelle
        )

        groupe = GROUPES_ROLES_ACADEMIQUES[
            page_cible
        ]

        super().__init__(
            label=groupe["tab_label"][:80],
            style=(
                discord.ButtonStyle.primary
                if est_page_actuelle
                else discord.ButtonStyle.secondary
            ),
            disabled=est_page_actuelle,
            row=row
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if (
            self.mode == "ce"
            and not utilisateur_autorise_interface_ce(
                interaction
            )
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        await interaction.response.defer()

        await interaction.edit_original_response(
            content=texte_interface_selection(
                self.etat,
                titre_mode_selection(
                    self.mode
                ),
                self.page_cible
            ),
            view=SelectionRolesView(
                etat=self.etat,
                mode=self.mode,
                request_id=self.request_id,
                page_index=self.page_cible
            )
        )


class SelectionRolesView(
    discord.ui.View
):

    def __init__(
        self,
        etat: EtatSelectionRoles,
        mode: str,
        request_id=None,
        page_index=None
    ):

        super().__init__(
            timeout=840
        )

        self.etat = etat
        self.mode = mode
        self.request_id = request_id

        if page_index is None:

            page_index = trouver_page_selection(
                self.etat.roles
            )

        self.page_index = max(
            0,
            min(
                page_index,
                len(GROUPES_ROLES_ACADEMIQUES) - 1
            )
        )

        groupe = GROUPES_ROLES_ACADEMIQUES[
            self.page_index
        ]

        # ----------------------------------------------------
        # LIGNES 0 ET 1 : RÔLES DE L'ONGLET
        # ----------------------------------------------------

        for index, nom_role in enumerate(
            groupe["roles"]
        ):

            self.add_item(
                RoleToggleButton(
                    etat=self.etat,
                    groupe=groupe,
                    nom_role=nom_role,
                    mode=self.mode,
                    request_id=self.request_id,
                    page_index=self.page_index,
                    row=index // 5
                )
            )

        # ----------------------------------------------------
        # LIGNES 2 ET 3 : ONGLETS
        #
        # Discord affiche au maximum 5 boutons par ligne.
        # Les 5 premiers onglets sont donc sur la ligne 2,
        # le 6e sur la ligne 3.
        #
        # L'onglet actif est bleu et désactivé.
        # Les autres sont gris et cliquables.
        # ----------------------------------------------------

        for page_cible in range(
            len(GROUPES_ROLES_ACADEMIQUES)
        ):

            ligne = (
                2
                if page_cible < 5
                else 3
            )

            self.add_item(
                PageRolesButton(
                    etat=self.etat,
                    mode=self.mode,
                    page_cible=page_cible,
                    page_actuelle=self.page_index,
                    request_id=self.request_id,
                    row=ligne
                )
            )

        # ----------------------------------------------------
        # LIGNE 4 : ACTIONS
        # ----------------------------------------------------

        bouton_vider_page = discord.ui.Button(
            label="EFFACER CET ONGLET",
            emoji="🧹",
            style=discord.ButtonStyle.danger,
            row=4
        )

        bouton_vider_page.callback = (
            self.vider_page
        )

        bouton_reinitialiser = discord.ui.Button(
            label="RÉINITIALISER",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=4
        )

        bouton_reinitialiser.callback = (
            self.reinitialiser
        )

        self.add_item(
            bouton_vider_page
        )

        self.add_item(
            bouton_reinitialiser
        )

        if self.mode == "student":

            bouton_continuer = discord.ui.Button(
                label="RÉCAPITULATIF",
                emoji="📋",
                style=discord.ButtonStyle.primary,
                row=4
            )

            bouton_continuer.callback = (
                self.recapitulatif_etudiant
            )

            bouton_annuler = discord.ui.Button(
                label="ANNULER",
                emoji="❌",
                style=discord.ButtonStyle.secondary,
                row=4
            )

            bouton_annuler.callback = (
                self.annuler_etudiant
            )

            self.add_item(
                bouton_continuer
            )

            self.add_item(
                bouton_annuler
            )

        else:

            bouton_appliquer = discord.ui.Button(
                label="VALIDER MODIF.",
                emoji="✅",
                style=discord.ButtonStyle.success,
                row=4
            )

            bouton_appliquer.callback = (
                self.valider_modification_ce
            )

            bouton_annuler = discord.ui.Button(
                label="ANNULER",
                emoji="❌",
                style=discord.ButtonStyle.secondary,
                row=4
            )

            bouton_annuler.callback = (
                self.annuler_modification_ce
            )

            self.add_item(
                bouton_appliquer
            )

            self.add_item(
                bouton_annuler
            )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item
    ):

        print()
        print("❌ ERREUR INTERFACE INSCRIPTION ACADÉMIQUE")
        print(f"Mode : {self.mode}")
        print(f"Request ID : {self.request_id}")
        print(f"Utilisateur : {interaction.user} ({interaction.user.id})")
        print(f"Composant : {item}")
        traceback.print_exception(
            type(error),
            error,
            error.__traceback__
        )
        print()

        message = (
            "❌ **UNE ERREUR EST SURVENUE**\n\n"
            "Le Bot ISIB n'a pas pu mettre à jour cette interface.\n"
            "Fermez cette interface puis relancez **MODIFIER** "
            "depuis la fiche de validation.\n\n"
            "L'erreur technique a été enregistrée dans les logs du bot."
        )

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    message,
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )

        except discord.HTTPException:

            pass

    async def vider_page(
        self,
        interaction: discord.Interaction
    ):

        if (
            self.mode == "ce"
            and not utilisateur_autorise_interface_ce(
                interaction
            )
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        groupe = GROUPES_ROLES_ACADEMIQUES[
            self.page_index
        ]

        await interaction.response.defer()

        for nom_role in groupe["roles"]:

            self.etat.roles.discard(
                nom_role
            )

        await interaction.edit_original_response(
            content=texte_interface_selection(
                self.etat,
                titre_mode_selection(
                    self.mode
                ),
                self.page_index
            ),
            view=SelectionRolesView(
                etat=self.etat,
                mode=self.mode,
                request_id=self.request_id,
                page_index=self.page_index
            )
        )

    async def reinitialiser(
        self,
        interaction: discord.Interaction
    ):

        if (
            self.mode == "ce"
            and not utilisateur_autorise_interface_ce(
                interaction
            )
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        await interaction.response.defer()

        self.etat.roles = set(
            self.etat.roles_depart
        )

        nouvelle_page = trouver_page_selection(
            self.etat.roles
        )

        await interaction.edit_original_response(
            content=texte_interface_selection(
                self.etat,
                titre_mode_selection(
                    self.mode
                ),
                nouvelle_page
            ),
            view=SelectionRolesView(
                etat=self.etat,
                mode=self.mode,
                request_id=self.request_id,
                page_index=nouvelle_page
            )
        )

    async def recapitulatif_etudiant(
        self,
        interaction: discord.Interaction
    ):

        roles_demandes = normaliser_roles_academiques(
            self.etat.roles
        )

        if not roles_demandes:

            await interaction.response.send_message(
                "❌ **AUCUN RÔLE SÉLECTIONNÉ**\n\n"
                "Sélectionnez au moins un rôle académique "
                "avant de continuer.",
                ephemeral=True
            )

            return

        await afficher_recapitulatif_roles(
            interaction,
            roles_demandes
        )

    async def annuler_etudiant(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.edit_message(
            content=(
                "❌ **INSCRIPTION ANNULÉE**\n\n"
                "Aucune demande n'a été envoyée."
            ),
            view=None
        )

    async def valider_modification_ce(
        self,
        interaction: discord.Interaction
    ):

        if not utilisateur_autorise_interface_ce(
            interaction
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        roles_finaux = normaliser_roles_academiques(
            self.etat.roles
        )

        if not roles_finaux:

            await interaction.response.send_message(
                "❌ Sélectionnez au moins un rôle académique.",
                ephemeral=True
            )

            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await traiter_validation_roles(
            interaction=interaction,
            request_id=self.request_id,
            roles_finaux=roles_finaux,
            correction=True
        )

    async def annuler_modification_ce(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.edit_message(
            content=(
                "↩️ Modification annulée.\n\n"
                "La demande CE originale reste en attente."
            ),
            view=None
        )


# ============================================================
# 6.4 RÉCAPITULATIF ÉTUDIANT
# ============================================================

async def afficher_recapitulatif_roles(
    interaction: discord.Interaction,
    roles_demandes: list[str]
):

    if not isinstance(
        interaction.user,
        discord.Member
    ):

        await interaction.response.send_message(
            "❌ Impossible d'identifier votre compte.",
            ephemeral=True
        )

        return

    roles_actuels = (
        lire_roles_academiques_membre(
            interaction.user
        )
    )

    a_retirer, a_ajouter, conserves = (
        calculer_modifications_roles(
            roles_actuels,
            roles_demandes
        )
    )

    texte_modifications = []

    for role in a_retirer:

        texte_modifications.append(
            f"➖ `{role}`"
        )

    for role in a_ajouter:

        texte_modifications.append(
            f"➕ `{role}`"
        )

    for role in conserves:

        texte_modifications.append(
            f"➡️ `{role}` conservé"
        )

    if not texte_modifications:

        texte_modifications.append(
            "➡️ Aucun changement"
        )

    contenu = (
        "🎓 **RÉCAPITULATIF DE VOTRE DEMANDE**\n\n"

        "📌 **Rôles académiques actuels :**\n"
        f"{formater_roles(roles_actuels)}\n\n"

        "🎓 **Rôles académiques demandés :**\n"
        f"{formater_roles(roles_demandes)}\n\n"

        "🔄 **Effet si le CE valide exactement cette demande :**\n"
        f"{chr(10).join(texte_modifications)}\n\n"

        "Vérifiez attentivement la liste avant l'envoi."
    )

    await interaction.response.edit_message(
        content=contenu,
        view=RecapitulatifRolesView(
            roles_demandes
        )
    )


class RecapitulatifRolesView(
    discord.ui.View
):

    def __init__(
        self,
        roles_demandes: list[str]
    ):

        super().__init__(
            timeout=840
        )

        self.roles_demandes = (
            normaliser_roles_academiques(
                roles_demandes
            )
        )

    @discord.ui.button(
        label="ENVOYER MA DEMANDE",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def envoyer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await envoyer_demande_academique(
            interaction,
            self.roles_demandes
        )

    @discord.ui.button(
        label="MODIFIER MA SÉLECTION",
        emoji="✏️",
        style=discord.ButtonStyle.secondary
    )
    async def modifier(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        roles_actuels = (
            lire_roles_academiques_membre(
                interaction.user
            )
            if isinstance(
                interaction.user,
                discord.Member
            )
            else []
        )

        etat = EtatSelectionRoles(
            roles_selectionnes=self.roles_demandes,
            roles_actuels=roles_actuels
        )

        await interaction.response.edit_message(
            content=texte_interface_selection(
                etat,
                "🎓 **SÉLECTION DE VOS RÔLES ACADÉMIQUES**"
            ),
            view=SelectionRolesView(
                etat=etat,
                mode="student"
            )
        )

    @discord.ui.button(
        label="ANNULER",
        emoji="❌",
        style=discord.ButtonStyle.secondary
    )
    async def annuler(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=(
                "❌ **DEMANDE ANNULÉE AVANT ENVOI**\n\n"
                "Aucune demande n'a été transmise au CE ISIB."
            ),
            view=None
        )


# ============================================================
# 6.5 CRÉATION SÉCURISÉE DE LA DEMANDE
# ============================================================

async def envoyer_demande_academique(
    interaction: discord.Interaction,
    roles_demandes: list[str]
):

    if not (
        interaction.guild
        and isinstance(
            interaction.user,
            discord.Member
        )
    ):

        await interaction.response.send_message(
            "❌ Impossible d'identifier votre compte.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Authentification obligatoire.
    # --------------------------------------------------------

    role_verifie = trouver_role_etudiant_verifie(
        interaction.guild
    )

    if (
        not role_verifie
        or role_verifie not in interaction.user.roles
    ):

        await interaction.response.send_message(
            "🔒 **AUTHENTIFICATION REQUISE**\n\n"
            "Vous devez d'abord effectuer votre "
            "authentification dans `#verification`.",
            ephemeral=True
        )

        return

    identite = recuperer_etudiant_authentifie(
        interaction.user.id
    )

    if not identite:

        await interaction.response.send_message(
            "⚠️ Votre rôle de vérification est présent, "
            "mais votre identité n'existe pas encore "
            "dans la base du bot.\n\n"
            "Relancez une authentification dans "
            "`#verification`.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Les demandes successives sont autorisées.
    #
    # Chaque envoi crée une demande indépendante dans le salon
    # interne du CE ISIB. Une demande précédente encore en
    # attente ne bloque donc jamais l'étudiant.
    # --------------------------------------------------------

    roles_demandes = normaliser_roles_academiques(
        roles_demandes
    )

    if not roles_demandes:

        await interaction.response.send_message(
            "❌ Sélectionnez au moins un rôle académique.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Vérification du salon CE AVANT d'enregistrer la demande.
    # --------------------------------------------------------

    salon_validation = (
        await recuperer_salon_validation(
            interaction.client
        )
    )

    if not isinstance(
        salon_validation,
        discord.TextChannel
    ):

        await interaction.response.send_message(
            "❌ **DEMANDE NON ENVOYÉE**\n\n"
            "Le salon interne de validation "
            "est actuellement indisponible.\n\n"
            "Aucune demande n'a été enregistrée.",
            ephemeral=True
        )

        return

    membre_bot = interaction.guild.me

    if membre_bot is None:

        await interaction.response.send_message(
            "❌ **DEMANDE NON ENVOYÉE**\n\n"
            "Impossible de vérifier les permissions "
            "du Bot ISIB.",
            ephemeral=True
        )

        return

    permissions = salon_validation.permissions_for(
        membre_bot
    )

    permissions_manquantes = []

    if not permissions.view_channel:

        permissions_manquantes.append(
            "Voir le salon"
        )

    if not permissions.send_messages:

        permissions_manquantes.append(
            "Envoyer des messages"
        )

    if not permissions.embed_links:

        permissions_manquantes.append(
            "Intégrer des liens"
        )

    if permissions_manquantes:

        print(
            "❌ Permissions manquantes dans "
            "#validation-inscriptions : "
            + ", ".join(
                permissions_manquantes
            )
        )

        await interaction.response.send_message(
            "❌ **DEMANDE NON ENVOYÉE**\n\n"
            "Le système interne de validation "
            "est momentanément indisponible.\n\n"
            "Aucune demande n'a été enregistrée.",
            ephemeral=True
        )

        return

    roles_actuels = (
        lire_roles_academiques_membre(
            interaction.user
        )
    )

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    request_id = creer_demande_academique(
        discord_user_id=interaction.user.id,
        nom=identite["nom"],
        prenom=identite["prenom"],
        email=identite["email"],
        roles_actuels=roles_actuels,
        roles_demandes=roles_demandes
    )

    demande = recuperer_demande(
        request_id
    )

    embed = construire_embed_validation(
        demande
    )

    try:

        message = await salon_validation.send(
            embed=embed,
            view=ValidationInscriptionView(
                request_id
            )
        )

    except discord.Forbidden as erreur:

        supprimer_demande_academique(
            request_id
        )

        print(
            "❌ Impossible d'envoyer la demande "
            "dans #validation-inscriptions :",
            erreur
        )

        await interaction.followup.send(
            "❌ **DEMANDE NON ENVOYÉE**\n\n"
            "Le bot ne possède pas les permissions "
            "nécessaires dans le salon interne.\n\n"
            "La demande n'a pas été conservée et "
            "vous pourrez réessayer.",
            ephemeral=True
        )

        return

    except discord.HTTPException as erreur:

        supprimer_demande_academique(
            request_id
        )

        print(
            "❌ Erreur Discord pendant "
            "l'envoi de la demande :",
            erreur
        )

        await interaction.followup.send(
            "❌ **DEMANDE NON ENVOYÉE**\n\n"
            "Discord a rencontré une erreur.\n\n"
            "La demande n'a pas été conservée "
            "et vous pouvez réessayer.",
            ephemeral=True
        )

        return

    enregistrer_message_validation(
        request_id=request_id,
        channel_id=salon_validation.id,
        message_id=message.id
    )

    await interaction.followup.send(
        "📩 **DEMANDE ENVOYÉE**\n\n"
        "Votre demande d'accès académique a bien "
        "été transmise au CE ISIB.\n\n"
        "Vos rôles ne changent pas tant que la "
        "demande n'est pas traitée.\n\n"
        "Vous recevrez un **message privé du Bot ISIB** "
        "après validation, modification ou refus.\n\n"
        "Vous pouvez introduire une autre demande si nécessaire ; "
        "chaque demande sera examinée séparément.",
        ephemeral=True
    )

    # Le panneau public reste fixe et épinglé.
    # L'étudiant peut revenir au même panneau pour introduire
    # une nouvelle demande, même si une précédente est en attente.


# ============================================================
# 7. VALIDATION INTERNE CE ISIB
# ============================================================


# ============================================================
# 7.1 FICHE DE VALIDATION
# ============================================================

def construire_embed_validation(
    demande
) -> discord.Embed:

    roles_actuels = normaliser_roles_academiques(
        json.loads(
            demande["current_roles_json"]
        )
    )

    roles_demandes = (
        roles_demandes_depuis_demande(
            demande
        )
    )

    a_retirer, a_ajouter, conserves = (
        calculer_modifications_roles(
            roles_actuels,
            roles_demandes
        )
    )

    embed = discord.Embed(
        title=(
            "🎓 DEMANDE D'ACCÈS ACADÉMIQUES"
        ),
        description=(
            "Chaque demande est indépendante. "
            "Si un même étudiant en envoie plusieurs, "
            "vérifiez leur ordre avant de valider afin que "
            "la décision la plus récente reste bien la situation finale."
        ),
        timestamp=datetime.fromtimestamp(
            demande["created_at"],
            timezone.utc
        )
    )

    embed.add_field(
        name="👤 Étudiant",
        value=(
            f"**Nom :** {demande['nom']}\n"
            f"**Prénom :** {demande['prenom']}\n"
            f"**Adresse mail :** {demande['email']}\n"
            f"**Compte Discord :** "
            f"<@{demande['discord_user_id']}>\n"
            f"**ID Discord :** "
            f"`{demande['discord_user_id']}`"
        ),
        inline=False
    )

    embed.add_field(
        name="📌 Situation au moment de la demande",
        value=formater_roles(
            roles_actuels
        ),
        inline=False
    )

    embed.add_field(
        name="🎓 Rôles demandés",
        value=formater_roles(
            roles_demandes
        ),
        inline=False
    )

    embed.add_field(
        name="➖ Rôles à retirer si validation",
        value=formater_roles(
            a_retirer,
            vide="• Aucun"
        ),
        inline=False
    )

    embed.add_field(
        name="➕ Rôles à ajouter si validation",
        value=formater_roles(
            a_ajouter,
            vide="• Aucun"
        ),
        inline=False
    )

    if conserves:

        embed.add_field(
            name="➡️ Rôles académiques conservés",
            value=formater_roles(
                conserves
            ),
            inline=False
        )

    statut = demande["status"]

    if statut == "pending":

        texte_statut = "🟠 EN ATTENTE"

    elif statut == "approved":

        texte_statut = "✅ VALIDÉE"

    elif statut == "corrected":

        texte_statut = (
            "✏️ MODIFIÉE ET VALIDÉE"
        )

    elif statut == "refused":

        texte_statut = "❌ REFUSÉE"

    else:

        texte_statut = statut

    embed.add_field(
        name="Statut",
        value=texte_statut,
        inline=False
    )

    if statut in {
        "approved",
        "corrected"
    }:

        roles_finaux = (
            roles_finaux_depuis_demande(
                demande
            )
        )

        embed.add_field(
            name="✅ Rôles finalement attribués",
            value=formater_roles(
                roles_finaux
            ),
            inline=False
        )

    if demande["reviewer_id"]:

        embed.add_field(
            name="Traité par",
            value=(
                f"<@{demande['reviewer_id']}>"
            ),
            inline=False
        )

    if demande["refusal_reason"]:

        embed.add_field(
            name="Motif du refus",
            value=demande["refusal_reason"],
            inline=False
        )

    embed.set_footer(
        text=(
            "Discord Étudiant ISIB | "
            f"Demande #{demande['id']}"
        )
    )

    return embed


async def mettre_a_jour_message_validation(
    client: discord.Client,
    request_id: int
):

    demande = recuperer_demande(
        request_id
    )

    if not demande:

        return

    channel_id = demande[
        "validation_channel_id"
    ]

    message_id = demande[
        "validation_message_id"
    ]

    if not (
        channel_id
        and message_id
    ):

        return

    salon = await recuperer_salon(
        client,
        channel_id
    )

    if not isinstance(
        salon,
        discord.TextChannel
    ):

        return

    try:

        message = await salon.fetch_message(
            message_id
        )

        await message.edit(
            embed=construire_embed_validation(
                demande
            ),
            view=None
        )

    except discord.HTTPException as erreur:

        print(
            "⚠️ Mise à jour fiche validation :",
            erreur
        )


# ============================================================
# 7.2 APPLICATION EXACTE DES RÔLES
# ============================================================

async def appliquer_roles_academiques(
    member: discord.Member,
    roles_finaux: list[str]
):

    roles_finaux = normaliser_roles_academiques(
        roles_finaux
    )

    noms_autorises = set(
        obtenir_tous_noms_roles_academiques()
    )

    if not set(
        roles_finaux
    ).issubset(
        noms_autorises
    ):

        return (
            False,
            "La demande contient un rôle académique non autorisé."
        )

    guild = member.guild

    roles_voulus = []
    roles_introuvables = []

    for nom_role in roles_finaux:

        role = discord.utils.get(
            guild.roles,
            name=nom_role
        )

        if role:

            roles_voulus.append(
                role
            )

        else:

            roles_introuvables.append(
                nom_role
            )

    if roles_introuvables:

        return (
            False,
            (
                "Rôles Discord introuvables : "
                + ", ".join(
                    roles_introuvables
                )
            )
        )

    roles_a_retirer = [
        role
        for role in member.roles
        if (
            role.name in noms_autorises
            and role not in roles_voulus
        )
    ]

    roles_a_ajouter = [
        role
        for role in roles_voulus
        if role not in member.roles
    ]

    # --------------------------------------------------------
    # Vérification de la hiérarchie AVANT toute modification.
    # Cela réduit fortement le risque de modification partielle.
    # --------------------------------------------------------

    bot_member = guild.me

    if bot_member is None:

        return (
            False,
            "Impossible d'identifier le rôle du Bot ISIB."
        )

    non_gerables = []

    for role in (
        roles_a_retirer
        + roles_a_ajouter
    ):

        if (
            role.managed
            or role >= bot_member.top_role
        ):

            non_gerables.append(
                role.name
            )

    if non_gerables:

        return (
            False,
            (
                "Le Bot ISIB ne peut pas gérer les rôles : "
                + ", ".join(
                    sorted(
                        set(
                            non_gerables
                        )
                    )
                )
                + ". Placez le rôle du bot au-dessus."
            )
        )

    # --------------------------------------------------------
    # On ajoute d'abord les nouveaux rôles.
    # Si cet ajout échoue, aucun ancien rôle n'est retiré.
    # --------------------------------------------------------

    try:

        if roles_a_ajouter:

            await member.add_roles(
                *roles_a_ajouter,
                reason=(
                    "Accès académiques validés par le CE ISIB"
                )
            )

    except (
        discord.Forbidden,
        discord.HTTPException
    ) as erreur:

        return (
            False,
            f"Impossible d'ajouter les nouveaux rôles : {erreur}"
        )

    # --------------------------------------------------------
    # Puis on retire les rôles académiques qui ne figurent
    # plus dans la liste finale.
    #
    # Le rôle de vérification n'est pas dans noms_autorises :
    # il ne peut donc jamais être retiré ici.
    # --------------------------------------------------------

    try:

        if roles_a_retirer:

            await member.remove_roles(
                *roles_a_retirer,
                reason=(
                    "Mise à jour des accès académiques "
                    "validée par le CE ISIB"
                )
            )

    except (
        discord.Forbidden,
        discord.HTTPException
    ) as erreur:

        # ----------------------------------------------------
        # Tentative de rollback des nouveaux rôles ajoutés.
        # ----------------------------------------------------

        if roles_a_ajouter:

            try:

                await member.remove_roles(
                    *roles_a_ajouter,
                    reason=(
                        "Rollback après échec de mise à jour "
                        "des accès académiques"
                    )
                )

            except discord.HTTPException:

                pass

        return (
            False,
            f"Impossible de retirer les anciens rôles : {erreur}"
        )

    return (
        True,
        None
    )


# ============================================================
# 7.3 VALIDATION ET NOTIFICATION
# ============================================================

async def notifier_validation_etudiant(
    member: discord.Member,
    roles_demandes: list[str],
    roles_finaux: list[str],
    correction=False
):

    if correction:

        texte = (
            "✏️ **DEMANDE ACADÉMIQUE MODIFIÉE ET VALIDÉE**\n\n"

            "Votre demande initiale était :\n"
            f"{formater_roles(roles_demandes)}\n\n"

            "Après vérification par le CE ISIB, "
            "les accès finalement retenus sont :\n"
            f"{formater_roles(roles_finaux)}\n\n"

            "Si vous pensez qu'il s'agit d'une erreur, "
            "contactez `isib-ce@he2b.be`."
        )

    else:

        texte = (
            "✅ **DEMANDE ACADÉMIQUE VALIDÉE**\n\n"

            "Votre demande a été validée.\n\n"

            "Vos accès académiques sont maintenant :\n"
            f"{formater_roles(roles_finaux)}\n\n"

        )

    try:

        await member.send(
            texte
        )

        return True

    except (
        discord.Forbidden,
        discord.HTTPException
    ):

        return False


async def traiter_validation_roles(
    interaction: discord.Interaction,
    request_id: int,
    roles_finaux: list[str],
    correction=False
):

    demande = recuperer_demande(
        request_id
    )

    if not demande:

        await interaction.followup.send(
            "❌ Demande introuvable.",
            ephemeral=True
        )

        return

    if demande["status"] != "pending":

        await interaction.followup.send(
            "⚠️ Cette demande a déjà été traitée.",
            ephemeral=True
        )

        return

    if not interaction.guild:

        await interaction.followup.send(
            "❌ Serveur Discord introuvable.",
            ephemeral=True
        )

        return

    roles_finaux = normaliser_roles_academiques(
        roles_finaux
    )

    if not roles_finaux:

        await interaction.followup.send(
            "❌ Aucun rôle académique final sélectionné.",
            ephemeral=True
        )

        return

    member = interaction.guild.get_member(
        demande["discord_user_id"]
    )

    if member is None:

        try:

            member = await interaction.guild.fetch_member(
                demande["discord_user_id"]
            )

        except discord.HTTPException:

            await interaction.followup.send(
                "❌ Cet étudiant n'est plus "
                "présent sur le serveur.",
                ephemeral=True
            )

            return

    succes, erreur = await appliquer_roles_academiques(
        member,
        roles_finaux
    )

    if not succes:

        await interaction.followup.send(
            "❌ **ATTRIBUTION DES RÔLES IMPOSSIBLE**\n\n"
            f"{erreur}",
            ephemeral=True
        )

        return

    statut = (
        "corrected"
        if correction
        else "approved"
    )

    enregistrer_decision(
        request_id=request_id,
        statut=statut,
        reviewer_id=interaction.user.id,
        final_roles=roles_finaux
    )

    await mettre_a_jour_message_validation(
        interaction.client,
        request_id
    )

    roles_demandes = (
        roles_demandes_depuis_demande(
            demande
        )
    )

    dm_envoye = await notifier_validation_etudiant(
        member=member,
        roles_demandes=roles_demandes,
        roles_finaux=roles_finaux,
        correction=correction
    )

    texte_confirmation = (
        "✅ **DEMANDE TRAITÉE**\n\n"
        "Les rôles académiques ont été mis à jour "
        "selon la liste finale."
    )

    if not dm_envoye:

        texte_confirmation += (
            "\n\n⚠️ Impossible d'envoyer un DM "
            "à l'étudiant. Il peut utiliser "
            "`/statut_inscription`."
        )

    await interaction.followup.send(
        texte_confirmation,
        ephemeral=True
    )


# ============================================================
# 7.4 BOUTONS VALIDER / MODIFIER / REFUSER
# ============================================================

class ValidationInscriptionView(
    discord.ui.View
):

    def __init__(
        self,
        request_id: int
    ):

        super().__init__(
            timeout=None
        )

        self.request_id = request_id

        bouton_valider = discord.ui.Button(
            label="VALIDER",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=(
                f"academic_approve_{request_id}"
            )
        )

        bouton_modifier = discord.ui.Button(
            label="MODIFIER",
            emoji="✏️",
            style=discord.ButtonStyle.primary,
            custom_id=(
                f"academic_correct_{request_id}"
            )
        )

        bouton_refuser = discord.ui.Button(
            label="REFUSER",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=(
                f"academic_refuse_{request_id}"
            )
        )

        bouton_valider.callback = (
            self.valider
        )

        bouton_modifier.callback = (
            self.modifier
        )

        bouton_refuser.callback = (
            self.refuser
        )

        self.add_item(
            bouton_valider
        )

        self.add_item(
            bouton_modifier
        )

        self.add_item(
            bouton_refuser
        )

    def permission_ok(
        self,
        interaction: discord.Interaction
    ) -> bool:

        return (
            isinstance(
                interaction.user,
                discord.Member
            )
            and utilisateur_peut_valider_inscription(
                interaction.user
            )
        )

    async def valider(
        self,
        interaction: discord.Interaction
    ):

        if not self.permission_ok(
            interaction
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        demande = recuperer_demande(
            self.request_id
        )

        if not demande:

            await interaction.response.send_message(
                "❌ Demande introuvable.",
                ephemeral=True
            )

            return

        roles_demandes = (
            roles_demandes_depuis_demande(
                demande
            )
        )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await traiter_validation_roles(
            interaction=interaction,
            request_id=self.request_id,
            roles_finaux=roles_demandes,
            correction=False
        )

    async def modifier(
        self,
        interaction: discord.Interaction
    ):

        if not self.permission_ok(
            interaction
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        demande = recuperer_demande(
            self.request_id
        )

        if (
            not demande
            or demande["status"] != "pending"
        ):

            await interaction.response.send_message(
                "⚠️ Cette demande a déjà été traitée.",
                ephemeral=True
            )

            return

        roles_demandes = (
            roles_demandes_depuis_demande(
                demande
            )
        )

        roles_actuels = []

        try:

            roles_actuels = normaliser_roles_academiques(
                json.loads(
                    demande["current_roles_json"]
                )
            )

        except (
            json.JSONDecodeError,
            TypeError
        ):

            roles_actuels = []

        etat = EtatSelectionRoles(
            roles_selectionnes=roles_demandes,
            roles_actuels=roles_actuels
        )

        await interaction.response.send_message(
            texte_interface_selection(
                etat,
                "✏️ **MODIFICATION DE LA DEMANDE PAR LE CE ISIB**"
            ),
            view=SelectionRolesView(
                etat=etat,
                mode="ce",
                request_id=self.request_id
            ),
            ephemeral=True
        )

    async def refuser(
        self,
        interaction: discord.Interaction
    ):

        if not self.permission_ok(
            interaction
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        demande = recuperer_demande(
            self.request_id
        )

        if (
            not demande
            or demande["status"] != "pending"
        ):

            await interaction.response.send_message(
                "⚠️ Cette demande a déjà été traitée.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            RefusInscriptionModal(
                self.request_id
            )
        )


# ============================================================
# 7.5 MODIFICATION CE PAR BOUTONS COCHABLES
# ============================================================
#
# La même interface paginée que celle de l'étudiant est
# réutilisée côté CE.
#
# Les rôles demandés sont pré-cochés en vert.
# Le CE peut :
# - en ajouter ;
# - en retirer ;
# - garder plusieurs années / orientations ;
# puis cliquer sur VALIDER LA MODIFICATION.
#
# ============================================================


# ============================================================
# 7.6 REFUS
# ============================================================

class RefusInscriptionModal(
    discord.ui.Modal,
    title="Refuser la demande académique"
):

    motif = discord.ui.TextInput(
        label="Motif du refus",
        placeholder=(
            "Expliquez brièvement le motif "
            "si nécessaire."
        ),
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph
    )

    def __init__(
        self,
        request_id: int
    ):

        super().__init__()

        self.request_id = request_id

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        if not (
            isinstance(
                interaction.user,
                discord.Member
            )
            and utilisateur_peut_valider_inscription(
                interaction.user
            )
        ):

            await interaction.response.send_message(
                "❌ Permission insuffisante.",
                ephemeral=True
            )

            return

        demande = recuperer_demande(
            self.request_id
        )

        if not demande:

            await interaction.response.send_message(
                "❌ Demande introuvable.",
                ephemeral=True
            )

            return

        if demande["status"] != "pending":

            await interaction.response.send_message(
                "⚠️ Cette demande a déjà été traitée.",
                ephemeral=True
            )

            return

        motif = (
            self.motif.value.strip()
            or "Aucun motif précisé."
        )

        enregistrer_decision(
            request_id=self.request_id,
            statut="refused",
            reviewer_id=interaction.user.id,
            final_roles=None,
            refusal_reason=motif
        )

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await mettre_a_jour_message_validation(
            interaction.client,
            self.request_id
        )

        member = None

        if interaction.guild:

            member = interaction.guild.get_member(
                demande["discord_user_id"]
            )

        if (
            member is None
            and interaction.guild
        ):

            try:

                member = await interaction.guild.fetch_member(
                    demande["discord_user_id"]
                )

            except discord.HTTPException:

                member = None

        dm_envoye = False

        if member:

            try:

                await member.send(
                    "❌ **DEMANDE ACADÉMIQUE REFUSÉE**\n\n"

                    "Votre demande d'accès académique "
                    "n'a pas été validée.\n\n"

                    f"**Motif :** {motif}\n\n"

                    "Aucun de vos rôles académiques "
                    "actuels n'a été modifié.\n\n"

                    "Si vous pensez qu'il s'agit d'une erreur, "
                    "contactez `isib-ce@he2b.be`."
                )

                dm_envoye = True

            except (
                discord.Forbidden,
                discord.HTTPException
            ):

                pass

        texte = (
            "✅ Demande refusée.\n\n"
            "Aucun rôle académique n'a été modifié."
        )

        if not dm_envoye:

            texte += (
                "\n\n⚠️ Impossible d'envoyer "
                "un message privé à l'étudiant."
            )

        await interaction.followup.send(
            texte,
            ephemeral=True
        )


# ============================================================
# 8. PANNEAU D'INSCRIPTION ACADÉMIQUE
# ============================================================


# ============================================================
# 8.1 BOUTON PUBLIC
# ============================================================

class InscriptionAcademiqueView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="CHOISIR MES ACCÈS ACADÉMIQUES",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="isib_academic_start"
    )
    async def commencer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not (
            interaction.guild
            and isinstance(
                interaction.user,
                discord.Member
            )
        ):

            return

        role_verifie = trouver_role_etudiant_verifie(
            interaction.guild
        )

        if (
            not role_verifie
            or role_verifie not in interaction.user.roles
        ):

            await interaction.response.send_message(
                "🔒 **AUTHENTIFICATION REQUISE**\n\n"
                "Vous devez d'abord effectuer votre "
                "authentification dans `#verification`.",
                ephemeral=True
            )

            return

        identite = recuperer_etudiant_authentifie(
            interaction.user.id
        )

        if not identite:

            await interaction.response.send_message(
                "⚠️ Votre rôle de vérification est présent, "
                "mais votre identité n'existe pas dans "
                "la base du bot.\n\n"
                "Relancez une authentification dans "
                "`#verification`.",
                ephemeral=True
            )

            return

        # Les demandes successives sont autorisées.
        # Aucune demande en attente ne bloque l'ouverture
        # d'une nouvelle sélection académique.

        roles_actuels = (
            lire_roles_academiques_membre(
                interaction.user
            )
        )

        # ----------------------------------------------------
        # Les rôles actuels sont pré-cochés.
        #
        # L'étudiant peut donc :
        # - les laisser cochés pour les conserver ;
        # - les décocher pour demander leur retrait ;
        # - cocher de nouveaux rôles ;
        # - garder plusieurs années simultanément.
        # ----------------------------------------------------

        etat = EtatSelectionRoles(
            roles_selectionnes=roles_actuels,
            roles_actuels=roles_actuels
        )

        await interaction.response.send_message(
            texte_interface_selection(
                etat,
                "🎓 **SÉLECTION DE VOS RÔLES ACADÉMIQUES**"
            ),
            view=SelectionRolesView(
                etat=etat,
                mode="student"
            ),
            ephemeral=True
        )


# ============================================================
# 8.2 EMBED PUBLIC
# ============================================================

def creer_embed_inscription():

    embed = discord.Embed(
        title=TITRE_PANNEAU_INSCRIPTION,

        description=(
            "Choisissez directement les rôles académiques "
            "correspondant aux espaces auxquels vous devez "
            "avoir accès :\n\n"

            "1. Ouvrez votre sélection académique\n"
            "2. Vos rôles actuels sont déjà cochés en vert\n"
            "3. Naviguez entre les pages BAPSIE, B1 ING, "
            "B2 ING, B3 & BC ING, M1 ING et M2 ING\n"
            "4. Cliquez directement sur les rôles pour "
            "les cocher ou les décocher\n"
            "5. Plusieurs niveaux peuvent être demandés "
            "si vous avez des cours sur plusieurs années ; "
            "la demande sera vérifiée par le CE ISIB\n"
            "6. Envoyez votre demande\n"
            "7. Vous pouvez introduire une nouvelle demande "
            "si votre situation évolue, même si une précédente "
            "est encore en attente\n"
            "8. Vous recevrez une validation, une modification "
            "ou un refus pour chaque demande\n\n"

            "🔵 CE ISIB | Conseil Étudiant ISIB\n"
            "📩 isib-ce@he2b.be\n"
            "💻 ISIBnet : Conseil Étudiant ISIB\n"
            "📸 Instagram : @cehe2b_isib\n"
            "🌐 https://www.cehe2b.be/"
        )
    )

    embed.set_footer(
        text=(
            "Discord Étudiant ISIB | "
            "Conseil Étudiant ISIB - HE2B"
        )
    )

    return embed


async def publier_panneau_inscription(
    channel: discord.TextChannel
):

    message = await channel.send(
        embed=creer_embed_inscription(),
        view=InscriptionAcademiqueView()
    )

    await epingler_panneau(
        message
    )

    return message


async def replacer_panneau_inscription(
    channel: discord.TextChannel
):

    messages_a_supprimer = []

    async for message in channel.history(
        limit=100
    ):

        if not (
            bot.user
            and message.author.id == bot.user.id
        ):

            continue

        for embed in message.embeds:

            if (
                embed.title
                == TITRE_PANNEAU_INSCRIPTION
            ):

                messages_a_supprimer.append(
                    message
                )

                break

    for message in messages_a_supprimer:

        try:

            await message.delete()

        except discord.HTTPException:

            pass

    nouveau = await publier_panneau_inscription(
        channel
    )

    print(
        "✅ Panneau d'inscription "
        "replacé en bas."
    )

    return nouveau


# ============================================================
# 9. BOT DISCORD
# ============================================================

class ISIBBot(
    discord.Client
):

    def __init__(self):

        super().__init__(
            intents=intents
        )

        self.tree = app_commands.CommandTree(
            self
        )

    async def setup_hook(self):

        # ----------------------------------------------------
        # Base de données (crée les tables si absentes).
        # ----------------------------------------------------

        initialiser_base_de_donnees()

        # ----------------------------------------------------
        # Nettoyage des demandes académiques orphelines.
        #
        # Une demande orpheline est une ancienne demande
        # enregistrée comme "pending" mais qui n'a jamais
        # réussi à produire de message dans le salon CE.
        # ----------------------------------------------------

        nettoyer_demandes_orphelines()

        # ----------------------------------------------------
        # Boutons publics persistants.
        # ----------------------------------------------------

        self.add_view(
            VerificationView()
        )

        self.add_view(
            InscriptionAcademiqueView()
        )

        # ----------------------------------------------------
        # Réactivation automatique des boutons
        # VALIDATION / MODIFICATION / REFUS après redémarrage.
        # ----------------------------------------------------

        for demande in recuperer_demandes_en_attente():

            self.add_view(
                ValidationInscriptionView(
                    demande["id"]
                )
            )

        guild = discord.Object(
            id=GUILD_ID
        )

        self.tree.copy_global_to(
            guild=guild
        )

        await self.tree.sync(
            guild=guild
        )

        print(
            "✅ Commandes Discord synchronisées."
        )


bot = ISIBBot()


@bot.event
async def on_ready():

    print()
    print(
        "----------------------------------------"
    )

    print(
        "✅ Bot ISIB connecté"
    )

    print(
        f"Nom : {bot.user}"
    )

    print(
        f"ID  : {bot.user.id}"
    )

    print(
        "----------------------------------------"
    )


# ============================================================
# 10. COMMANDES
# ============================================================


# ============================================================
# 10.1 /PING
# ============================================================

@bot.tree.command(
    name="ping",
    description="Vérifie que le Bot ISIB fonctionne."
)
async def ping(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        "✅ **Bot ISIB - HE2B opérationnel.**",
        ephemeral=True
    )


# ============================================================
# 10.2 /TEST_AUDIT
# ============================================================

@bot.tree.command(
    name="test_audit",
    description="Teste le salon d'audit."
)
async def test_audit(
    interaction: discord.Interaction
):

    if not (
        isinstance(
            interaction.user,
            discord.Member
        )
        and utilisateur_est_admin_bot(
            interaction.user
        )
    ):

        await interaction.response.send_message(
            "❌ Permission insuffisante.",
            ephemeral=True
        )

        return

    salon = await recuperer_salon_audit(
        interaction.client
    )

    if not isinstance(
        salon,
        discord.TextChannel
    ):

        await interaction.response.send_message(
            "❌ Salon d'audit introuvable.",
            ephemeral=True
        )

        return

    await salon.send(
        "🧪 **TEST DU SYSTÈME D'AUDIT**\n\n"
        f"Test effectué par "
        f"{interaction.user.mention}."
    )

    await interaction.response.send_message(
        "✅ Test envoyé.",
        ephemeral=True
    )


# ============================================================
# 10.3 /INSTALLER_VERIFICATION
# ============================================================

@bot.tree.command(
    name="installer_verification",

    description=(
        "Installe ou replace le panneau "
        "d'authentification."
    )
)
async def installer_verification(
    interaction: discord.Interaction
):

    if not (
        isinstance(
            interaction.user,
            discord.Member
        )
        and utilisateur_est_admin_bot(
            interaction.user
        )
    ):

        await interaction.response.send_message(
            "❌ Permission insuffisante.",
            ephemeral=True
        )

        return

    if not isinstance(
        interaction.channel,
        discord.TextChannel
    ):

        await interaction.response.send_message(
            "❌ Utilisez cette commande "
            "dans un salon textuel.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    await replacer_panneau_verification(
        interaction.channel
    )

    await interaction.followup.send(
        "✅ Panneau d'authentification installé et épinglé "
        "si le bot possède la permission nécessaire.",
        ephemeral=True
    )


# ============================================================
# 10.4 /INSTALLER_INSCRIPTION
# ============================================================

@bot.tree.command(
    name="installer_inscription",

    description=(
        "Installe ou replace le panneau "
        "d'inscription académique."
    )
)
async def installer_inscription(
    interaction: discord.Interaction
):

    if not (
        isinstance(
            interaction.user,
            discord.Member
        )
        and utilisateur_est_admin_bot(
            interaction.user
        )
    ):

        await interaction.response.send_message(
            "❌ Permission insuffisante.",
            ephemeral=True
        )

        return

    if not isinstance(
        interaction.channel,
        discord.TextChannel
    ):

        await interaction.response.send_message(
            "❌ Utilisez cette commande "
            "dans un salon textuel.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    await replacer_panneau_inscription(
        interaction.channel
    )

    await interaction.followup.send(
        "✅ Panneau d'inscription académique installé et "
        "épinglé si le bot possède la permission nécessaire.",
        ephemeral=True
    )


# ============================================================
# 10.5 /STATUT_INSCRIPTION
# ============================================================

@bot.tree.command(
    name="statut_inscription",

    description=(
        "Affiche le statut de votre dernière "
        "demande académique."
    )
)
async def statut_inscription(
    interaction: discord.Interaction
):

    demande = recuperer_derniere_demande_etudiant(
        interaction.user.id
    )

    if not demande:

        await interaction.response.send_message(
            "ℹ️ Vous n'avez encore effectué "
            "aucune demande académique.",
            ephemeral=True
        )

        return

    statut = demande["status"]

    roles_demandes = (
        roles_demandes_depuis_demande(
            demande
        )
    )

    if statut == "pending":

        texte = (
            "⏳ **DEMANDE EN ATTENTE**\n\n"
            "Votre dernière demande est "
            "en cours de validation.\n\n"

            "**Rôles demandés :**\n"
            f"{formater_roles(roles_demandes)}"
        )

    elif statut == "approved":

        roles_finaux = (
            roles_finaux_depuis_demande(
                demande
            )
        )

        texte = (
            "✅ **DERNIÈRE DEMANDE VALIDÉE**\n\n"

            "**Rôles académiques validés :**\n"
            f"{formater_roles(roles_finaux)}"
        )

    elif statut == "corrected":

        roles_finaux = (
            roles_finaux_depuis_demande(
                demande
            )
        )

        texte = (
            "✏️ **DERNIÈRE DEMANDE "
            "MODIFIÉE ET VALIDÉE**\n\n"

            "**Votre demande initiale :**\n"
            f"{formater_roles(roles_demandes)}\n\n"

            "**Rôles finalement validés :**\n"
            f"{formater_roles(roles_finaux)}"
        )

    elif statut == "refused":

        texte = (
            "❌ **DERNIÈRE DEMANDE REFUSÉE**\n\n"

            "**Rôles demandés :**\n"
            f"{formater_roles(roles_demandes)}\n\n"

            f"**Motif :** "
            f"{demande['refusal_reason'] or 'Non précisé'}\n\n"

            "Vos rôles académiques précédents "
            "ont été conservés."
        )

    else:

        texte = (
            f"Statut : {statut}"
        )

    await interaction.response.send_message(
        texte,
        ephemeral=True
    )


# ============================================================
# 11. DÉMARRAGE
# ============================================================
#
# Un mini serveur web (aiohttp) tourne en parallèle du bot.
#
# Il ne sert à rien pour Discord : il existe uniquement pour
# satisfaire Render, qui exige qu'un "Web Service" réponde sur
# le port $PORT, et pour permettre à un service externe de
# "ping" régulièrement l'app afin d'empêcher le plan gratuit
# de se mettre en veille après 15 minutes d'inactivité.
#
# Voir README.md, section "Déploiement 24h/24 gratuit".
# ============================================================

from aiohttp import web


async def page_accueil(request):

    return web.Response(
        text="✅ Bot ISIB en ligne."
    )


async def demarrer_serveur_web():

    app = web.Application()

    app.router.add_get(
        "/",
        page_accueil
    )

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(
        os.getenv("PORT", 10000)
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        f"✅ Serveur web (keep-alive) démarré sur le port {port}."
    )


async def main():

    await demarrer_serveur_web()

    async with bot:

        await bot.start(TOKEN)


asyncio.run(main())
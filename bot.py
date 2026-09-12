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
# 6. INSCRIPTIONS ACADÉMIQUES
#    6.1 Profils académiques
#    6.2 Lecture des rôles académiques actuels
#    6.3 Choix du cursus
#    6.4 Choix de l'année/niveau
#    6.5 Choix de l'orientation
#    6.6 Récapitulatif
#    6.7 Création de la demande
#
# 7. VALIDATION INTERNE CE ISIB
#    7.1 Fiche de validation
#    7.2 Application d'un profil
#    7.3 Validation
#    7.4 Correction
#    7.5 Refus
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

DATABASE_URL = os.getenv("DATABASE_URL")


VARIABLES_OBLIGATOIRES = {
    "DISCORD_TOKEN": TOKEN,
    "GUILD_ID": GUILD_ID,
    "BREVO_API_KEY": BREVO_API_KEY,
    "EMAIL_SENDER": EMAIL_SENDER,
    "EMAIL_SENDER_NAME": EMAIL_SENDER_NAME,
    "AUDIT_CHANNEL_ID": AUDIT_CHANNEL_ID,
    "VALIDATION_CHANNEL_ID": VALIDATION_CHANNEL_ID,
    "DATABASE_URL": DATABASE_URL,
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
        DATABASE_URL,
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
    # Historique permanent des demandes académiques.
    #
    # current_roles_json :
    # rôles académiques réellement possédés au moment
    # où la demande a été introduite.
    #
    # requested_profile_key :
    # ce que l'étudiant a demandé.
    #
    # final_profile_key :
    # ce que le CE a finalement validé.
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
    profile_key: str
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
            status,
            created_at
        )

        VALUES (%s, %s, %s, %s, %s, %s, NULL, 'pending', %s)

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
            profile_key,
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


def recuperer_demande_en_attente_etudiant(
    discord_user_id: int
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        SELECT *
        FROM academic_requests

        WHERE discord_user_id = %s
        AND status = 'pending'

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


def enregistrer_decision(
    request_id: int,
    statut: str,
    reviewer_id: int,
    final_profile_key=None,
    refusal_reason=None
):

    connexion = connexion_db()
    curseur = connexion.cursor()

    curseur.execute(
        """
        UPDATE academic_requests

        SET
            status = %s,
            reviewer_id = %s,
            reviewed_at = %s,
            final_profile_key = %s,
            refusal_reason = %s

        WHERE id = %s
        """,
        (
            statut,
            reviewer_id,
            time.time(),
            final_profile_key,
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

        if isinstance(
            interaction.channel,
            discord.TextChannel
        ):

            try:

                await replacer_panneau_verification(
                    interaction.channel
                )

            except discord.HTTPException as erreur:

                print(
                    "⚠️ Replacement du panneau "
                    "de vérification impossible :",
                    erreur
                )


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
        placeholder="prenom.nom@etu.he2b.be",
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
        # ----------------------------------------------------

        if not email.endswith(
            "@etu.he2b.be"
        ):

            await interaction.response.send_message(
                "❌ **ADRESSE MAIL NON VALIDE**\n\n"
                "L'adresse doit se terminer par "
                "`@etu.he2b.be`.",
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
            "3. Un code temporaire sera envoyé par mail, "
            "entrez ensuite le code reçu.\n"
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

    return await channel.send(
        embed=creer_embed_verification(),
        view=VerificationView()
    )


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
# 6. INSCRIPTIONS ACADÉMIQUES
# ============================================================


# ============================================================
# 6.1 PROFILS ACADÉMIQUES
# ============================================================
#
# ATTENTION :
# les chaînes placées dans "roles" doivent porter
# EXACTEMENT le même nom que les rôles Discord.
#
# Si un rôle sur ton Discord s'appelle différemment,
# il suffit de modifier son nom ici.
#
# ============================================================

PROFILS_ACADEMIQUES = {

    # --------------------------------------------------------
    # BAPSIE
    # --------------------------------------------------------

    "bapsie_b1": {
        "cursus": "BAPSIE",
        "niveau": "B1",
        "option": None,
        "roles": [
            "B1 BAPSIE"
        ]
    },

    "bapsie_b2": {
        "cursus": "BAPSIE",
        "niveau": "B2",
        "option": None,
        "roles": [
            "B2 BAPSIE"
        ]
    },

    "bapsie_b3": {
        "cursus": "BAPSIE",
        "niveau": "B3",
        "option": None,
        "roles": [
            "B3 BAPSIE"
        ]
    },


    # --------------------------------------------------------
    # INGÉNIERIE - B1
    # --------------------------------------------------------

    "ing_b1": {
        "cursus": "Ingénierie",
        "niveau": "B1",
        "option": None,
        "roles": [
            "B1 INGÉNIERIE"
        ]
    },


    # --------------------------------------------------------
    # INGÉNIERIE - B2
    # --------------------------------------------------------

    "ing_b2_chimie": {
        "cursus": "Ingénierie",
        "niveau": "B2",
        "option": "Chimie",
        "roles": [
            "B2 INGÉNIERIE",
            "B2 CHIMIE"
        ]
    },

    "ing_b2_physique": {
        "cursus": "Ingénierie",
        "niveau": "B2",
        "option": "Physique",
        "roles": [
            "B2 INGÉNIERIE",
            "B2 PHYSIQUE"
        ]
    },

    "ing_b2_mecanique": {
        "cursus": "Ingénierie",
        "niveau": "B2",
        "option": "Mécanique",
        "roles": [
            "B2 INGÉNIERIE",
            "B2 MÉCANIQUE"
        ]
    },

    "ing_b2_eei": {
        "cursus": "Ingénierie",
        "niveau": "B2",
        "option": (
            "Électricité - Électronique - Informatique"
        ),
        "roles": [
            "B2 INGÉNIERIE",
            "B2 ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE"
        ]
    },


    # --------------------------------------------------------
    # INGÉNIERIE - B3 & BC
    # --------------------------------------------------------

    "ing_b3bc_chimie": {
        "cursus": "Ingénierie",
        "niveau": "B3 & BC",
        "option": "Chimie",
        "roles": [
            "B3 & BC INGÉNIERIE",
            "B3 & BC CHIMIE"
        ]
    },

    "ing_b3bc_physique": {
        "cursus": "Ingénierie",
        "niveau": "B3 & BC",
        "option": "Physique",
        "roles": [
            "B3 & BC INGÉNIERIE",
            "B3 & BC PHYSIQUE"
        ]
    },

    "ing_b3bc_mecanique": {
        "cursus": "Ingénierie",
        "niveau": "B3 & BC",
        "option": "Mécanique",
        "roles": [
            "B3 & BC INGÉNIERIE",
            "B3 & BC MÉCANIQUE"
        ]
    },

    "ing_b3bc_eei": {
        "cursus": "Ingénierie",
        "niveau": "B3 & BC",
        "option": (
            "Électricité - Électronique - Informatique"
        ),
        "roles": [
            "B3 & BC INGÉNIERIE",
            "B3 & BC ÉLECTRICITÉ - ÉLECTRONIQUE - INFORMATIQUE"
        ]
    },


    # --------------------------------------------------------
    # INGÉNIERIE - M1
    # --------------------------------------------------------

    "ing_m1_chimie": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Chimie",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 CHIMIE"
        ]
    },

    "ing_m1_physique": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Physique",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 PHYSIQUE"
        ]
    },

    "ing_m1_mecanique": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Mécanique",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 MÉCANIQUE"
        ]
    },

    "ing_m1_electricite": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Électricité",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 ÉLECTRICITÉ"
        ]
    },

    "ing_m1_electronique": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Électronique",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 ÉLECTRONIQUE"
        ]
    },

    "ing_m1_informatique": {
        "cursus": "Ingénierie",
        "niveau": "M1",
        "option": "Informatique",
        "roles": [
            "M1 INGÉNIERIE",
            "M1 INFORMATIQUE"
        ]
    },


    # --------------------------------------------------------
    # INGÉNIERIE - M2
    # --------------------------------------------------------

    "ing_m2_chimie": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Chimie",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 CHIMIE"
        ]
    },

    "ing_m2_physique": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Physique",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 PHYSIQUE"
        ]
    },

    "ing_m2_mecanique": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Mécanique",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 MÉCANIQUE"
        ]
    },

    "ing_m2_electricite": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Électricité",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 ÉLECTRICITÉ"
        ]
    },

    "ing_m2_electronique": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Électronique",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 ÉLECTRONIQUE"
        ]
    },

    "ing_m2_informatique": {
        "cursus": "Ingénierie",
        "niveau": "M2",
        "option": "Informatique",
        "roles": [
            "M2 INGÉNIERIE",
            "M2 INFORMATIQUE"
        ]
    },
}


# ============================================================
# 6.2 LECTURE DES RÔLES ACADÉMIQUES ACTUELS
# ============================================================

def obtenir_tous_noms_roles_academiques():

    noms = set()

    for profil in PROFILS_ACADEMIQUES.values():

        noms.update(
            profil["roles"]
        )

    return noms


def lire_roles_academiques_membre(
    member: discord.Member
) -> list[str]:

    noms_roles_academiques = (
        obtenir_tous_noms_roles_academiques()
    )

    roles_trouves = [
        role.name
        for role in member.roles
        if role.name in noms_roles_academiques
    ]

    return roles_trouves


def description_profil(
    profile_key: str
) -> str:

    profil = PROFILS_ACADEMIQUES[
        profile_key
    ]

    texte = (
        f"{profil['niveau']} "
        f"{profil['cursus']}"
    )

    if profil["option"]:

        texte += (
            f" — {profil['option']}"
        )

    return texte


def trouver_profile_key(
    cursus: str,
    niveau: str,
    option=None
):

    for cle, profil in PROFILS_ACADEMIQUES.items():

        if (
            profil["cursus"] == cursus
            and profil["niveau"] == niveau
            and profil["option"] == option
        ):

            return cle

    return None


def calculer_modifications_roles(
    roles_actuels: list[str],
    roles_demandes: list[str]
):

    anciens = set(
        roles_actuels
    )

    nouveaux = set(
        roles_demandes
    )

    a_retirer = sorted(
        anciens - nouveaux
    )

    a_ajouter = sorted(
        nouveaux - anciens
    )

    conserves = sorted(
        anciens & nouveaux
    )

    return (
        a_retirer,
        a_ajouter,
        conserves
    )


# ============================================================
# 6.3 CHOIX DU CURSUS
# ============================================================

class CursusSelect(
    discord.ui.Select
):

    def __init__(self):

        super().__init__(
            placeholder="Sélectionnez votre cursus",
            min_values=1,
            max_values=1,

            options=[
                discord.SelectOption(
                    label="Ingénierie",
                    value="Ingénierie",
                    emoji="⚙️"
                ),

                discord.SelectOption(
                    label="BAPSIE",
                    value="BAPSIE",
                    emoji="🎓"
                ),
            ]
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        cursus = self.values[0]

        await interaction.response.edit_message(
            content=(
                "🎓 **INSCRIPTION ACADÉMIQUE**\n\n"
                f"Cursus sélectionné : **{cursus}**\n\n"
                "Sélectionnez maintenant votre niveau :"
            ),

            view=NiveauView(
                cursus
            )
        )


class CursusView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )

        self.add_item(
            CursusSelect()
        )


# ============================================================
# 6.4 CHOIX DU NIVEAU
# ============================================================

class NiveauSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cursus: str
    ):

        self.cursus = cursus

        if cursus == "BAPSIE":

            niveaux = [
                "B1",
                "B2",
                "B3"
            ]

        else:

            niveaux = [
                "B1",
                "B2",
                "B3 & BC",
                "M1",
                "M2"
            ]

        super().__init__(
            placeholder="Sélectionnez votre niveau",
            min_values=1,
            max_values=1,

            options=[
                discord.SelectOption(
                    label=niveau,
                    value=niveau
                )

                for niveau in niveaux
            ]
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        niveau = self.values[0]

        # ----------------------------------------------------
        # BAPSIE n'a pas de choix d'orientation ici.
        # ----------------------------------------------------

        if self.cursus == "BAPSIE":

            profile_key = trouver_profile_key(
                "BAPSIE",
                niveau,
                None
            )

            await afficher_recapitulatif_inscription(
                interaction,
                profile_key
            )

            return

        # ----------------------------------------------------
        # B1 Ingénierie n'a pas encore de spécialisation.
        # ----------------------------------------------------

        if (
            self.cursus == "Ingénierie"
            and niveau == "B1"
        ):

            profile_key = trouver_profile_key(
                "Ingénierie",
                "B1",
                None
            )

            await afficher_recapitulatif_inscription(
                interaction,
                profile_key
            )

            return

        # ----------------------------------------------------
        # Les autres niveaux nécessitent une orientation.
        # ----------------------------------------------------

        await interaction.response.edit_message(
            content=(
                "🎓 **INSCRIPTION ACADÉMIQUE**\n\n"
                f"Cursus : **{self.cursus}**\n"
                f"Niveau : **{niveau}**\n\n"
                "Sélectionnez votre orientation :"
            ),

            view=OrientationView(
                self.cursus,
                niveau
            )
        )


class NiveauView(
    discord.ui.View
):

    def __init__(
        self,
        cursus: str
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            NiveauSelect(
                cursus
            )
        )


# ============================================================
# 6.5 CHOIX DE L'ORIENTATION
# ============================================================

class OrientationSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cursus: str,
        niveau: str
    ):

        self.cursus = cursus
        self.niveau = niveau

        if niveau in {
            "B2",
            "B3 & BC"
        }:

            orientations = [
                "Chimie",
                "Physique",
                "Mécanique",
                "Électricité - Électronique - Informatique",
            ]

        else:

            orientations = [
                "Chimie",
                "Physique",
                "Mécanique",
                "Électricité",
                "Électronique",
                "Informatique",
            ]

        super().__init__(
            placeholder="Sélectionnez votre orientation",
            min_values=1,
            max_values=1,

            options=[
                discord.SelectOption(
                    label=orientation,
                    value=orientation
                )

                for orientation in orientations
            ]
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        orientation = self.values[0]

        profile_key = trouver_profile_key(
            self.cursus,
            self.niveau,
            orientation
        )

        if not profile_key:

            await interaction.response.send_message(
                "❌ Profil académique introuvable.",
                ephemeral=True
            )

            return

        await afficher_recapitulatif_inscription(
            interaction,
            profile_key
        )


class OrientationView(
    discord.ui.View
):

    def __init__(
        self,
        cursus: str,
        niveau: str
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            OrientationSelect(
                cursus,
                niveau
            )
        )


# ============================================================
# 6.6 RÉCAPITULATIF
# ============================================================

async def afficher_recapitulatif_inscription(
    interaction: discord.Interaction,
    profile_key: str
):

    profil = PROFILS_ACADEMIQUES[
        profile_key
    ]

    roles_actuels = []

    if isinstance(
        interaction.user,
        discord.Member
    ):

        roles_actuels = (
            lire_roles_academiques_membre(
                interaction.user
            )
        )

    roles_demandes = profil[
        "roles"
    ]

    texte_actuel = (
        "\n".join(
            f"• `{role}`"
            for role in roles_actuels
        )

        if roles_actuels

        else "• Aucun rôle académique actuellement attribué"
    )

    texte_demande = "\n".join(
        f"• `{role}`"
        for role in roles_demandes
    )

    orientation = (
        profil["option"]
        if profil["option"]
        else "Aucune"
    )

    contenu = (
        "🎓 **RÉCAPITULATIF DE VOTRE DEMANDE**\n\n"

        "**Situation académique actuelle :**\n"
        f"{texte_actuel}\n\n"

        "**Nouvelle demande :**\n"
        f"**Cursus :** {profil['cursus']}\n"
        f"**Niveau :** {profil['niveau']}\n"
        f"**Orientation :** {orientation}\n\n"

        "**Rôles demandés :**\n"
        f"{texte_demande}\n\n"

        "Vérifiez attentivement vos choix avant "
        "de transmettre votre demande."
    )

    await interaction.response.edit_message(
        content=contenu,

        view=RecapitulatifInscriptionView(
            profile_key
        )
    )


class RecapitulatifInscriptionView(
    discord.ui.View
):

    def __init__(
        self,
        profile_key: str
    ):

        super().__init__(
            timeout=300
        )

        self.profile_key = profile_key

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
            self.profile_key
        )

    @discord.ui.button(
        label="RECOMMENCER",
        emoji="🔄",
        style=discord.ButtonStyle.secondary
    )
    async def recommencer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=(
                "🎓 **INSCRIPTION ACADÉMIQUE**\n\n"
                "Sélectionnez votre cursus :"
            ),

            view=CursusView()
        )


# ============================================================
# 6.7 CRÉATION DE LA DEMANDE
# ============================================================

async def envoyer_demande_academique(
    interaction: discord.Interaction,
    profile_key: str
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
    # Il faut avoir terminé l'authentification mail.
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
    # Une seule demande EN ATTENTE à la fois.
    #
    # Une ancienne demande validée/corrigée/refusée
    # n'empêche absolument pas une nouvelle demande.
    # --------------------------------------------------------

    demande_attente = (
        recuperer_demande_en_attente_etudiant(
            interaction.user.id
        )
    )

    if demande_attente:

        await interaction.response.send_message(
            "⏳ **DEMANDE DÉJÀ EN ATTENTE**\n\n"
            "Votre précédente demande académique "
            "n'a pas encore été traitée.\n\n"
            "Attendez sa validation ou contactez "
            "`isib-ce@he2b.be`.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Lecture EXACTE des rôles académiques présents
    # au moment de la demande.
    # --------------------------------------------------------

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
        profile_key=profile_key
    )

    salon_validation = (
        await recuperer_salon_validation(
            interaction.client
        )
    )

    if not isinstance(
        salon_validation,
        discord.TextChannel
    ):

        await interaction.followup.send(
            "❌ Le salon interne de validation "
            "est introuvable.",
            ephemeral=True
        )

        return

    demande = recuperer_demande(
        request_id
    )

    embed = construire_embed_validation(
        demande
    )

    message = await salon_validation.send(
        embed=embed,

        view=ValidationInscriptionView(
            request_id
        )
    )

    enregistrer_message_validation(
        request_id=request_id,
        channel_id=salon_validation.id,
        message_id=message.id
    )

    await interaction.followup.send(
        "📩 **DEMANDE ENVOYÉE**\n\n"
        "Votre demande d'inscription académique "
        "a bien été transmise.\n\n"
        "Elle est maintenant **en attente de validation** "
        "par les équipes internes du Discord Étudiant ISIB.\n\n"
        "Vos rôles actuels restent inchangés "
        "jusqu'à la validation.",
        ephemeral=True
    )

    if isinstance(
        interaction.channel,
        discord.TextChannel
    ):

        try:

            await replacer_panneau_inscription(
                interaction.channel
            )

        except discord.HTTPException:

            pass


# ============================================================
# 7. VALIDATION INTERNE CE ISIB
# ============================================================


# ============================================================
# 7.1 FICHE DE VALIDATION
# ============================================================

def construire_embed_validation(
    demande
) -> discord.Embed:

    profil_demande = PROFILS_ACADEMIQUES[
        demande["requested_profile_key"]
    ]

    roles_actuels = json.loads(
        demande["current_roles_json"]
    )

    roles_demandes = profil_demande[
        "roles"
    ]

    a_retirer, a_ajouter, conserves = (
        calculer_modifications_roles(
            roles_actuels,
            roles_demandes
        )
    )

    embed = discord.Embed(
        title=(
            "🎓 DEMANDE D'INSCRIPTION ACADÉMIQUE"
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

    texte_actuel = (
        "\n".join(
            f"• `{role}`"
            for role in roles_actuels
        )

        if roles_actuels

        else "• Aucun rôle académique actuellement attribué"
    )

    embed.add_field(
        name="📌 Situation actuelle au moment de la demande",
        value=texte_actuel,
        inline=False
    )

    embed.add_field(
        name="🎓 Nouvelle demande",
        value=(
            f"**Cursus :** "
            f"{profil_demande['cursus']}\n"

            f"**Niveau :** "
            f"{profil_demande['niveau']}\n"

            f"**Orientation :** "
            f"{profil_demande['option'] or 'Aucune'}"
        ),
        inline=False
    )

    texte_roles_demandes = "\n".join(
        f"• `{role}`"
        for role in roles_demandes
    )

    embed.add_field(
        name="Rôles demandés",
        value=texte_roles_demandes,
        inline=False
    )

    modifications = []

    for role in a_retirer:

        modifications.append(
            f"➖ `{role}`"
        )

    for role in a_ajouter:

        modifications.append(
            f"➕ `{role}`"
        )

    for role in conserves:

        modifications.append(
            f"➡️ `{role}` conservé"
        )

    if not modifications:

        modifications.append(
            "➡️ Aucun changement de rôle"
        )

    embed.add_field(
        name="🔄 Modifications prévues",
        value="\n".join(
            modifications
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
            "✏️ CORRIGÉE ET VALIDÉE"
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

    if demande["final_profile_key"]:

        final_key = demande[
            "final_profile_key"
        ]

        final = PROFILS_ACADEMIQUES[
            final_key
        ]

        embed.add_field(
            name="✅ Profil finalement validé",
            value=description_profil(
                final_key
            ),
            inline=False
        )

        embed.add_field(
            name="Rôles finalement attribués",
            value="\n".join(
                f"• `{role}`"
                for role in final["roles"]
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
# 7.2 APPLICATION D'UN PROFIL
# ============================================================

async def appliquer_profil_academique(
    member: discord.Member,
    profile_key: str
):

    profil = PROFILS_ACADEMIQUES[
        profile_key
    ]

    guild = member.guild

    noms_roles_academiques = (
        obtenir_tous_noms_roles_academiques()
    )

    # --------------------------------------------------------
    # Recherche des rôles qui doivent être attribués.
    # --------------------------------------------------------

    roles_voulus = []
    roles_introuvables = []

    for nom_role in profil["roles"]:

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
                "Rôles introuvables : "
                + ", ".join(
                    roles_introuvables
                )
            )
        )

    # --------------------------------------------------------
    # IMPORTANT :
    #
    # on regarde ici la situation RÉELLE AU MOMENT
    # DE LA VALIDATION.
    #
    # On retire seulement les rôles académiques gérés
    # par ce système.
    #
    # Le rôle vérifié, les rôles CE, administration,
    # communication, etc. ne sont jamais touchés.
    # --------------------------------------------------------

    roles_a_retirer = [
        role
        for role in member.roles

        if (
            role.name in noms_roles_academiques
            and role not in roles_voulus
        )
    ]

    roles_a_ajouter = [
        role
        for role in roles_voulus

        if role not in member.roles
    ]

    try:

        if roles_a_retirer:

            await member.remove_roles(
                *roles_a_retirer,

                reason=(
                    "Mise à jour de "
                    "l'inscription académique"
                )
            )

        if roles_a_ajouter:

            await member.add_roles(
                *roles_a_ajouter,

                reason=(
                    "Inscription académique validée"
                )
            )

    except discord.Forbidden:

        return (
            False,
            (
                "Le bot n'a pas le droit de gérer "
                "un ou plusieurs de ces rôles. "
                "Vérifiez la hiérarchie des rôles."
            )
        )

    except discord.HTTPException as erreur:

        return (
            False,
            f"Erreur Discord : {erreur}"
        )

    return (
        True,
        None
    )


# ============================================================
# 7.3 VALIDATION
# ============================================================

async def notifier_validation_etudiant(
    member: discord.Member,
    profile_key: str,
    correction=False,
    ancien_profile_key=None
):

    profil = PROFILS_ACADEMIQUES[
        profile_key
    ]

    roles = "\n".join(
        f"• {role}"
        for role in profil["roles"]
    )

    if correction:

        ancien = description_profil(
            ancien_profile_key
        )

        nouveau = description_profil(
            profile_key
        )

        texte = (
            "✏️ **INSCRIPTION ACADÉMIQUE "
            "CORRIGÉE ET VALIDÉE**\n\n"

            "Vous aviez indiqué :\n"
            f"**{ancien}**\n\n"

            "Après vérification par les équipes "
            "internes du Discord Étudiant ISIB, "
            "votre profil a été corrigé en :\n"

            f"**{nouveau}**\n\n"

            "Vous disposez désormais "
            "des accès académiques suivants :\n"

            f"{roles}\n\n"

            "Si vous pensez qu'il s'agit d'une erreur, "
            "contactez `isib-ce@he2b.be`."
        )

    else:

        texte = (
            "✅ **INSCRIPTION ACADÉMIQUE VALIDÉE**\n\n"

            "Votre demande a été validée.\n\n"

            "Vous disposez désormais des accès "
            "académiques suivants :\n"

            f"{roles}\n\n"

            "Bienvenue dans la communauté étudiante "
            "de l'ISIB - HE2B !"
        )

    try:

        await member.send(
            texte
        )

        return True

    except discord.Forbidden:

        return False


async def traiter_validation(
    interaction: discord.Interaction,
    request_id: int,
    profile_key: str,
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

    succes, erreur = await appliquer_profil_academique(
        member,
        profile_key
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
        final_profile_key=profile_key
    )

    await mettre_a_jour_message_validation(
        interaction.client,
        request_id
    )

    dm_envoye = await notifier_validation_etudiant(
        member=member,
        profile_key=profile_key,
        correction=correction,

        ancien_profile_key=(
            demande["requested_profile_key"]
        )
    )

    texte_confirmation = (
        "✅ **INSCRIPTION TRAITÉE**\n\n"
        "Les rôles académiques ont été mis à jour."
    )

    if not dm_envoye:

        texte_confirmation += (
            "\n\n⚠️ L'étudiant bloque ses messages privés. "
            "Il peut consulter son résultat avec "
            "`/statut_inscription`."
        )

    await interaction.followup.send(
        texte_confirmation,
        ephemeral=True
    )


# ============================================================
# 7.3.1 BOUTONS DE VALIDATION
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

        bouton_corriger = discord.ui.Button(
            label="CORRIGER",
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

        bouton_corriger.callback = (
            self.corriger
        )

        bouton_refuser.callback = (
            self.refuser
        )

        self.add_item(
            bouton_valider
        )

        self.add_item(
            bouton_corriger
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

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await traiter_validation(
            interaction=interaction,
            request_id=self.request_id,

            profile_key=(
                demande[
                    "requested_profile_key"
                ]
            ),

            correction=False
        )

    async def corriger(
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

        await interaction.response.send_message(
            "✏️ **CORRECTION DE LA DEMANDE**\n\n"
            "Sélectionnez le profil académique "
            "qui doit réellement être attribué.",
            view=CorrectionProfilView(
                self.request_id
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

        await interaction.response.send_modal(
            RefusInscriptionModal(
                self.request_id
            )
        )


# ============================================================
# 7.4 CORRECTION
# ============================================================

class CorrectionProfilSelect(
    discord.ui.Select
):

    def __init__(
        self,
        request_id: int
    ):

        self.request_id = request_id

        options = []

        for key in PROFILS_ACADEMIQUES:

            options.append(
                discord.SelectOption(
                    label=(
                        description_profil(
                            key
                        )[:100]
                    ),

                    value=key
                )
            )

        super().__init__(
            placeholder=(
                "Sélectionnez le profil correct"
            ),
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
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

        profile_key = self.values[0]

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await traiter_validation(
            interaction=interaction,
            request_id=self.request_id,
            profile_key=profile_key,
            correction=True
        )


class CorrectionProfilView(
    discord.ui.View
):

    def __init__(
        self,
        request_id: int
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            CorrectionProfilSelect(
                request_id
            )
        )


# ============================================================
# 7.5 REFUS
# ============================================================

class RefusInscriptionModal(
    discord.ui.Modal,
    title="Refuser l'inscription"
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

        dm_envoye = False

        if member:

            try:

                await member.send(
                    "❌ **INSCRIPTION ACADÉMIQUE REFUSÉE**\n\n"

                    "Votre demande d'inscription académique "
                    "a été refusée.\n\n"

                    f"**Motif :** {motif}\n\n"

                    "Aucun de vos rôles académiques "
                    "actuels n'a été modifié.\n\n"

                    "Si vous pensez qu'il s'agit d'une erreur, "
                    "contactez `isib-ce@he2b.be`."
                )

                dm_envoye = True

            except discord.Forbidden:

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
        label="COMMENCER MON INSCRIPTION",
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

        # ----------------------------------------------------
        # Seule une demande encore EN ATTENTE bloque.
        #
        # Une demande passée validée, corrigée ou refusée
        # n'empêche jamais de recommencer.
        # ----------------------------------------------------

        demande_attente = (
            recuperer_demande_en_attente_etudiant(
                interaction.user.id
            )
        )

        if demande_attente:

            await interaction.response.send_message(
                "⏳ **DEMANDE DÉJÀ EN ATTENTE**\n\n"
                "Une de vos demandes est actuellement "
                "en cours de validation.",
                ephemeral=True
            )

            return

        roles_actuels = (
            lire_roles_academiques_membre(
                interaction.user
            )
        )

        if roles_actuels:

            texte_roles = "\n".join(
                f"• `{role}`"
                for role in roles_actuels
            )

        else:

            texte_roles = (
                "• Aucun rôle académique actuellement attribué"
            )

        await interaction.response.send_message(
            "🎓 **INSCRIPTION ACADÉMIQUE**\n\n"

            "**Votre situation académique actuelle :**\n"
            f"{texte_roles}\n\n"

            "Sélectionnez maintenant votre cursus :",

            view=CursusView(),
            ephemeral=True
        )


# ============================================================
# 8.2 EMBED PUBLIC
# ============================================================

def creer_embed_inscription():

    embed = discord.Embed(
        title=TITRE_PANNEAU_INSCRIPTION,

        description=(
            "Sélectionnez les choix correspondant "
            "à votre situation académique :\n\n"

            "1. Sélectionnez votre cursus\n"
            "2. Sélectionnez votre niveau\n"
            "3. Sélectionnez votre orientation "
            "si nécessaire\n"
            "4. Vérifiez puis envoyez votre demande\n"
            "5. Votre demande sera contrôlée "
            "par les équipes internes du Discord\n\n"

            "Une nouvelle demande peut être introduite "
            "ultérieurement si votre situation académique "
            "évolue.\n\n"

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


async def publier_panneau_inscription(
    channel: discord.TextChannel
):

    return await channel.send(
        embed=creer_embed_inscription(),
        view=InscriptionAcademiqueView()
    )


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
        # VALIDATION / CORRECTION / REFUS après redémarrage.
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
        "✅ Panneau d'authentification installé.",
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
        "✅ Panneau d'inscription "
        "académique installé.",
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

    if statut == "pending":

        texte = (
            "⏳ **DEMANDE EN ATTENTE**\n\n"
            "Votre dernière demande est "
            "en cours de validation."
        )

    elif statut == "approved":

        profil = (
            demande["final_profile_key"]
            or demande["requested_profile_key"]
        )

        texte = (
            "✅ **DERNIÈRE DEMANDE VALIDÉE**\n\n"
            f"Profil : "
            f"**{description_profil(profil)}**"
        )

    elif statut == "corrected":

        profil = demande[
            "final_profile_key"
        ]

        texte = (
            "✏️ **DERNIÈRE DEMANDE "
            "CORRIGÉE ET VALIDÉE**\n\n"

            f"Profil finalement retenu : "
            f"**{description_profil(profil)}**"
        )

    elif statut == "refused":

        texte = (
            "❌ **DERNIÈRE DEMANDE REFUSÉE**\n\n"

            f"Motif : "
            f"{demande['refusal_reason'] or 'Non précisé'}\n\n"

            "Vos rôles précédents ont été conservés."
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
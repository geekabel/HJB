# Glossaire du code (carte T14b)

Depuis la carte T14b, le code est en anglais : noms, commentaires, docstrings et tests.
Les textes affichés restent en français, ainsi que les adresses visibles (/activer/,
/connexion/, /equipe/…). Ce glossaire relie les mots du métier (français) aux noms du code.
Colonne de gauche : ancien nom ; colonne de droite : nouveau nom.

## Applications et modules

| Ancien | Nouveau |
|---|---|
| `comptes` | `accounts` |
| `comptes/activation.py` | `accounts/activation_codes.py` |
| `comptes/telephone.py` | `accounts/phone.py` |
| `comptes/verification.py` | `accounts/phone_verification.py` |
| `comptes/sessions.py` | `accounts/sessions.py` |
| `comptes/backends.py` | `accounts/backends.py` |
| `comptes/roles.py` | `accounts/roles.py` |
| `comptes/management/commands/code_activation.py` | `accounts/management/commands/activation_code.py` |
| `comptes/tests/outils.py` | `accounts/tests/helpers.py` |
| `logement` | `housing` |
| `logement/services.py` | `housing/services.py` |
| `residents` | `residents` |
| `residents/depart.py` | `residents/departure.py` |
| `residents/importation.py` | `residents/bulk_import.py` |
| `journal` | `audit` |
| `journal/service.py` | `audit/service.py` |
| `interface` | `ui` |
| `interface/formulaires.py` | `ui/forms.py` |
| `interface/templatetags/icones.py` | `ui/templatetags/icons.py` |
| `sms/fournisseurs/` | `sms/providers/` |
| `sms/fournisseurs/aucun.py` | `sms/providers/disabled.py` |
| `sms/fournisseurs/memoire.py` | `sms/providers/memory.py` |
| `sms/management/commands/envoyer_sms_essai.py` | `sms/management/commands/send_test_sms.py` |
| `activation/parcours.py` | `activation/journey.py` |
| `connexion` | `access` |
| `connexion/decorateurs.py` | `access/decorators.py` |
| `connexion/erreurs.py` | `access/errors.py` |
| `connexion/limites.py` | `access/rate_limits.py` |
| `connexion/session.py` | `access/session_policy.py` |
| `connexion/signaux.py` | `access/signals.py` |
| `connexion/tests/authentificateur.py` | `access/tests/authenticator.py` |
| `outils` | `tools` |
| `outils/capture_html.py` | `tools/html_capture.py` |
| `outils/lanceur_tests.py` | `tools/test_runner.py` |
| `outils/valider_w3c.py` | `tools/validate_w3c.py` |

## Modèles et champs

| Ancien | Nouveau |
|---|---|
| `User.telephone` | `User.phone` |
| `User.telephone_verifie` | `User.verified_phone` |
| `User.telephone_verifie_le` | `User.phone_verified_at` |
| `User.roles` | `User.roles` |
| `User.a_le_role()` | `User.has_role()` |
| `User.libelle_roles` | `User.roles_label` |
| `User.etat_compte` | `User.account_state` |
| `User.telephone_est_verifie` | `User.phone_is_verified` |
| `User.telephone_affiche` | `User.phone_display` |
| `User.telephone_masque` | `User.phone_masked` |
| `User.est_equipe` | `User.has_staff_role` |
| `GestionnaireUtilisateurs` (`residents()`, `avec_role()`) | `HJBUserManager` (`residents()`, `with_role()`) |
| `EtatCompte` (`ACTIVE`, `EN_ATTENTE`, `DESACTIVE`) | `AccountState` (`ACTIVE`, `PENDING`, `DISABLED`), valeurs `active`, `pending`, `disabled` |
| `FILTRE_ETAT_COMPTE` | `ACCOUNT_STATE_FILTERS` |
| `CodeActivation` | `ActivationCode` |
| `.utilisateur`, `.empreinte`, `.cree_par`, `.cree_le`, `.expire_le`, `.utilise_le`, `.annule_le`, `.pour_personnel` | `.user`, `.digest`, `.created_by`, `.created_at`, `.expires_at`, `.used_at`, `.cancelled_at`, `.for_staff` |
| `CodeActivation.objects.valides()` | `ActivationCode.objects.valid()` |
| `related_name="codes_activation"` | `related_name="activation_codes"` |
| `EchecActivation` (`adresse_ip`, `cree_le`) | `ActivationFailure` (`ip_address`, `created_at`) |
| `VerificationTelephone` | `PhoneVerification` |
| `.utilisateur`, `.telephone`, `.empreinte`, `.cree_le`, `.expire_le`, `.tentatives`, `.verifie_le` | `.user`, `.phone`, `.digest`, `.created_at`, `.expires_at`, `.attempts`, `.verified_at` |
| `related_name="verifications_telephone"` | `related_name="phone_verifications"` |
| `Etage` (`numero`, `nom`, `ordre_visite`, `libelle_court`) | `Floor` (`number`, `name`, `visit_order`, `short_label`) |
| `libelle_court_etage()` | `floor_short_label()` |
| `Chambre` (`numero`, `etage`, `active`) ; `Chambre.objects.libres()` | `Room` (`number`, `floor`, `active`) ; `Room.objects.free()` |
| `related_name="chambres"` | `related_name="rooms"` |
| `Sejour` (`resident`, `chambre`, `arrivee`, `depart`, `en_cours`) ; `Sejour.objects.en_cours()` | `Stay` (`resident`, `room`, `arrival`, `departure`, `is_current`) ; `Stay.objects.current()` |
| `related_name="sejours"` | `related_name="stays"` |
| `EntreeJournal` | `AuditEntry` |
| `.cree_le`, `.acteur`, `.acteur_libelle`, `.action`, `.cible_type`, `.cible_id`, `.cible`, `.cible_libelle`, `.details`, `.adresse_ip`, `.resume()` | `.created_at`, `.actor`, `.actor_label`, `.action`, `.target_type`, `.target_id`, `.target`, `.target_label`, `.details`, `.ip_address`, `.summary()` |
| `EntreeJournalNonModifiable` | `AuditEntryImmutable` |
| `ImportResidents` (`jeton`, `importe_le`, `importe_par`, `fichier`, `nombre`) | `ResidentImport` (`token`, `imported_at`, `imported_by`, `file_name`, `count`) |

## Valeurs enregistrées

| Ancien | Nouveau |
|---|---|
| `Role.ACCUEIL` = `"ACCUEIL"` | `Role.FRONT_DESK` = `"front_desk"` (libellé « Accueil ») |
| `Role.EDUCATEUR` | `Role.EDUCATOR` = `"educator"` |
| `Role.MAINTENANCE` | `Role.MAINTENANCE` = `"maintenance"` |
| `Role.ADMIN` | `Role.ADMIN` = `"admin"` |
| `Role.MODERATEUR` | `Role.MODERATOR` = `"moderator"` |
| Noms des groupes (« Accueil », « Éducateurs »…) | inchangés : ils s'affichent dans l'administration |
| `Action.ROLES_MODIFIES` | `Action.ROLES_CHANGED` |
| `Action.CODE_ACTIVATION_GENERE` | `Action.ACTIVATION_CODE_ISSUED` |
| `Action.CODE_WIFI_AFFICHE` | `Action.WIFI_PASSWORD_SHOWN` |
| `Action.DEPART_RESIDENT` | `Action.RESIDENT_DEPARTED` |
| `Action.RETOUR_RESIDENT` | `Action.RESIDENT_RETURNED` |
| `Action.CLE_ACCES_CREEE` | `Action.PASSKEY_CREATED` |
| `Action.ACCES_COUPE` | `Action.ACCESS_CUT` |
| Clés de `details` : `avant`, `apres`, `expire_le`, `personnel`, `chambre`, `depart`, `arrivee`, `sessions_fermees`, `cles_retirees`, `anciennes_retirees` | `before`, `after`, `expires_at`, `staff`, `room`, `departure`, `arrival`, `sessions_closed`, `passkeys_removed`, `previous_removed` |
| Les valeurs des actions et des rôles sont les noms en minuscules (`"roles_changed"`…). Les libellés restent en français. | |

## Permissions (codename)

| Ancien | Nouveau |
|---|---|
| `acceder_espace_equipe` | `access_staff_area` |
| `voir_residents` | `view_residents` |
| `gerer_residents` | `manage_residents` |
| `generer_code_activation` | `issue_activation_codes` |
| `voir_code_wifi` | `view_wifi_password` |
| `envoyer_messages` | `send_messages` |
| `gerer_signalements` | `manage_reports` |
| `gerer_rendezvous` | `manage_appointments` |
| `moderer_discussion` | `moderate_discussion` |
| `voir_journal` | `view_audit_log` |
| `gerer_roles` | `manage_roles` |

## Fonctions et constantes partagées

| Ancien | Nouveau |
|---|---|
| `comptes.roles` : `ROLES_EQUIPE`, `GROUPE_PAR_ROLE`, `ROLE_PAR_GROUPE`, `PERMISSIONS`, `PERMISSIONS_PAR_ROLE`, `installer_groupes()`, `creer_groupes_apres_migration()`, `roles_de()`, `definir_roles()` | `accounts.roles` : `STAFF_ROLES`, `GROUP_BY_ROLE`, `ROLE_BY_GROUP`, `PERMISSIONS`, `PERMISSIONS_BY_ROLE`, `install_groups()`, `create_groups_after_migrate()`, `roles_of()`, `set_roles()` |
| `comptes.activation` : `ALPHABET`, `LONGUEUR`, `DUREE_VALIDITE`, `ECHECS_MAX`, `ECHECS_MAX_ADRESSE`, `FENETRE_ECHECS`, `ErreurActivation`, `normaliser()`, `formater()`, `empreinte()`, `generer_code()` (`pour_personnel=`), `trop_d_echecs()`, `utiliser_code()`, `etat_activation()`, `envoyer_code_par_sms()` | `accounts.activation_codes` : `ALPHABET`, `LENGTH`, `VALIDITY`, `MAX_FAILURES`, `MAX_FAILURES_PER_ADDRESS`, `FAILURE_WINDOW`, `ActivationError`, `normalize()`, `format_code()`, `digest()`, `issue_code()` (`for_staff=`), `too_many_failures()`, `redeem_code()`, `activation_state()`, `send_code_by_sms()` |
| États de `etat_activation()` : `actif`, `utilise`, `expire` | `active`, `used`, `expired` |
| `comptes.telephone` : `REGION_PAR_DEFAUT`, `TYPES_PORTABLES`, `valider_e164`, `normaliser_telephone()`, `afficher_telephone()`, `masquer_telephone()` | `accounts.phone` : `DEFAULT_REGION`, `MOBILE_TYPES`, `validate_e164`, `normalize_phone()`, `display_phone()`, `mask_phone()` |
| `comptes.verification` : `DUREE`, `ESSAIS_MAX`, `DELAI_RENVOI`, `ENVOIS_PAR_HEURE`, `ErreurVerification`, `derniere()`, `renvoi_possible_le()`, `attente_avant_renvoi()`, `envoyer_code()`, `verifier_code()` | `accounts.phone_verification` : `DURATION`, `MAX_ATTEMPTS`, `RESEND_DELAY`, `SENDS_PER_HOUR`, `VerificationError`, `latest()`, `resend_available_at()`, `wait_before_resend()`, `send_code()`, `check_code()` |
| Codes d'erreur de `ErreurVerification` / `ErreurActivation` : `sans_numero`, `trop_tot`, `trop_d_envois`, `sms`, `aucun`, `trop_essais`, `incorrect`, `invalide` | `no_number`, `too_soon`, `too_many_sends`, `sms`, `none`, `too_many_attempts`, `incorrect`, `invalid` |
| `comptes.sessions` : `cles_de_session()`, `fermer_sessions()`, `fermer_toutes()` | `accounts.sessions` : `session_keys_for()`, `close_sessions()`, `close_all()` |
| `comptes.backends.PermissionsSansMotDePasse` | `accounts.backends.PermissionsOnlyBackend` |
| `comptes.tests.outils` : `creer_utilisateur()`, `connecter()` | `accounts.tests.helpers` : `make_user()`, `log_in_verified()` |
| Commande `code_activation` | Commande `activation_code` |
| `logement.services` : `sejour_en_cours()`, `affecter_chambre()` | `housing.services` : `current_stay()`, `assign_room()` |
| `residents.depart` : `depart_enregistre` (signal), `est_parti()`, `verifier_date()`, `enregistrer_depart()`, `enregistrer_retour()` | `residents.departure` : `departure_recorded`, `has_left()`, `check_date()`, `record_departure()`, `record_return()` |
| Arguments du signal : `resident`, `sejour`, `le` | `resident`, `stay`, `on` |
| `residents.views.feuille_code()` | `residents.views.activation_sheet()` |
| `journal.service` : `adresse_ip()`, `journaliser()` | `audit.service` : `client_ip()`, `log_action()` |
| `journaliser(action, *, acteur, cible, details, requete)` | `log_action(action, *, actor, target, details, request)` |
| `sms.service` : `envoyer_sms()`, `fournisseur_actif()`, `SEGMENTS_MAX` | `sms.service` : `send_sms()`, `active_provider()`, `MAX_SEGMENTS` |
| `sms.fournisseurs.base` : `ErreurSms` (`temporaire`, `incertain`), `ErreurConfiguration`, `ErreurEnvoi`, `ResultatEnvoi` (`fournisseur`, `identifiant`), `FournisseurSms` (`nom`, `options_obligatoires`, `options_manquantes()`, `envoyer()`) | `sms.providers.base` : `SmsError` (`temporary`, `uncertain`), `ConfigurationError`, `SendError`, `SendResult` (`provider`, `message_id`), `SmsProvider` (`name`, `required_options`, `missing_options()`, `send()`) |
| `FournisseurAucun`, `FournisseurConsole`, `FournisseurMemoire`, `FournisseurOvh`, `FournisseurSmsGate` | `DisabledProvider`, `ConsoleProvider`, `MemoryProvider`, `OvhProvider`, `SmsGateProvider` |
| `memoire.boite`, `SmsEnvoye` (`numero`, `texte`, `identifiant`) | `memory.outbox`, `SentSms` (`number`, `text`, `message_id`) |
| `sms.segments` : `InfoSms` (`encodage`, `unites`, `segments`, `restant`, `hors_gsm`), `analyser()` | `sms.segments` : `SmsInfo` (`encoding`, `units`, `segments`, `remaining`, `non_gsm`), `analyze()` |
| `activation.parcours` : `CLE`, `DUREE`, `demarrer()`, `personne_en_cours()`, `noter()`, `retirer()`, `etape_faite()`, `terminer()` | `activation.journey` : `KEY`, `DURATION`, `start()`, `current_person()`, `remember()`, `pop()`, `step_done()`, `finish()` |
| Étape notée `telephone_verifie` | `phone_verified` |
| `connexion.session` : `DUREE_RESIDENT`, `FENETRE_CONFIRMATION`, `CLE_CONFIRMEE`, `est_resident()`, `ouvrir()`, `confirmee_recemment()` | `access.session_policy` : `RESIDENT_SESSION_LENGTH`, `CONFIRMATION_WINDOW`, `CONFIRMED_AT_KEY`, `is_resident()`, `open_session()`, `confirmed_recently()` |
| `connexion.decorateurs.confirmation_recente` | `access.decorators.recent_confirmation_required` |
| `connexion.erreurs` : `MESSAGES`, `MESSAGE_PAR_DEFAUT`, `en_francais()`, `reponse_erreur()`, `ErreursEnFrancais` | `access.errors` : `MESSAGES`, `DEFAULT_MESSAGE`, `message_for()`, `error_response()`, `FrenchErrorsMixin` |
| `connexion.limites` : `DEBUTS_MAX`, `FENETRE_DEBUTS`, `groupe()`, `atteinte()`, `noter()` | `access.rate_limits` : `MAX_BEGINS`, `BEGIN_WINDOW`, `address_group()`, `limit_reached()`, `record_attempt()` |
| `connexion.middleware.EspaceEquipeMiddleware` | `access.middleware.StaffAreaMiddleware` |
| `connexion.services.couper_acces()` | `access.services.cut_access()` |
| `connexion.webauthn` : `AideWebAuthn`, `AideActivation` | `access.webauthn` : `HJBWebAuthnHelper`, `ActivationWebAuthnHelper` |
| `connexion.api` : `DebutVerification`, `FinVerification` | `access.api` : `VerifyBeginView`, `VerifyCompleteView` |
| `connexion.tests.authentificateur.Authentificateur` (`enregistrer()`, `creer()`, `verifier()`, `verification=`, `origine=`, `identifiant=`) | `access.tests.authenticator.SoftwareAuthenticator` (`register()`, `create()`, `get()`, `user_verified=`, `origin=`, `credential_id=`) |
| `outils.capture_html.enregistrer_page()` | `tools.html_capture.save_page()` |
| `outils.lanceur_tests.LanceurTests` | `tools.test_runner.HJBTestRunner` |
| `interface.formulaires.RenduHJB` | `ui.forms.HJBFormRenderer` |

## Adresses (noms d'URL)

Les chemins ne changent pas. Seuls les noms changent.

| Ancien | Nouveau |
|---|---|
| `accueil` | `home` |
| `activation:saisie`, `telephone`, `mauvais_numero`, `cle`, `cle_debut`, `cle_fin` | `activation:enter_code`, `phone`, `wrong_number`, `passkey`, `passkey_begin`, `passkey_complete` |
| `connexion:connexion`, `confirmer`, `deconnexion`, `verification_debut`, `verification_fin` | `access:login`, `confirm`, `logout`, `verify_begin`, `verify_complete` |
| `journal:liste` | `audit:list` |
| `interface:guide`, `interface:guide-resident` | `ui:guide`, `ui:guide_resident` |
| `residents:liste`, `creer`, `fiche`, `depart`, `retour`, `code_activation`, `couper_acces`, `import`, `import_apercu`, `import_modele` | `residents:list`, `create`, `detail`, `departure`, `return`, `activation_code`, `cut_access`, `import`, `import_preview`, `import_template` |

## Gabarits

| Ancien | Nouveau |
|---|---|
| `interface/base.html`, `equipe.html`, `resident.html`, `formulaires/champ.html`, `guide/index.html`, `guide/resident.html` | `ui/base.html`, `staff.html`, `resident.html`, `forms/field.html`, `guide/index.html`, `guide/resident.html` |
| Blocs `titre`, `tete`, `classe_corps`, `corps`, `entete`, `contenu`, `navigation`, `etape` | `title`, `head`, `body_class`, `body`, `header`, `content`, `nav`, `step` |
| Variable `actif` : `accueil`, `messages`, `signaler`, `rendezvous`, `compte`, `tableau`, `signalements`, `residents`, `journal` | `active_nav` : `home`, `messages`, `report`, `appointments`, `account`, `dashboard`, `reports`, `residents`, `audit` |
| Variable `etape` (1, 2, 3) | `step` |
| `activation/base_activation.html`, `saisie.html`, `telephone.html`, `mauvais_numero.html`, `cle.html` | `activation/base.html`, `enter_code.html`, `phone.html`, `wrong_number.html`, `passkey.html` |
| `connexion/_bouton_cle.html` (variables `configuration`, `libelle`), `accueil.html`, `confirmer.html`, `connexion.html` | `access/_passkey_button.html` (variables `config`, `label`), `home.html`, `confirm.html`, `login.html` |
| `journal/liste.html` | `audit/list.html` |
| `residents/code_activation.html`, `depart.html`, `fiche.html`, `import.html`, `liste.html`, `retour.html` | `residents/activation_code.html`, `departure.html`, `detail.html`, `import.html`, `list.html`, `return.html` |
| Balises `{% load icones %}`, `{% icone "nom" %}`, `{% toits %}` | `{% load icons %}`, `{% icon "name" %}`, `{% roofs %}` |
| Icônes : `maison`, `message`, `plus`, `calendrier`, `wifi`, `personne`, `cloche`, `alerte`, `info`, `coche`, `horloge`, `cadenas`, `retour`, `importer`, `envoyer`, `porte`, `porte-voix`, `vote`, `tableau`, `outil`, `groupe` | `home`, `message`, `plus`, `calendar`, `wifi`, `person`, `bell`, `alert`, `info`, `check`, `clock`, `lock`, `back`, `import`, `send`, `door`, `megaphone`, `vote`, `table`, `tool`, `group` |
| Étiquettes des messages (`MESSAGE_TAGS`) : `succes`, `info`, `attention` | `success`, `info`, `warning` |

## Fichiers statiques et JavaScript

| Ancien | Nouveau |
|---|---|
| `interface/css/hjb.css` | `ui/css/hjb.css` |
| `interface/js/cle-acces.js`, `imprimer.js` | `ui/js/passkey.js`, `print.js` |
| `interface/fonts/` | `ui/fonts/` |
| `activation/code-depuis-lien.js` | `activation/code-from-link.js` |
| `data-cle-acces-bouton`, `-statut`, `-indisponible`, `-icone` | `data-passkey-button`, `-status`, `-unavailable`, `-icon` |
| `data-imprimer` | `data-print` |
| `id="cle-acces-config"` ; clés `mode`, `debut`, `fin`, `suite` ; modes `creation`, `connexion`, `confirmation` | `id="passkey-config"` ; clés `mode`, `begin`, `complete`, `next` ; modes `register`, `login`, `confirm` |

## Classes CSS

| Ancien | Nouveau |
|---|---|
| `alerte` (`--attention`, `--info`, `--succes`) | `alert` (`--warning`, `--info`, `--success`) |
| `badge` (`--attention`, `--erreur`, `--info`, `--neutre`, `--succes`) | `badge` (`--warning`, `--error`, `--info`, `--neutral`, `--success`) |
| `bouton` (`--bloc`, `--danger`, `--discret`, `--secondaire`) | `button` (`--block`, `--danger`, `--quiet`, `--secondary`) |
| `bouton-icone` | `icon-button` |
| `carte` (`--accent`, `--cadre`, `--lien`, `__texte`, `__titre`) | `card` (`--accent`, `--framed`, `--link`, `__text`, `__title`) |
| `champ` (`__aide`, `__erreur`, `__erreurs`), `champ-code` | `field` (`__help`, `__error`, `__errors`), `code-field` |
| `choix`, `compteur`, `details` | `choices`, `counter`, `details` |
| `echantillon` (`__couleur`, `__couleur--action`, `--attention`, `--encre`, `--erreur`, `--fond`, `--succes`, `--toit-bleu`, `--toit-jaune`, `--toit-vert`) | `swatch` (`__color`, `__color--action`, `--warning`, `--ink`, `--error`, `--bg`, `--success`, `--roof-blue`, `--roof-yellow`, `--roof-green`) |
| `entete-page` | `page-header` |
| `etapes` (`__etape`, `__etape--atteinte`) | `steps` (`__step`, `__step--reached`) |
| `feuille-code` (`__code`) | `code-sheet` (`__code`) |
| `fiche` | `profile` |
| `filtres` (`__recherche`) | `filters` (`__search`) |
| `grille-2`, `grille-auto` | `grid-2`, `grid-auto` |
| `indicateur` (`__valeur`) | `stat` (`__value`) |
| `lien-evitement`, `lien-retour` | `skip-link`, `back-link` |
| `liste-puces`, `liste-simple` | `bullet-list`, `plain-list` |
| `masque-impression` | `no-print` |
| `menu-equipe` (`__marque`, `__personne`) | `staff-menu` (`__brand`, `__person`) |
| `nav-resident` | `resident-nav` |
| `page-equipe` (`__contenu`) | `staff-page` (`__content`) |
| `page-resident` (`__contenu`, `__entete`) | `resident-page` (`__content`, `__header`) |
| `pagination` | `pagination` |
| `pile` (`--aeree`, `--serree`) | `stack` (`--loose`, `--tight`) |
| `puce` | `chip` |
| `rangee` (`--haut`) | `row` (`--top`) |
| `tableau` (`__action`, `__entete-ligne`, `__etat`, `__nombre`), `tableau-defilant` | `table` (`__action`, `__row-header`, `__state`, `__number`), `table-scroll` |
| `telephone-masque` | `masked-phone` |
| `texte-action`, `texte-attention`, `texte-doux`, `texte-petit` | `text-action`, `text-warning`, `text-muted`, `text-small` |
| `toits`, `tuile-logo` | `roofs`, `logo-tile` |
| `visuellement-cache` | `visually-hidden` |
| Couches `reset`, `jetons`, `base`, `mise-en-page`, `composants`, `utilitaires` | `reset`, `tokens`, `base`, `layout`, `components`, `utilities` |

## Variables CSS

| Ancien | Nouveau |
|---|---|
| `--action-doux`, `--action-fond`, `--action-survol`, `--sur-action` | `--action-soft`, `--action-bg`, `--action-hover`, `--on-action` |
| `--attention`, `--attention-doux`, `--attention-texte`, `--sur-attention` | `--warning`, `--warning-soft`, `--warning-text`, `--on-warning` |
| `--erreur`, `--erreur-doux`, `--sur-erreur` | `--error`, `--error-soft`, `--on-error` |
| `--succes`, `--succes-doux` | `--success`, `--success-soft` |
| `--atteinte`, `--cible`, `--controle`, `--discret`, `--secondaire` | `--reached`, `--target`, `--control`, `--quiet`, `--secondary` |
| `--e-N` (espacements) | `--s-N` |
| `--encre`, `--fond`, `--lien`, `--ligne`, `--texte-doux` | `--ink`, `--bg`, `--link`, `--line`, `--text-muted` |
| `--largeur-resident`, `--largeur-texte` | `--resident-width`, `--text-width` |
| `--menu-actif`, `--menu-doux`, `--menu-fond`, `--menu-ligne`, `--menu-texte` | `--menu-active`, `--menu-soft`, `--menu-bg`, `--menu-line`, `--menu-text` |
| `--police-code`, `--police-texte`, `--police-titre` | `--font-code`, `--font-text`, `--font-title` |
| `--r-grand`, `--r-petit` | `--r-large`, `--r-small` |
| `--t-gros`, `--t-petit`, `--t-texte` | `--t-large`, `--t-small`, `--t-body` |
| `--toit-bleu`, `--toit-jaune`, `--toit-vert` | `--roof-blue`, `--roof-yellow`, `--roof-green` |
| Inchangées : `--action`, `--danger`, `--focus`, `--r`, `--surface`, `--surface-2`, `--t-h1`, `--t-h2`, `--t-h3` | |

## Réglages, sessions et environnement

| Ancien | Nouveau |
|---|---|
| `FOURNISSEURS_SMS`, `reglage_sms()` | `SMS_PROVIDERS`, `sms_setting()` |
| Noms des fournisseurs : `aucun`, `console`, `smsgate`, `ovh` | `disabled`, `console`, `smsgate`, `ovh` |
| Options SMSGate : `url`, `jeton`, `identifiant`, `mot_de_passe`, `sim` | `url`, `token`, `username`, `password`, `sim` |
| Option OVH `expediteur`, variable `OVH_SMS_EXPEDITEUR` | `sender`, `OVH_SMS_SENDER` |
| `DJANGO_SMS_FOURNISSEUR`, `SMSGATE_JETON`, `SMSGATE_IDENTIFIANT`, `SMSGATE_MOT_DE_PASSE` | `DJANGO_SMS_PROVIDER`, `SMSGATE_TOKEN`, `SMSGATE_USERNAME`, `SMSGATE_PASSWORD` |
| `DJANGO_WEBAUTHN_ORIGINES` | `DJANGO_WEBAUTHN_ORIGINS` |
| Clés de session : `activation`, `activation_echecs`, `connexion_confirmee_le`, `import_residents`, jetons du code | `activation_journey`, `activation_failures`, `passkey_confirmed_at`, `resident_import`, `activation_code_tokens` |
| `HTML_CAPTURE_DIR` | inchangé |
| Contrôles : `connexion.E001`, `connexion.W001`, `sms.E001`… | `access.E001`, `access.W001`, `sms.E001`… |

## Modèles prévus

Les modèles des cartes à venir (wifi, messages, sondages, rendez-vous, signalements,
discussion) ont déjà leurs noms anglais dans le schéma de
[modele-de-donnees.md](modele-de-donnees.md). Par exemple : `WifiAccess`, `Campaign`,
`Delivery`, `Poll`, `Appointment`, `Report`. Le salon de discussion s'appelle `Channel`, car
`Room` désigne déjà la chambre.

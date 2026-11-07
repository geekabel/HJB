# Registre des activités de traitement

Application de la résidence Habitat Jeunes Belfort (carte T36).

Ce registre suit le modèle de la CNIL :
[le registre des activités de traitement](https://www.cnil.fr/fr/le-registre-des-activites-de-traitement).
Il décrit ce que fait l'application. L'association le complète, le valide
et le tient à jour. Les parties « à compléter » ne se devinent pas : elles
dépendent de l'association ou de l'hébergement choisi (carte T38).

## Responsable du traitement

- **Organisme** : association Habitat Jeunes Belfort. Adresse : à compléter.
- **Représentant** : à compléter (la direction).
- **Contact pour les données** : réglé par `DJANGO_PRIVACY_CONTACT`, affiché
  sur la page « Vos données » (`/donnees/`). Vide : « l'accueil de la
  résidence ».
- **Délégué à la protection des données** : à compléter (aucun, ou son nom).

## Durées de conservation

Les durées sont réglées dans `RETENTION_DAYS` (`config/settings/base.py`).
La page « Vos données » affiche les mêmes. La commande
`manage.py purge_personal_data` compte ce qui a passé sa durée ; avec
`--apply`, elle le supprime et note les nombres dans le journal. Elle tourne
une fois par jour, **une fois les durées validées par l'association**.

| Données | Durée par défaut | Point de départ |
| --- | --- | --- |
| Compte d'un ancien résident, et ce qui s'y rattache (ses signalements restent, rendus anonymes) | 365 jours | dernier départ |
| Photos d'un signalement | 180 jours | clôture du signalement |
| Rendez-vous et leur motif | 365 jours | fin du rendez-vous |
| Messages directs avec un éducateur | 365 jours | envoi |
| Destinataires d'un message, réponses « Présent ou Absent » | 365 jours | début de l'envoi |
| Anciens accès wifi d'une chambre | 365 jours | fin de l'accès |
| Journal d'audit | 365 jours | action |
| Codes d'activation, essais ratés, vérifications du téléphone | 30 jours | expiration ou envoi |

Repères :

- **Journal** : la CNIL recommande de six mois à un an
  ([recommandation sur la journalisation](https://cnil.fr/la-cnil-publie-une-recommandation-relative-aux-mesures-de-journalisation)).
- **Après le départ** : pas de durée fixée par un texte. Le responsable la
  choisit, au plus juste
  ([CNIL, logement social, fiche 7](https://www.cnil.fr/sites/default/files/2025-11/logement_social-fiche07.pdf)).
  Un an laisse le temps de régler un retour ou une réclamation.
- Les dossiers papier (bail, état des lieux, comptabilité) ne sont pas dans
  l'application. Ils suivent leurs propres durées.

## 1. Comptes et séjours

- **Finalité** : gérer les résidents et leur chambre ; leur donner accès à
  l'application.
- **Base légale** : exécution du contrat de résidence.
- **Personnes** : résidents, membres de l'équipe.
- **Données** : nom, prénom, téléphone portable (vérifié par SMS), chambre,
  dates d'arrivée et de départ, rôles de l'équipe, clés d'accès (partie
  publique seulement), applications de codes de l'équipe, codes d'activation
  et codes SMS (leur empreinte seulement, jamais en clair).
- **Destinataires** : l'équipe selon ses droits (`accounts/roles.py`).
- **Durée** : le séjour, puis 365 jours après le dernier départ. Le compte
  est coupé le jour du départ. Un compte désactivé sans aucun séjour n'est
  jamais supprimé tout seul : rien ne dit quand il a servi pour la dernière
  fois. L'équipe le supprime à la main.

## 2. Messages aux résidents et SMS

- **Finalité** : informer les résidents (annonces, visites de chambre,
  coupures) et recueillir « Présent ou Absent ».
- **Base légale** : exécution du contrat (vie de la résidence, visites).
- **Personnes** : résidents.
- **Données** : destinataire, canal (notification ou SMS), état de l'envoi
  et de la lecture, réponse « Présent ou Absent ».
- **Destinataires** : l'équipe qui envoie des messages ; le service SMS.
  - OVHcloud (France), par son API d'envoi de SMS ;
  - ou SMSGate, pour les essais : un téléphone Android de la résidence, en
    mode local, cloud ou serveur privé (à préciser).
- **Durée** : 365 jours après l'envoi pour les destinataires, les personnes
  choisies ou retirées par leur nom, et les réponses. Le texte du message
  reste.

## 3. Notifications (Web Push)

- **Finalité** : prévenir le résident sur son téléphone.
- **Base légale** : consentement (le résident les active, et peut les
  couper).
- **Données** : adresse technique de l'appareil, clés de chiffrement.
- **Destinataires** : le service de notification du navigateur (Apple,
  Google, Microsoft, Mozilla). Le contenu est chiffré pour l'appareil : le service ne
  le lit pas.
- **Transfert hors UE** : possible selon le service du téléphone (Apple,
  Google). À noter dans l'information des résidents (c'est fait sur
  « Vos données »).
- **Durée** : jusqu'à la désactivation, un abonnement mort, ou le départ.

## 4. Votes

- **Finalité** : consulter les résidents.
- **Base légale** : intérêt légitime (vie collective).
- **Données** : totaux par choix ; « a voté, tel jour » pour éviter un double
  vote. **Jamais** le choix d'une personne.
- **Durée** : la participation part avec le compte.

## 5. Rendez-vous et messages avec un éducateur

- **Finalité** : prendre rendez-vous et échanger avec un éducateur.
- **Base légale** : exécution du contrat (accompagnement prévu par le projet
  de la résidence).
- **Données** : créneau, motif choisi dans une liste (papiers, emploi,
  budget, logement, autre), messages écrits.
- **Destinataires** : l'éducateur concerné seulement. Le tableau de bord
  compte les rendez-vous, sans le motif.
- **Durée** : 365 jours après le rendez-vous ou l'envoi. Une conversation
  restée vide part aussi.

## 6. Signalements et photos

- **Finalité** : réparer ce qui ne va pas dans une chambre.
- **Base légale** : exécution du contrat (entretien du logement).
- **Données** : chambre, type de problème, description, photos (réduites,
  sans position GPS ni métadonnées, nom de fichier aléatoire), étapes du
  suivi, présence demandée pour l'intervention.
- **Destinataires** : accueil et maintenance. Les photos ne sont servies
  qu'aux personnes autorisées, jamais par un lien public.
- **Durée** : photos 180 jours après la clôture. À la suppression du
  compte, le signalement reste, mais rendu anonyme : plus de nom, de texte,
  de note ni de photo ; s'il était ouvert, il est clos. Il ne garde que la
  chambre, le type de problème, les dates et les étapes : l'histoire des
  réparations de la chambre.

## 7. Wifi des chambres

- **Finalité** : donner l'accès wifi de la chambre.
- **Base légale** : exécution du contrat.
- **Données** : identifiant et mot de passe de la chambre (chiffré), dates.
  Chaque affichage du mot de passe par l'équipe est noté au journal.
- **Durée** : 365 jours après la fin de l'accès.

## 8. Sécurité et journal d'audit

- **Finalité** : savoir qui a fait une action sensible ; détecter un abus.
- **Base légale** : intérêt légitime (sécurité), obligation de sécurité
  (article 32 du RGPD).
- **Données** : auteur, action, cible, date, adresse IP, détails sans
  contenu sensible.
- **Destinataires** : administration (droit « journal d'audit »).
- **Durée** : 365 jours. Une entrée ne se modifie pas et ne se supprime pas
  à la main. Elle garde le nom de l'auteur et de la cible : ce nom peut donc
  durer jusqu'à 365 jours après la suppression d'un compte.

## Mesures de sécurité

- Connexion par clé d'accès (passkey) ; application de codes pour l'équipe.
- Droits par rôle ; pages sensibles jamais gardées en cache.
- Mots de passe wifi chiffrés ; codes stockés en empreinte.
- HTTPS obligatoire, cookies sécurisés (`Secure`, `HttpOnly`, préfixe
  `__Host-`), politique de sécurité du contenu (CSP), fonctions du
  navigateur inutiles coupées (Permissions-Policy).
- Sauvegardes chaque nuit, relues aussitôt (`backup_data`) ; les clés n'y
  sont pas. Copie chiffrée hors du serveur : à fixer avec T38.
- Dépendances vérifiées contre les failles connues à chaque push (`pip-audit`).
- Hébergement, sauvegardes, dossier des photos hors du site public : à
  compléter avec la carte T38 (hébergeur, pays, contrat de sous-traitance).

## Hors de l'application, à prévoir au déploiement (T38)

- Sessions expirées : `manage.py clearsessions` une fois par jour.
- Résultats des tâches de fond : `prune_db_task_results` les efface après
  14 jours (déjà prévu).
- Sauvegardes : leur durée suit celle des données (une donnée supprimée
  disparaît des sauvegardes à leur rotation).

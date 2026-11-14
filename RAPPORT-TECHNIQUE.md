# Rapport technique — SaaS Compliance B2B

**Établissement :** à compléter  
**Auteur :** à compléter  
**Encadrant :** à compléter  
**Version :** 1.0 — document de travail  
**Périmètre :** preuve de concept Flask déployée sur AWS Learner Lab

> Ce rapport décrit l'implémentation et les vérifications disponibles dans le dépôt et dans les résultats communiqués pour l'environnement de démonstration. Il ne constitue ni une certification de conformité ni un audit indépendant de l'environnement AWS.

## Résumé exécutif

SaaS Compliance B2B est une application web de démonstration qui aide à suivre des contrôles de conformité dans un contexte multi-tenant. Elle propose un questionnaire d'évaluation RGPD simplifié, le suivi d'un catalogue de contrôles inspirés d'ISO 27001, la génération de modèles de politiques, l'export de rapports et une piste d'audit.

Le projet met en œuvre plusieurs contrôles de sécurité applicatifs : authentification, rôles, isolation par tenant, protection CSRF et MFA TOTP pour les administrateurs. Les exports sont conservés localement et envoyés dans Amazon S3 avec chiffrement côté serveur. Les journaux applicatifs JSON sont collectés par CloudWatch Agent ; CloudWatch Logs, les filtres métriques, les alarmes, un dashboard et un topic SNS complètent la supervision.

Les **40 tests automatisés** ont réussi lors de la dernière exécution rapportée. Des vérifications EC2 ont également confirmé les endpoints de santé, l'ingestion de journaux et l'existence de la métrique de requêtes. En revanche, la notification par e-mail n'est pas déclarée opérationnelle : l'interrogation SNS du topic a retourné `Topic does not exist`. La sauvegarde/restauration SQLite, le chiffrement EBS et le moindre privilège effectif du rôle de laboratoire restent à documenter.

## 1. Contexte, problématique et objectifs

Les organisations doivent pouvoir suivre des obligations et contrôles de sécurité, conserver des éléments d'audit et détecter des incidents d'exploitation. La problématique du projet est de montrer comment une application B2B peut réunir ces fonctions tout en appliquant des contrôles d'accès par utilisateur et par tenant, puis utiliser des services AWS pour stocker des exports et surveiller l'application.

### Objectifs

1. Mettre à disposition des fonctions simples de suivi RGPD et de contrôles ISO 27001.
2. Séparer les données et exports de chaque tenant.
3. Contrôler les actions selon des rôles et protéger les opérations de modification.
4. Tracer les événements utiles et permettre la corrélation des logs d'une requête.
5. Archiver les rapports sur S3 et surveiller la disponibilité et les événements applicatifs avec CloudWatch.
6. Documenter les procédures de déploiement, de test et d'exploitation.

### Périmètre et exclusions

Le système est une **preuve de concept**. Il n'effectue pas une analyse juridique complète, ne certifie pas une organisation et n'applique pas l'intégralité des référentiels RGPD ou ISO 27001. La notation RGPD dépend d'un questionnaire de démonstration ; le catalogue ISO est un sous-ensemble de contrôles.

Les éléments suivants ne sont pas inclus ou ne sont pas démontrés : haute disponibilité, équilibrage de charge, accès public HTTPS, stockage inviolable des logs, reprise automatisée, déploiement multi-région et moindre privilège effectif du rôle fourni par Learner Lab.

## 2. Besoins fonctionnels et utilisateurs

| Acteur | Besoin | Réponse de l'application |
|---|---|---|
| Administrateur (`admin`) | Administrer l'accès et les opérations de conformité | Rôle applicatif d'écriture, MFA TOTP obligatoire ; comptes gérés par une commande CLI opérateur |
| Responsable conformité (`compliance`) | Créer et mettre à jour des évaluations et contrôles | Accès de lecture et d'écriture dans son tenant |
| Auditeur (`auditor`) | Consulter des éléments sans les modifier | Accès en lecture aux fonctions d'audit autorisées ; les écritures sont refusées |
| Opérateur technique | Déployer, sauvegarder et diagnostiquer l'application | Accès contrôlé au terminal EC2 et identité AWS de l'instance |

### Fonctions principales

- **RGPD :** formulaire de contrôle simplifié, score indicatif, statut, recommandations et historique.
- **ISO 27001 :** catalogue sélectionné de contrôles et état d'avancement.
- **Politiques :** génération de modèles de politiques de sécurité.
- **Rapports :** export JSON/CSV et génération PDF texte ; téléchargement dans le navigateur et archivage S3.
- **Piste d'audit :** actions métier et résultats des opérations importantes.
- **Supervision :** contrôles health, logs JSON corrélés, métriques, alarmes et dashboard.

## 3. Architecture technique

```text
Poste d'administration
   ├── navigateur → http://127.0.0.1:5000
   └── tunnel SSH chiffré vers EC2:127.0.0.1:8000
                                      │
                                      ▼
                         EC2 Amazon Linux
                         ├── Gunicorn
                         │    └── application Flask
                         ├── SQLAlchemy / Flask-Migrate
                         │    └── SQLite (configuration de démonstration)
                         ├── rôle IAM d'instance → Amazon S3
                         └── app.log (événements JSON)
                                  │
                         CloudWatch Agent
                                  ▼
                         CloudWatch Logs
                           ├── filtres métriques → CloudWatch Alarms
                           ├── CloudWatch Dashboard
                           └── SNS → abonnement e-mail
```

Le serveur Gunicorn écoute sur `127.0.0.1:8000`. Le port n'est pas destiné à être exposé directement ; l'accès de démonstration se fait par un tunnel SSH. Flask fournit les routes et vues web, Flask-Login gère la session, SQLAlchemy l'accès aux données, Flask-Migrate les migrations et Flask-WTF la protection CSRF.

La base est SQLite par défaut. La configuration SQLAlchemy peut recevoir une autre URI via `DATABASE_URL`, et le pilote PostgreSQL est présent dans les dépendances ; toutefois, les résultats de tests et de déploiement décrits dans ce rapport concernent principalement SQLite.

## 4. Services AWS et technologies

| Technologie/service | Utilisation | Justification dans la preuve de concept |
|---|---|---|
| Python 3 et Flask | Routes, logique métier et interfaces applicatives | Cadre léger adapté à une application web de démonstration |
| Flask-Login / Flask-WTF | Session authentifiée et CSRF | Réutilisation de mécanismes établis pour les formulaires et sessions |
| SQLAlchemy / Flask-Migrate | Modèles de données et migrations | Séparation entre modèles applicatifs et accès SQL ; évolution versionnée du schéma |
| PyOTP | Codes TOTP des administrateurs | Second facteur sans intégrer un fournisseur MFA externe |
| Gunicorn | Serveur WSGI sur EC2 | Serveur de production Python distinct du serveur de développement Flask |
| EC2 | Hébergement de la PoC | Fournit l'environnement Linux et le rôle IAM d'instance |
| IAM Instance Profile / LabRole | Identité technique AWS de l'application | Évite les clés AWS permanentes dans le code ou les variables de configuration |
| Amazon S3 | Archivage des rapports et exports | Stockage objet durable ; chaque envoi demande SSE-S3 (`AES256`) et conserve aussi une copie locale |
| CloudWatch Agent | Lecture de `app.log` et collecte vers AWS | Relie les événements produits sur EC2 à CloudWatch Logs |
| CloudWatch Logs | Réception et conservation des événements | Centralise les logs ; groupe avec rétention configurée à 30 jours |
| CloudWatch Metric Filters / Alarms | Transformation des événements en indicateurs et seuils d'alerte | Détection des erreurs, événements de sécurité et latence |
| CloudWatch Dashboard | Visualisation des métriques | Regroupe les indicateurs d'exploitation et de sécurité |
| Amazon SNS | Distribution des notifications d'alarmes | Sépare la détection CloudWatch du canal de notification e-mail |
| AWS CloudFormation | Déclaration des ressources de supervision | Rend la configuration du groupe, filtres, alarmes et topic reproductible |

Les ressources CloudWatch sont définies dans [infra/cloudwatch-metric-filters.json](./infra/cloudwatch-metric-filters.json), la collecte dans [infra/cloudwatch-agent-config.json](./infra/cloudwatch-agent-config.json), et les widgets dans [infra/cloudwatch-dashboard.json](./infra/cloudwatch-dashboard.json).

## 5. Conception et implémentation

### 5.1 Gestion des comptes, rôles et MFA

Les rôles de l'application sont distincts du rôle IAM AWS. Les autorisations applicatives sont `admin`, `compliance` et `auditor`. Les fonctions sensibles vérifient l'authentification puis le rôle. L'auditeur est en lecture seule ; les écritures sont réservées aux rôles autorisés.

Chaque utilisateur est rattaché à un tenant. Les routes utilisent le tenant de l'utilisateur connecté et les requêtes de données sont filtrées par ce tenant ; une valeur de tenant transmise par le navigateur ne doit pas servir de source d'autorité. La MFA TOTP est exigée pour les administrateurs avant l'accès aux pages protégées. Le code TOTP déjà utilisé est refusé afin de limiter sa réutilisation.

### 5.2 Données et piste d'audit

Les modèles principaux couvrent `Tenant`, `User`, `RgpdAudit`, `Iso27001Control` et `AuditLog`. Les migrations sont gérées par Flask-Migrate. La piste d'audit en base conserve notamment l'action, le résultat, la ressource, l'acteur lorsqu'il est connu et le tenant associé.

La piste d'audit applicative ne remplace pas AWS CloudTrail. L'attribution d'une commande CLI est limitée, car la CLI n'authentifie pas à elle seule une identité humaine opératrice.

### 5.3 Exports vers S3

Les rapports et exports générés par l'interface sont associés au tenant de la session authentifiée. Ils sont écrits localement sous `instance/audit_exports/<tenant>/reports/`, puis envoyés vers S3 sous `tenants/<tenant>/reports/`. Les fichiers locaux sont créés de façon exclusive avec des permissions POSIX restreintes lorsqu'elles sont disponibles.

L'envoi transmet le type de chiffrement serveur demandé et vérifie que S3 confirme le chiffrement dans la réponse. Les erreurs réseau ou S3 transitoires sont réessayées jusqu'à trois fois ; un refus d'accès n'est pas réessayé. En cas d'échec de transfert, la copie locale est conservée et l'application affiche un échec/état partiel au lieu de déclarer l'envoi réussi.

### 5.4 Journaux, santé et supervision

Une ligne de fin de requête JSON contient l'horodatage UTC, l'événement, l'identifiant généré côté serveur, la méthode, le nom de route, le statut et la durée. L'en-tête fourni par un client ne peut pas imposer l'identifiant de corrélation. Les champs de requête sensibles ne sont pas inclus dans le message de fin de requête.

Les événements suivis incluent notamment authentification/MFA, refus d'accès, HTTP 5xx, exceptions, exports S3 et disponibilité de la base. `/health/live` teste la réponse du processus ; `/health/ready` effectue un `SELECT 1` et renvoie HTTP 503 sans exposer de détails internes si la base est indisponible.

Le modèle CloudFormation configure sept métriques et six alarmes, sans dimension par tenant ou utilisateur. Le groupe de journaux est rétenté 30 jours. `DeletionPolicy: Retain` et `UpdateReplacePolicy: Retain` évitent la suppression du groupe par la pile lors de certains changements, mais ne fournissent pas d'immutabilité.

## 6. Sécurité, confidentialité et limites

### Mesures mises en œuvre

- Hash des mots de passe, sessions HTTP-only et SameSite configuré.
- MFA obligatoire pour les comptes administrateurs.
- Autorisations selon le rôle et isolation tenant.
- CSRF pour les mutations, contrôles et validations côté serveur.
- Identité AWS de l'instance plutôt que clés IAM permanentes.
- Exports avec SSE-S3 ; vérification antérieure rapportée du blocage d'accès public et du chiffrement par défaut du bucket.
- Fichier local `app.log` vérifié avec mode `600`.
- Chiffrement au repos CloudWatch Logs géré par AWS ; aucun `KmsKeyId` client n'est associé au groupe selon la vérification fournie.
- Exposition réseau de démonstration limitée à SSH et à un tunnel local.

### Limites et risques résiduels

1. **Pas de HTTPS public.** Le déploiement est conçu pour la démonstration par tunnel SSH ; `SESSION_COOKIE_SECURE=false` ne doit pas être repris tel quel pour un service public.
2. **Pas de haute disponibilité.** Une seule instance ne protège pas contre la panne de l'hôte ou de sa zone.
3. **Protection des journaux non immuable.** La rétention et `Retain` ne bloquent pas un principal AWS autorisé à supprimer des logs. S3 Object Lock n'est pas configuré.
4. **IAM du laboratoire.** Les permissions exactes du `LabRole` ne sont pas démontrées comme étant au moindre privilège.
5. **SNS à confirmer.** Une requête `list-subscriptions-by-topic` a retourné `Topic does not exist`. Il faut confirmer le compte et `us-east-1`, récupérer l'ARN de sortie de la pile, rattacher l'abonnement confirmé à ce topic et vérifier une notification de test.
6. **Base et volume.** Les preuves de restauration SQLite et de chiffrement EBS ne sont pas consignées dans l'état actuel des livrables.
7. **Fonctions métier indicatives.** Un score RGPD, un contrôle ISO sélectionné et les modèles de politiques ne sont pas une preuve de conformité ni un avis juridique.
8. **Contrôles de compte à renforcer.** La limitation de débit et le verrouillage après échecs répétés restent à ajouter si le projet devait sortir du cadre de PoC.

## 7. Stratégie de test et résultats

### Tests automatisés

La suite est lancée par :

```bash
python3 -m unittest discover -s tests
```

La dernière exécution rapportée donne **40 tests, résultat `OK`**. Les cas couvrent :

| Domaine | Exemples de vérification | Nombre de cas rapporté |
|---|---|---:|
| Authentification, MFA, rôles, isolation tenant et CSRF | Refus d'accès, MFA admin, rejeu TOTP, données inter-tenant | 19 |
| Exports/audit S3 | Chiffrement demandé, copie locale, erreurs, retries, sécurité du bucket | 8 |
| Exports navigateur | JSON/CSV/PDF, rôles, CSRF, contenu invalide, échec S3 | 5 |
| Logs structurés | JSON, requête non trouvée, corrélation, absence de détails sensibles | 4 |
| Health | Liveness indépendante de la base et readiness disponible/indisponible | 3 |
| Migrations | Schéma sur base neuve | 1 |
| **Total** |  | **40** |

Les tests S3 utilisent des doubles/mocks pour vérifier les comportements du code ; ils ne remplacent pas une validation des permissions et ressources AWS réelles.

### Vérifications d'environnement communiquées

| Contrôle | Résultat observé | Statut |
|---|---|---|
| `/health/live`, `/health/ready` | HTTP 200 | Vérifié |
| CloudWatch Agent | `running`, `configured` | Vérifié au moment du test |
| Ingestion CloudWatch Logs | Événement JSON reçu dans le flux de l'instance après une requête | Vérifié |
| `RequestCount` | Série retournée par `cloudwatch list-metrics` | Existence observée ; datapoint récent à confirmer |
| CloudFormation | Pile créée avec succès, puis mise à jour réussie | Vérifié |
| Groupe CloudWatch Logs | 30 jours ; `KmsKeyId` vide | Vérifié |
| Permissions du fichier local | `600 ec2-user:ec2-user` | Vérifié |
| Abonnement SNS du topic CloudFormation | Appel AWS a répondu `NotFound: Topic does not exist` | Non validé |
| Chiffrement EBS et test de restauration | Pas de preuve disponible | À vérifier |

## 8. Déploiement et exploitation

La procédure complète est dans [DEPLOYMENT.md](./DEPLOYMENT.md), [COMMANDES-PROJET.md](./COMMANDES-PROJET.md) et [PROCEDURES-EXPLOITATION.md](./PROCEDURES-EXPLOITATION.md). Le principe de déploiement est :

1. Préparer l'instance Amazon Linux, le rôle IAM, l'environnement Python et `.env` protégé.
2. Appliquer les migrations et créer le compte initial par la CLI.
3. Lancer Gunicorn sur `127.0.0.1:8000` et accéder via un tunnel SSH.
4. Vérifier les contrôles health et les tests applicatifs.
5. Déployer la pile CloudFormation et configurer CloudWatch Agent.
6. Vérifier le groupe, les métriques et le dashboard.
7. Confirmer l'abonnement au topic SNS exact avant de déclarer les alertes opérationnelles.
8. Sauvegarder la base séparément des exports de rapports et vérifier les sauvegardes.

## 9. Perspectives d'amélioration

Priorité recommandée :

1. Résoudre et documenter le topic SNS de la pile, puis valider la notification de bout en bout.
2. Vérifier l'accès IAM effectif et réduire les autorisations si le laboratoire le permet.
3. Effectuer un test documenté de sauvegarde et restauration ; confirmer le chiffrement du volume EBS.
4. Ajouter limitation de débit et procédures de récupération de compte.
5. Pour un service réel, déployer derrière un point d'entrée HTTPS, activer les cookies sécurisés et mettre en place haute disponibilité et surveillance de l'hôte.
6. Si l'immutabilité est requise, concevoir une archive séparée avec S3 Object Lock et des règles de rétention approuvées.
7. Compléter le catalogue métier et faire valider les questions, scores et modèles de politiques par des spécialistes.

## Conclusion

La preuve de concept démontre une chaîne applicative cohérente associant contrôle d'accès, cloisonnement multi-tenant, audit, exports S3 et supervision CloudWatch. La suite de 40 tests et les vérifications de santé et de collecte rapportées fournissent des éléments de validation utiles. Le projet reste toutefois un environnement de démonstration : la livraison SNS, la reprise de la base, le chiffrement EBS, la configuration IAM effective et plusieurs exigences de production restent des travaux identifiés.

## Références du dépôt

- [Analyse du projet](./ANALYSE-PROJET.md)
- [Argumentaire des choix](./FICHE-ARGUMENTATION.md)
- [Plan de présentation](./PLAN-PRESENTATION.md)
- [IAM et Zero Trust](./IAM-ZERO-TRUST.md)
- [Piste d'audit et supervision](./AUDIT-LOGGING.md)

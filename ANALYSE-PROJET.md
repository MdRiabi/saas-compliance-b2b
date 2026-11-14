# Analyse du projet SaaS Compliance B2B

**Nature du document :** analyse fonctionnelle, technique et sécurité de la preuve de concept.  
**Périmètre :** dépôt applicatif et éléments de configuration AWS documentés ici. Les résultats d'exploitation mentionnés proviennent des vérifications communiquées par l'équipe du projet et ne constituent pas une nouvelle vérification de l'environnement AWS.

## 1. Contexte et objectif

Le projet est une application web de démonstration destinée à aider une organisation à suivre certains éléments de conformité. Il regroupe des fonctions RGPD, un suivi de contrôles inspirés d'ISO 27001, la génération de politiques de sécurité, la journalisation des actions et l'archivage d'exports. L'hébergement sur AWS sert aussi à mettre en pratique l'identité IAM, EC2, S3 et la supervision CloudWatch.

L'application est une **preuve de concept** et un outil de suivi. Elle ne réalise pas un audit juridique, ne certifie pas la conformité RGPD ou ISO 27001 et ne remplace pas l'analyse d'un professionnel.

## 2. Périmètre fonctionnel

| Domaine | Fonction réalisée | Limite importante |
|---|---|---|
| Comptes et accès | Connexion par mot de passe, rôles `admin`, `compliance`, `auditor`, MFA TOTP obligatoire pour `admin` | Pas de limitation de débit ni de verrouillage après échecs répétés |
| Cloisonnement B2B | Données filtrées selon le tenant associé à l'utilisateur connecté | La séparation doit rester vérifiée à chaque nouvelle route ou requête |
| RGPD | Questionnaire de contrôle simple, score, état et recommandations, historique | Le score est indicatif et ne démontre pas à lui seul la conformité |
| ISO 27001 | Catalogue de contrôles sélectionnés et suivi d'avancement | Le catalogue ne constitue pas une implémentation complète d'ISO 27001 |
| Politiques | Génération de textes de politiques prédéfinis | Les textes sont des modèles à faire valider et adapter |
| Exports | JSON/CSV et génération de PDF texte, copie locale et envoi S3 | Le PDF ne reproduit pas exactement la mise en page imprimée du navigateur |
| Audit applicatif | Enregistrement d'actions et résultats associés | Ne remplace pas CloudTrail ni un journal inviolable |
| Supervision | Logs JSON, identifiant de requête, métriques, alarmes et dashboard CloudWatch | La notification SNS doit être vérifiée pour le topic réellement utilisé par la pile |

## 3. Architecture et flux

```text
Navigateur
   │ tunnel SSH local (accès de démonstration)
   ▼
EC2 Amazon Linux ── Gunicorn ── application Flask
   │                                  ├── SQLite (configuration locale par défaut)
   │                                  ├── rôle IAM d'instance → S3 (exports chiffrés)
   │                                  └── app.log (JSON)
   │                                         │
   └── CloudWatch Agent ────────────────────┘
                      ▼
        CloudWatch Logs → filtres métriques → alarmes
                      ├── dashboard
                      └── topic SNS → abonnement e-mail
```

Le dépôt contient les configurations de collecte et de tableau de bord sous `infra/`. Le modèle CloudFormation déclare le groupe CloudWatch Logs, les filtres métriques, les alarmes et le topic SNS. La région de démonstration documentée est `us-east-1`.

## 4. Données et composants principaux

- **Données applicatives :** utilisateurs et tenant, audits RGPD, contrôles ISO, événements d'audit.
- **Identifiants :** mots de passe stockés sous forme de hash ; secret TOTP conservé dans la base. Le secret Flask doit être fourni hors du dépôt.
- **Données de journalisation :** horodatage, niveau, événement, identifiant de requête, méthode, endpoint, statut, durée et métadonnées limitées. Les secrets, mots de passe, codes MFA, cookies, URL complètes et corps de requête ne doivent pas y figurer.
- **Exports :** copie locale sous `instance/audit_exports/` et objets S3 sous `tenants/<tenant>/reports/`. Le tenant est déterminé depuis la session authentifiée.
- **Ressources de supervision :** groupe `/saas-compliance-b2b/app`, rétention de 30 jours et métriques dans `SaasCompliance/Application`.

## 5. Contrôles de sécurité réalisés

### Contrôles applicatifs

- Authentification requise pour les pages protégées et autorisation fondée sur les rôles.
- Tenant dérivé de l'utilisateur authentifié, pas d'un `tenant_id` fourni par le navigateur.
- Écritures protégées par rôles et CSRF ; validation des entrées sur les fonctions principales.
- MFA TOTP pour les administrateurs, avec refus des codes déjà utilisés.
- Identifiant de requête généré côté serveur et propagation dans l'en-tête `X-Request-ID` et les logs.
- Endpoints `/health/live` et `/health/ready` : le second exécute `SELECT 1` et retourne un statut non détaillé si la base est indisponible.

### Contrôles AWS et hôte

- Identité AWS de l'application par rôle d'instance, sans clé permanente dans le code ou `.env`.
- Exports envoyés avec chiffrement SSE-S3 (`AES256`) et accès public du bucket vérifié dans les résultats précédemment rapportés.
- Gunicorn prévu pour écouter sur `127.0.0.1:8000`, accessible au poste via tunnel SSH ; SSH devrait être limité à l'IP d'administration.
- `app.log` vérifié avec le mode Unix `600`.
- Le groupe CloudWatch a une rétention de 30 jours, un chiffrement au repos géré par AWS et les politiques de conservation CloudFormation `Retain`.
- Ces protections ne rendent pas les journaux inviolables. Object Lock S3 n'est pas configuré.

## 6. Analyse synthétique des risques

| Risque | Mesures présentes | Risque résiduel / action |
|---|---|---|
| Accès inter-tenant | Filtrage par tenant authentifié et tests dédiés | Conserver des tests d'isolation pour chaque nouvelle route et chaque export |
| Compromission d'un compte | Hash de mot de passe, MFA admin, rôles, CSRF | Ajouter limitation de débit, verrouillage/récupération contrôlée et MFA pour les autres rôles si le périmètre l'exige |
| Fuite de secrets par les logs | Champs de log limités et événements structurés | Continuer à vérifier les nouvelles exceptions et éviter les payloads sensibles |
| Compromission ou suppression des logs | Accès local `600`, groupe avec rétention et chiffrement au repos | Restreindre les permissions AWS de lecture/suppression ; prévoir Object Lock si une preuve immuable est nécessaire |
| Perte de la base locale | Procédure de sauvegarde SQLite documentée | Effectuer régulièrement des sauvegardes hors instance et tester une restauration ; chiffrement EBS à confirmer dans la console |
| Indisponibilité de l'instance | Contrôles health et alarmes d'application | Une seule instance, pas de haute disponibilité ni de bascule automatique |
| Exposition HTTP | SSH et tunnel local pour la démonstration | Ce déploiement ne convient pas à un accès public ; prévoir domaine, HTTPS, terminaison TLS et cookie sécurisé avant publication |
| Alertes non reçues | Topic SNS et alarmes déclarés dans CloudFormation | L'appel `list-subscriptions-by-topic` a retourné `Topic does not exist` ; vérifier région, compte et abonnement au topic exact de la pile |
| IAM trop large | Rôle EC2, aucune clé statique | Le moindre privilège effectif de `LabRole` n'est pas démontré ; vérifier la politique attachée ou utiliser un rôle dédié |
| Interprétation excessive des scores | Évaluations et recommandations explicites dans l'interface | Ne pas présenter les scores comme une certification ou un avis juridique |

## 7. Supervision CloudWatch

Le modèle définit sept métriques : `Http5xxCount`, `AuthenticationFailureCount`, `AuthorizationDeniedCount`, `S3ExportFailureCount`, `DatabaseExceptionCount`, `RequestCount` et `RequestDurationMs`.

Les six alarmes ont les seuils initiaux suivants :

- au moins un 5xx, échec S3 ou exception de base sur 5 minutes ;
- au moins cinq échecs d'authentification ou dix refus d'accès sur 5 minutes ;
- durée moyenne supérieure à 2 000 ms durant deux périodes consécutives de 5 minutes.

Les périodes sans données ne sont pas considérées comme des dépassements. Les métriques ne comportent pas de dimensions par tenant ou utilisateur afin de limiter la cardinalité et l'exposition de données personnelles.

## 8. Résultats de validation disponibles

| Vérification | Résultat rapporté | Conclusion |
|---|---|---|
| Tests automatisés | 40 tests exécutés, `OK` | Réussite du jeu de tests local, pas preuve d'absence de défaut |
| Contrôles `/health/live` et `/health/ready` | HTTP 200 | Processus Flask et connexion de test à la base répondent |
| CloudWatch Agent | `running`, `configured` | Agent actif au moment de la vérification |
| CloudWatch Logs | Flux d'instance présent et événement JSON reçu après une requête | Collecte de logs observée |
| CloudWatch métrique `RequestCount` | Métrique retournée par `list-metrics` | Métrique créée ; consulter les datapoints pour vérifier sa valeur temporelle |
| CloudFormation | `CREATE_COMPLETE`, puis déploiement de mise à jour réussi | Ressources de la pile créées/mises à jour |
| Groupe CloudWatch | rétention 30 jours, `KmsKeyId` vide | Pas de clé KMS client associée ; CloudWatch Logs chiffre au repos par défaut |
| Protection du fichier local | mode `600`, propriétaire `ec2-user` | Protection locale constatée |
| Abonnement SNS du topic de pile | `ListSubscriptionsByTopic` a renvoyé `NotFound: Topic does not exist` | Livraison d'alarme par e-mail non validée ; vérifier l'ARN de sortie avec la région `us-east-1` |
| Sauvegarde/restauration SQLite et chiffrement EBS | preuves non consignées ici | À vérifier avant de conclure ces contrôles |

Les résultats d'une commande AWS dépendent de la région et de l'identité active. Pour les contrôles de cette architecture, utiliser explicitement `us-east-1` et vérifier que l'ARN de SNS est celui de la sortie `AlarmNotificationTopicArn` de la pile `saas-compliance-supervision`.

## 9. Conclusion

La preuve de concept couvre l'isolation multi-tenant, les rôles applicatifs, la MFA administrateur, l'archivage S3, la journalisation structurée et une chaîne de supervision CloudWatch. Les tests applicatifs et plusieurs contrôles réels d'exploitation ont réussi.

Le statut ne doit pas être présenté comme « tout validé » tant que l'abonnement SNS au topic exact de la pile et la réception d'une notification de test ne sont pas confirmés. La sauvegarde/restauration de la base, le chiffrement EBS et le moindre privilège réel de `LabRole` restent également à documenter. Le déploiement demeure une démonstration non HA, non publique et non certifiante.

## 10. Documents associés

- [Procédures d'exploitation et de test](./PROCEDURES-EXPLOITATION.md)
- [Commandes du projet](./COMMANDES-PROJET.md)
- [Déploiement provisoire EC2](./DEPLOYMENT.md)
- [IAM et Zero Trust](./IAM-ZERO-TRUST.md)
- [Piste d'audit et CloudWatch](./AUDIT-LOGGING.md)

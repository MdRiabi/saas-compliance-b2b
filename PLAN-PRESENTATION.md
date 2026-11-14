# Plan de présentation du projet

**Durée proposée :** 15 minutes, démonstration comprise.  
**Public :** jury technique / sécurité cloud.  
**Fil conducteur :** besoin → conception → réalisation → preuves → limites et suites.

## 1. Répartition du temps

| N° | Diapositive | Durée | Message clé |
|---:|---|---:|---|
| 1 | Titre et accroche | 0 min 30 | Présenter SaaS Compliance B2B et l'objectif de la démonstration |
| 2 | Contexte, problème et objectifs | 1 min | Expliquer le besoin de suivi, de cloisonnement et de supervision |
| 3 | Périmètre et utilisateurs | 1 min | Montrer les rôles et les fonctions couvertes, sans prétendre certifier la conformité |
| 4 | Architecture générale | 1 min 30 | Décrire le flux navigateur, EC2, Flask, base, S3 et CloudWatch |
| 5 | Implémentation applicative | 1 min 30 | Expliquer les modules RGPD/ISO, les exports, les modèles et les migrations |
| 6 | Sécurité et IAM | 1 min 30 | Défendre l'isolation tenant, les rôles, MFA, CSRF et l'identité d'instance |
| 7 | Services AWS et observabilité | 1 min 30 | Expliquer S3, CloudWatch, CloudFormation, alarmes et SNS |
| 8 | Démonstration | 3 min | Montrer un parcours contrôlé et des preuves de supervision |
| 9 | Tests et résultats | 1 min 30 | Présenter les 40 tests et les vérifications réelles, en séparant les deux |
| 10 | Limites, prochaines étapes et conclusion | 1 min 30 | Montrer une analyse honnête et une trajectoire d'amélioration |
|  | **Total** | **15 min** |  |

## 2. Contenu conseillé par diapositive

### Diapositive 1 — Titre et accroche (30 secondes)

- Nom du projet, auteur, établissement et encadrant.
- Accroche : « Comment combiner suivi de conformité, isolation multi-tenant et supervision AWS dans une preuve de concept ? »
- Annoncer la démonstration et le périmètre : application web et intégration AWS.

### Diapositive 2 — Contexte, problème et objectifs (1 minute)

- Les équipes doivent suivre contrôles, actions et preuves.
- Un SaaS B2B doit empêcher qu'un tenant consulte les données d'un autre.
- Le projet vise à construire un support de suivi et à démontrer IAM, S3 et CloudWatch.
- Préciser qu'il s'agit d'une aide au suivi, pas d'une certification juridique.

### Diapositive 3 — Périmètre et utilisateurs (1 minute)

- `admin`, `compliance`, `auditor`.
- Fonctions RGPD indicatives, contrôles ISO sélectionnés, génération de politiques et exports.
- L'auditeur consulte sans pouvoir modifier.
- Exclusions : conformité certifiée, plateforme haute disponibilité, accès public HTTPS.

### Diapositive 4 — Architecture générale (1 min 30)

Présenter un schéma simplifié :

```text
Navigateur ── tunnel SSH ── EC2/Gunicorn ── Flask ── SQLite
                                  ├── rôle IAM ── S3
                                  └── app.log ── Agent ── CloudWatch
                                                        ├── métriques/alarmes
                                                        ├── dashboard
                                                        └── SNS/e-mail
```

- Expliquer le choix d'une seule instance et du tunnel SSH pour cette démonstration.
- Distinguer les logs applicatifs et les appels AWS suivis par CloudTrail.

### Diapositive 5 — Implémentation et technologies (1 min 30)

- Python/Flask pour les routes et la logique métier.
- Flask-Login, Flask-WTF, SQLAlchemy, Flask-Migrate et PyOTP.
- Gunicorn comme serveur WSGI.
- SQLite pour le déploiement de démonstration ; S3 pour les rapports.
- JSON/CSV et PDF texte ; copie locale conservée si S3 échoue.

### Diapositive 6 — Sécurité et IAM (1 min 30)

- Le tenant vient de l'utilisateur authentifié, pas du navigateur.
- Contrôles de rôles, CSRF, validation d'entrées.
- MFA TOTP pour `admin`.
- Rôle IAM d'instance au lieu de clés statiques.
- Logs limités aux champs nécessaires ; `app.log` en mode `600`.
- Mentionner la limite : le moindre privilège effectif de `LabRole` reste à examiner.

### Diapositive 7 — AWS et supervision (1 min 30)

- S3 : archivage chiffré SSE-S3.
- CloudWatch Agent → Logs → 7 métriques → 6 alarmes.
- Tableau de bord pour trafic, erreurs, sécurité, échecs de services et latence.
- CloudFormation pour créer les ressources de manière reproductible.
- SNS pour les notifications ; signaler que l'abonnement au topic de la pile reste à confirmer.

### Diapositive 8 — Démonstration (3 minutes)

Scénario proposé :

1. Ouvrir une session de test et afficher un module métier.
2. Montrer une page ou route protégée et expliquer le rôle/tenant.
3. Générer un export de démonstration et montrer la confirmation S3 si le Lab est actif.
4. Appeler `/health/ready` et montrer `200` ainsi que l'entrée correspondante dans CloudWatch Logs.
5. Afficher `RequestCount` ou le dashboard.

**Sécurité de la démo :** masquer adresses e-mail, codes MFA, IDs de compte AWS, ARNs complets et données métier réelles. Ne pas déclencher volontairement une vraie alarme en production de démonstration.

**Plan de secours :** si Internet, Learner Lab ou SNS est indisponible, utiliser des captures anonymisées et indiquer précisément quelles preuves ont été observées et quel point reste non validé. Ne jamais présenter une capture ancienne comme un résultat actuel.

### Diapositive 9 — Tests et résultats (1 min 30)

- `python3 -m unittest discover -s tests` : 40 tests, `OK` lors de la dernière exécution rapportée.
- Domaines couverts : authentification/MFA, tenant, exports, logs, health et migrations.
- Résultats AWS rapportés : agent actif, logs reçus, `RequestCount` visible, CloudFormation déployé, rétention 30 jours.
- Échec encore constaté : `list-subscriptions-by-topic` a retourné `Topic does not exist`.
- Distinguer tests unitaires avec mocks et vérifications réelles AWS.

### Diapositive 10 — Limites et conclusion (1 min 30)

- Le score ne prouve pas une conformité réglementaire.
- Pas d'HTTPS public, de haute disponibilité ou de journaux immuables.
- Restauration SQLite, chiffrement EBS, permissions IAM et topic SNS à finaliser/documenter.
- Prochaine étape : résoudre SNS, vérifier IAM, effectuer un test de restauration, puis préparer les évolutions production.
- Conclusion : la valeur du projet est de démontrer des contrôles concrets et de rendre visibles les limites restantes.

## 3. Préparation de la démonstration

### La veille

- Vérifier que le Learner Lab est actif et que l'instance répond.
- Confirmer que le tunnel SSH fonctionne depuis le poste de présentation.
- Tester `/health/live`, `/health/ready`, les logs récents et le dashboard.
- Préparer un compte et des données de démonstration, pas des données personnelles.
- Masquer les identifiants AWS et les adresses dans les captures.
- Garder des captures de secours des tests et résultats réellement vérifiés.

### Juste avant l'oral

- Réduire les fenêtres et préparer les onglets nécessaires.
- Vérifier la région AWS `us-east-1`.
- Éviter les opérations de déploiement, migration et suppression pendant la soutenance.
- Ne pas publier de secrets, `.env`, codes MFA, clés SSH ou détails de compte.
- Si un appel SNS échoue, l'annoncer comme limite observée et passer au plan de secours.

## 4. Répartition possible entre membres

Pour une présentation en groupe, répartir les parties selon les responsabilités réellement réalisées :

| Partie | Responsable possible |
|---|---|
| Contexte, besoin et périmètre | Porteur du sujet |
| Architecture et implémentation Flask | Responsable application |
| Sécurité, IAM et isolation tenant | Responsable sécurité |
| S3, CloudWatch et démonstration AWS | Responsable cloud |
| Tests, limites et conclusion | Présentateur principal |

Chaque membre doit pouvoir expliquer les limites et ne pas attribuer à son travail une configuration AWS qu'il n'a pas vérifiée.

## 5. Documents de préparation

- [Rapport technique](./RAPPORT-TECHNIQUE.md)
- [Fiche d'argumentation](./FICHE-ARGUMENTATION.md)
- [Procédures d'exploitation et de test](./PROCEDURES-EXPLOITATION.md)
- [Analyse du projet](./ANALYSE-PROJET.md)

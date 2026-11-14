# Fiche d'argumentation — SaaS Compliance B2B

Cette fiche sert de support oral pour expliquer les choix du projet, leurs bénéfices et leurs limites. L'argumentation présente la solution comme une **preuve de concept**, et non comme une plateforme certifiée ou prête à être exposée publiquement.

## 1. Message central

> Le projet montre comment une application web multi-tenant peut associer contrôles d'accès, MFA administrateur, archivage chiffré sur S3 et supervision CloudWatch, tout en explicitant les limites d'un déploiement de démonstration dans un Learner Lab.

## 2. Argumentaire des services AWS

| Service | Pourquoi l'utiliser ici ? | Ce qu'il démontre | Limite à reconnaître |
|---|---|---|---|
| **EC2** | Héberger Flask/Gunicorn sur une machine Linux administrable | Déploiement d'une application sur une instance cloud | Instance unique, pas de haute disponibilité ; pas de HTTPS public dans la configuration de démo |
| **IAM rôle d'instance** | Donner une identité AWS à l'application sans clé statique | Authentification AWS temporaire et séparation des identités | `LabRole` est imposé par l'environnement ; ses permissions effectives n'ont pas été démontrées comme minimales |
| **S3** | Archiver les rapports sans les inclure dans l'instance applicative | Stockage objet et chiffrement SSE-S3 (`AES256`) à l'envoi | Les exports ne constituent pas une sauvegarde de la base ; Object Lock n'est pas activé |
| **CloudWatch Logs** | Centraliser les journaux JSON envoyés par CloudWatch Agent | Collecte de logs et rétention définie | La rétention de 30 jours n'est pas une immutabilité |
| **CloudWatch Metric Filters** | Convertir des événements de logs en métriques exploitables | Observabilité pilotée par événements structurés | Les métriques apparaissent après ingestion et ne remplacent pas une supervision de tous les composants |
| **CloudWatch Alarms** | Déclencher des états d'alerte sur des seuils explicites | Détection d'erreurs, d'échecs et de latence | Leur notification e-mail n'est pas validée tant que l'abonnement SNS au bon topic n'est pas confirmé |
| **CloudWatch Dashboard** | Présenter les indicateurs en un même endroit | Visibilité opérationnelle pour la démonstration | Les courbes dépendent de la présence de datapoints |
| **SNS** | Séparer l'alarme de son canal de notification | Distribution e-mail asynchrone | Abonnement confirmé dans la console peut appartenir à un autre topic ; le topic de la pile reste à vérifier |
| **CloudFormation** | Décrire le groupe, filtres, alarmes et topic sous forme de modèle | Infrastructure répétable et changements traçables | Le déploiement nécessite des permissions distinctes de celles de l'agent de logs |

### Pourquoi ne pas utiliser une seule solution de logs ?

CloudWatch Agent lit le fichier local ; CloudWatch Logs centralise les événements ; les filtres produisent des métriques ; les alarmes évaluent ces métriques ; SNS transmet les notifications. Chaque composant a une responsabilité distincte et peut être vérifié séparément.

### Pourquoi CloudTrail ne remplace-t-il pas les logs applicatifs ?

CloudTrail trace les appels d'API AWS et l'activité du compte. Les logs applicatifs décrivent les requêtes HTTP, les routes, les résultats d'authentification et les erreurs métier de cette application. Les deux sources sont complémentaires.

## 3. Argumentaire des technologies applicatives

### Python et Flask

- **Choix :** Python avec Flask pour des routes explicites et une application web légère.
- **Bénéfice :** facilité d'implémentation et de test des fonctions de démonstration.
- **Alternative possible :** framework plus intégré si les besoins de production, le volume ou la gouvernance augmentent.
- **Limite :** la simplicité du framework ne remplace pas la conception des contrôles de sécurité et d'exploitation.

### SQLAlchemy, migrations et SQLite

- **Choix :** ORM SQLAlchemy et Flask-Migrate pour représenter les données et faire évoluer le schéma.
- **Bénéfice :** migrations versionnées et accès aux données séparé de certaines routes.
- **SQLite :** pratique pour une PoC mono-instance et les tests locaux.
- **Limite :** stockage local plus fragile pour une plateforme multi-instance ; la migration vers une base managée demanderait configuration, tests et stratégie de sauvegarde.

### Gunicorn et tunnel SSH

- **Choix :** Gunicorn comme serveur WSGI, lié à `127.0.0.1:8000`, et tunnel SSH pour l'accès de démonstration.
- **Bénéfice :** ne pas exposer directement le serveur de développement Flask ni ouvrir les ports de l'application au public.
- **Limite :** méthode adaptée à une démonstration, pas à un accès utilisateur public à grande échelle. Un environnement réel nécessiterait notamment un domaine, TLS, un point d'entrée contrôlé et des cookies `Secure`.

### Unittest et mocks AWS

- **Choix :** tests `unittest` avec clients AWS simulés pour plusieurs scénarios d'échec.
- **Bénéfice :** tests déterministes, rapides et sans dépendre de l'état du Learner Lab.
- **Limite :** ils ne valident pas à eux seuls les permissions IAM, les configurations AWS déployées ni la livraison réelle d'un e-mail.

## 4. Principes de sécurité à défendre

1. **Séparer identité humaine et identité machine.** Les rôles `admin`, `compliance`, `auditor` sont applicatifs ; le rôle IAM d'EC2 donne des permissions AWS.
2. **Appliquer l'isolation tenant côté serveur.** Le tenant est pris depuis la session authentifiée, et non depuis une valeur de formulaire.
3. **Limiter les privilèges applicatifs.** L'auditeur est en lecture seule ; les mutations ont un contrôle de rôle et CSRF.
4. **Renforcer le rôle privilégié.** La MFA TOTP est obligatoire pour l'administrateur.
5. **Ne pas stocker de clés AWS statiques.** L'application s'appuie sur le rôle de l'instance.
6. **Protéger et minimiser les logs.** Les événements évitent les secrets et contenus de requête ; les noms de routes remplacent les URL complètes.
7. **Énoncer les limites.** Le groupe est rétenté et chiffré au repos, mais les événements ne sont pas inviolables et le compte Learner Lab peut limiter le moindre privilège.

## 5. Questions possibles du jury

### « Votre application garantit-elle la conformité RGPD ? »

Non. Elle fournit un support de suivi et des indicateurs de démonstration. La conformité dépend du contexte, des traitements, des preuves et de la validation des responsables ; un score d'interface ne vaut pas certification.

### « Pourquoi stocker les rapports dans S3 et pas dans CloudWatch ? »

Les rapports sont des objets à conserver et télécharger ; S3 est adapté à leur archivage. CloudWatch sert à centraliser et analyser les événements opérationnels, à produire des métriques et à déclencher des alarmes.

### « Comment le cloisonnement entre clients est-il assuré ? »

Les données sont associées à un `tenant_id` et les routes utilisent le tenant de l'utilisateur authentifié. La valeur soumise par le client n'est pas la source de décision. Des tests vérifient les lectures et écritures entre tenants.

### « Pourquoi garder une copie locale si l'envoi S3 échoue ? »

Pour éviter de perdre le rapport lors d'un problème réseau ou d'un refus AWS. Le résultat signale alors explicitement un échec ou un état partiel ; l'interface ne prétend pas que l'archivage S3 a réussi.

### « Le groupe CloudWatch est-il immuable ? »

Non. Le chiffrement au repos et une rétention de 30 jours protègent la confidentialité et la durée de conservation configurée. `DeletionPolicy: Retain` protège contre la suppression du groupe via certaines opérations de pile, mais un principal ayant des permissions directes peut encore supprimer des logs. S3 Object Lock n'est pas configuré.

### « Pourquoi la notification SNS n'est-elle pas déclarée validée ? »

Parce que l'appel `list-subscriptions-by-topic` effectué sur l'ARN obtenu a répondu `Topic does not exist`. L'abonnement confirmé vu auparavant dans la console pourrait concerner un autre topic ou une autre région. Il faut vérifier la sortie `AlarmNotificationTopicArn` de la pile avec le compte et la région `us-east-1`, puis confirmer l'abonnement et effectuer un test d'envoi.

### « Pourquoi les tests réussis ne suffisent-ils pas pour déclarer AWS entièrement validé ? »

Les tests applicatifs couvrent la logique locale et utilisent des mocks pour AWS. Ils ne prouvent pas que les permissions réelles, le topic SNS, le datapoint d'une période donnée, les sauvegardes ou la restauration fonctionnent dans le compte cloud.

### « Que feriez-vous ensuite pour une mise en production ? »

Je confirmerais l'abonnement SNS, vérifierais et réduirais les permissions IAM, testerais sauvegarde/restauration, confirmerais le chiffrement EBS, puis ajouterais une exposition HTTPS maîtrisée, une stratégie de haute disponibilité, des contrôles de comptes complémentaires et une supervision de l'infrastructure.

## 6. Formulations recommandées

### À dire

- « Les tests automatisés exécutés dans le dépôt ont réussi ; les contrôles AWS en production de démonstration sont rapportés séparément. »
- « Le rôle de laboratoire permet d'illustrer l'identité d'instance, mais nous n'affirmons pas que sa politique est au moindre privilège. »
- « Le topic SNS doit encore être rapproché de la sortie de la pile ; l'e-mail d'alarme n'est donc pas annoncé comme testé. »
- « L'application aide au suivi de conformité ; elle ne certifie pas l'organisation. »

### À éviter

- « L'application est entièrement conforme RGPD/ISO. »
- « Le compte est inviolable parce que les journaux sont chiffrés. »
- « L'alarme envoie correctement les e-mails » sans preuve de réception.
- « Le projet est prêt pour Internet » sans HTTPS, haute disponibilité et durcissement complémentaire.

## Documents complémentaires

- [Rapport technique](./RAPPORT-TECHNIQUE.md)
- [Plan de présentation](./PLAN-PRESENTATION.md)
- [Analyse du projet](./ANALYSE-PROJET.md)
- [Procédures d'exploitation et de test](./PROCEDURES-EXPLOITATION.md)

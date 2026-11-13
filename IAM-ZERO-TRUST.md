# IAM et Zero Trust

## Périmètre de la PoC

Deux plans d'identité sont à distinguer :

- **Application B2B** : utilisateurs `admin`, `compliance` et `auditor`, isolés par tenant.
- **AWS** : identité technique de l'instance EC2, utilisée par boto3 pour écrire les rapports dans S3 et vérifier la configuration du bucket.

Le rôle applicatif d'un utilisateur ne lui donne aucun droit IAM AWS. Inversement, le rôle IAM EC2 ne doit pas être utilisé comme identité d'un utilisateur B2B.

## Autorisations applicatives actuelles

| Rôle | RGPD | ISO 27001 | Politiques | Gestion des comptes |
|---|---|---|---|---|
| `admin` | Lecture et écriture | Lecture et écriture | Lecture et génération | Création par un opérateur via la CLI, pas depuis l'application |
| `compliance` | Lecture et écriture | Lecture et écriture | Lecture et génération | Aucune |
| `auditor` | Lecture seule | Lecture seule | Accès refusé à l'espace des politiques | Aucune |

Les mutations sont protégées par authentification, contrôle de rôle et CSRF. Le tenant est pris depuis l'utilisateur connecté, pas depuis une valeur `tenant_id` fournie par le navigateur. Les tests vérifient notamment l'accès refusé aux écritures pour un auditeur et l'isolation des données entre tenants.

`admin` et `compliance` ont les mêmes droits d'écriture dans les modules. La MFA TOTP est obligatoire pour `admin` : au premier accès, l'administrateur doit enrôler une application d'authentification, puis fournir un code à chaque connexion. Les sessions d'administration antérieures à la MFA sont refusées. Les rôles `compliance` et `auditor` n'ont pas de MFA dans cette PoC. Le verrouillage après échecs répétés et la limitation de débit à la connexion restent à ajouter.

La clé TOTP est conservée dans la base de l'application et n'est jamais écrite dans les journaux. Le fichier SQLite, ses sauvegardes et le volume EC2 doivent donc être protégés contre l'accès non autorisé et chiffrés au repos. Une réinitialisation d'urgence est possible uniquement depuis la CLI de l'hôte ; elle doit suivre une vérification d'identité hors bande et son événement est journalisé comme `system:cli-operator`, sans prétendre identifier la personne derrière le terminal.

## Identité AWS de l'application

Sur EC2, utiliser un **rôle IAM attaché à un instance profile**. Ne pas stocker de clés d'accès IAM dans le dépôt, `.env`, le crontab ou le code. boto3 utilise alors la chaîne d'identifiants de l'instance.

Sur l'instance vérifiée, le profil `LabInstanceProfile` est attaché et `aws sts get-caller-identity` retourne une identité assumée `LabRole`. L'accès S3 de l'application a également été vérifié avec succès. Cela confirme l'utilisation du rôle d'instance, mais pas que ses permissions respectent le moindre privilège : la politique gérée par le Learner Lab doit encore être examinée et peut être plus large que nécessaire.

Sur cette instance, `~/.aws/credentials` contient aussi d'anciens identifiants temporaires expirés, qui prennent priorité sur le rôle EC2. Pour les commandes de vérification ci-dessous, `AWS_SHARED_CREDENTIALS_FILE=/dev/null` permet d'ignorer ce fichier et d'utiliser le rôle d'instance. Ne copiez pas de clés AWS dans `.env`.

La politique ci-dessous reste la **cible de moindre privilège** pour un rôle dédié à l'application. Elle correspond aux appels actuellement effectués sur le bucket `saas-audit-reports-sec-2026-unique` : `PutObject` sous `tenants/*/reports/*` avec SSE-S3, et lectures des paramètres de sécurité du bucket. Ne pas présenter cette politique cible comme celle effectivement attachée à `LabRole` sans avoir vérifié les politiques du rôle.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteEncryptedTenantReports",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::saas-audit-reports-sec-2026-unique/tenants/*/reports/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-server-side-encryption": "AES256"
        }
      }
    },
    {
      "Sid": "ReadAuditBucketSecuritySettings",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketPolicyStatus",
        "s3:GetEncryptionConfiguration"
      ],
      "Resource": "arn:aws:s3:::saas-audit-reports-sec-2026-unique"
    }
  ]
}
```

Cette politique n'accorde ni lecture de rapports, ni suppression, ni liste du bucket, ni modification de sa politique ou de ses paramètres. L'application utilise actuellement `AES256` par défaut. Si SSE-KMS est activé, adapter explicitement la condition et accorder au rôle uniquement les actions KMS requises sur la clé choisie.

Un rôle dédié à l'application doit avoir une relation de confiance permettant à EC2 de l'assumer :

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Un rôle dédié serait attaché à l'instance via un instance profile. Si le Lab ne permet pas de créer une politique dédiée, conserver la politique ci-dessus comme **architecture cible** et signaler que le moindre privilège n'est pas démontré ; ne pas remplacer le rôle par des identifiants administrateur permanents.

## Vérifications à effectuer

Les vérifications ne se font pas toutes au même endroit : la console AWS sert à contrôler la configuration de l'instance, le terminal SSH sert à tester l'instance et son identité, et le navigateur sert à tester les rôles applicatifs.

### 1. Contrôler les ports dans la console AWS

Dans AWS Console : **EC2 → Instances → sélectionner l'instance → onglet Security → cliquer sur le Security group → Inbound rules**.

Vérifier que :

- SSH TCP `22` est autorisé uniquement depuis votre adresse IP d'administration (`My IP`) ;
- il n'existe aucune règle entrante TCP `5000` ou `8000`.

Le port `5000` est utilisé uniquement sur votre ordinateur par le tunnel SSH. Gunicorn écoute sur `127.0.0.1:8000` dans EC2 ; aucun de ces deux ports ne doit être ouvert au public.

### 2. Vérifier le serveur depuis le terminal SSH d'EC2

Connectez-vous à EC2 en SSH, activez l'environnement virtuel, puis exécutez :

```bash
ss -ltn
curl -I http://127.0.0.1:8000/login
```

Dans la sortie de `ss`, Gunicorn doit écouter sur `127.0.0.1:8000`, et non `0.0.0.0:8000`. `curl` doit recevoir une réponse HTTP (généralement `200` ou une redirection `302`).

### 3. Vérifier l'identité et les permissions AWS

Dans **EC2 → Instances → sélectionner l'instance → onglet Security**, regarder le champ **IAM role**. Si un rôle est affiché, ouvrez-le dans IAM et vérifiez qu'il ne dispose que des permissions nécessaires décrites plus haut.

Après connexion SSH à EC2, exécutez :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws sts get-caller-identity
```

Le résultat doit montrer une identité de rôle assumée par EC2. Si aucun rôle n'est attaché, si la commande échoue faute de permissions, ou si le Learner Lab interdit cette configuration, **ne créez pas de clés IAM permanentes pour contourner le blocage** : notez ce contrôle comme non réalisé et indiquez cette limite dans le rapport.

### 4. Vérifier la sécurité et l'export S3

Toujours depuis le terminal SSH d'EC2, à la racine du dépôt et avec l'environnement virtuel activé :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null python3 -m flask --app run.py verify-audit-s3
AWS_SHARED_CREDENTIALS_FILE=/dev/null python3 -m flask --app run.py export-audit-logs
```

La commande `verify-audit-s3` doit confirmer le blocage de l'accès public et le chiffrement par défaut. `export-audit-logs` doit indiquer que les événements ont été envoyés vers S3 ; s'il n'y a aucun événement à exporter, connectez-vous à l'application pour en générer un, puis relancez la commande. Ces vérifications doivent réussir sans clés AWS statiques dans `.env`.

Lors de la vérification de l'instance de démonstration, l'identité assumée `LabRole` a été confirmée, 11 événements ont été exportés vers S3, et `verify-audit-s3` a retourné un blocage public actif, une politique non publique et un chiffrement par défaut `AES256`. Ces résultats valident le chemin d'accès et les contrôles du bucket, mais pas le moindre privilège des politiques attachées à `LabRole`.

### 5. Vérifier les rôles de l'application

Dans le navigateur, connectez-vous avec des comptes de test de rôles différents. Vérifiez qu'un compte `auditor` peut consulter les données mais ne peut pas les modifier, et que les données d'un tenant ne sont pas visibles depuis un autre tenant. Les tests automatisés du dépôt couvrent également ces contrôles :

```bash
python3 -m unittest discover -s tests
```

Conservez les résultats utiles pour le rapport, mais masquez les adresses e-mail, codes MFA, clés, identifiants de compte AWS et autres informations sensibles dans les captures.

## MFA et contrôles complémentaires

La MFA TOTP des administrateurs est implémentée dans la PoC. Les codes sont à usage unique et une répétition du même code pendant sa fenêtre temporelle est refusée. La commande `reset-admin-mfa` permet à un opérateur autorisé, après vérification d'identité hors bande, de réinitialiser l'enrôlement ; cette commande exige l'accès au terminal de l'hôte.

Les comptes opérateurs AWS doivent également utiliser la MFA lorsque le mécanisme de comptes du Learner Lab le permet. Avant un usage réel, ajouter une limitation des tentatives de connexion et une politique de récupération plus complète.

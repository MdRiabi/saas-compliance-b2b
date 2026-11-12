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

Le Learner Lab ne permet pas actuellement de créer et d'attacher ce rôle à l'instance. La politique ci-dessous est donc une **cible d'architecture**, pas un contrôle déployé. Elle correspond aux appels actuellement effectués par l'application sur le bucket `saas-audit-reports-sec-2026-unique` : `PutObject` sous `tenants/*/reports/*` avec SSE-S3, et lectures des paramètres de sécurité du bucket.

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

Le rôle cible doit avoir une relation de confiance permettant à EC2 de l'assumer :

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

Il serait attaché à l'instance via un instance profile. Comme le Lab ne permet pas cette opération, conserver rôle et politique comme **architecture cible** et préciser cette limite dans le rapport ; ne pas remplacer le rôle par des identifiants administrateur permanents.

## Vérifications à effectuer

Après attachement du rôle, dans un environnement qui l'autorise :

```bash
aws sts get-caller-identity
python3 -m flask --app run.py verify-audit-s3
python3 -m flask --app run.py export-audit-logs
```

La première commande doit indiquer une identité assumée par le rôle EC2. La vérification S3 doit confirmer le blocage public et le chiffrement par défaut. L'export doit réussir sans clés statiques. Conserver des captures des résultats et retirer de celles-ci toute information de compte qui n'est pas nécessaire au rapport. Dans le Learner Lab actuel, cette vérification de rôle ne peut pas être présentée comme réalisée.

## MFA et contrôles complémentaires

La MFA TOTP des administrateurs est implémentée dans la PoC. Les codes sont à usage unique et une répétition du même code pendant sa fenêtre temporelle est refusée. La commande `reset-admin-mfa` permet à un opérateur autorisé, après vérification d'identité hors bande, de réinitialiser l'enrôlement ; cette commande exige l'accès au terminal de l'hôte.

Les comptes opérateurs AWS doivent également utiliser la MFA lorsque le mécanisme de comptes du Learner Lab le permet. Avant un usage réel, ajouter une limitation des tentatives de connexion et une politique de récupération plus complète.

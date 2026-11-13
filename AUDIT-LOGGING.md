# Piste d’audit interne

Cette piste enregistre les actions de l’application; elle ne remplace ni CloudTrail ni les journaux AWS.

## Événements et données

Chaque entrée conserve l’horodatage UTC, le tenant lorsque celui-ci est connu, l’acteur, l’action, la ressource, le résultat et l’identifiant de ressource. Les connexions réussies et échouées sont enregistrées. Pour un identifiant de connexion inconnu, l’adresse saisie n’est pas conservée; les échecs associés à un compte existant sont rattachés à son tenant et à son adresse de compte.

Les modifications et évaluations de contrôles ISO 27001, les audits RGPD, la génération de politiques et les résultats des exports sont également tracés. Les mots de passe, jetons, clés, notes de preuve et contenus des politiques ne sont pas ajoutés aux événements d’audit. Les attributions de rôle via la commande CLI ne sont pas journalisées, conformément au périmètre retenu; la CLI ne fournit pas d’identité d’opérateur authentifiée.

## Journaux applicatifs structurés

L'application génère un identifiant aléatoire côté serveur pour chaque requête HTTP, même si le client fournit son propre en-tête `X-Request-ID`. L'identifiant est retourné dans l'en-tête de réponse `X-Request-ID` et ajouté aux journaux applicatifs émis pendant cette requête. Une ligne JSON de fin de requête contient l'horodatage UTC, le niveau, le nom du journal, l'événement `http.request.completed`, l'identifiant de requête, la méthode HTTP, le nom de route Flask, le statut HTTP et la durée en millisecondes. Les événements sont écrits sur la sortie standard afin que Gunicorn puisse les transmettre à son journal; avec la commande de déploiement actuelle, ils se retrouvent dans `app.log`.

Les événements de sécurité et d'exploitation incluent les échecs/réussites d'authentification et MFA, les refus HTTP 403, les réponses HTTP 5xx, les exceptions applicatives (catégorie et type seulement) et les réussites/échecs d'export S3 (opération et code d'erreur AWS lorsque disponible). Ces événements partagent le même identifiant de requête que la réponse et les autres logs produits pendant la requête.

Les URL complètes, chaînes de requête, en-têtes autres que l'identifiant généré, adresses e-mail, corps des requêtes, cookies, jetons, mots de passe et codes MFA ne sont pas inclus dans ces lignes. Le nom de route est utilisé à la place du chemin afin d'éviter de journaliser des identifiants présents dans l'URL.

Sur EC2, consulter les dernières lignes ainsi :

```bash
tail -n 50 app.log
```

Les lignes doivent être des objets JSON individuels. Cette modification prépare l'application à la collecte par CloudWatch Agent; la configuration de l'agent, du groupe de journaux, de la rétention et des alarmes reste une étape AWS distincte.

## Migration et export

Après déploiement d’une version contenant une nouvelle migration, appliquer le schéma avec :

```powershell
python -m flask --app run.py db upgrade
```

La commande `export-audit-logs` exporte les événements non encore inclus dans un export S3 réussi, séparément par tenant. Un échec ne fait pas avancer le curseur; les événements seront repris au prochain lancement. Chaque lot est d’abord copié dans `instance/audit_exports/<tenant>/reports/` sous un nom UTC unique, puis envoyé à S3. Les copies locales ne sont pas supprimées automatiquement. Sur les systèmes POSIX, les répertoires sont créés avec des permissions restreintes et les fichiers avec le mode `0600`; sur Windows, appliquer une ACL de répertoire adaptée.

Les exports déclenchés dans les interfaces « Plan d’action & rapport d’audit » et « Couverture référentiels & export du pack » sont également archivés : JSON, CSV et PDF. JSON/CSV restent téléchargés par le navigateur; les rapports imprimables sont convertis en PDF texte côté serveur puis archivés. Le PDF n’est pas une reproduction pixel-identique de la mise en page imprimée. Chaque export est envoyé dans `tenants/<tenant>/reports/` et conservé localement sous `instance/audit_exports/<tenant>/reports/`. Le tenant est déterminé par la session authentifiée, jamais par les données envoyées par le navigateur. Les exports d’audit sont autorisés aux rôles admin, compliance et auditor; le pack de politiques est réservé aux rôles d’écriture. Les requêtes sont protégées par CSRF et limitées à 1 Mio par fichier. Un échec S3 est signalé dans l’interface et ne supprime pas la copie locale.

Configurer les variables d’environnement sans enregistrer de clés AWS dans le code :

```text
S3_BUCKET_NAME=saas-audit-reports-sec-2026-unique
AWS_REGION=us-east-1
S3_SERVER_SIDE_ENCRYPTION=AES256
```

L’accès AWS utilise la chaîne d’identifiants standard de boto3 (rôle d’instance lorsqu’il est disponible, sinon identifiants temporaires configurés pour le Lab). Le chiffrement demandé est transmis à chaque `PutObject` et doit être confirmé dans la réponse S3. Les erreurs non transitoires, notamment les refus d’accès, ne sont pas réessayées; les erreurs réseau et S3 transitoires bénéficient de trois tentatives au maximum. Un échec de transfert conserve la copie locale, crée un événement d’échec et rend la commande non réussie.

Pour vérifier en lecture seule le blocage de l’accès public et le chiffrement par défaut du bucket :

```powershell
python -m flask --app run.py verify-audit-s3
```

Cette vérification nécessite les autorisations de lecture S3 correspondantes. Un refus ou une absence d’identifiants est affiché comme un échec, jamais comme une validation.

Après un export depuis l’interface, vérifier dans la console S3 que le nouvel objet apparaît sous `tenants/<tenant>/reports/`. Le préfixe utilise l’identifiant du tenant de l’utilisateur connecté. Le bucket doit confirmer le chiffrement configuré dans `S3_SERVER_SIDE_ENCRYPTION`.

## Planification sur EC2

Exemple de tâche quotidienne à 02:00 UTC dans le crontab du compte qui exécute l’application :

```cron
0 2 * * * cd /chemin/vers/saas-compliance-b2b && /chemin/vers/saas-compliance-b2b/venv/bin/flask --app run.py export-audit-logs >> /chemin/vers/logs/audit-export.log 2>&1
```

Le compte cron doit pouvoir écrire dans le répertoire local d’archives et accéder aux identifiants temporaires AWS. Ne placez pas de clés dans le crontab. Les identifiants temporaires du Learner Lab peuvent expirer; sans rôle IAM ou renouvellement autorisé, l’export planifié vers S3 échouera et restera visible. Dans ce cas, exécuter la commande après avoir renouvelé les identifiants temporaires autorisés.

La vérification réelle du bucket dépend de l’accès accordé par le Lab. L’application ne modifie pas la politique du bucket et n’active pas ses paramètres de sécurité.

# Commandes du projet saas-compliance-b2b

Ce guide rassemble les commandes usuelles pour mettre à jour, démarrer et vérifier l'application. Les commandes AWS ci-dessous sont prévues pour EC2 avec le rôle d'instance `LabRole`. Ne mettez jamais de clés AWS dans le dépôt ou dans `.env`.

## 1. Se connecter à EC2

Depuis PowerShell sur le poste d'administration, ouvrez un tunnel SSH et laissez ce terminal ouvert :

```powershell
ssh -i "C:\chemin\vers\la-cle.pem" -N -L 5000:127.0.0.1:8000 ec2-user@ADRESSE_IP_EC2
```

Ouvrez ensuite `http://127.0.0.1:5000/login` dans le navigateur. Remplacez le chemin de la clé et l'adresse IP par vos valeurs. Si le port local `5000` est déjà utilisé, utilisez `5001` des deux côtés du tunnel et dans l'adresse du navigateur.

Dans un autre terminal SSH, placez-vous dans le dépôt :

```bash
cd /home/ec2-user/saas-compliance-b2b
source venv/bin/activate
```

## 2. Mettre à jour le dépôt existant

Ces commandes récupèrent les commits de la branche distante sans recloner le dépôt :

```bash
cd /home/ec2-user/saas-compliance-b2b
git status --short
git fetch origin
git pull --ff-only origin "$(git branch --show-current)"
git log -1 --oneline
```

Si `git status --short` montre des modifications locales, examinez-les avant le `pull`. Ne lancez pas `git reset --hard` pour forcer la mise à jour. Après le pull, installez les dépendances :

```bash
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 3. Base de données et comptes

Vérifier la révision actuelle, puis appliquer les migrations après une mise à jour qui en ajoute :

```bash
python3 -m flask --app run.py db current
python3 -m flask --app run.py db upgrade
```

Créer un compte initial ou un compte supplémentaire. La commande demande le mot de passe sans l'afficher :

```bash
python3 -m flask --app run.py create-user --email admin@example.com --tenant-id demo --role admin
```

Rôles acceptés : `admin`, `compliance`, `auditor`. Remplacez l'adresse, le tenant et le rôle selon le besoin. La MFA TOTP est obligatoire pour les comptes `admin`.

Réinitialiser la MFA d'un administrateur uniquement après avoir vérifié son identité par un autre canal :

```bash
python3 -m flask --app run.py reset-admin-mfa --email admin@example.com
```

La commande demande confirmation, révoque les sessions administrateur et impose un nouvel enrôlement MFA.

### Contrôler l'intégrité de la base SQLite

Cette commande utilise la base configurée pour l'application et ne montre pas les données des comptes :

```bash
python3 - <<'PY'
from app import create_app, db

app = create_app()
with app.app_context():
    if db.engine.dialect.name != "sqlite":
        raise SystemExit("La commande PRAGMA ci-dessous ne s'applique qu'à SQLite.")
    with db.engine.connect() as connection:
        result = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
    print("PRAGMA integrity_check:", result)
    if result != "ok":
        raise SystemExit("La vérification SQLite a échoué.")
PY
```

Le résultat attendu est `PRAGMA integrity_check: ok`.

### Créer une sauvegarde cohérente de SQLite

L'API de sauvegarde SQLite produit une copie cohérente même si l'application est active. La sauvegarde est écrite dans `instance/backups/` :

```bash
python3 - <<'PY'
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import create_app, db

app = create_app()
with app.app_context():
    if db.engine.dialect.name != "sqlite":
        raise SystemExit("Cette sauvegarde concerne SQLite uniquement.")

    backup_dir = Path("instance/backups")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_path = backup_dir / (
        "saas_local_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".db"
    )
    source = db.engine.raw_connection()
    destination = sqlite3.connect(str(backup_path))
    try:
        source.driver_connection.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        destination.close()
        source.close()

    if os.name != "nt":
        os.chmod(backup_path, 0o600)
    print("Sauvegarde :", backup_path)
    print("Intégrité de la sauvegarde :", integrity)
    if integrity != "ok":
        raise SystemExit("La vérification de la sauvegarde a échoué.")
PY
```

Conservez les sauvegardes dans un emplacement protégé et définissez une durée de rétention. Une sauvegarde de base n'est pas automatiquement envoyée dans S3 par cette commande.

## 4. Vérifications AWS et exports S3

Sur cette instance, `~/.aws/credentials` peut contenir des identifiants temporaires expirés. Préfixez les commandes AWS par `AWS_SHARED_CREDENTIALS_FILE=/dev/null` pour ignorer ce fichier et utiliser le rôle EC2 :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws sts get-caller-identity
```

Le résultat attendu est une identité assumée `LabRole`. Vérifier le blocage de l'accès public et le chiffrement par défaut du bucket :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null python3 -m flask --app run.py verify-audit-s3
```

Exporter vers S3 les événements d'audit en attente :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null python3 -m flask --app run.py export-audit-logs
```

Cette dernière commande exporte les événements d'audit de l'application. Elle est distincte des boutons d'export des pages web.

Les exports générés par l'interface sont archivés automatiquement après clic sur les boutons JSON/CSV ou sur le bouton qui prépare le rapport imprimable PDF. Le navigateur doit afficher un message de confirmation. Les objets sont rangés sous :

```text
s3://saas-audit-reports-sec-2026-unique/tenants/<tenant-id>/reports/
```

Lister les objets du tenant `demo` lorsque le rôle AWS autorise `s3:ListBucket` :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws s3 ls --recursive s3://saas-audit-reports-sec-2026-unique/tenants/demo/reports/
```

Si la liste est vide ou si `AccessDenied` est retourné, vérifiez aussi la console **AWS → S3 → bucket → tenants → tenant → reports**. Un refus de liste ne prouve pas qu'un téléversement a échoué. Les exports d'audit et de politiques n'apparaissent que pour le tenant connecté.

### Vérifier le chiffrement du volume EC2

Dans la console AWS, ouvrez **EC2 → Volumes**, identifiez le volume attaché à l'instance et vérifiez que la colonne **Encrypted** indique `Yes`. En CLI, remplacez `vol-...` par l'identifiant relevé dans la console :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws ec2 describe-volumes \
  --volume-ids vol-REMPLACER \
  --query 'Volumes[].{VolumeId:VolumeId,Encrypted:Encrypted}' \
  --output table
```

## 5. Démarrer ou redémarrer Gunicorn

Gunicorn doit écouter seulement sur `127.0.0.1:8000`. Vérifier le processus et l'écoute avant toute action :

```bash
ps -u "$USER" -f | grep -E '[g]unicorn|[p]ython.*run.py'
ss -ltn
```

Dans l'installation actuelle, Gunicorn est lancé manuellement depuis EC2. Pour le redémarrer, repérez dans `ps` le PID du processus maître Gunicorn, vérifiez sa commande, puis arrêtez uniquement ce PID :

```bash
ps -p PID_MAITRE -o pid,ppid,args
kill -TERM PID_MAITRE
sleep 2
ss -ltn | grep ':8000'
```

Attendez que l'écoute sur `8000` ait disparu. Ne tuez pas le worker séparément et ne lancez pas un second Gunicorn pendant que le premier écoute encore. Redémarrer avec le rôle EC2, sans le fichier local d'identifiants expirés :

```bash
cd /home/ec2-user/saas-compliance-b2b
source venv/bin/activate
AWS_SHARED_CREDENTIALS_FILE=/dev/null nohup ./venv/bin/gunicorn --workers 1 --bind 127.0.0.1:8000 run:app >> app.log 2>&1 &
```

Vérifier l'écoute et la réponse HTTP :

```bash
sleep 2
ss -ltn | grep ':8000'
curl -I http://127.0.0.1:8000/login
tail -n 50 app.log
```

Le tunnel SSH doit rester ouvert dans le terminal du poste d'administration. N'ouvrez pas les ports `5000` ou `8000` dans le groupe de sécurité EC2.

## 6. Tests et diagnostic

Lancer les tests automatisés après une modification du code :

```bash
python3 -m unittest discover -s tests
```

### Vérifier la santé de l'application

Depuis EC2, vérifier que le processus Flask répond et que la base de données est disponible :

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Les réponses attendues sont `{"status":"alive"}` et `{"status":"ready"}`. `/health/live` vérifie uniquement que l'application répond; `/health/ready` exécute une requête simple sur la base de données et renvoie HTTP 503 si elle est indisponible, sans exposer de détails internes. Une réponse 503 est aussi comptabilisée par le filtre métrique HTTP 5xx CloudWatch. Ces routes ne vérifient pas S3.

Lister les routes d'archivage :

```bash
python3 -m flask --app run.py routes | grep exports
```

Pour un échec d'export depuis le navigateur, ouvrir **F12 → Network**, sélectionner le `POST /exports/...` et lire le statut et le message de réponse. Repères :

- `201` : export archivé avec succès ;
- `400` : contenu manquant, invalide ou trop volumineux ;
- `403` : rôle non autorisé ;
- `502` : copie locale possible, mais envoi S3 échoué ; lire le message d'erreur ;
- `ExpiredToken` : redémarrer Gunicorn avec `AWS_SHARED_CREDENTIALS_FILE=/dev/null` comme indiqué ci-dessus ;
- `Address already in use` : un processus écoute déjà sur le port ; ne pas lancer un second serveur.

## 7. Configurer CloudWatch, indicateurs et alertes

Le rôle EC2 doit pouvoir créer un flux et publier ses événements dans le groupe (`logs:CreateLogStream`, `logs:PutLogEvents`, généralement `logs:DescribeLogStreams`). Le modèle crée le groupe et demande également les permissions CloudFormation, CloudWatch Logs, CloudWatch Alarms et SNS. Les deux permissions de flux seules ne suffisent pas pour déployer le modèle. Si la commande CLI est refusée, essayez dans la console AWS en région `us-east-1` : **CloudFormation → Create stack → With new resources**, puis téléversez le modèle. Si la console refuse aussi, demandez l'aide de l'administrateur du Lab; ne créez pas de clés permanentes.

Depuis la racine du dépôt sur EC2, valider puis déployer le modèle, qui crée le groupe avec 30 jours de rétention, les filtres, six alarmes et le topic SNS :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudformation validate-template \
  --template-body file://infra/cloudwatch-metric-filters.json

AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudformation deploy \
  --template-file infra/cloudwatch-metric-filters.json \
  --stack-name saas-compliance-supervision
```

Installer l'agent sur Amazon Linux et lui fournir la configuration du dépôt :

```bash
sudo dnf install -y amazon-cloudwatch-agent
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 \
  -c file:/home/ec2-user/saas-compliance-b2b/infra/cloudwatch-agent-config.json -s
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
```

Mettre à jour le dashboard existant et récupérer l'ARN SNS :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudwatch put-dashboard \
  --dashboard-name saas-audit-dash \
  --dashboard-body file://infra/cloudwatch-dashboard.json

AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudformation describe-stacks \
  --stack-name saas-compliance-supervision \
  --query 'Stacks[0].Outputs' --output table
```

Créer ensuite une subscription e-mail depuis **SNS → Topics → topic indiqué par l'ARN → Create subscription** et confirmer le lien reçu par e-mail. Ne mettez pas votre adresse e-mail dans le dépôt.

Vérifier les filtres, métriques et alarmes :

```bash
AWS_SHARED_CREDENTIALS_FILE=/dev/null aws logs describe-metric-filters \
  --log-group-name /saas-compliance-b2b/app \
  --query 'metricFilters[].filterName' --output table

AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudwatch list-metrics \
  --namespace SaasCompliance/Application --output table

AWS_SHARED_CREDENTIALS_FILE=/dev/null aws cloudwatch describe-alarms \
  --alarm-name-prefix SaasCompliance-
```

Les métriques ne deviennent visibles qu'après l'arrivée de logs correspondants; leur première apparition peut prendre quelques minutes. Le modèle utilise les seuils initiaux décrits dans `AUDIT-LOGGING.md`; aucune alarme ne se déclenche sur des périodes sans données.

## 8. État de vérification constaté

La capture S3 partagée montre trois objets sous `tenants/demo/reports/` : un export JSON du pack de politiques et des exports JSON/CSV de l'audit RGPD. Elle confirme que ces formats ont été archivés. Aucun PDF n'est visible sur cette capture ; pour le vérifier, lancer l'action d'impression du rapport dans l'interface, attendre le message de confirmation, puis rechercher un objet `.pdf` dans le même préfixe.

Pour déclarer terminée la vérification de la base, conserver le résultat `PRAGMA integrity_check: ok`, une sauvegarde SQLite vérifiée et la confirmation du chiffrement EBS. Ces éléments ne sont pas établis par la seule présence des fichiers S3 ni par la réussite des tests automatisés.

Pour les détails des contrôles IAM/Zero Trust et de la piste d'audit, consulter `IAM-ZERO-TRUST.md` et `AUDIT-LOGGING.md`.

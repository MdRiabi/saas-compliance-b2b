# Déploiement provisoire sécurisé sur EC2

Cette procédure convient à une instance Amazon Linux 2023 sans nom de domaine. Elle n'expose pas l'application sur Internet : l'accès se fait temporairement par un tunnel SSH. Elle ne remplace pas un déploiement HTTPS public.

## 1. Réduire l'exposition réseau

Dans le groupe de sécurité de l'instance :

- supprimer toute règle entrante TCP `5000` ;
- conserver SSH TCP `22` uniquement depuis l'adresse IP d'administration (`My IP`).

Ne pas ouvrir le port `8000` : Gunicorn écoutera uniquement sur `127.0.0.1`.

## 2. Installer et configurer l'application

Dans le terminal EC2, depuis le dépôt et avec son environnement virtuel activé :

```bash
python3 -m pip install -r requirements.txt
```

Créer une clé stable dans le fichier `.env` ignoré par Git, si ce fichier n'existe pas déjà :

```bash
if [ ! -f .env ]; then
  umask 077
  printf 'SECRET_KEY=%s\nSESSION_COOKIE_SECURE=false\n' \
    "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env
fi
chmod 600 .env
unset SECRET_KEY
python3 -m flask --app run.py db upgrade
```

Ne pas publier ni partager ce fichier. `SESSION_COOKIE_SECURE=false` est nécessaire uniquement pour l'accès HTTP local via tunnel SSH ; la connexion entre le poste et EC2 est chiffrée par SSH. Lorsqu'un HTTPS public sera configuré, passer cette valeur à `true`.

## 3. Remplacer le serveur Flask de développement

Arrêter l'ancien processus `python3 run.py` après avoir vérifié son PID, puis démarrer Gunicorn :

```bash
nohup gunicorn --workers 1 --bind 127.0.0.1:8000 run:app >> app.log 2>&1 &
curl -I http://127.0.0.1:8000/login
```

Une réponse HTTP confirme que l'application répond localement. Le processus ne doit pas écouter sur `0.0.0.0`.

## 4. Ouvrir un tunnel depuis le poste d'administration

Dans un terminal local disposant de la clé SSH de l'instance, garder cette commande active :

```bash
ssh -i "C:\chemin\vers\la-cle.pem" -N -L 5000:127.0.0.1:8000 ec2-user@ADRESSE_IP_EC2
```

Ouvrir ensuite `http://127.0.0.1:5000/login` dans le navigateur local. Remplacer le chemin de la clé et l'adresse EC2 par leurs valeurs réelles. Si le port local `5000` est déjà utilisé, remplacer le premier `5000` par `5001` et ouvrir `http://127.0.0.1:5001/login`.

## Limite et prochaine étape

Sans domaine, l'application n'est pas accessible publiquement en HTTPS. Pour un accès B2B public, associer un domaine à l'instance ou à un équilibreur de charge, configurer un certificat TLS, puis activer `SESSION_COOKIE_SECURE=true`. Le port `5000` ne doit pas être rouvert sur Internet.

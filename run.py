from app import create_app, db

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Création automatique des tables dans la base SQLite locale
    app.run(host='127.0.0.1', debug=False, port=5000)
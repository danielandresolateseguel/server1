from main import app, init_db, start_background_tasks

# Inicializar base de datos al arrancar el servidor WSGI
init_db()
start_background_tasks()

# Waitress/WSGI importará 'app' desde aquí
# Ejecución por CLI: waitress-serve --listen=127.0.0.1:8000 wsgi:app
from waitress import serve
from wsgi import app

if __name__ == '__main__':
    # Servir en loopback para uso local estable
    serve(app, host='127.0.0.1', port=8000)
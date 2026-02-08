import os
from flask import Flask
from dotenv import load_dotenv
from . import database

load_dotenv()

def create_app(test_config=None):
    # Create and configure the app
    # static_folder='../' means serve files from project root
    app = Flask(__name__, instance_relative_config=True, static_folder='../', static_url_path='/')
    
    # Default config
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev'),
        DATABASE=os.getenv('DATABASE_PATH', os.path.join(app.root_path, '..', 'orders.db')),
        CONFIG_DIR=os.path.join(app.root_path, '..', 'config'),
        JSON_AS_ASCII=True  # Force ASCII JSON to avoid encoding issues with emojis
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize DB
    database.init_app(app)
    
    # Initialize DB tables and seed data
    with app.app_context():
        database.init_db()
        database.seed_products_from_config(app.config['CONFIG_DIR'])
        database.backfill_product_details_from_config(app.config['CONFIG_DIR'])
        database.backfill_product_images_from_config(app.config['CONFIG_DIR'])
        database.seed_admin_users_from_env(app.config['CONFIG_DIR'])

    # Start background tasks
    from .tasks import start_background_tasks
    start_background_tasks(app)

    # Register Blueprints
    from .blueprints import auth, orders, cash, products, carousel, public, archive, tenants, system
    
    print("DEBUG: Registrando blueprints...")
    app.register_blueprint(auth.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(cash.bp)
    app.register_blueprint(products.bp)
    app.register_blueprint(carousel.bp)
    app.register_blueprint(archive.bp)
    print("DEBUG: Registrando blueprint tenants...")
    app.register_blueprint(tenants.bp)
    print("DEBUG: Registrando blueprint system...")
    app.register_blueprint(system.bp)
    print("DEBUG: Blueprints registrados.")

    # Register public last to avoid catching API routes
    app.register_blueprint(public.bp)

    return app

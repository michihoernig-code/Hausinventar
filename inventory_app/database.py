"""Datenbankzugriff fuer das Hausinventarsystem.

Hier wird die SQLite-Verbindung pro Request verwaltet und beim Start sichergestellt,
dass die benoetigten Tabellen vorhanden sind.
"""

import sqlite3
from pathlib import Path

from flask import current_app, g


DEFAULT_SHOPPING_CATEGORIES = [
    "Basics",
    "Wocheneinkauf",
    "Getraenke",
    "Haushalt",
    "Hygiene",
]


def get_db() -> sqlite3.Connection:
    """Liefert die SQLite-Verbindung fuer den aktuellen Request-Kontext."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None) -> None:
    """Schliesst die Verbindung am Ende eines Requests sauber."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Legt beim ersten Start die Tabellen fuer Produkte und Lagerbewegungen an."""
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            barcode TEXT UNIQUE,
            sku TEXT,
            category TEXT,
            storage_location TEXT,
            unit TEXT NOT NULL DEFAULT 'Stk',
            target_quantity INTEGER NOT NULL DEFAULT 0,
            current_quantity INTEGER NOT NULL DEFAULT 0,
            min_quantity INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            extra_attributes TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product_barcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            barcode TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        );

        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            reference TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        );

        CREATE TABLE IF NOT EXISTS product_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shopping_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shopping_category_inclusions (
            shopping_category_id INTEGER NOT NULL,
            included_shopping_category_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (shopping_category_id, included_shopping_category_id),
            FOREIGN KEY (shopping_category_id) REFERENCES shopping_categories (id),
            FOREIGN KEY (included_shopping_category_id) REFERENCES shopping_categories (id)
        );

        CREATE TABLE IF NOT EXISTS product_category_shopping_links (
            product_category_id INTEGER NOT NULL,
            shopping_category_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (product_category_id, shopping_category_id),
            FOREIGN KEY (product_category_id) REFERENCES product_categories (id),
            FOREIGN KEY (shopping_category_id) REFERENCES shopping_categories (id)
        );

        CREATE TABLE IF NOT EXISTS product_expiry_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            expires_on TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            quantity_remaining INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        );

        CREATE INDEX IF NOT EXISTS idx_products_category_name ON products (category);
        CREATE INDEX IF NOT EXISTS idx_product_barcodes_product_id ON product_barcodes (product_id);
        CREATE INDEX IF NOT EXISTS idx_shopping_category_inclusions_category ON shopping_category_inclusions (shopping_category_id);
        CREATE INDEX IF NOT EXISTS idx_shopping_category_inclusions_included ON shopping_category_inclusions (included_shopping_category_id);
        CREATE INDEX IF NOT EXISTS idx_product_category_links_product ON product_category_shopping_links (product_category_id);
        CREATE INDEX IF NOT EXISTS idx_product_category_links_shopping ON product_category_shopping_links (shopping_category_id);
        CREATE INDEX IF NOT EXISTS idx_product_expiry_batches_product ON product_expiry_batches (product_id);
        CREATE INDEX IF NOT EXISTS idx_product_expiry_batches_expires_on ON product_expiry_batches (expires_on);
        """
    )

    _ensure_products_schema(db)
    _migrate_existing_primary_barcodes(db)
    _seed_default_shopping_categories(db)
    _migrate_legacy_categories(db)
    db.commit()


def init_app(app) -> None:
    """Bindet die Datenbankverwaltung an die Flask-App an."""
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()


def _ensure_products_schema(db: sqlite3.Connection) -> None:
    """Ergaenzt neue Spalten fuer die Kategorietrennung in bestehenden Datenbanken."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(products)").fetchall()}

    if "product_category_id" not in columns:
        db.execute("ALTER TABLE products ADD COLUMN product_category_id INTEGER REFERENCES product_categories (id)")

    if "requires_expiry_date" not in columns:
        db.execute("ALTER TABLE products ADD COLUMN requires_expiry_date INTEGER NOT NULL DEFAULT 0")

    db.execute("CREATE INDEX IF NOT EXISTS idx_products_product_category_id ON products (product_category_id)")


def _migrate_existing_primary_barcodes(db: sqlite3.Connection) -> None:
    """Spiegelt bestehende Primar-Barcodes in die Zusatz-Barcode-Tabelle."""
    rows = db.execute(
        """
        SELECT id, barcode
        FROM products
        WHERE TRIM(COALESCE(barcode, '')) != ''
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        db.execute(
            "INSERT OR IGNORE INTO product_barcodes (product_id, barcode) VALUES (?, ?)",
            (row["id"], row["barcode"].strip()),
        )


def _seed_default_shopping_categories(db: sqlite3.Connection) -> None:
    """Legt einige sinnvolle Startkategorien fuer Einkaufslisten an."""
    for index, category_name in enumerate(DEFAULT_SHOPPING_CATEGORIES, start=1):
        db.execute(
            "INSERT OR IGNORE INTO shopping_categories (name, sort_order) VALUES (?, ?)",
            (category_name, index * 10),
        )


def _migrate_legacy_categories(db: sqlite3.Connection) -> None:
    """Uebernimmt vorhandene Freitextkategorien in das neue relationale Modell."""
    rows = db.execute(
        """
        SELECT id, category, product_category_id
        FROM products
        WHERE TRIM(COALESCE(category, '')) != ''
        ORDER BY id
        """
    ).fetchall()

    for row in rows:
        category_name = row["category"].strip()
        product_category_id = row["product_category_id"]

        if product_category_id is None:
            product_category_id = _get_or_create_category_id(db, "product_categories", category_name)
            db.execute(
                "UPDATE products SET product_category_id = ?, category = ? WHERE id = ?",
                (product_category_id, category_name, row["id"]),
            )

        shopping_category_id = _get_or_create_category_id(db, "shopping_categories", category_name)
        db.execute(
            """
            INSERT OR IGNORE INTO product_category_shopping_links (product_category_id, shopping_category_id)
            VALUES (?, ?)
            """,
            (product_category_id, shopping_category_id),
        )

    rows_without_label = db.execute(
        """
        SELECT p.id, pc.name
        FROM products AS p
        JOIN product_categories AS pc ON pc.id = p.product_category_id
        WHERE TRIM(COALESCE(p.category, '')) = ''
        """
    ).fetchall()
    for row in rows_without_label:
        db.execute("UPDATE products SET category = ? WHERE id = ?", (row["name"], row["id"]))


def _get_or_create_category_id(db: sqlite3.Connection, table_name: str, category_name: str) -> int:
    """Liefert die ID einer Kategorie und legt sie bei Bedarf an."""
    row = db.execute(f"SELECT id FROM {table_name} WHERE name = ?", (category_name,)).fetchone()
    if row:
        return int(row["id"])

    cursor = db.execute(f"INSERT INTO {table_name} (name) VALUES (?)", (category_name,))
    return int(cursor.lastrowid)

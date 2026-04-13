"""Geschaeftslogik fuer Produkte, Dashboard und Lagerbewegungen.

Dieses Modul kapselt alle Zugriffe auf Produktdaten, damit die Routen in der
Flask-App moeglichst lesbar bleiben.
"""

import json
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .database import DEFAULT_SHOPPING_CATEGORIES, get_db


BARCODE_LOOKUP_SOURCES = [
    {
        "name": "Open Food Facts",
        "url": "https://world.openfoodfacts.org/api/v2/product/{barcode}.json?fields=code,product_name,brands,quantity,categories",
    },
    {
        "name": "Open Beauty Facts",
        "url": "https://world.openbeautyfacts.org/api/v2/product/{barcode}.json?fields=code,product_name,brands,quantity,categories",
    },
]

DEVELOPER_MODE_CONFIRMATION = "LOESCHEN"


def get_dashboard_data(search: str = "") -> dict:
    """Laedt alle Dashboard-Daten inklusive Filter und Kennzahlen."""
    db = get_db()
    rows = db.execute("SELECT * FROM products ORDER BY name COLLATE NOCASE").fetchall()
    products = [_serialize_product(row) for row in rows]

    if search:
        needle = search.casefold()
        products = [product for product in products if _product_matches_search(product, needle)]

    low_stock = [product for product in products if product["current_quantity"] <= product["min_quantity"]]
    expiry_summary = _build_expiry_summary(products)
    expiry_alert_products = [
        product
        for product in expiry_summary["items"]
        if product["expiry_status"] in {"expired", "expiring_soon", "missing"}
    ]

    return {
        "products": products,
        "low_stock_products": low_stock,
        "product_count": len(products),
        "low_stock_count": len(low_stock),
        "total_units": sum(product["current_quantity"] for product in products),
        "expiry_products": expiry_summary["items"],
        "expiry_alert_products": expiry_alert_products,
        "expiry_good_count": expiry_summary["counts"]["good"],
        "expiry_soon_count": expiry_summary["counts"]["expiring_soon"],
        "expiry_expired_count": expiry_summary["counts"]["expired"],
        "expiry_missing_count": expiry_summary["counts"]["missing"],
    }


def get_product_category_suggestions() -> list[str]:
    """Liefert alle vorhandenen Produktkategorien fuer die Schnellauswahl."""
    rows = get_db().execute("SELECT name FROM product_categories ORDER BY name COLLATE NOCASE").fetchall()
    return [row["name"] for row in rows]


def get_shopping_category_suggestions() -> list[str]:
    """Liefert alle vorhandenen Einkaufskategorien fuer Filter und Verwaltung."""
    rows = get_db().execute(
        "SELECT name FROM shopping_categories ORDER BY sort_order ASC, name COLLATE NOCASE"
    ).fetchall()
    return [row["name"] for row in rows]


def list_product_categories() -> list[dict]:
    """Liefert alle Produktkategorien inklusive Produktanzahl und verknuepften Einkaufslisten."""
    rows = get_db().execute(
        """
        SELECT pc.id, pc.name, COUNT(p.id) AS product_count
        FROM product_categories AS pc
        LEFT JOIN products AS p ON p.product_category_id = pc.id
        GROUP BY pc.id, pc.name
        ORDER BY pc.name COLLATE NOCASE
        """
    ).fetchall()

    categories = []
    for row in rows:
        linked_shopping_category_links = _get_linked_shopping_category_links(int(row["id"]))
        linked_shopping_categories = [category["name"] for category in linked_shopping_category_links]
        categories.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "product_count": int(row["product_count"] or 0),
                "shopping_category_links": linked_shopping_category_links,
                "shopping_categories": linked_shopping_categories,
                "shopping_category_label": ", ".join(linked_shopping_categories),
            }
        )

    return categories


def list_shopping_categories() -> list[dict]:
    """Liefert alle Einkaufskategorien inklusive zugeordneter Produktkategorien."""
    rows = get_db().execute(
        """
        SELECT
            sc.id,
            sc.name,
            sc.sort_order,
            COUNT(DISTINCT pcsl.product_category_id) AS product_category_count,
            COUNT(p.id) AS product_count
        FROM shopping_categories AS sc
        LEFT JOIN product_category_shopping_links AS pcsl ON pcsl.shopping_category_id = sc.id
        LEFT JOIN products AS p ON p.product_category_id = pcsl.product_category_id
        GROUP BY sc.id, sc.name, sc.sort_order
        ORDER BY sc.sort_order ASC, sc.name COLLATE NOCASE
        """
    ).fetchall()

    categories = []
    for row in rows:
        linked_product_categories = _get_linked_product_categories(int(row["id"]))
        included_shopping_category_links = _get_included_shopping_category_links(int(row["id"]))
        categories.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "sort_order": int(row["sort_order"] or 0),
                "product_category_count": int(row["product_category_count"] or 0),
                "product_count": int(row["product_count"] or 0),
                "product_categories": linked_product_categories,
                "product_category_label": ", ".join(linked_product_categories),
                "included_shopping_category_links": included_shopping_category_links,
                "included_shopping_category_ids": [category["id"] for category in included_shopping_category_links],
                "included_shopping_categories": [category["name"] for category in included_shopping_category_links],
                "included_shopping_category_label": ", ".join(
                    category["name"] for category in included_shopping_category_links
                ),
            }
        )

    return categories


def get_product_form_data(selected_product_category_id: int | None = None) -> dict:
    """Stellt Auswahl- und Hinweisdaten fuer das Produktformular bereit."""
    product_categories = list_product_categories()
    product_rows = get_db().execute(
        """
        SELECT id, name, barcode, sku
        FROM products
        ORDER BY name COLLATE NOCASE, id ASC
        """
    ).fetchall()
    linked_shopping_categories = []
    if selected_product_category_id:
        linked_shopping_categories = _get_linked_shopping_categories(int(selected_product_category_id))

    return {
        "product_categories": product_categories,
        "product_category_suggestions": [category["name"] for category in product_categories],
        "linked_shopping_categories": linked_shopping_categories,
        "existing_products": [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "barcode": (row["barcode"] or "").strip(),
                "sku": (row["sku"] or "").strip(),
            }
            for row in product_rows
        ],
    }


def get_category_management_data() -> dict:
    """Baut die Uebersicht fuer die Kategorienverwaltung auf."""
    product_categories = list_product_categories()
    shopping_categories = list_shopping_categories()
    unlinked_product_categories = [category for category in product_categories if not category["shopping_categories"]]

    return {
        "product_categories": product_categories,
        "shopping_categories": shopping_categories,
        "unlinked_product_categories": unlinked_product_categories,
        "linked_product_categories": [category for category in product_categories if category["shopping_categories"]],
        "product_category_count": len(product_categories),
        "shopping_category_count": len(shopping_categories),
    }


def get_developer_mode_data() -> dict:
    """Liefert Kennzahlen und die Bestaetigungsphrase fuer den Entwicklermodus."""
    db = get_db()
    product_count = _count_table_rows(db, "products")
    product_barcode_count = _count_table_rows(db, "product_barcodes")
    stock_movement_count = _count_table_rows(db, "stock_movements")
    product_category_count = _count_table_rows(db, "product_categories")
    shopping_category_count = _count_table_rows(db, "shopping_categories")
    category_link_count = _count_table_rows(db, "product_category_shopping_links")
    expiry_batch_count = _count_table_rows(db, "product_expiry_batches")

    return {
        "confirmation_phrase": DEVELOPER_MODE_CONFIRMATION,
        "product_count": product_count,
        "product_barcode_count": product_barcode_count,
        "stock_movement_count": stock_movement_count,
        "product_category_count": product_category_count,
        "shopping_category_count": shopping_category_count,
        "category_link_count": category_link_count,
        "expiry_batch_count": expiry_batch_count,
    }


def execute_developer_mode_action(action: str, confirmation_text: str) -> str:
    """Fuehrt bewusst destructive Entwickleraktionen mit Bestaetigungsphrase aus."""
    normalized_action = action.strip()
    if normalized_action not in {
        "clear-products",
        "clear-categories",
        "clear-stock-movements",
        "clear-expiry-batches",
        "reset-all",
    }:
        raise ValueError("Unbekannte Entwickleraktion.")

    if confirmation_text.strip().upper() != DEVELOPER_MODE_CONFIRMATION:
        raise ValueError(f"Bitte zur Bestaetigung genau {DEVELOPER_MODE_CONFIRMATION} eingeben.")

    db = get_db()

    if normalized_action == "clear-products":
        product_count = _count_table_rows(db, "products")
        barcode_count = _count_table_rows(db, "product_barcodes")
        movement_count = _count_table_rows(db, "stock_movements")
        expiry_batch_count = _count_table_rows(db, "product_expiry_batches")

        db.execute("DELETE FROM product_expiry_batches")
        db.execute("DELETE FROM stock_movements")
        db.execute("DELETE FROM product_barcodes")
        db.execute("DELETE FROM products")
        _reset_autoincrement_sequences(db, ["product_expiry_batches", "stock_movements", "product_barcodes", "products"])
        db.commit()
        return (
            f"{product_count} Produkte, {barcode_count} Barcodes, {movement_count} Lagerbewegungen und "
            f"{expiry_batch_count} MHD-Chargen wurden geloescht."
        )

    if normalized_action == "clear-categories":
        product_category_count = _count_table_rows(db, "product_categories")
        shopping_category_count = _count_table_rows(db, "shopping_categories")
        category_link_count = _count_table_rows(db, "product_category_shopping_links")

        db.execute("UPDATE products SET product_category_id = NULL, category = ''")
        db.execute("DELETE FROM product_category_shopping_links")
        db.execute("DELETE FROM product_categories")
        db.execute("DELETE FROM shopping_categories")
        _reset_autoincrement_sequences(db, ["product_categories", "shopping_categories"])
        db.commit()
        return (
            f"{product_category_count} Produktkategorien, {shopping_category_count} Einkaufskategorien und "
            f"{category_link_count} Zuordnungen wurden geloescht."
        )

    if normalized_action == "clear-stock-movements":
        movement_count = _count_table_rows(db, "stock_movements")
        db.execute("DELETE FROM stock_movements")
        _reset_autoincrement_sequences(db, ["stock_movements"])
        db.commit()
        return f"{movement_count} Lagerbewegungen wurden geloescht."

    if normalized_action == "clear-expiry-batches":
        expiry_batch_count = _count_table_rows(db, "product_expiry_batches")
        db.execute("DELETE FROM product_expiry_batches")
        _reset_autoincrement_sequences(db, ["product_expiry_batches"])
        db.commit()
        return f"{expiry_batch_count} MHD-Chargen wurden geloescht."

    product_count = _count_table_rows(db, "products")
    barcode_count = _count_table_rows(db, "product_barcodes")
    product_category_count = _count_table_rows(db, "product_categories")
    shopping_category_count = _count_table_rows(db, "shopping_categories")
    movement_count = _count_table_rows(db, "stock_movements")
    expiry_batch_count = _count_table_rows(db, "product_expiry_batches")
    category_link_count = _count_table_rows(db, "product_category_shopping_links")

    db.execute("DELETE FROM product_expiry_batches")
    db.execute("DELETE FROM stock_movements")
    db.execute("DELETE FROM product_category_shopping_links")
    db.execute("DELETE FROM product_barcodes")
    db.execute("DELETE FROM products")
    db.execute("DELETE FROM product_categories")
    db.execute("DELETE FROM shopping_categories")
    _reset_autoincrement_sequences(
        db,
        [
            "product_expiry_batches",
            "stock_movements",
            "product_category_shopping_links",
            "product_barcodes",
            "products",
            "product_categories",
            "shopping_categories",
        ],
    )
    _seed_default_shopping_categories_for_developer_mode(db)
    db.commit()
    return (
        "Komplettreset abgeschlossen: "
        f"{product_count} Produkte, {barcode_count} Barcodes, {product_category_count} Produktkategorien, "
        f"{shopping_category_count} Einkaufskategorien, {category_link_count} Zuordnungen, "
        f"{movement_count} Lagerbewegungen und {expiry_batch_count} MHD-Chargen wurden geloescht. "
        "Die Standard-Einkaufskategorien wurden neu angelegt."
    )


def create_product_category(name: str, shopping_category_ids: list[int] | None = None) -> int:
    """Legt eine neue Produktkategorie an oder liefert die bestehende ID."""
    product_category_id = _get_or_create_named_category("product_categories", name)
    if shopping_category_ids:
        bulk_link_product_categories_to_shopping([product_category_id], shopping_category_ids)
    return product_category_id


def create_shopping_category(name: str, product_category_ids: list[int] | None = None) -> int:
    """Legt eine neue Einkaufskategorie an oder liefert die bestehende ID."""
    shopping_category_id = _get_or_create_named_category("shopping_categories", name)
    if product_category_ids:
        bulk_link_product_categories_to_shopping(product_category_ids, [shopping_category_id])
    return shopping_category_id


def update_product_category(product_category_id: int, name: str) -> None:
    """Benennt eine Produktkategorie um und aktualisiert die Anzeigekopie in Produkten."""
    normalized_name = _normalize_category_name(name)
    if not normalized_name:
        raise ValueError("Der Kategoriename darf nicht leer sein.")

    db = get_db()
    _require_category_exists("product_categories", product_category_id, "Produktkategorie")
    duplicate_id = _find_category_id_by_name("product_categories", normalized_name)
    if duplicate_id is not None and duplicate_id != product_category_id:
        raise ValueError("Eine Produktkategorie mit diesem Namen existiert bereits.")

    db.execute("UPDATE product_categories SET name = ? WHERE id = ?", (normalized_name, product_category_id))
    db.execute("UPDATE products SET category = ? WHERE product_category_id = ?", (normalized_name, product_category_id))
    db.commit()


def update_shopping_category(shopping_category_id: int, name: str, sort_order: int | None = None) -> None:
    """Aktualisiert Name und Reihenfolge einer Einkaufskategorie."""
    normalized_name = _normalize_category_name(name)
    if not normalized_name:
        raise ValueError("Der Kategoriename darf nicht leer sein.")

    db = get_db()
    _require_category_exists("shopping_categories", shopping_category_id, "Einkaufskategorie")
    duplicate_id = _find_category_id_by_name("shopping_categories", normalized_name)
    if duplicate_id is not None and duplicate_id != shopping_category_id:
        raise ValueError("Eine Einkaufskategorie mit diesem Namen existiert bereits.")

    if sort_order is None:
        row = db.execute("SELECT sort_order FROM shopping_categories WHERE id = ?", (shopping_category_id,)).fetchone()
        sort_order = int(row["sort_order"] or 0) if row else 0

    db.execute(
        "UPDATE shopping_categories SET name = ?, sort_order = ? WHERE id = ?",
        (normalized_name, int(sort_order), shopping_category_id),
    )
    db.commit()


def update_shopping_category_inclusions(shopping_category_id: int, included_shopping_category_ids: list[int] | list[str]) -> None:
    """Speichert, welche weiteren Einkaufskategorien automatisch mit in eine Liste aufgenommen werden."""
    normalized_included_ids = _normalize_optional_id_list(included_shopping_category_ids)
    db = get_db()
    _require_category_exists("shopping_categories", shopping_category_id, "Einkaufskategorie")

    if shopping_category_id in normalized_included_ids:
        raise ValueError("Eine Einkaufskategorie kann sich nicht selbst mit aufnehmen.")

    for included_shopping_category_id in normalized_included_ids:
        _require_category_exists("shopping_categories", included_shopping_category_id, "Einkaufskategorie")

    db.execute("DELETE FROM shopping_category_inclusions WHERE shopping_category_id = ?", (shopping_category_id,))
    for included_shopping_category_id in normalized_included_ids:
        db.execute(
            """
            INSERT INTO shopping_category_inclusions (shopping_category_id, included_shopping_category_id)
            VALUES (?, ?)
            """,
            (shopping_category_id, included_shopping_category_id),
        )
    db.commit()


def reorder_shopping_categories(shopping_category_ids: list[int] | list[str]) -> None:
    """Aktualisiert die Sortierreihenfolge der Einkaufskategorien anhand einer geordneten ID-Liste."""
    ordered_ids = _normalize_id_list(shopping_category_ids, "Einkaufskategorien")
    db = get_db()

    existing_ids = {
        int(row["id"])
        for row in db.execute("SELECT id FROM shopping_categories").fetchall()
    }
    missing_ids = [category_id for category_id in ordered_ids if category_id not in existing_ids]
    if missing_ids:
        raise ValueError("Mindestens eine Einkaufskategorie wurde nicht gefunden.")

    for position, shopping_category_id in enumerate(ordered_ids, start=1):
        db.execute(
            "UPDATE shopping_categories SET sort_order = ? WHERE id = ?",
            (position * 10, shopping_category_id),
        )
    db.commit()


def link_product_category_to_shopping(product_category_id: int, shopping_category_id: int) -> None:
    """Ordnet eine Produktkategorie einer Einkaufskategorie zu."""
    db = get_db()
    _require_category_exists("product_categories", product_category_id, "Produktkategorie")
    _require_category_exists("shopping_categories", shopping_category_id, "Einkaufskategorie")
    db.execute(
        """
        INSERT OR IGNORE INTO product_category_shopping_links (product_category_id, shopping_category_id)
        VALUES (?, ?)
        """,
        (product_category_id, shopping_category_id),
    )
    db.commit()


def unlink_product_category_from_shopping(product_category_id: int, shopping_category_id: int) -> None:
    """Entfernt die Zuordnung zwischen Produkt- und Einkaufskategorie."""
    db = get_db()
    db.execute(
        "DELETE FROM product_category_shopping_links WHERE product_category_id = ? AND shopping_category_id = ?",
        (product_category_id, shopping_category_id),
    )
    db.commit()


def bulk_link_product_categories_to_shopping(product_category_ids: list[int], shopping_category_ids: list[int]) -> None:
    """Verknuepft mehrere Produktkategorien mit einer oder mehreren Einkaufskategorien."""
    normalized_product_ids = _normalize_id_list(product_category_ids, "Produktkategorien")
    normalized_shopping_ids = _normalize_id_list(shopping_category_ids, "Einkaufskategorien")

    db = get_db()
    for product_category_id in normalized_product_ids:
        _require_category_exists("product_categories", product_category_id, "Produktkategorie")
    for shopping_category_id in normalized_shopping_ids:
        _require_category_exists("shopping_categories", shopping_category_id, "Einkaufskategorie")

    for product_category_id in normalized_product_ids:
        for shopping_category_id in normalized_shopping_ids:
            db.execute(
                """
                INSERT OR IGNORE INTO product_category_shopping_links (product_category_id, shopping_category_id)
                VALUES (?, ?)
                """,
                (product_category_id, shopping_category_id),
            )
    db.commit()


def delete_product_category(product_category_id: int) -> None:
    """Loescht eine Produktkategorie, sofern ihr keine Produkte mehr zugeordnet sind."""
    db = get_db()
    linked_products = db.execute(
        "SELECT COUNT(*) AS product_count FROM products WHERE product_category_id = ?",
        (product_category_id,),
    ).fetchone()
    if int(linked_products["product_count"] or 0) > 0:
        raise ValueError("Produktkategorie kann nicht geloescht werden, solange Produkte darauf verweisen.")

    db.execute("DELETE FROM product_category_shopping_links WHERE product_category_id = ?", (product_category_id,))
    db.execute("DELETE FROM product_categories WHERE id = ?", (product_category_id,))
    db.commit()


def delete_shopping_category(shopping_category_id: int) -> None:
    """Loescht eine Einkaufskategorie und entfernt ihre Zuordnungen."""
    db = get_db()
    db.execute(
        "DELETE FROM shopping_category_inclusions WHERE shopping_category_id = ? OR included_shopping_category_id = ?",
        (shopping_category_id, shopping_category_id),
    )
    db.execute("DELETE FROM product_category_shopping_links WHERE shopping_category_id = ?", (shopping_category_id,))
    db.execute("DELETE FROM shopping_categories WHERE id = ?", (shopping_category_id,))
    db.commit()


def bulk_update_products(product_ids: list[int] | list[str], payload: dict) -> int:
    """Aktualisiert mehrere Produkte in einem Schritt fuer wiederkehrende Stammdaten."""
    normalized_product_ids = _normalize_id_list(product_ids, "Produkte")
    update_fields: dict[str, object] = {}

    storage_location = payload.get("storage_location", "")
    if storage_location is not None:
        storage_location = str(storage_location).strip()
        if storage_location:
            update_fields["storage_location"] = storage_location

    unit = str(payload.get("unit", "")).strip()
    if unit:
        update_fields["unit"] = unit

    notes = str(payload.get("notes", "")).strip()
    if notes:
        update_fields["notes"] = notes

    for field_name in ("target_quantity", "min_quantity"):
        raw_value = str(payload.get(field_name, "")).strip()
        if not raw_value:
            continue
        try:
            update_fields[field_name] = int(raw_value)
        except ValueError as exc:
            raise ValueError("Soll- und Mindestbestand muessen ganze Zahlen sein.") from exc

    selected_product_category_id = str(payload.get("product_category_id", "")).strip()
    if selected_product_category_id:
        try:
            product_category_id = int(selected_product_category_id)
        except ValueError as exc:
            raise ValueError("Die ausgewaehlte Produktkategorie ist ungueltig.") from exc
        _require_category_exists("product_categories", product_category_id, "Produktkategorie")
        category_name = _get_product_category_name(product_category_id)
        update_fields["product_category_id"] = product_category_id
        update_fields["category"] = category_name

    requires_expiry_date = _parse_optional_boolean_field(payload.get("requires_expiry_date", ""))
    if requires_expiry_date is not None:
        update_fields["requires_expiry_date"] = 1 if requires_expiry_date else 0

    if not update_fields:
        raise ValueError("Bitte mindestens ein Feld fuer die Massenbearbeitung ausfuellen.")

    assignments = ", ".join(f"{field_name} = ?" for field_name in update_fields)
    params = list(update_fields.values())
    placeholders = ", ".join("?" for _ in normalized_product_ids)

    db = get_db()
    cursor = db.execute(
        f"UPDATE products SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        params + normalized_product_ids,
    )
    db.commit()
    return int(cursor.rowcount or 0)


def get_shopping_list_data(list_mode: str = "min", category: str = "", email_recipient: str = "") -> dict:
    """Erzeugt eine Einkaufsliste fuer Mindest- oder Vollbestand mit optionalem Kategoriefilter."""
    mode = list_mode if list_mode in {"min", "target"} else "min"
    products = get_dashboard_data()["products"]
    effective_categories = _resolve_effective_shopping_category_names(category) if category else []

    if category:
        products = [
            product
            for product in products
            if any(shopping_category in effective_categories for shopping_category in product.get("shopping_categories", []))
        ]

    shopping_items = []
    for product in products:
        missing_to_min = max(product["min_quantity"] - product["current_quantity"], 0)
        missing_to_target = max(product["target_quantity"] - product["current_quantity"], 0)
        shopping_quantity = missing_to_min if mode == "min" else missing_to_target

        if shopping_quantity <= 0:
            continue

        shopping_item = dict(product)
        shopping_item["missing_to_min"] = missing_to_min
        shopping_item["missing_to_target"] = missing_to_target
        shopping_item["shopping_quantity"] = shopping_quantity
        shopping_items.append(shopping_item)

    shopping_items.sort(
        key=lambda item: (
            (item.get("shopping_categories") or ["zzz"])[0].lower(),
            (item.get("product_category") or "zzz").lower(),
            -item["shopping_quantity"],
            item["name"].lower(),
        )
    )

    total_missing_units = sum(item["shopping_quantity"] for item in shopping_items)
    mail_subject = _build_shopping_mail_subject(mode=mode, category=category)
    mail_body = _build_shopping_mail_body(
        items=shopping_items,
        mode=mode,
        category=category,
        total_missing_units=total_missing_units,
    )
    recipient = email_recipient.strip()

    return {
        "list_mode": mode,
        "selected_category": category,
        "effective_categories": effective_categories,
        "selected_category_includes": [name for name in effective_categories if name != category],
        "email_recipient": recipient,
        "items": shopping_items,
        "category_suggestions": get_shopping_category_suggestions(),
        "item_count": len(shopping_items),
        "total_missing_units": total_missing_units,
        "mail_subject": mail_subject,
        "mail_body": mail_body,
    }


def get_expiry_overview_data(status_filter: str = "all") -> dict:
    """Erzeugt die Uebersicht fuer Produkte mit Haltbarkeitsdatum."""
    allowed_statuses = {"all", "good", "expiring_soon", "expired", "missing"}
    normalized_status = status_filter if status_filter in allowed_statuses else "all"

    products = [product for product in get_dashboard_data()["products"] if product.get("requires_expiry_date")]
    expiry_summary = _build_expiry_summary(products)
    items = expiry_summary["items"]
    if normalized_status != "all":
        items = [item for item in items if item.get("expiry_status") == normalized_status]

    return {
        "status_filter": normalized_status,
        "items": items,
        "expiry_good_count": expiry_summary["counts"]["good"],
        "expiry_soon_count": expiry_summary["counts"]["expiring_soon"],
        "expiry_expired_count": expiry_summary["counts"]["expired"],
        "expiry_missing_count": expiry_summary["counts"]["missing"],
        "tracked_product_count": len(products),
    }


def get_product(product_id: int) -> dict | None:
    """Laedt ein einzelnes Produkt anhand seiner Datenbank-ID."""
    row = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return _serialize_product(row) if row else None


def find_product_by_barcode(barcode: str) -> dict | None:
    """Sucht ein Produkt ueber den Barcode fuer den Scanner-Workflow."""
    normalized_barcode = _normalize_barcode(barcode)
    if not normalized_barcode:
        return None

    row = get_db().execute(
        """
        SELECT p.*
        FROM products AS p
        LEFT JOIN product_barcodes AS pb ON pb.product_id = p.id
        WHERE p.barcode = ? OR pb.barcode = ?
        ORDER BY CASE WHEN p.barcode = ? THEN 0 ELSE 1 END, p.id ASC
        LIMIT 1
        """,
        (normalized_barcode, normalized_barcode, normalized_barcode),
    ).fetchone()
    return _serialize_product(row) if row else None


def add_barcode_to_product(product_id: int, barcode: str) -> None:
    """Ordnet einem bestehenden Produkt einen weiteren Barcode zu."""
    normalized_barcode = _normalize_barcode(barcode)
    if not normalized_barcode:
        raise ValueError("Bitte zuerst einen Barcode eingeben.")

    product = get_product(product_id)
    if product is None:
        raise ValueError("Produkt wurde nicht gefunden.")

    if normalized_barcode in product.get("all_barcodes", []):
        raise ValueError("Der Barcode ist diesem Produkt bereits zugeordnet.")

    _ensure_barcode_available(normalized_barcode, current_product_id=product_id)

    db = get_db()
    db.execute(
        "INSERT INTO product_barcodes (product_id, barcode) VALUES (?, ?)",
        (product_id, normalized_barcode),
    )
    db.commit()


def list_product_barcodes(product_id: int) -> list[str]:
    """Liefert alle bekannten Barcodes eines Produkts."""
    product = get_product(product_id)
    return product.get("all_barcodes", []) if product else []


def lookup_product_by_barcode_online(barcode: str, timeout: int = 8) -> dict | None:
    """Sucht Produktdaten zu einem Barcode ueber mehrere externe Datenquellen."""
    normalized_barcode = barcode.strip()
    if not normalized_barcode:
        raise ValueError("Bitte zuerst einen Barcode eingeben.")
    if not normalized_barcode.isdigit() or len(normalized_barcode) < 8:
        raise ValueError("Der Barcode muss mindestens 8 Ziffern enthalten.")

    errors = []
    checked_sources = [source["name"] for source in BARCODE_LOOKUP_SOURCES]
    for source in BARCODE_LOOKUP_SOURCES:
        request = Request(
            source["url"].format(barcode=quote(normalized_barcode)),
            headers={
                "User-Agent": "Hausinventar/1.0 (+local barcode lookup)",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                continue
            errors.append(f"{source['name']}: HTTP {exc.code}")
            continue
        except URLError:
            errors.append(f"{source['name']}: nicht erreichbar")
            continue

        if int(payload.get("status", 0) or 0) != 1:
            continue

        product = payload.get("product") or {}
        product_name = _clean_lookup_text(product.get("product_name"))
        if not product_name:
            continue

        return {
            "source": source["name"],
            "searched_sources": checked_sources,
            "barcode": normalized_barcode,
            "name": product_name,
            "brand": _clean_lookup_text(product.get("brands")),
            "quantity": _clean_lookup_text(product.get("quantity")),
            "category_hint": _clean_lookup_text(product.get("categories")),
        }

    if errors and len(errors) == len(BARCODE_LOOKUP_SOURCES):
        raise ValueError("Die Online-Quellen sind aktuell nicht erreichbar.")

    return None


def merge_lookup_into_product_payload(payload: dict, lookup_data: dict) -> tuple[dict, dict]:
    """Uebernimmt Online-Daten in das Produktformular, ohne bereits erfasste Werte zu zerstören."""
    merged_payload = dict(payload)
    updated_field_keys = []
    updated_labels = []
    updated_attribute_keys = []

    if not merged_payload.get("name") and lookup_data.get("name"):
        merged_payload["name"] = lookup_data["name"]
        updated_field_keys.append("name")
        updated_labels.append("Produktname")

    existing_extra_attributes = parse_extra_attributes(merged_payload.get("extra_attributes", ""))
    attribute_mapping = {
        "Marke": lookup_data.get("brand", ""),
        "Packungsangabe": lookup_data.get("quantity", ""),
        "Kategoriehinweis": lookup_data.get("category_hint", ""),
        "Datenquelle": lookup_data.get("source", ""),
    }

    for key, value in attribute_mapping.items():
        if value and key not in existing_extra_attributes:
            existing_extra_attributes[key] = value
            updated_labels.append(key)
            updated_attribute_keys.append(key)

    if updated_attribute_keys:
        updated_field_keys.append("extra_attributes")

    merged_payload["extra_attributes"] = "\n".join(
        f"{key}: {value}" for key, value in existing_extra_attributes.items()
    )
    return merged_payload, {
        "field_keys": updated_field_keys,
        "labels": updated_labels,
        "attribute_keys": updated_attribute_keys,
    }


def list_product_movements(product_id: int) -> list[dict]:
    """Liefert die Historie aller Ein- und Auslagerungen zu einem Produkt."""
    rows = get_db().execute(
        "SELECT * FROM stock_movements WHERE product_id = ? ORDER BY created_at DESC, id DESC",
        (product_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_product(payload: dict) -> int:
    """Legt ein neues Produkt an und gibt dessen neue ID zurueck."""
    db = get_db()
    extra_attributes = json.dumps(parse_extra_attributes(payload["extra_attributes"]), ensure_ascii=True)
    product_category_id, product_category_name = _resolve_product_category_selection(payload)
    normalized_barcode = _normalize_barcode(payload.get("barcode", ""))

    _ensure_barcode_available(normalized_barcode)

    try:
        cursor = db.execute(
            """
            INSERT INTO products (
                name, barcode, sku, category, product_category_id, storage_location, unit,
                target_quantity, current_quantity, min_quantity, notes, extra_attributes, requires_expiry_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["name"],
                normalized_barcode or None,
                payload["sku"] or None,
                product_category_name or None,
                product_category_id,
                payload["storage_location"] or None,
                payload["unit"],
                int(payload["target_quantity"]),
                int(payload["current_quantity"]),
                int(payload["min_quantity"]),
                payload["notes"] or None,
                extra_attributes,
                1 if payload.get("requires_expiry_date") else 0,
            ),
        )
        if normalized_barcode:
            db.execute(
                "INSERT INTO product_barcodes (product_id, barcode) VALUES (?, ?)",
                (int(cursor.lastrowid), normalized_barcode),
            )
    except Exception:
        raise

    db.commit()
    return int(cursor.lastrowid)


def update_product(product_id: int, payload: dict) -> None:
    """Aktualisiert die Stammdaten eines vorhandenen Produkts."""
    db = get_db()
    extra_attributes = json.dumps(parse_extra_attributes(payload["extra_attributes"]), ensure_ascii=True)
    product_category_id, product_category_name = _resolve_product_category_selection(payload)
    product = get_product(product_id)
    if product is None:
        raise ValueError("Produkt wurde nicht gefunden.")

    normalized_barcode = _normalize_barcode(payload.get("barcode", ""))
    previous_primary_barcode = _normalize_barcode(product.get("barcode", ""))

    _ensure_barcode_available(normalized_barcode, current_product_id=product_id)

    try:
        db.execute(
            """
            UPDATE products
            SET name = ?, barcode = ?, sku = ?, category = ?, product_category_id = ?, storage_location = ?,
                unit = ?, target_quantity = ?, current_quantity = ?, min_quantity = ?,
                notes = ?, extra_attributes = ?, requires_expiry_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload["name"],
                normalized_barcode or None,
                payload["sku"] or None,
                product_category_name or None,
                product_category_id,
                payload["storage_location"] or None,
                payload["unit"],
                int(payload["target_quantity"]),
                int(payload["current_quantity"]),
                int(payload["min_quantity"]),
                payload["notes"] or None,
                extra_attributes,
                1 if payload.get("requires_expiry_date") else 0,
                product_id,
            ),
        )
        if previous_primary_barcode and previous_primary_barcode != normalized_barcode:
            db.execute("DELETE FROM product_barcodes WHERE product_id = ? AND barcode = ?", (product_id, previous_primary_barcode))

        if normalized_barcode:
            db.execute("DELETE FROM product_barcodes WHERE product_id = ? AND barcode = ?", (product_id, normalized_barcode))
            db.execute(
                "INSERT INTO product_barcodes (product_id, barcode) VALUES (?, ?)",
                (product_id, normalized_barcode),
            )
    except Exception:
        raise

    db.commit()


def update_product_categories_from_list(
    product_id: int,
    product_category_id_raw: str | int | None,
    shopping_category_id_raw: str | int | None,
    requires_expiry_date_raw: str | int | None = None,
) -> dict:
    """Aktualisiert Kategorien direkt aus der Produktliste heraus."""
    product = get_product(product_id)
    if product is None:
        raise ValueError("Produkt wurde nicht gefunden.")

    selected_product_category_id = str(product_category_id_raw or "").strip()
    if not selected_product_category_id:
        raise ValueError("Bitte eine Lebensmittelkategorie auswaehlen.")

    try:
        product_category_id = int(selected_product_category_id)
    except ValueError as exc:
        raise ValueError("Die ausgewaehlte Lebensmittelkategorie ist ungueltig.") from exc

    _require_category_exists("product_categories", product_category_id, "Produktkategorie")
    product_category_name = _get_product_category_name(product_category_id)

    db = get_db()
    requires_expiry_date = _parse_checkbox_value(requires_expiry_date_raw)
    db.execute(
        """
        UPDATE products
        SET product_category_id = ?, category = ?, requires_expiry_date = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (product_category_id, product_category_name or None, 1 if requires_expiry_date else 0, product_id),
    )

    shopping_category_name = ""
    selected_shopping_category_id = str(shopping_category_id_raw or "").strip()
    if selected_shopping_category_id:
        try:
            shopping_category_id = int(selected_shopping_category_id)
        except ValueError as exc:
            raise ValueError("Die ausgewaehlte Einkaufskategorie ist ungueltig.") from exc

        _require_category_exists("shopping_categories", shopping_category_id, "Einkaufskategorie")
        db.execute(
            """
            INSERT OR IGNORE INTO product_category_shopping_links (product_category_id, shopping_category_id)
            VALUES (?, ?)
            """,
            (product_category_id, shopping_category_id),
        )
        shopping_category_name = _get_shopping_category_name(shopping_category_id)

    db.commit()
    return {
        "product_name": product["name"],
        "product_category_name": product_category_name,
        "shopping_category_name": shopping_category_name,
        "requires_expiry_date": requires_expiry_date,
    }


def record_stock_movement(
    product_id: int,
    movement_type: str,
    quantity: int,
    reference: str = "",
    note: str = "",
    expiry_date: str = "",
) -> dict:
    """Bucht eine Ein- oder Auslagerung und aktualisiert den aktuellen Bestand."""
    if quantity <= 0:
        raise ValueError("Die Menge muss groesser als 0 sein.")

    product = get_product(product_id)
    if product is None:
        raise ValueError("Produkt wurde nicht gefunden.")

    normalized_expiry_date = str(expiry_date or "").strip()
    if movement_type == "in" and product.get("requires_expiry_date"):
        if not normalized_expiry_date:
            raise ValueError("Fuer dieses Produkt ist ein Haltbarkeitsdatum erforderlich.")
        normalized_expiry_date = _validate_expiry_date(normalized_expiry_date)

    oldest_expiry_before = product.get("next_expiry_date") or ""

    current_quantity = int(product["current_quantity"])
    if movement_type == "out":
        if quantity > current_quantity:
            raise ValueError("Nicht genug Bestand fuer diese Auslagerung vorhanden.")
        new_quantity = current_quantity - quantity
    elif movement_type == "in":
        new_quantity = current_quantity + quantity
    else:
        raise ValueError("Ungueltiger Bewegungstyp.")

    db = get_db()
    db.execute(
        "UPDATE products SET current_quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_quantity, product_id),
    )
    db.execute(
        """
        INSERT INTO stock_movements (product_id, movement_type, quantity, reference, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (product_id, movement_type, quantity, reference or None, note or None),
    )

    expiry_tracking_incomplete = False
    if movement_type == "in" and product.get("requires_expiry_date"):
        db.execute(
            """
            INSERT INTO product_expiry_batches (product_id, expires_on, quantity, quantity_remaining)
            VALUES (?, ?, ?, ?)
            """,
            (product_id, normalized_expiry_date, quantity, quantity),
        )
    elif movement_type == "out" and product.get("requires_expiry_date"):
        consumption_result = _consume_expiry_batches(db, product_id, quantity)
        expiry_tracking_incomplete = consumption_result["missing_quantity"] > 0

    db.commit()
    return {
        "expiry_date": normalized_expiry_date,
        "expiry_date_display": _format_expiry_date(normalized_expiry_date),
        "oldest_expiry_before": oldest_expiry_before,
        "oldest_expiry_before_display": _format_expiry_date(oldest_expiry_before),
        "expiry_tracking_incomplete": expiry_tracking_incomplete,
    }


def parse_extra_attributes(raw_text: str | dict | None) -> dict:
    """Wandelt freie Formular-Attribute im Format Schluessel: Wert in ein Dict um."""
    if raw_text is None:
        return {}

    if isinstance(raw_text, dict):
        return raw_text

    text = raw_text.strip()
    if not text:
        return {}

    attributes = {}
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"Zusatzattribute muessen als Schluessel: Wert erfasst werden. Fehler in Zeile {index}.")
        key, value = line.split(":", 1)
        cleaned_key = key.strip()
        cleaned_value = value.strip()
        if not cleaned_key:
            raise ValueError(f"Der Attributname fehlt in Zeile {index}.")
        attributes[cleaned_key] = cleaned_value
    return attributes


def _serialize_product(row) -> dict:
    """Ergaenzt Rohdaten aus der Datenbank um Anzeigehilfen fuer Templates."""
    if row is None:
        return {}

    product = dict(row)
    primary_barcode = _normalize_barcode(product.get("barcode"))
    all_barcodes = _get_all_product_barcodes(product.get("id"), primary_barcode)
    additional_barcodes = all_barcodes[1:] if primary_barcode and len(all_barcodes) > 1 else all_barcodes
    extra_attributes = product.get("extra_attributes") or "{}"
    parsed_attributes = json.loads(extra_attributes)
    product_category_name = _get_product_category_name(product.get("product_category_id")) or (product.get("category") or "")
    shopping_category_links = _get_linked_shopping_category_links(product.get("product_category_id"))
    shopping_categories = [category["name"] for category in shopping_category_links]
    requires_expiry_date = bool(product.get("requires_expiry_date"))
    expiry_batches = _list_open_expiry_batches(product.get("id")) if requires_expiry_date else []
    tracked_expiry_quantity = sum(batch["quantity_remaining"] for batch in expiry_batches)
    missing_expiry_quantity = max(int(product.get("current_quantity") or 0) - tracked_expiry_quantity, 0)
    next_expiry_date = expiry_batches[0]["expires_on"] if expiry_batches else ""
    next_expiry_quantity = sum(
        batch["quantity_remaining"] for batch in expiry_batches if batch["expires_on"] == next_expiry_date
    ) if next_expiry_date else 0
    expiry_status = _classify_expiry_status(next_expiry_date, requires_expiry_date, missing_expiry_quantity)

    product["attributes"] = parsed_attributes
    product["extra_attributes"] = "\n".join(f"{key}: {value}" for key, value in parsed_attributes.items())
    product["product_category"] = product_category_name
    product["category"] = product_category_name
    product["shopping_category_links"] = shopping_category_links
    product["shopping_category_ids"] = [category["id"] for category in shopping_category_links]
    product["primary_shopping_category_id"] = shopping_category_links[0]["id"] if shopping_category_links else None
    product["shopping_categories"] = shopping_categories
    product["shopping_category_label"] = ", ".join(shopping_categories)
    product["barcode"] = primary_barcode
    product["all_barcodes"] = all_barcodes
    product["additional_barcodes"] = additional_barcodes
    product["barcode_label"] = ", ".join(all_barcodes)
    product["requires_expiry_date"] = requires_expiry_date
    product["expiry_batches"] = expiry_batches
    product["tracked_expiry_quantity"] = tracked_expiry_quantity
    product["missing_expiry_quantity"] = missing_expiry_quantity
    product["next_expiry_date"] = next_expiry_date
    product["next_expiry_quantity"] = next_expiry_quantity
    product["next_expiry_display"] = _format_expiry_date(next_expiry_date)
    product["expiry_days_until"] = _days_until_expiry(next_expiry_date)
    product["expiry_status"] = expiry_status
    product["expiry_status_label"] = _get_expiry_status_label(expiry_status, product["expiry_days_until"])
    product["difference_quantity"] = product["target_quantity"] - product["current_quantity"]
    return product


def _build_shopping_mail_subject(mode: str, category: str) -> str:
    """Erzeugt einen passenden Betreff fuer den Mailversand der Einkaufsliste."""
    mode_label = "Mindestbestand" if mode == "min" else "Vollbestand"
    if category:
        return f"Einkaufsliste {mode_label} - {category}"
    return f"Einkaufsliste {mode_label}"


def _build_shopping_mail_body(items: list[dict], mode: str, category: str, total_missing_units: int) -> str:
    """Erzeugt einen gut lesbaren Text fuer Druck und Mailversand."""
    mode_label = "Mindestbestand" if mode == "min" else "Vollbestand"
    today = date.today().strftime("%d.%m.%Y")

    lines = [
        f"Einkaufsliste {today}",
        f"Modus: {mode_label}",
        "",
    ]

    if category:
        lines.insert(2, f"Kategorie: {category}")

    lines.append(f"Produkte: {len(items)}, Fehlmenge gesamt: {total_missing_units}")
    lines.append("")

    if not items:
        lines.append("Keine fehlenden Produkte.")
        return "\n".join(lines)

    for item in items:
        detail_parts = [f"{item['shopping_quantity']} {item['unit']}"]
        if item.get("product_category"):
            detail_parts.append(item["product_category"])
        if item.get("shopping_category_label"):
            detail_parts.append(item["shopping_category_label"])
        if item.get("storage_location"):
            detail_parts.append(item["storage_location"])
        lines.append(f"- {item['name']}: {', '.join(detail_parts)}")

    return "\n".join(lines)


def _resolve_effective_shopping_category_names(category_name: str) -> list[str]:
    """Ermittelt eine Einkaufskategorie inklusive aller mitgenommenen Unterlisten."""
    normalized_category_name = _normalize_category_name(category_name)
    if not normalized_category_name:
        return []

    root_row = get_db().execute(
        "SELECT id, name FROM shopping_categories WHERE lower(name) = lower(?)",
        (normalized_category_name,),
    ).fetchone()
    if root_row is None:
        return [normalized_category_name]

    pending_ids = [int(root_row["id"])]
    resolved_ids: list[int] = []
    seen_ids: set[int] = set()

    while pending_ids:
        current_category_id = pending_ids.pop(0)
        if current_category_id in seen_ids:
            continue

        seen_ids.add(current_category_id)
        resolved_ids.append(current_category_id)
        for included_category_id in _get_included_shopping_category_ids(current_category_id):
            if included_category_id not in seen_ids:
                pending_ids.append(included_category_id)

    placeholders = ", ".join("?" for _ in resolved_ids)
    rows = get_db().execute(
        f"SELECT id, name FROM shopping_categories WHERE id IN ({placeholders}) ORDER BY sort_order ASC, name COLLATE NOCASE",
        resolved_ids,
    ).fetchall()
    return [row["name"] for row in rows]


def _count_table_rows(db, table_name: str) -> int:
    """Zaehlt Zeilen einer Tabelle fuer Status- und Entwickleransichten."""
    row = db.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"] or 0)


def _reset_autoincrement_sequences(db, table_names: list[str]) -> None:
    """Setzt die SQLite-Autoincrement-Sequenzen fuer geleerte Tabellen zurueck."""
    placeholders = ", ".join("?" for _ in table_names)
    db.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", table_names)


def _seed_default_shopping_categories_for_developer_mode(db) -> None:
    """Legt nach einem Komplettreset wieder sinnvolle Standardkategorien an."""
    for index, category_name in enumerate(DEFAULT_SHOPPING_CATEGORIES, start=1):
        db.execute(
            "INSERT INTO shopping_categories (name, sort_order) VALUES (?, ?)",
            (category_name, index * 10),
        )


def _normalize_optional_id_list(raw_ids: list[int] | list[str]) -> list[int]:
    """Normalisiert optionale ID-Listen und entfernt leere Werte sowie Duplikate."""
    normalized_ids: list[int] = []
    seen_ids: set[int] = set()
    for raw_id in raw_ids:
        raw_text = str(raw_id or "").strip()
        if not raw_text:
            continue
        try:
            normalized_id = int(raw_text)
        except ValueError as exc:
            raise ValueError("Mindestens eine Einkaufskategorie ist ungueltig.") from exc
        if normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)
    return normalized_ids


def _product_matches_search(product: dict, needle: str) -> bool:
    """Prueft, ob ein Produkt auf einen Suchbegriff passt."""
    searchable_values = [
        product.get("name", ""),
        product.get("barcode", ""),
        product.get("barcode_label", ""),
        product.get("sku", ""),
        product.get("product_category", ""),
        product.get("shopping_category_label", ""),
        product.get("storage_location", ""),
        product.get("next_expiry_display", ""),
    ]
    return any(needle in str(value).casefold() for value in searchable_values if value)


def _build_expiry_summary(products: list[dict]) -> dict:
    """Gruppiert Produkte nach Haltbarkeitsstatus fuer Dashboard und Uebersicht."""
    items = [product for product in products if product.get("requires_expiry_date")]
    counts = {
        "good": 0,
        "expiring_soon": 0,
        "expired": 0,
        "missing": 0,
    }

    for item in items:
        status = item.get("expiry_status") or "good"
        counts[status] = counts.get(status, 0) + 1

    items.sort(
        key=lambda item: (
            _expiry_status_sort_key(item.get("expiry_status", "good")),
            item.get("next_expiry_date") or "9999-12-31",
            item.get("name", "").casefold(),
        )
    )
    return {"items": items, "counts": counts}


def _expiry_status_sort_key(status: str) -> int:
    order = {"expired": 0, "expiring_soon": 1, "missing": 2, "good": 3}
    return order.get(status, 4)


def _resolve_product_category_selection(payload: dict) -> tuple[int | None, str]:
    """Ermittelt die Produktkategorie aus Auswahl oder Freitextfeld."""
    new_category_name = _normalize_category_name(payload.get("new_product_category", ""))
    if new_category_name:
        category_id = create_product_category(new_category_name)
        return category_id, new_category_name

    selected_category_id = str(payload.get("product_category_id", "")).strip()
    if not selected_category_id:
        return None, ""

    try:
        category_id = int(selected_category_id)
    except ValueError as exc:
        raise ValueError("Die ausgewaehlte Produktkategorie ist ungueltig.") from exc

    row = get_db().execute("SELECT id, name FROM product_categories WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise ValueError("Die ausgewaehlte Produktkategorie wurde nicht gefunden.")

    return int(row["id"]), row["name"]


def _get_or_create_named_category(table_name: str, name: str) -> int:
    """Liefert die ID einer benannten Kategorie und legt sie bei Bedarf an."""
    normalized_name = _normalize_category_name(name)
    if not normalized_name:
        raise ValueError("Der Kategoriename darf nicht leer sein.")

    db = get_db()
    row = db.execute(f"SELECT id FROM {table_name} WHERE lower(name) = lower(?)", (normalized_name,)).fetchone()
    if row:
        return int(row["id"])

    cursor = db.execute(f"INSERT INTO {table_name} (name) VALUES (?)", (normalized_name,))
    db.commit()
    return int(cursor.lastrowid)


def _find_category_id_by_name(table_name: str, name: str) -> int | None:
    """Sucht eine Kategorie-ID ueber den Namen ohne Beruecksichtigung der Gross-/Kleinschreibung."""
    row = get_db().execute(f"SELECT id FROM {table_name} WHERE lower(name) = lower(?)", (name,)).fetchone()
    return int(row["id"]) if row else None


def _require_category_exists(table_name: str, category_id: int, label: str) -> None:
    """Stellt sicher, dass eine Kategorie-ID in der erwarteten Tabelle vorhanden ist."""
    row = get_db().execute(f"SELECT id FROM {table_name} WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise ValueError(f"{label} wurde nicht gefunden.")


def _get_product_category_name(product_category_id: int | None) -> str:
    """Liest den Namen einer Produktkategorie anhand ihrer ID."""
    if not product_category_id:
        return ""

    row = get_db().execute("SELECT name FROM product_categories WHERE id = ?", (product_category_id,)).fetchone()
    return row["name"] if row else ""


def _get_shopping_category_name(shopping_category_id: int | None) -> str:
    """Liest den Namen einer Einkaufskategorie anhand ihrer ID."""
    if not shopping_category_id:
        return ""

    row = get_db().execute("SELECT name FROM shopping_categories WHERE id = ?", (shopping_category_id,)).fetchone()
    return row["name"] if row else ""


def _list_open_expiry_batches(product_id: int | None) -> list[dict]:
    """Liefert alle offenen MHD-Chargen eines Produkts in FIFO-Reihenfolge."""
    if not product_id:
        return []

    rows = get_db().execute(
        """
        SELECT id, expires_on, quantity, quantity_remaining, created_at
        FROM product_expiry_batches
        WHERE product_id = ? AND quantity_remaining > 0
        ORDER BY expires_on ASC, created_at ASC, id ASC
        """,
        (product_id,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "expires_on": row["expires_on"],
            "expires_display": _format_expiry_date(row["expires_on"]),
            "quantity": int(row["quantity"]),
            "quantity_remaining": int(row["quantity_remaining"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _consume_expiry_batches(db, product_id: int, quantity: int) -> dict:
    """Verbraucht beim Auslagern zuerst die aeltesten MHD-Chargen."""
    rows = db.execute(
        """
        SELECT id, quantity_remaining
        FROM product_expiry_batches
        WHERE product_id = ? AND quantity_remaining > 0
        ORDER BY expires_on ASC, created_at ASC, id ASC
        """,
        (product_id,),
    ).fetchall()

    remaining_to_consume = quantity
    for row in rows:
        if remaining_to_consume <= 0:
            break

        batch_remaining = int(row["quantity_remaining"])
        consumed_quantity = min(batch_remaining, remaining_to_consume)
        db.execute(
            "UPDATE product_expiry_batches SET quantity_remaining = quantity_remaining - ? WHERE id = ?",
            (consumed_quantity, row["id"]),
        )
        remaining_to_consume -= consumed_quantity

    return {"missing_quantity": remaining_to_consume}


def _validate_expiry_date(raw_value: str) -> str:
    """Prueft ein MHD im ISO-Format und liefert den normierten Wert zurueck."""
    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError("Das Haltbarkeitsdatum ist ungueltig.") from exc

    return parsed.isoformat()


def _format_expiry_date(raw_value: str | None) -> str:
    """Formatiert ein MHD fuer die Anzeige."""
    if not raw_value:
        return ""

    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError:
        return raw_value

    return parsed.strftime("%d.%m.%Y")


def _days_until_expiry(raw_value: str | None) -> int | None:
    """Berechnet die Resttage bis zum MHD."""
    if not raw_value:
        return None

    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError:
        return None

    return (parsed - date.today()).days


def _classify_expiry_status(raw_value: str | None, requires_expiry_date: bool, missing_expiry_quantity: int) -> str:
    """Ordnet ein Produkt in den passenden MHD-Status ein."""
    if requires_expiry_date and missing_expiry_quantity > 0 and not raw_value:
        return "missing"

    days_until_expiry = _days_until_expiry(raw_value)
    if days_until_expiry is None:
        return "good"
    if days_until_expiry < 0:
        return "expired"
    if days_until_expiry <= 5:
        return "expiring_soon"
    return "good"


def _get_expiry_status_label(status: str, days_until_expiry: int | None) -> str:
    """Liefert einen lesbaren Labeltext fuer den MHD-Status."""
    if status == "expired":
        return "Bereits abgelaufen"
    if status == "expiring_soon":
        if days_until_expiry == 0:
            return "Laeuft heute ab"
        if days_until_expiry == 1:
            return "Laeuft morgen ab"
        if days_until_expiry is not None and days_until_expiry > 1:
            return f"Laeuft in {days_until_expiry} Tagen ab"
        return "Laeuft bald ab"
    if status == "missing":
        return "Kein MHD erfasst"
    return "Gut"


def _parse_checkbox_value(raw_value: str | int | None) -> bool:
    """Wertet Checkbox- und Formularwerte als booleschen Status aus."""
    return str(raw_value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _parse_optional_boolean_field(raw_value: str | int | None) -> bool | None:
    """Wertet optionale Formularauswahl fuer boolesche Bulk-Felder aus."""
    normalized = str(raw_value or "").strip().casefold()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Die Auswahl fuer das Haltbarkeitsdatum ist ungueltig.")


def _get_linked_shopping_categories(product_category_id: int | None) -> list[str]:
    """Liefert alle Einkaufskategorien zu einer Produktkategorie."""
    return [category["name"] for category in _get_linked_shopping_category_links(product_category_id)]


def _get_linked_shopping_category_links(product_category_id: int | None) -> list[dict]:
    """Liefert alle Einkaufskategorien zu einer Produktkategorie inklusive IDs."""
    if not product_category_id:
        return []

    rows = get_db().execute(
        """
        SELECT sc.id, sc.name
        FROM shopping_categories AS sc
        JOIN product_category_shopping_links AS pcsl ON pcsl.shopping_category_id = sc.id
        WHERE pcsl.product_category_id = ?
        ORDER BY sc.sort_order ASC, sc.name COLLATE NOCASE
        """,
        (product_category_id,),
    ).fetchall()
    return [{"id": int(row["id"]), "name": row["name"]} for row in rows]


def _get_linked_product_categories(shopping_category_id: int) -> list[str]:
    """Liefert alle Produktkategorien, die einer Einkaufskategorie zugeordnet sind."""
    rows = get_db().execute(
        """
        SELECT pc.name
        FROM product_categories AS pc
        JOIN product_category_shopping_links AS pcsl ON pcsl.product_category_id = pc.id
        WHERE pcsl.shopping_category_id = ?
        ORDER BY pc.name COLLATE NOCASE
        """,
        (shopping_category_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _get_included_shopping_category_ids(shopping_category_id: int) -> list[int]:
    """Liefert alle direkt mitgenommenen Einkaufskategorien einer Liste."""
    rows = get_db().execute(
        """
        SELECT included_shopping_category_id
        FROM shopping_category_inclusions
        WHERE shopping_category_id = ?
        ORDER BY included_shopping_category_id ASC
        """,
        (shopping_category_id,),
    ).fetchall()
    return [int(row["included_shopping_category_id"]) for row in rows]


def _get_included_shopping_category_links(shopping_category_id: int) -> list[dict]:
    """Liefert alle direkt mitgenommenen Einkaufskategorien inklusive IDs und Namen."""
    rows = get_db().execute(
        """
        SELECT sc.id, sc.name
        FROM shopping_categories AS sc
        JOIN shopping_category_inclusions AS sci ON sci.included_shopping_category_id = sc.id
        WHERE sci.shopping_category_id = ?
        ORDER BY sc.sort_order ASC, sc.name COLLATE NOCASE
        """,
        (shopping_category_id,),
    ).fetchall()
    return [{"id": int(row["id"]), "name": row["name"]} for row in rows]


def _normalize_category_name(name: str | None) -> str:
    """Bereinigt Kategorienamen fuer Speicherung und Vergleich."""
    return " ".join((name or "").strip().split())


def _normalize_barcode(value: str | None) -> str:
    """Bereinigt Barcodes fuer Vergleich und Speicherung."""
    return " ".join((value or "").strip().split())


def _ensure_barcode_available(barcode: str, current_product_id: int | None = None) -> None:
    """Stellt sicher, dass ein Barcode noch keinem anderen Produkt zugeordnet ist."""
    if not barcode:
        return

    db = get_db()
    row = db.execute("SELECT id FROM products WHERE barcode = ?", (barcode,)).fetchone()
    if row is not None and int(row["id"]) != int(current_product_id or 0):
        raise ValueError("Der Barcode ist bereits vergeben.")

    row = db.execute("SELECT product_id FROM product_barcodes WHERE barcode = ?", (barcode,)).fetchone()
    if row is not None and int(row["product_id"]) != int(current_product_id or 0):
        raise ValueError("Der Barcode ist bereits vergeben.")


def _get_all_product_barcodes(product_id: int | None, primary_barcode: str | None = None) -> list[str]:
    """Liefert alle bekannten Barcodes eines Produkts ohne Duplikate."""
    normalized_primary = _normalize_barcode(primary_barcode)
    if not product_id:
        return [normalized_primary] if normalized_primary else []

    rows = get_db().execute(
        "SELECT barcode FROM product_barcodes WHERE product_id = ? ORDER BY id ASC",
        (product_id,),
    ).fetchall()

    barcodes: list[str] = []
    if normalized_primary:
        barcodes.append(normalized_primary)

    for row in rows:
        candidate = _normalize_barcode(row["barcode"])
        if candidate and candidate not in barcodes:
            barcodes.append(candidate)

    return barcodes


def _clean_lookup_text(value: str | None) -> str:
    """Bereinigt Textwerte aus externen Barcodequellen."""
    return " ".join((value or "").strip().split())


def _normalize_id_list(raw_ids: list[int] | list[str], label: str) -> list[int]:
    """Bereinigt eine Liste numerischer IDs und verwirft Duplikate."""
    normalized_ids = []
    for raw_id in raw_ids:
        try:
            normalized_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Mindestens eine Auswahl in {label} ist ungueltig.") from exc

        if normalized_id > 0 and normalized_id not in normalized_ids:
            normalized_ids.append(normalized_id)

    if not normalized_ids:
        raise ValueError(f"Bitte mindestens einen Eintrag fuer {label} auswaehlen.")

    return normalized_ids

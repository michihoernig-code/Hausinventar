"""Flask-App-Factory und alle Webrouten fuer das Hausinventarsystem.

Diese Datei muss __init__.py heissen, weil Python sie als Einstieg fuer das
Paket inventory_app verwendet. Deshalb wurde sie nicht umbenannt.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

from flask import Flask, flash, redirect, render_template, request, url_for

from .database import init_app
from .inventory_logic import (
    add_barcode_to_product,
    bulk_link_product_categories_to_shopping,
    bulk_update_products,
    create_product_category,
    create_product,
    create_shopping_category,
    delete_product_category,
    delete_shopping_category,
    execute_developer_mode_action,
    find_product_by_barcode,
    get_category_management_data,
    get_dashboard_data,
    get_developer_mode_data,
    get_expiry_overview_data,
    get_product_form_data,
    get_product,
    get_shopping_list_data,
    link_product_category_to_shopping,
    lookup_product_by_barcode_online,
    list_product_movements,
    list_shopping_categories,
    merge_lookup_into_product_payload,
    parse_extra_attributes,
    record_stock_movement,
    reorder_shopping_categories,
    update_shopping_category_inclusions,
    update_product_categories_from_list,
    update_product_category,
    update_shopping_category,
    unlink_product_category_from_shopping,
    update_product,
)


def create_app() -> Flask:
    """Erzeugt und konfiguriert die Flask-Anwendung."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="inventory-dev-key",
        DATABASE=app.instance_path + "/inventory.db",
        MAIL_SERVER="",
        MAIL_PORT=587,
        MAIL_USE_TLS=True,
        MAIL_USE_SSL=False,
        MAIL_USERNAME="",
        MAIL_PASSWORD="",
        MAIL_DEFAULT_SENDER="",
        MAIL_TIMEOUT=20,
    )
    app.config.from_pyfile("config.py", silent=True)
    app.config.from_prefixed_env(prefix="INVENTORY")

    init_app(app)

    @app.route("/help")
    def help_page():
        # Einstiegshilfe fuer Personen, die das Programm noch nicht kennen.
        return render_template("help_page.html")

    @app.route("/developer-mode", methods=("GET", "POST"))
    def developer_mode():
        # Bewusst abgesicherter Bereich fuer Testdaten und manuelle Resets.
        if request.method == "POST":
            action = request.form.get("action", "").strip()
            confirmation_text = request.form.get("confirmation_text", "")

            try:
                result_message = execute_developer_mode_action(action, confirmation_text)
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                flash(result_message, "warning")

            return redirect(url_for("developer_mode"))

        return render_template("developer_mode_page.html", **get_developer_mode_data())

    @app.route("/")
    def index():
        # Dashboard zeigt nur noch die Uebersicht und schnelle Einstiege.
        dashboard = get_dashboard_data()
        return render_template("dashboard.html", **dashboard)

    @app.route("/scanner")
    def scanner_page():
        # Gemeinsamer Einstieg fuer die beiden Scanner-Workflows.
        return render_template("scanner_page.html")

    @app.route("/products")
    def products_page():
        # Eigene Produktverwaltung mit Suche, Tabelle und Massenbearbeitung.
        search = request.args.get("q", "").strip()
        dashboard = get_dashboard_data(search)
        product_form_data = get_product_form_data()
        shopping_categories = list_shopping_categories()
        return render_template(
            "products_page.html",
            search=search,
            bulk_product_categories=product_form_data["product_categories"],
            shopping_categories=shopping_categories,
            **dashboard,
        )

    @app.route("/products/bulk-update", methods=("POST",))
    def bulk_update_products_route():
        # Erlaubt das gemeinsame Aktualisieren mehrerer Produkte direkt aus der Produktverwaltung.
        search = request.form.get("search", "").strip()
        product_ids = request.form.getlist("product_ids")

        try:
            updated_count = bulk_update_products(product_ids, request.form)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            flash(f"{updated_count} Produkte wurden aktualisiert.", "success")

        return redirect(
            url_for("products_page", q=search, _anchor="product-table") if search else url_for("products_page", _anchor="product-table")
        )

    @app.route("/products/<int:product_id>/categories", methods=("POST",))
    def update_product_categories_from_list_route(product_id: int):
        # Direkte Kategoriepflege einzelner Produkte direkt in der Produktliste.
        search = request.form.get("search", "").strip()
        return_anchor = f"product-row-{product_id}"

        try:
            result = update_product_categories_from_list(
                product_id,
                request.form.get("product_category_id", ""),
                request.form.get("shopping_category_id", ""),
                request.form.get("requires_expiry_date", ""),
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            if result["shopping_category_name"]:
                flash(
                    f"{result['product_name']} wurde auf {result['product_category_name']} gesetzt und mit {result['shopping_category_name']} verknuepft.",
                    "success",
                )
            else:
                flash(f"Lebensmittelkategorie fuer {result['product_name']} wurde aktualisiert.", "success")

            flash(
                "Haltbarkeitsdatum ist aktiviert." if result["requires_expiry_date"] else "Haltbarkeitsdatum ist deaktiviert.",
                "success",
            )

        return redirect(
            url_for("products_page", q=search, _anchor=return_anchor)
            if search
            else url_for("products_page", _anchor=return_anchor)
        )

    @app.route("/products/new", methods=("GET", "POST"))
    def new_product():
        # Neues Produkt anlegen und Formulardaten bei Fehlern wieder anzeigen.
        scanner_context = _build_scanner_context(
            scanner_mode=request.values.get("scanner_mode", ""),
            scanner_action=request.values.get("scanner_action", ""),
        )

        if request.method == "POST":
            form_data = _build_product_payload(request)
            lookup_result = None
            lookup_updated_fields = []
            lookup_updated_attribute_keys = []
            form_action = request.form.get("form_action", "").strip()

            if form_action == "lookup_barcode":
                existing_product = find_product_by_barcode(form_data["barcode"]) if form_data["barcode"] else None
                if existing_product is not None:
                    flash("Dieser Barcode existiert bereits im Inventar.", "error")
                    return redirect(url_for("product_detail", product_id=existing_product["id"]))

                try:
                    lookup_result = lookup_product_by_barcode_online(form_data["barcode"])
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    if lookup_result is None:
                        flash("Online wurden keine Produktdaten zu diesem Barcode gefunden.", "error")
                    else:
                        form_data, lookup_update_info = merge_lookup_into_product_payload(form_data, lookup_result)
                        lookup_updated_fields = lookup_update_info["field_keys"]
                        lookup_updated_attribute_keys = lookup_update_info["attribute_keys"]
                        if lookup_update_info["labels"]:
                            flash(
                                f"Produktdaten aus {lookup_result['source']} uebernommen: {', '.join(lookup_update_info['labels'])}.",
                                "success",
                            )
                        else:
                            flash("Onlinedaten gefunden, aber vorhandene Eingaben wurden nicht ueberschrieben.", "success")

                return _render_product_form(
                    form_data,
                    is_new=True,
                    lookup_result=lookup_result,
                    lookup_updated_fields=lookup_updated_fields,
                    lookup_updated_attribute_keys=lookup_updated_attribute_keys,
                    scanner_context=scanner_context,
                )

            if form_action == "assign_existing_product":
                existing_product_id = request.form.get("existing_product_id", "").strip()
                form_data["existing_product_id"] = existing_product_id

                if not form_data["barcode"]:
                    flash("Bitte zuerst einen Barcode eingeben.", "error")
                    return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

                if not existing_product_id:
                    flash("Bitte ein bestehendes Produkt auswaehlen.", "error")
                    return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

                try:
                    target_product_id = int(existing_product_id)
                except ValueError:
                    flash("Die Produktauswahl ist ungueltig.", "error")
                    return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

                try:
                    add_barcode_to_product(target_product_id, form_data["barcode"])
                except ValueError as exc:
                    flash(str(exc), "error")
                    return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

                target_product = get_product(target_product_id)
                if target_product is None:
                    flash("Produkt wurde nicht gefunden.", "error")
                    return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

                if scanner_context["auto_record_inbound"]:
                    if target_product.get("requires_expiry_date"):
                        flash(
                            "Barcode wurde zugeordnet. Bitte die Einlagerung jetzt mit Haltbarkeitsdatum buchen.",
                            "warning",
                        )
                        return redirect(url_for("product_detail", product_id=target_product_id, _anchor="product-movement"))

                    try:
                        record_stock_movement(
                            product_id=target_product_id,
                            movement_type="in",
                            quantity=1,
                            reference="Scanner-Barcodezuordnung",
                            note="Automatische Einlagerung nach Zuordnung eines neuen Barcodes",
                        )
                    except ValueError as exc:
                        flash(f"Barcode wurde zugeordnet, automatische Einlagerung aber nicht gebucht: {exc}", "warning")
                    else:
                        flash("Barcode wurde zugeordnet und der Artikel direkt mit +1 eingelagert.", "success")
                        return redirect(url_for("product_detail", product_id=target_product_id))

                flash("Barcode wurde dem bestehenden Produkt zugeordnet.", "success")
                return redirect(url_for("product_detail", product_id=target_product_id))

            error = _validate_product_payload(form_data)
            if error:
                flash(error, "error")
                return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

            try:
                product_id = create_product(form_data)
            except ValueError as exc:
                flash(str(exc), "error")
                return _render_product_form(form_data, is_new=True, scanner_context=scanner_context)

            if scanner_context["auto_record_inbound"]:
                if form_data.get("requires_expiry_date"):
                    flash("Produkt wurde angelegt. Bitte die erste Einlagerung jetzt mit Haltbarkeitsdatum buchen.", "warning")
                    return redirect(url_for("product_detail", product_id=product_id, _anchor="product-movement"))

                try:
                    record_stock_movement(
                        product_id=product_id,
                        movement_type="in",
                        quantity=1,
                        reference="Scanner-Neuanlage",
                        note="Automatische Einlagerung nach unbekanntem Barcode-Scan",
                    )
                except ValueError as exc:
                    flash(f"Produkt wurde angelegt, automatische Einlagerung aber nicht gebucht: {exc}", "warning")
                else:
                    flash("Produkt wurde angelegt und direkt mit +1 eingelagert.", "success")
                    return redirect(url_for("product_detail", product_id=product_id))

            flash("Produkt wurde angelegt.", "success")
            return redirect(url_for("product_detail", product_id=product_id))

        initial_product = {}
        lookup_result = None
        lookup_updated_fields = []
        lookup_updated_attribute_keys = []
        preselected_product_category_id = request.args.get("product_category_id", "").strip()
        if preselected_product_category_id:
            initial_product["product_category_id"] = preselected_product_category_id

        initial_barcode = request.args.get("barcode", "").strip()
        if initial_barcode:
            existing_product = find_product_by_barcode(initial_barcode)
            if existing_product is not None:
                flash("Dieser Barcode existiert bereits im Inventar.", "error")
                return redirect(url_for("product_detail", product_id=existing_product["id"]))

            initial_product["barcode"] = initial_barcode

            if request.args.get("lookup", "").strip() in {"1", "true", "yes"}:
                try:
                    lookup_result = lookup_product_by_barcode_online(initial_barcode)
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    if lookup_result is None:
                        flash("Unbekannter Barcode erkannt. Bitte Produktdaten ergaenzen.", "warning")
                    else:
                        initial_product, lookup_update_info = merge_lookup_into_product_payload(initial_product, lookup_result)
                        lookup_updated_fields = lookup_update_info["field_keys"]
                        lookup_updated_attribute_keys = lookup_update_info["attribute_keys"]
                        flash(
                            f"Neuer Barcode erkannt. Produktdaten aus {lookup_result['source']} wurden vorbefuellt.",
                            "success",
                        )

        return _render_product_form(
            initial_product,
            is_new=True,
            lookup_result=lookup_result,
            lookup_updated_fields=lookup_updated_fields,
            lookup_updated_attribute_keys=lookup_updated_attribute_keys,
            scanner_context=scanner_context,
        )

    @app.route("/products/<int:product_id>")
    def product_detail(product_id: int):
        # Detailseite zeigt Stammdaten und Bewegungshistorie des Produkts.
        product = get_product(product_id)
        if product is None:
            flash("Produkt wurde nicht gefunden.", "error")
            return redirect(url_for("index"))

        movements = list_product_movements(product_id)
        return render_template("product_detail_page.html", product=product, movements=movements)

    @app.route("/products/<int:product_id>/barcodes", methods=("POST",))
    def add_product_barcode(product_id: int):
        # Erlaubt das Nachtragen weiterer Barcodes direkt am Produkt.
        barcode = request.form.get("barcode", "").strip()

        try:
            add_barcode_to_product(product_id, barcode)
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            flash("Neuer Barcode wurde hinzugefuegt.", "success")

        return redirect(url_for("product_detail", product_id=product_id, _anchor="product-barcodes"))

    @app.route("/products/<int:product_id>/edit", methods=("GET", "POST"))
    def edit_product(product_id: int):
        # Bestehendes Produkt bearbeiten, Bestand selbst bleibt ueber Buchungen konsistent.
        product = get_product(product_id)
        if product is None:
            flash("Produkt wurde nicht gefunden.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":
            form_data = _build_product_payload(request, current_quantity=product["current_quantity"])
            error = _validate_product_payload(form_data)
            if error:
                flash(error, "error")
                form_data["id"] = product_id
                return _render_product_form(form_data, is_new=False)

            try:
                update_product(product_id, form_data)
            except ValueError as exc:
                flash(str(exc), "error")
                form_data["id"] = product_id
                return _render_product_form(form_data, is_new=False)

            flash("Produkt wurde aktualisiert.", "success")
            return redirect(url_for("product_detail", product_id=product_id))

        return _render_product_form(product, is_new=False)

    @app.route("/products/<int:product_id>/move", methods=("POST",))
    def move_product(product_id: int):
        # Ein- und Auslagerungen laufen ueber dieselbe Route.
        direction = request.form.get("direction", "out")
        quantity = request.form.get("quantity", "1")
        reference = request.form.get("reference", "").strip()
        note = request.form.get("note", "").strip()
        expiry_date = request.form.get("expiry_date", "").strip()

        try:
            quantity_value = int(quantity)
        except ValueError:
            flash("Die Menge muss eine ganze Zahl sein.", "error")
            return redirect(url_for("product_detail", product_id=product_id))

        if direction not in {"in", "out"}:
            flash("Ungueltige Lagerbewegung.", "error")
            return redirect(url_for("product_detail", product_id=product_id))

        try:
            movement_result = record_stock_movement(
                product_id=product_id,
                movement_type=direction,
                quantity=quantity_value,
                reference=reference,
                note=note,
                expiry_date=expiry_date,
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("product_detail", product_id=product_id, _anchor="product-movement"))

        flash("Lagerbewegung wurde gespeichert.", "success")
        _flash_expiry_messages(direction, movement_result)
        return redirect(url_for("product_detail", product_id=product_id, _anchor="product-movement"))

    @app.route("/scan", methods=("GET", "POST"))
    def scan():
        # Scanner-Seite sucht Produkte ueber den Barcode.
        product = None
        barcode = ""

        if request.method == "POST":
            barcode = request.form.get("barcode", "").strip()
            product = find_product_by_barcode(barcode) if barcode else None
            if product is None and barcode:
                flash("Barcode noch nicht bekannt. Produktanlage wurde vorbereitet.", "warning")
                return redirect(url_for("new_product", barcode=barcode, lookup="1"))

        return render_template(
            "barcode_scan_page.html",
            product=product,
            barcode=barcode,
        )

    @app.route("/shopping-list")
    def shopping_list():
        # Einkaufsliste mit Fokus auf Mindest- oder Vollbestand.
        list_mode = request.args.get("mode", "min").strip()
        category = request.args.get("category", "").strip()
        email_recipient = request.args.get("email", "").strip()
        shopping_data = get_shopping_list_data(
            list_mode=list_mode,
            category=category,
            email_recipient=email_recipient,
        )
        return render_template("shopping_list_page.html", **shopping_data)

    @app.route("/expiry")
    def expiry_page():
        # Uebersicht fuer Produkte mit Haltbarkeitsdatum und drohendem Ablauf.
        status_filter = request.args.get("status", "all").strip()
        return render_template("expiry_page.html", **get_expiry_overview_data(status_filter=status_filter))

    @app.route("/categories", methods=("GET", "POST"))
    def categories():
        # Verwaltung fuer Lebensmittelarten und Einkaufskategorien inklusive Zuordnungen.
        if request.method == "POST":
            action = request.form.get("action", "").strip()

            try:
                if action == "create-product-category":
                    category_name = request.form.get("product_category_name", "").strip()
                    shopping_category_ids = request.form.getlist("shopping_category_ids")
                    create_product_category(category_name, shopping_category_ids=[int(category_id) for category_id in shopping_category_ids if category_id])
                    flash(f"Produktkategorie '{category_name}' wurde gespeichert.", "success")
                elif action == "create-shopping-category":
                    category_name = request.form.get("shopping_category_name", "").strip()
                    product_category_ids = request.form.getlist("product_category_ids")
                    create_shopping_category(category_name, product_category_ids=[int(category_id) for category_id in product_category_ids if category_id])
                    flash(f"Einkaufskategorie '{category_name}' wurde gespeichert.", "success")
                elif action == "link-categories":
                    product_category_id = int(request.form.get("product_category_id", "0"))
                    shopping_category_id = int(request.form.get("shopping_category_id", "0"))
                    link_product_category_to_shopping(product_category_id, shopping_category_id)
                    flash("Kategoriezuordnung wurde gespeichert.", "success")
                elif action == "bulk-link-categories":
                    product_category_ids = request.form.getlist("product_category_ids")
                    shopping_category_ids = request.form.getlist("shopping_category_ids")
                    bulk_link_product_categories_to_shopping(product_category_ids, shopping_category_ids)
                    flash("Mehrere Kategoriezuordnungen wurden gespeichert.", "success")
                elif action == "update-product-category":
                    product_category_id = int(request.form.get("product_category_id", "0"))
                    category_name = request.form.get("product_category_name", "").strip()
                    update_product_category(product_category_id, category_name)
                    flash("Produktkategorie wurde umbenannt.", "success")
                elif action == "update-shopping-category":
                    shopping_category_id = int(request.form.get("shopping_category_id", "0"))
                    category_name = request.form.get("shopping_category_name", "").strip()
                    sort_order = int(request.form.get("sort_order", "0"))
                    update_shopping_category(shopping_category_id, category_name, sort_order)
                    flash("Einkaufskategorie wurde aktualisiert.", "success")
                elif action == "update-shopping-category-inclusions":
                    shopping_category_id = int(request.form.get("shopping_category_id", "0"))
                    included_shopping_category_ids = request.form.getlist("included_shopping_category_ids")
                    update_shopping_category_inclusions(shopping_category_id, included_shopping_category_ids)
                    flash("Mitnahme-Regeln fuer die Einkaufskategorie wurden aktualisiert.", "success")
                elif action == "reorder-shopping-categories":
                    shopping_category_ids = request.form.getlist("shopping_category_ids")
                    reorder_shopping_categories(shopping_category_ids)
                    flash("Reihenfolge der Einkaufskategorien wurde aktualisiert.", "success")
                elif action == "unlink-categories":
                    product_category_id = int(request.form.get("product_category_id", "0"))
                    shopping_category_id = int(request.form.get("shopping_category_id", "0"))
                    unlink_product_category_from_shopping(product_category_id, shopping_category_id)
                    flash("Kategoriezuordnung wurde entfernt.", "success")
                elif action == "delete-product-category":
                    product_category_id = int(request.form.get("product_category_id", "0"))
                    delete_product_category(product_category_id)
                    flash("Produktkategorie wurde geloescht.", "success")
                elif action == "delete-shopping-category":
                    shopping_category_id = int(request.form.get("shopping_category_id", "0"))
                    delete_shopping_category(shopping_category_id)
                    flash("Einkaufskategorie wurde geloescht.", "success")
                else:
                    flash("Unbekannte Kategorien-Aktion.", "error")
            except ValueError as exc:
                flash(str(exc), "error")

            return redirect(url_for("categories"))

        return render_template("categories_page.html", **get_category_management_data())

    @app.route("/shopping-list/send", methods=("POST",))
    def send_shopping_list():
        # Verschickt die aktuelle Einkaufsliste direkt ueber den konfigurierten SMTP-Server.
        list_mode = request.form.get("mode", "min").strip()
        category = request.form.get("category", "").strip()
        email_recipient = request.form.get("email", "").strip()

        if not _is_valid_email_address(email_recipient):
            flash("Bitte eine gueltige Empfaenger-Mailadresse angeben.", "error")
            return redirect(url_for("shopping_list", mode=list_mode, category=category, email=email_recipient))

        shopping_data = get_shopping_list_data(
            list_mode=list_mode,
            category=category,
            email_recipient=email_recipient,
        )

        try:
            _send_email(
                recipient=email_recipient,
                subject=shopping_data["mail_subject"],
                body=shopping_data["mail_body"],
                config=app.config,
            )
        except ValueError as exc:
            flash(str(exc), "error")
        except (OSError, smtplib.SMTPException) as exc:
            flash(f"Mailversand fehlgeschlagen: {exc}", "error")
        else:
            flash(f"Einkaufsliste wurde an {email_recipient} gesendet.", "success")

        return redirect(url_for("shopping_list", mode=list_mode, category=category, email=email_recipient))

    @app.route("/quick-scan", methods=("GET", "POST"))
    def quick_scan():
        # Scanner-Alltag: Standardansicht fuer direkte Barcode-Aktionen.
        return _handle_quick_scan(fullscreen_mode=False)

    @app.route("/quick-scan/focus", methods=("GET", "POST"))
    def quick_scan_focus():
        # Vollbildansicht fuer Scannerbetrieb mit moeglichst wenig Ablenkung.
        return _handle_quick_scan(fullscreen_mode=True)

    def _handle_quick_scan(fullscreen_mode: bool):
        # Scanner-Alltag: ein Scan lagert aus, zwei identische Scans kurz hintereinander lagern ein.
        last_result = None
        scanned_barcode = ""
        pending_expiry_capture = None

        if request.method == "POST":
            scanned_barcode = request.form.get("barcode", "").strip()
            movement_type = request.form.get("movement_type", "out").strip()
            expiry_date = request.form.get("expiry_date", "").strip()
            quantity_raw = request.form.get("quantity", "1").strip()

            if movement_type not in {"in", "out"}:
                flash("Ungueltiger Schnellscan-Modus.", "error")
                return redirect(url_for("quick_scan_focus" if fullscreen_mode else "quick_scan"))

            try:
                quantity_value = int(quantity_raw)
            except ValueError:
                flash("Die Menge muss eine ganze Zahl sein.", "error")
                return redirect(url_for("quick_scan_focus" if fullscreen_mode else "quick_scan"))

            if quantity_value <= 0:
                flash("Die Menge muss mindestens 1 sein.", "error")
                return redirect(url_for("quick_scan_focus" if fullscreen_mode else "quick_scan"))

            product = find_product_by_barcode(scanned_barcode) if scanned_barcode else None
            if product is None:
                flash("Barcode noch nicht bekannt. Produktanlage wurde vorbereitet.", "warning")
                create_params = {
                    "barcode": scanned_barcode,
                    "lookup": "1",
                    "scanner_mode": "1",
                    "scanner_action": movement_type,
                }

                return redirect(
                    url_for(
                        "new_product",
                        **create_params,
                    )
                )

            if movement_type == "in" and product.get("requires_expiry_date") and not expiry_date:
                pending_expiry_capture = {
                    "barcode": scanned_barcode,
                    "movement_type": movement_type,
                    "quantity": quantity_value,
                    "product": product,
                }
                return _render_quick_scan_page(
                    last_result=last_result,
                    scanned_barcode="",
                    fullscreen_mode=fullscreen_mode,
                    pending_expiry_capture=pending_expiry_capture,
                )

            note = "Einlagerung per 2x-Scan" if movement_type == "in" else "Auslagerung per 1x-Scan"
            try:
                movement_result = record_stock_movement(
                    product_id=product["id"],
                    movement_type=movement_type,
                    quantity=quantity_value,
                    reference="Schnellscan",
                    note=note,
                    expiry_date=expiry_date,
                )
            except ValueError as exc:
                flash(str(exc), "error")
                return _render_quick_scan_page(
                    last_result=last_result,
                    scanned_barcode=scanned_barcode,
                    fullscreen_mode=fullscreen_mode,
                    pending_expiry_capture=pending_expiry_capture,
                )

            updated_product = get_product(product["id"])
            last_result = {
                "product": updated_product,
                "movement_type": movement_type,
                "message": f"{updated_product['name']} eingelagert" if movement_type == "in" else f"{updated_product['name']} ausgelagert",
                "expiry_display": updated_product["next_expiry_display"] if movement_type == "in" else movement_result.get("oldest_expiry_before_display", ""),
            }
            _flash_expiry_messages(movement_type, movement_result)
            scanned_barcode = ""

        return _render_quick_scan_page(
            last_result=last_result,
            scanned_barcode=scanned_barcode,
            fullscreen_mode=fullscreen_mode,
            pending_expiry_capture=pending_expiry_capture,
        )

    def _render_quick_scan_page(
        last_result: dict | None,
        scanned_barcode: str,
        fullscreen_mode: bool,
        pending_expiry_capture: dict | None = None,
    ):
        return render_template(
            "quick_scan_page.html",
            last_result=last_result,
            scanned_barcode=scanned_barcode,
            fullscreen_mode=fullscreen_mode,
            pending_expiry_capture=pending_expiry_capture,
            body_class="focus-mode" if fullscreen_mode else "",
        )

    return app


def _build_product_payload(request, current_quantity: int | None = None) -> dict:
    """Sammelt und vereinheitlicht alle Produktdaten aus dem HTML-Formular."""
    payload = {
        "name": request.form.get("name", "").strip(),
        "barcode": request.form.get("barcode", "").strip(),
        "existing_product_id": request.form.get("existing_product_id", "").strip(),
        "sku": request.form.get("sku", "").strip(),
        "product_category_id": request.form.get("product_category_id", "").strip(),
        "new_product_category": request.form.get("new_product_category", "").strip(),
        "storage_location": request.form.get("storage_location", "").strip(),
        "unit": request.form.get("unit", "Stk").strip() or "Stk",
        "target_quantity": request.form.get("target_quantity", "0").strip(),
        "current_quantity": current_quantity if current_quantity is not None else request.form.get("current_quantity", "0").strip(),
        "min_quantity": request.form.get("min_quantity", "0").strip(),
        "notes": request.form.get("notes", "").strip(),
        "extra_attributes": request.form.get("extra_attributes", "").strip(),
        "requires_expiry_date": request.form.get("requires_expiry_date", "").strip() in {"1", "true", "yes", "on"},
    }
    return payload


def _validate_product_payload(payload: dict) -> str | None:
    """Prueft Pflichtfelder und Zahlenwerte vor dem Speichern."""
    if not payload["name"]:
        return "Produktname ist erforderlich."

    for field_name in ("target_quantity", "current_quantity", "min_quantity"):
        try:
            int(payload[field_name])
        except (TypeError, ValueError):
            return "Soll-, Ist- und Mindestmenge muessen ganze Zahlen sein."

    try:
        parse_extra_attributes(payload["extra_attributes"])
    except ValueError as exc:
        return str(exc)

    return None


def _render_product_form(
    product: dict,
    is_new: bool,
    lookup_result: dict | None = None,
    lookup_updated_fields: list[str] | None = None,
    lookup_updated_attribute_keys: list[str] | None = None,
    scanner_context: dict | None = None,
):
    """Rendert das Produktformular mit allen Auswahlhilfen fuer Kategorien."""
    selected_product_category_id = product.get("product_category_id")
    if selected_product_category_id in {"", None}:
        selected_product_category_id = None

    try:
        selected_product_category_id = int(selected_product_category_id) if selected_product_category_id is not None else None
    except (TypeError, ValueError):
        selected_product_category_id = None

    form_data = get_product_form_data(selected_product_category_id)
    return render_template(
        "product_edit_form.html",
        product=product,
        is_new=is_new,
        lookup_result=lookup_result,
        lookup_updated_fields=lookup_updated_fields or [],
        lookup_updated_attribute_keys=lookup_updated_attribute_keys or [],
        scanner_context=scanner_context or _build_scanner_context("", ""),
        **form_data,
    )


def _build_scanner_context(scanner_mode: str | None, scanner_action: str | None) -> dict:
    """Bereitet Scanner-Kontext fuer die Produktanlage auf."""
    is_active = str(scanner_mode or "").strip() in {"1", "true", "yes"}
    action = str(scanner_action or "").strip()
    if action not in {"in", "out"}:
        action = ""

    return {
        "is_active": is_active,
        "action": action,
        "auto_record_inbound": is_active and action == "in",
    }


def _flash_expiry_messages(direction: str, movement_result: dict | None) -> None:
    """Ergaenzt Rueckmeldungen zum Haltbarkeitsdatum nach Lagerbewegungen."""
    if not movement_result:
        return

    expiry_date = str(movement_result.get("expiry_date") or "").strip()
    expiry_date_display = str(movement_result.get("expiry_date_display") or expiry_date).strip()
    oldest_expiry_before = str(movement_result.get("oldest_expiry_before") or "").strip()
    oldest_expiry_before_display = str(movement_result.get("oldest_expiry_before_display") or oldest_expiry_before).strip()

    if direction == "in" and expiry_date:
        flash(f"Haltbarkeitsdatum erfasst: {expiry_date_display}.", "success")

    if direction == "out" and oldest_expiry_before:
        flash(f"Aeltestes Produkt vom {oldest_expiry_before_display}. Bitte pruefen, ob wirklich die aelteste Charge entnommen wurde.", "warning")

    if movement_result.get("expiry_tracking_incomplete"):
        flash("Nicht fuer den gesamten Bestand liegen Haltbarkeitsdaten vor. Die MHD-Historie ist noch unvollstaendig.", "warning")


def _is_valid_email_address(value: str) -> bool:
    """Prueft einfach, ob die uebergebene Zeichenkette wie eine E-Mail-Adresse aussieht."""
    _, parsed = parseaddr(value)
    if parsed != value or "@" not in parsed or " " in parsed:
        return False

    local_part, _, domain_part = parsed.rpartition("@")
    return bool(local_part and domain_part)


def _send_email(recipient: str, subject: str, body: str, config: dict) -> None:
    """Versendet eine Textmail ueber den konfigurierten SMTP-Server."""
    mail_server = str(config.get("MAIL_SERVER", "")).strip()
    mail_port = int(config.get("MAIL_PORT", 587) or 587)
    use_tls = bool(config.get("MAIL_USE_TLS", True))
    use_ssl = bool(config.get("MAIL_USE_SSL", False))
    username = str(config.get("MAIL_USERNAME", "")).strip()
    password = str(config.get("MAIL_PASSWORD", ""))
    sender = str(config.get("MAIL_DEFAULT_SENDER", "")).strip() or username
    timeout = int(config.get("MAIL_TIMEOUT", 20) or 20)

    if not mail_server:
        raise ValueError("MAIL_SERVER ist nicht konfiguriert. Bitte instance/config.py oder INVENTORY_MAIL_SERVER setzen.")
    if use_tls and use_ssl:
        raise ValueError("MAIL_USE_TLS und MAIL_USE_SSL koennen nicht gleichzeitig aktiv sein.")
    if not _is_valid_email_address(sender):
        raise ValueError("MAIL_DEFAULT_SENDER oder MAIL_USERNAME muss eine gueltige Absenderadresse enthalten.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    ssl_context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(mail_server, mail_port, timeout=timeout, context=ssl_context) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(mail_server, mail_port, timeout=timeout) as server:
        if use_tls:
            server.starttls(context=ssl_context)
        if username:
            server.login(username, password)
        server.send_message(message)

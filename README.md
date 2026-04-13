# Hausinventar fuer Raspberry Pi 3

Dieses Projekt ist ein schlankes Hausinventarsystem mit Flask, SQLite und Browser-Oberflaeche. Es ist auf einen Raspberry Pi 3 ausgelegt und deckt folgende Kernfaelle ab:

- Produkte mit Soll- und Ist-Anzahl verwalten
- Einkaufslisten fuer Mindest- und Vollbestand erzeugen
- feste und freie Attribute pro Produkt erfassen
- Produkte anlegen und bearbeiten
- Ein- und Auslagerungen buchen
- Barcode-Scanner ueber die Browser-Oberflaeche nutzen
- Schnellscan-Modus fuer 1x Auslagern und 2x Einlagern

## Technologie

- Python 3.11+
- Flask fuer Weboberflaeche und Routen
- SQLite als lokale Datenbank
- HTML/CSS ohne schweres Frontend-Framework

## Start

1. Virtuelle Umgebung anlegen und aktivieren
2. Abhaengigkeiten installieren:

   pip install -r requirements.txt

3. Anwendung starten:

   python start_inventory_webserver.py

4. Im Browser oeffnen:

   http://localhost:5000

## Direkter Mailversand

Die Einkaufsliste kann jetzt direkt aus der Anwendung per SMTP versendet werden. Die Zugangsdaten sollen nicht im Quellcode liegen, deshalb laedt die App optionale Werte aus instance/config.py oder aus Umgebungsvariablen mit dem Prefix INVENTORY_.

Beispiel fuer instance/config.py:

   MAIL_SERVER = "smtp.example.com"
   MAIL_PORT = 587
   MAIL_USE_TLS = True
   MAIL_USE_SSL = False
   MAIL_USERNAME = "dein-konto@example.com"
   MAIL_PASSWORD = "app-passwort"
   MAIL_DEFAULT_SENDER = "dein-konto@example.com"
   MAIL_TIMEOUT = 20

Alternativ koennen dieselben Werte als Umgebungsvariablen gesetzt werden, zum Beispiel INVENTORY_MAIL_SERVER oder INVENTORY_MAIL_PASSWORD.

Hinweise:

- Fuer Gmail, Outlook und viele andere Anbieter wird meist ein App-Passwort benoetigt.
- MAIL_USE_TLS und MAIL_USE_SSL duerfen nicht gleichzeitig aktiv sein.
- Ohne Konfiguration bleibt der bisherige Mail-App-Button als Fallback nutzbar.

## Barcode-Scanner

Die meisten USB-Barcodescanner verhalten sich wie Tastaturen. Deshalb reicht die Scanner-Seite der Anwendung aus:

- Fokus in das Barcode-Feld setzen
- Barcode scannen
- Scanner sendet meist automatisch Enter
- Produkt erscheint und kann direkt ein- oder ausgelagert werden

Der Schnellzugriff arbeitet ebenfalls rein barcodebasiert:

- Ein Barcode bucht eine Auslagerung
- Zwei identische Barcodes kurz hintereinander buchen eine Einlagerung
- Unbekannte Barcodes oeffnen direkt die Neuanlage mit vorausgefuelltem Barcode und optionaler Online-Vorbefuellung
- Wenn ein unbekannter Barcode als Einlagerung erkannt wurde, wird nach dem Speichern automatisch eine erste Einlagerung gebucht
- Fuer den Raspberry gibt es zusaetzlich einen Vollbildmodus, der nur Scanfeld und Rueckmeldung zeigt

## Neue Navigation und Einkaufslisten

- Die linke Seitenleiste enthaelt jetzt direkte Menuepunkte fuer Einkaufsliste und Schnellzugriff Ein/Auslagern.
- Ganz unten in der linken Seitenleiste gibt es eine Hilfeseite fuer neue Nutzerinnen und Nutzer mit Einstieg, Scanner-Ablauf und den wichtigsten Arbeitswegen.
- Die komplette Produktliste mit Suche und Massenbearbeitung liegt jetzt in einem eigenen Menuepunkt Produktverwaltung und nicht mehr direkt im Dashboard.
- Es gibt jetzt getrennte Produktkategorien fuer Lebensmittelarten wie Nudeln oder Reis und getrennte Einkaufskategorien wie Basics oder Getraenke.
- Produktkategorien koennen im Bereich Kategorien einer oder mehreren Einkaufskategorien zugeordnet werden.
- Beim Anlegen neuer Produkte lassen sich vorhandene Produktkategorien direkt auswaehlen; neue Kategorien stehen nach dem Speichern ebenfalls in der Schnellauswahl bereit.
- Beim Anlegen neuer Produkte kann ein Barcode online nachgeschlagen werden. Die App prueft zuerst Open Food Facts und danach Open Beauty Facts, um leere Felder vorzufuellen.
- Neue Produkt- und Einkaufskategorien koennen direkt beim Anlegen schon miteinander verknuepft werden.
- Auf der Kategorienseite gibt es ausserdem eine Mehrfach-Zuordnung, um mehrere Lebensmittelarten in einem Schritt passenden Einkaufslisten zuzuweisen.
- Aus der Kategorienverwaltung kann man direkt ins gefilterte Dashboard, in die Einkaufsliste oder in ein neues Produkt mit vorausgewaehlter Lebensmittelart springen.
- Produkt- und Einkaufskategorien lassen sich direkt in der Kategorienverwaltung umbenennen; Einkaufskategorien koennen dort auch ueber ihre Sortierreihenfolge fuer Listen neu geordnet werden.
- Im Dashboard koennen mehrere Produkte markiert und gesammelt auf neue Lebensmittelarten, Lagerorte oder Soll- und Mindestbestaende aktualisiert werden.
- Einkaufskategorien lassen sich zusaetzlich per Drag-and-Drop sortieren.
- Die Massenbearbeitung im Dashboard unterstuetzt jetzt auch Einheit und Notizen fuer mehrere Produkte gleichzeitig.
- Die Einkaufsliste filtert nach Einkaufskategorien und kann zwischen Mindestbestand und Vollbestand umgeschaltet werden.

## Projektstruktur

- start_inventory_webserver.py: Startet den lokalen Flask-Webserver.
- inventory_app/__init__.py: Enthaeelt die Flask-App-Factory und alle Routen.
- inventory_app/database.py: Verwaltet SQLite-Verbindung und Tabellenaufbau.
- inventory_app/inventory_logic.py: Enthaeelt Produktlogik und Lagerbuchungen.
- inventory_app/templates/categories_page.html: Verwaltung fuer Produkt- und Einkaufskategorien.
- inventory_app/templates/layout.html: Gemeinsames Seitenlayout fuer alle HTML-Seiten.
- inventory_app/templates/dashboard.html: Startseite mit Kennzahlen und Produktliste.
- inventory_app/templates/products_page.html: Eigene Produktverwaltung mit Suche, Tabelle und Massenbearbeitung.
- inventory_app/templates/product_edit_form.html: Formular fuer neue und bestehende Produkte.
- inventory_app/templates/product_detail_page.html: Detailseite mit Lagerbewegungen und Attributen.
- inventory_app/templates/barcode_scan_page.html: Scan-Seite fuer den Barcode-Workflow.
- inventory_app/static/inventory_theme.css: Gesamtes Styling der Weboberflaeche.

## Datenmodell

### Produkte

- Name
- Barcode
- SKU / Artikelnummer
- Kategorie
- Lagerort
- Einheit
- Soll-Anzahl
- Ist-Anzahl
- Mindestbestand
- Notizen
- Zusatzattribute als freie Schluessel-Wert-Paare

### Lagerbewegungen

- Typ: Einlagerung oder Auslagerung
- Menge
- Referenz
- Notiz
- Zeitstempel

## Naechste sinnvolle Ausbaustufen

- Benutzer und Rollen
- CSV-Import / Export
- Inventurmodus mit Korrekturbuchungen
- Etikettendruck fuer Barcodes
- API fuer mobile Scanner oder ESP32-Terminals

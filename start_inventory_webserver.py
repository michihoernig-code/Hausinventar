"""Startdatei fuer die Webanwendung.

Diese Datei ist bewusst klein gehalten: Sie erzeugt die Flask-App ueber die
App-Factory und startet den lokalen Webserver fuer Entwicklung und kleine
Installationen auf dem Raspberry Pi.
"""

from inventory_app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

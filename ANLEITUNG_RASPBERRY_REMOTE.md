# Ausfuehrliche Anleitung: Vom Laptop auf dem Raspberry programmieren

Diese Anleitung zeigt dir Schritt fuer Schritt, wie du von deinem Windows-Laptop aus auf einem Raspberry Pi programmierst und dabei dein Hausinventarsystem direkt auf dem Pi laufen laesst.

Das Ziel ist:

- du schreibst den Code bequem am Laptop in VS Code
- die Dateien liegen auf dem Raspberry Pi
- Python, Flask und SQLite laufen direkt auf dem Raspberry
- du kannst die Weboberflaeche vom Laptop oder Handy im Browser aufrufen
- ein USB-Barcodescanner kann direkt am Raspberry angeschlossen werden

## Warum das sinnvoll ist

Fuer dein Projekt ist das der beste Weg, weil:

- der Raspberry spaeter ohnehin die Anwendung ausfuehren soll
- ein Barcodescanner meistens direkt am Raspberry haengt
- du dir das staendige Kopieren von Dateien sparst
- du die echte Zielumgebung direkt benutzt

## Was du brauchst

Auf dem Laptop:

- Windows
- VS Code
- WLAN oder LAN im selben Netzwerk wie der Raspberry

Auf dem Raspberry:

- Raspberry Pi OS
- Stromversorgung
- Netzwerkverbindung
- aktiviertes SSH

## Uebersicht des Ablaufs

1. Raspberry vorbereiten
2. SSH aktivieren
3. IP-Adresse des Raspberry herausfinden
4. Vom Laptop per SSH verbinden
5. VS Code mit Remote SSH einrichten
6. Projektordner auf dem Raspberry oeffnen
7. Python-Umgebung auf dem Raspberry anlegen
8. Anwendung starten
9. Weboberflaeche im Browser aufrufen

## Schritt 1: Raspberry vorbereiten

Falls dein Raspberry noch nicht eingerichtet ist:

1. Raspberry Pi OS installieren
2. Raspberry starten
3. Mit dem WLAN verbinden oder per LAN anschliessen
4. Benutzername und Passwort merken

Der Standardbenutzer ist oft `pi`, aber bei neueren Installationen legst du den Benutzer haeufig selbst an.

## Schritt 2: SSH auf dem Raspberry aktivieren

SSH ist der Fernzugriff, ueber den du vom Laptop aus auf dem Raspberry arbeitest.

### Variante A: Mit grafischer Oberflaeche

Auf dem Raspberry:

1. Menue oeffnen
2. Einstellungen oeffnen
3. Raspberry Pi Configuration suchen
4. Reiter Interfaces oeffnen
5. SSH auf Enabled setzen

### Variante B: Im Terminal

Auf dem Raspberry im Terminal:

```bash
sudo raspi-config
```

Dann:

1. Interface Options
2. SSH
3. Yes
4. Finish

## Schritt 3: IP-Adresse des Raspberry herausfinden

Auf dem Raspberry im Terminal:

```bash
hostname -I
```

Beispielausgabe:

```text
192.168.178.75          // mein Raspberry Pi3+
```

Diese Adresse brauchst du spaeter fuer die Verbindung vom Laptop.

Wichtig:

- der Laptop und der Raspberry muessen im selben Netzwerk sein
- am besten bekommt der Raspberry im Router immer dieselbe IP-Adresse

## Schritt 4: Vom Windows-Laptop per SSH testen

Oeffne auf dem Laptop PowerShell und gib ein:

```powershell
ssh BENUTZERNAME@192.168.178.75
```

Beispiel:

```powershell
ssh michi@192.168.178.75
```

Beim ersten Mal fragt Windows, ob du dem Geraet vertraust. Antworte mit:

```text
yes
```

Dann gib das Passwort des Raspberry-Benutzers ein.

Wenn alles klappt, bist du auf dem Raspberry eingeloggt.

## Schritt 5: VS Code fuer Remote SSH einrichten

### Erweiterung installieren

Auf dem Laptop in VS Code:

1. Erweiterungen oeffnen
2. Nach `Remote - SSH` suchen
3. Erweiterung von Microsoft installieren

### Verbindung in VS Code aufbauen

1. In VS Code `Strg + Shift + P` druecken
2. `Remote-SSH: Connect to Host` eingeben
3. `Add New SSH Host` waehlen, falls der Raspberry noch nicht eingetragen ist
4. Diesen Befehl eingeben:

```text
ssh pi@192.168.178.75
```

5. Die vorgeschlagene SSH-Config-Datei speichern
6. Danach erneut `Remote-SSH: Connect to Host` auswaehlen
7. Deinen Raspberry anklicken

Jetzt oeffnet VS Code ein neues Fenster, das direkt auf dem Raspberry arbeitet.

## Schritt 6: Projektordner auf dem Raspberry anlegen oder oeffnen

Wenn du noch keinen Ordner hast, oeffne in VS Code das Terminal auf dem Raspberry und lege einen Projektordner an:

```bash
mkdir -p ~/projekte/hausinventar
cd ~/projekte/hausinventar
```

Danach in VS Code:

1. Datei
2. Ordner oeffnen
3. `/home/pi/projekte/hausinventar` auswaehlen

Wenn dein Benutzer nicht `pi` heisst, ist der Pfad eher so:

```text
/home/dein-benutzername/projekte/hausinventar
```

## Schritt 7: Projektdateien auf den Raspberry bringen

Wenn dein Projekt bereits auf dem Windows-Laptop existiert, kannst du es am einfachsten per `scp` auf den Raspberry kopieren.

### Variante A: Neues Projekt direkt auf dem Raspberry beginnen

Wenn du direkt per Remote SSH verbunden bist, kannst du die Dateien einfach in diesem Ordner erstellen. Das ist die einfachste Methode.

### Variante B: Vorhandenen Projektordner kopieren

Oeffne auf dem Laptop PowerShell und fuehre aus:

```powershell
scp -r "C:\Users\michi\OneDrive\Dokumente\Andere Dateien\Technikprojekte\Hausinventar" michi@192.168.178.75:~/projekte/
```

Wenn dein Benutzer auf dem Raspberry nicht `pi` heisst, ersetze `pi` durch deinen echten Benutzernamen.

Wenn der Befehl fertig ist, liegt das Projekt auf dem Raspberry normalerweise hier:

```text
/home/pi/projekte/Hausinventar
```

Danach kannst du dich per SSH verbinden und in den Ordner wechseln:

```bash
ssh pi@192.168.178.75
cd ~/projekte/Hausinventar
```

Falls du den Zielordner vorher anlegen willst, kannst du auf dem Raspberry ausfuehren:

```bash
mkdir -p ~/projekte
```

### Variante C: Spaeter mit Git arbeiten

Wenn du das Projekt kuenftig haeufig zwischen Laptop und Raspberry abgleichen willst, ist Git langfristig sauberer.

Der Grundablauf ist dann:

1. Projekt auf dem Laptop in ein Git-Repository legen
2. Repository zu GitHub, Gitea oder einem anderen Git-Server pushen
3. Repository auf dem Raspberry mit `git clone` holen
4. Spaetere Aenderungen mit `git add`, `git commit`, `git push` und auf dem Raspberry mit `git pull` uebernehmen

#### Git auf dem Laptop vorbereiten

Oeffne im Projektordner auf dem Laptop PowerShell:

```powershell
cd "C:\Users\michi\OneDrive\Dokumente\Andere Dateien\Technikprojekte\Hausinventar"
git init
git add .
git commit -m "Erster Stand Hausinventar"
```

In deinem Projekt gibt es bereits eine `.gitignore`. Dadurch werden unter anderem `.venv`, `instance` und Python-Cache-Dateien nicht mit ins Repository aufgenommen.

#### Remote-Repository anlegen

Lege danach auf GitHub, Gitea oder GitLab ein neues leeres Repository an, zum Beispiel `hausinventar`.

Danach verbindest du dein lokales Projekt mit diesem Remote-Repository:

```powershell
git branch -M main
git remote add origin https://github.com/repos?q=owner%3A%40me
git push -u origin main
```

Beispiel fuer GitHub:

```powershell
git remote add origin https://github.com/DEIN-NAME/hausinventar.git
git push -u origin main
```

#### Projekt auf dem Raspberry holen

Auf dem Raspberry im Terminal:

```bash
mkdir -p ~/projekte
cd ~/projekte
git clone URL-DEINES-REPOSITORYS
cd hausinventar
```

Beispiel:

```bash
git clone https://github.com/DEIN-NAME/hausinventar.git
cd hausinventar
```

Danach kannst du wie gewohnt die virtuelle Umgebung anlegen und die App starten.

#### Spaetere Aenderungen uebertragen

Wenn du spaeter am Laptop weiterarbeitest:

```powershell
git add .
git commit -m "Aenderungen gespeichert"
git push
```

Und auf dem Raspberry holst du die neuesten Aenderungen mit:

```bash
cd ~/projekte/hausinventar
git pull
```

#### Wann Git besser ist als scp

Git ist besser, wenn du dein Projekt regelmaessig weiterentwickelst, Zwischenstaende behalten willst oder spaeter auch von mehreren Geraeten aus arbeiten moechtest.

`scp` ist besser, wenn du nur einmal schnell den aktuellen Stand auf den Raspberry kopieren willst.

## Schritt 8: Python auf dem Raspberry pruefen

Im Remote-Terminal in VS Code auf dem Raspberry:

```bash
python3 --version
```

Wenn eine Python-Version angezeigt wird, ist alles gut.

Beispiel:

```text
Python 3.11.2
```

## Schritt 9: Virtuelle Umgebung anlegen

Im Projektordner auf dem Raspberry:

```bash
python3 -m venv .venv
```

Danach aktivieren:

```bash
source .venv/bin/activate
```

Wenn links im Terminal jetzt `(.venv)` steht, ist die Umgebung aktiv.

## Schritt 10: Abhaengigkeiten installieren

Wenn du im Projektordner schon die Datei requirements.txt hast:

```bash
pip install -r requirements.txt
```

Falls `pip` nicht gefunden wird, versuche:

```bash
python3 -m pip install -r requirements.txt
```

## Schritt 11: Flask-App auf dem Raspberry starten

In deinem Projektordner:

```bash
python3 start_inventory_webserver.py
```

Wichtig ist, dass die App auf `0.0.0.0` lauscht. In deinem Projekt ist das bereits so vorgesehen.

Dann solltest du etwa sehen:

```text
Running on http://127.0.0.1:5000
Running on http://192.168.178.45:5000
```

## Schritt 12: Weboberflaeche vom Laptop aus oeffnen

Jetzt kannst du auf dem Laptop im Browser oeffnen:

```text
http://192.168.178.45:5000
```

Wenn alles funktioniert, siehst du die Weboberflaeche deines Hausinventarsystems.

## Schritt 13: Barcodescanner nutzen

Wenn der Scanner per USB am Raspberry angeschlossen ist, funktioniert er oft wie eine Tastatur.

Das bedeutet:

1. Scanner an Raspberry anschliessen
2. Browser-Seite fuer Scan aufrufen
3. Cursor ins Barcode-Feld setzen
4. Barcode scannen
5. Der Scanner tippt den Code automatisch ein
6. Viele Scanner senden danach automatisch Enter

So kannst du Produkte sehr schnell finden und buchen.

## Empfohlener Arbeitsablauf im Alltag

So solltest du am besten arbeiten:

1. Raspberry einschalten
2. Laptop und Raspberry ins gleiche Netzwerk bringen
3. In VS Code per Remote SSH verbinden
4. Projektordner auf dem Raspberry oeffnen
5. Im Terminal virtuelle Umgebung aktivieren
6. Flask-App starten
7. Im Browser testen

## Sehr hilfreiche Zusatzverbesserungen

### 1. Feste IP-Adresse fuer den Raspberry

Wenn sich die IP staendig aendert, ist das nervig. Stelle im Router am besten eine feste DHCP-Zuweisung ein.

### 2. SSH-Key statt Passwort

Das ist komfortabler und sicherer.

Auf dem Laptop in PowerShell:

```powershell
ssh-keygen
```

Dann den Key auf den Raspberry kopieren:

```powershell
type $env:USERPROFILE\.ssh\id_rsa.pub | ssh pi@192.168.178.45 "mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

Danach solltest du dich meist ohne Passwort verbinden koennen.

### 3. Automatischer Start der App spaeter

Wenn die Anwendung dauerhaft laufen soll, kannst du spaeter einen systemd-Service einrichten. Fuer den Start ist das aber noch nicht noetig.

## Typische Fehler und Loesungen

### Fehler: SSH funktioniert nicht

Pruefe:

- ist SSH auf dem Raspberry aktiviert
- sind Laptop und Raspberry im selben Netzwerk
- stimmt die IP-Adresse
- stimmt der Benutzername

Teste auf dem Raspberry:

```bash
sudo systemctl status ssh
```

### Fehler: VS Code verbindet sich nicht

Pruefe zuerst, ob die normale SSH-Verbindung in PowerShell klappt. Wenn `ssh pi@DEINE-IP` nicht funktioniert, wird VS Code auch nicht funktionieren.

### Fehler: Die Webseite ist im Browser nicht erreichbar

Pruefe:

- laeuft die App wirklich noch
- wurde sie mit `python3 start_inventory_webserver.py` gestartet
- verwendet die App Port 5000
- oeffnest du die richtige IP-Adresse

Teste auf dem Raspberry:

```bash
curl http://127.0.0.1:5000
```

Wenn dort eine Antwort kommt, laeuft die App lokal auf dem Raspberry.

### Fehler: Scanner scannt nicht richtig

Pruefe:

- ist das richtige Feld im Browser aktiv
- arbeitet der Scanner als Tastaturgeraet
- sendet der Scanner nach dem Code ein Enter

## Kurzfassung fuer spaeter

Wenn alles einmal eingerichtet ist, reichen meistens diese Schritte:

1. Raspberry einschalten
2. In VS Code per Remote SSH verbinden
3. Projektordner oeffnen
4. Terminal starten
5. Virtuelle Umgebung aktivieren:

```bash
source .venv/bin/activate
```

6. App starten:

```bash
python3 start_inventory_webserver.py
```

7. Im Browser oeffnen:

```text
http://DEINE-RASPBERRY-IP:5000
```

## Empfehlung fuer dein Projekt

Fuer dein Hausinventarsystem wuerde ich genau so arbeiten:

- Code direkt auf dem Raspberry speichern
- mit VS Code per Remote SSH entwickeln
- Flask und SQLite direkt auf dem Raspberry laufen lassen
- Scanner am Raspberry anschliessen
- Browser vom Laptop oder Handy zur Bedienung nutzen

Das ist einfach, robust und passend fuer einen Raspberry Pi 3.

## Wenn du komplett festhaengst

Dann arbeite diese Minimalliste ab:

1. Raspberry starten
2. SSH aktivieren
3. IP mit `hostname -I` herausfinden
4. Vom Laptop `ssh pi@DEINE-IP` testen
5. In VS Code `Remote-SSH: Connect to Host` benutzen
6. Projektordner auf dem Raspberry oeffnen
7. `python3 -m venv .venv`
8. `source .venv/bin/activate`
9. `pip install -r requirements.txt`
10. `python3 start_inventory_webserver.py`
11. Im Browser `http://DEINE-IP:5000` aufrufen

Wenn du willst, kann ich dir als naechsten Schritt noch eine zweite Datei erstellen mit einer noch einfacheren Checkliste nur zum Abhaken.
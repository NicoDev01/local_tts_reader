# TTS Vorleser – Details

Ausführliche Beschreibung von Bedienung, Technik und Prüfungen. Die Kurzfassung steht in der
[README](../README.md).

Windows-Vorleser für markierten Text, mit Bedienung im Infobereich (System-Tray).
Die Spracherzeugung erfolgt **online über Microsoft**; der ausgewählte Text wird
an den Sprachdienst übertragen. Audioverarbeitung und Wiedergabe erfolgen lokal.

## Bedienung

- **Desktop-Verknüpfung:** Startet ausschließlich im Tray, ohne Terminal und ohne Einstellungsfenster. Ein erneuter Start erzeugt keine zweite Instanz.
- **Tray-Symbol anklicken:** Öffnet die Einstellungen. Rechtsklick öffnet das Menü mit Pause, Stopp, „Weiterlesen“ (an der zuletzt gestoppten Stelle), „Zuletzt Vorgelesenes wiederholen“ und Beenden. Der letzte Text bleibt nur im Arbeitsspeicher und wird nie gespeichert.
- **Fenster schließen:** Blendet die Einstellungen aus; die Tastenkürzel bleiben aktiv.
- **Strg + Alt + V:** Markierten Text übernehmen und vorlesen. Die Tasten danach loslassen. Der Mini-Player erscheint sofort; ohne Markierung meldet er kurz „Kein Text markiert“.
- **Strg + Alt + Leertaste:** Pause / Weiter.
- **Strg + Alt + ← / →:** Satz zurück / vor.
- **Esc:** Vorlesen und ausstehende Spracherzeugung abbrechen.
- Alle Tastenkürzel lassen sich in den Einstellungen ändern: Feld anklicken, neue Kombination drücken (Rücktaste stellt den Standard wieder her). Einzelne Tasten außer Esc und F-Tasten sowie doppelt belegte Kombinationen werden abgelehnt.
- **Beenden im Tray-Menü:** Beendet die Anwendung vollständig.

Windows kann das Tray-Symbol im aufklappbaren Bereich hinter dem Pfeil verstecken.
Es lässt sich bei Bedarf aus diesem Bereich in die sichtbare Taskleiste ziehen.

## Mini-Player

Der Mini-Player erscheint unten rechts und nimmt dem Dokument nie den Fokus. Er zeigt
den Satz, der gerade gesprochen wird: bereits gesprochene Wörter voll, das aktuelle Wort in
Violett, kommende Wörter gedämpft. Dazu Fortschritt und ungefähre Restzeit.

- **Verschieben:** Mini-Player oder eingeklappte Pille mit der Maus ziehen; die Position bleibt gespeichert. Doppelklick setzt ihn in die Ecke zurück.
- **Pause** blendet über 80 ms aus und beim Fortsetzen wieder ein, statt mitten im Wort abzuschneiden.
- **Buch-Symbol:** öffnet die Leseansicht.
- **Spulen:** Über dem Fortschrittsbalken erscheint ein Knopf. Ziehen zeigt Zielsatz, Zeit und Satznummer als Vorschau; beim Loslassen geht es am Anfang dieses Satzes weiter (etwa 1 s). Ein Satzanfang klingt natürlicher als ein Einstieg mitten im Satz.

- **Satz zurück / vor:** Wie bei einem Musikplayer springt „zurück“ zuerst an den Anfang des aktuellen Satzes (nach mehr als 2 s) und erst sonst einen Satz weiter zurück. Ein Sprung braucht etwa 0,6 s.
- **Tempo-Chip:** Klick wechselt 1× → 1,25× → 1,5× → 1,75× → 2×; das Mausrad ändert in 0,05er-Schritten. Bereich **0,70× bis 2,00×**, ohne beabsichtigte Änderung der Tonhöhe.
- **Lautsprecher:** Klick schaltet stumm; das Mausrad ändert die Lautstärke (**0 bis 150 %**, unabhängig von Windows).
- **Minus** klappt ihn zu einer Pille mit Pause-Taste und Satzzähler ein; ein Klick auf die Pille klappt ihn auf. **×** beendet das Vorlesen.
- Die Satzanzeige nutzt die Satzzeitpunkte, die der Sprachdienst mitliefert; die Restzeit ist eine Schätzung (2,5 Wörter/s bei 1×).
- **Tempo ändern während des Vorlesens:** Der laufende Satz wird weder unterbrochen noch gestreckt (Strecken klang verzerrt). Der Mini-Player zeigt sofort den neuen Wert und „ab nächstem Satz“; ab dann kommt frisch im neuen Tempo erzeugte Sprache. Nur im letzten Satz wird das Tempo direkt angepasst.
- Lautstärke wirkt sofort, auch auf bereits geladenes Audio.

## Leseansicht

Ein ruhiges Fenster mit dem ganzen Text (Buch-Symbol im Mini-Player oder Tray-Menü). Gelesene
Sätze sind gedämpft, der aktuelle Satz ist hinterlegt, das aktuelle Wort violett; die Ansicht
scrollt mit. Ein Klick auf einen Satz liest dort weiter, auch nachdem das Vorlesen beendet ist.

## Englische Begriffe

Der kostenlose Microsoft-Dienst nimmt keine SSML-Auszeichnungen an (`<lang>`, `<phoneme>` und
`<sub>` wurden am 26.10.2026 getestet und abgelehnt). Wie englische Begriffe klingen, hängt daher
allein von der Stimme ab. Eine Kontrolle mit Whisper ergab: Gängiges Denglisch wie „Pull Request“,
„Deployment“ oder „ready for review“ wurde bei allen geprüften Stimmen richtig verstanden.
Die Hörproben `tests/artifacts/voices/<Stimme> Denglisch.wav` zeigen den Akzent im Vergleich.

Schwierig sind englische Wörter mit Bindestrich: „Tray-Symbol“ klang wie „Dreh-Symbol“. Mit
Leerzeichen („Tray Symbol“) liest die Stimme den englischen Teil englisch. Deshalb ersetzt
`speakable()` in `text_cleaner.py` den Bindestrich neben bekannten englischen Wörtern durch ein
Leerzeichen, nur im Text für die Stimme; die Anzeige bleibt unverändert. Whisper-Kontrolle vom
27.10.2026: vorher 4 von 12 Testsätzen falsch verstanden, danach keiner. Fehlt ein Wort, lässt es
sich in `ENGLISH_PARTS` ergänzen.

Einzelne Wörter sprechen die deutschen Stimmen trotzdem deutsch aus. Geprüft wurde jedes Wort
allein, gehört von Whisper im Englisch-Modus (das erkennt einen deutschen Akzent, anders als im
Satzzusammenhang): Von 31 gängigen Begriffen klangen 5 deutsch. Für vier gibt es eine Schreibweise,
die alle drei geprüften Stimmen englisch aussprechen; sie steht in `RESPELLINGS` und erreicht nur
die Stimme: Clipboard → „Clip Board“, Login → „Logginn“, Shortcut → „Shortkatt“, Cache → „Kässch“.
„Tray“ klang bei den deutschen Stimmen in jeder Schreibweise wie „drei“; nur Florian spricht es
englisch.

Entwicklerbegriffe (geprüft 2026-10-27, 114 Wörter wie Git, Commit, Pull Request, Deployment, Docker,
JavaScript): 22 klangen falsch. Neu in `RESPELLINGS` u. a. README → „Riedmi“, ElevenLabs → „Ilewen Läbs“,
Backend → „Bäck End“, Debugging → „Dibagging“, JSON → „Jason“, macOS → „Mäk OS“, OpenAI → „Open Eh Ei“,
Node.js → „Node Dschäi Es“ (Frameworks wie Node.js und Vue.js werden nicht mehr als Dateiendung
abgeschnitten). Ohne funktionierende Schreibweise bleiben Merge, Bug, Bugfix, Thread, Async und Await.

Business- und Alltagsbegriffe (geprüft 2026-11-18 mit `tests/english_terms_check.py`, 128 Wörter):
97 klangen schon englisch. Neu u. a. Deadline → „Dedd Lain“, Manager → „Männidschr“, Agent →
„Ejtschent“, Deployment → „Diploiment“, Developer → „Diwellopper“, Plugin → „Plagin“, Chatbot →
„Tschett Bott“, Use Case → „Jus Käis“. Ohne Lösung: Sales, Prompts, Tracking. „Code“ bleibt beim
üblichen deutschen „Kohd“, „Budget“ beim französisch-deutschen „Büdschee“.

## Einstellungen

Alles auf einer Seite: Stimme mit Hörprobe, Tempo, Lautstärke, Klang, ein Feld für eigenen
Text (Strg + Enter liest vor), Mini-Player, Autostart, Darstellung (System, Hell, Dunkel) und
die Tastenkürzel. Stimme gilt ab dem nächsten Vorlesen, Klang für neu vorbereitete Abschnitte.

Zusammenhängende Sätze werden gemeinsam erzeugt (höchstens 80 Wörter pro Anfrage).
Doppelpunkte, Klammern und Zitate bleiben im Satzkontext. Absatzgrenzen bleiben
erhalten. Nur an Anfragegrenzen ergänzt der Player eine kurze Pause.
Das Standardprofil „Warm“ verwendet dezente Klangfilter ohne Kompressor und Limiter.
Jede Stimme wird mit einem festen, gemessenen Ausgleich auf Killians Pegel gebracht (bis 3,1 dB), damit die
Lautstärke-Einstellung zu jeder Stimme passt; innerhalb einer Stimme schwankte der Pegel nur um höchstens 1,4 dB.
Kopierte PDF-Zeilen werden verbunden; Listen, Überschriften und Absätze behalten ihre
Grenzen, auch wenn sie nur durch das Layout erkennbar waren: Browser und Word kopieren eine
Überschrift als kurze Zeile ohne Punkt. Eine Zeile gilt als Umbruch, wenn sie etwa so breit ist
wie die breiteste oder auf ein Wort wie „und“ endet; kürzere Zeilen enden mit einer Pause,
Überschriften mit einer Absatzpause. Tabellen (Tabs aus Browser und Word, Markdown mit `|`)
werden zeilenweise gelesen; mit Kopfzeile steht vor jedem Wert sein Spaltenname mit Doppelpunkt:
„Position: Miete. Betrag: 800 Euro. Anteil: 40 Prozent.“
HTML-Zeichenreferenzen werden dekodiert. Die Textaufbereitung
ist regelbasiert und kann ungewöhnliche Formatierungen weiterhin falsch interpretieren.

## Installation und Reparatur

Voraussetzungen: Windows 10/11, .NET Framework 4.x, PowerShell und `uv`.

```powershell
.\setup.ps1
```

Das Skript erstellt bei Bedarf eine Python-3.12-Umgebung, synchronisiert die
Abhängigkeiten aus `requirements.lock`, kompiliert den Windows-Launcher und erstellt
die Desktop-Verknüpfung. Den bestehenden Vorleser vor einer Reparatur im Tray beenden.

Nur Launcher und Verknüpfung erneuern:

```powershell
.\setup.ps1 -SkipDependencies
```

Der Launcher nutzt `CreateNoWindow` und startet `.venv\Scripts\python.exe` ohne Konsole.
Python-Binärdateien werden nicht gepatcht oder aus anderen Umgebungen kopiert.
Desktop und Autostart verwenden denselben Launcher. `--show` öffnet die Einstellungen
bei Bedarf auch aus einem Skript. Die früheren Batch-/VBScript-Starter wurden entfernt.

## Zuverlässigkeit

- Windows-Mutex verhindert mehrere Instanzen; ein Windows-Event dient zum expliziten Öffnen der Einstellungen. Kein TCP-Port.
- Jeder Vorleseauftrag hat ein eigenes Abbruchsignal. Überholte Aufträge und Netzwerkanfragen werden abgebrochen.
- Das Audio wird gestreamt: Die Wiedergabe beginnt mit den ersten etwa 0,3 s eines Abschnitts, während der Sprachdienst noch spricht. Die Verbindung wird schon beim Drücken des Tastenkürzels aufgebaut. Gemessen (26.10.2026): erstes Audio nach etwa 0,5 s statt 1,2 s bei schnellem Dienst; bei langsamem Dienst war der Unterschied größer.
- Ein Abbruch vor dem ersten Audio eines Abschnitts wird bis zu dreimal wiederholt; ein Abbruch mitten im Abschnitt wird gemeldet statt Audio doppelt abzuspielen.
- Höchstens vier Audiostücke warten zusätzlich zum aktuellen. Eine zeitliche Vorabrufgrenze (auf 2× Tempo bezogen) vermeidet unnötig große Puffer.
- Ein Audiostream bleibt für den gesamten Auftrag geöffnet. Aufbereitung erfolgt im Vorabruf; Pufferunterläufe des Audiotreibers werden protokolliert. Bei längeren Netzwerkausfällen sind weiterhin Unterbrechungen möglich.
- Bei Nachladepausen wird „Lädt nach …“ angezeigt und der Treiber weiter mit Stille versorgt. „Fertig“ erscheint erst, wenn das letzte Audio ausgegeben ist.
- Oberhalb von 90 % Signalamplitude begrenzt eine sanfte Kennlinie die Spitzen. Das vermeidet hartes digitales Abschneiden bei hoher Lautstärke; geringere Pegel bleiben unverändert.
- Qt-Oberflächenzugriffe erfolgen ausschließlich auf dem Hauptthread; Tastenkürzel, Netzwerk und Audio melden sich über Qt-Signale.
- Die Zwischenablage wird vor dem Kopieren nicht geleert; alter Inhalt wird niemals als Ersatztext vorgelesen.
- Unterstützte Zwischenablageformate werden unabhängig gesichert und nur wiederhergestellt, wenn keine neuere Kopie vorliegt. Die Prüfung erfolgt unter der Windows-Zwischenablagesperre.
- Nicht sicher kopierbare Spezialformate oder mehr als 64 MiB Clipboard-Daten führen zum Abbruch vor dem Kopieren. So werden vorhandene Daten nicht absichtlich verworfen.
- Konfiguration wird validiert und atomar gespeichert. Frühere `rate`-Werte werden zu `speed` migriert.
- Fehler stehen in `reader.log` (rotierend, maximal drei Dateien à etwa 1 MB). Sprachdienst-/Audiofehler werden zusätzlich sichtbar gemeldet.

Es gibt keine Garantie auf eine bestimmte Startlatenz, Speichernutzung oder subjektive Audioqualität.
Der HD-Anfragepfad verwendet interne Funktionen der festgehaltenen `edge-tts`-Version;
bei einer Protokolländerung kann eine Aktualisierung nötig werden. Ein Standardformat-Fallback ist vorhanden.

## Prüfungen

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
uv pip check --python .venv\Scripts\python.exe
```

Die folgenden Integrationstests öffnen kurz eigene Testfenster. Der UI-Test läuft auch neben
einem laufenden Vorleser (ohne Tastenkürzel) und speichert Screenshots in hellem und dunklem
Design unter `tests/artifacts/`. Für den Clipboard-Test vorher den Vorleser beenden:

```powershell
.venv\Scripts\python.exe -B tests\ui_smoke.py
.venv\Scripts\python.exe -B tests\clipboard_smoke.py
```

Der Clipboard-Test verwendet einen kontrollierten Kopiervorgang im eigenen Textfeld.
Er prüft die echte Windows-Zwischenablage, jedoch nicht die Tastenkürzel-Integration
in Word, Browsern oder PDF-Programmen. Diese sollte dort zusätzlich ausprobiert werden.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `launcher.cs`, `setup.ps1` | Fensterloser Windows-Start und reproduzierbare Einrichtung |
| `main_app.py`, `windows_runtime.py` | Programmeinstieg, Instanzsicherung, Fokus- und Titelleisten-Details |
| `reader_ui.py` | Tray, Tastenkürzel, Ablaufsteuerung zwischen Oberfläche und Wiedergabe |
| `mini_player.py`, `settings_window.py` | Mini-Player mit Satznavigation; Einstellungen auf einer Seite (PySide6) |
| `ui_theme.py`, `ui_widgets.py` | Farben hell/dunkel, Stylesheet, Lucide-Symbole (ISC), Schalter und Bedienelemente |
| `reading_view.py` | Leseansicht mit Satz- und Wortmarkierung, Klick-Navigation |
| `assets/`, `tools/make_icon.py` | App-Icon; das Skript erzeugt `assets/vorleser.ico` aus der Zeichnung in `ui_theme.py` |
| `playback.py` | Vorleseaufträge, begrenzter Puffer, Abbruch und Netzwerk-Loop |
| `audio_player.py` | Klangverarbeitung, Live-Tempo, Live-Lautstärke und Ausgabe |
| `high_fidelity_tts.py` | Online-Spracherzeugung als Stream, Vorab-Verbindung und Fallback |
| `clipboard_capture.py` | Frische Textmarkierung und sichere Wiederherstellung |
| `text_cleaner.py`, `settings.py` | Textnormalisierung und Einstellungen |

Stimmenvergleich: derselbe Text in allen Stimmen, mit Tempo, Lautheitsausgleich und Klangprofil wie in der App
(Ausgabe in `tests/artifacts/voices/`):

```powershell
.venv\Scripts\python.exe -B tests\voice_samples.py
```

Liegt bereits ein Whisper-Modell vor (zum Beispiel über OpenWhispr), kann dessen Server die Prüfung ohne Download übernehmen.

Aussprache-Prüfung: Jeder knifflige Fall wird roh und aufbereitet gesprochen und von Whisper zurückgelesen
(Bericht `tests/artifacts/pronunciation/report.md`). Whisper läuft in einer Wegwerf-Umgebung; das Modell
(etwa 1,6 GB) liegt in `tests/.whisper_cache/` und kann jederzeit gelöscht werden:

```powershell
.venv\Scripts\python.exe -B tests\pronunciation_check.py synthesize
uv run --isolated --no-project --python 3.12 --with faster-whisper==1.2.1 --with soundfile --with soxr python -I tests\pronunciation_check.py transcribe
```

Gezielte Online-Audioprüfung (synthetischer Testtext; stumme Ausgabe über den echten Audiotreiber):

```powershell
.venv\Scripts\python.exe -B tests\audio_quality_check.py
```

Hörproben und Messwerte werden unter `tests/artifacts/smooth/` gespeichert.

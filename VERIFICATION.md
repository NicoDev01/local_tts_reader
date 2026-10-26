# Stabilität, Pausenhierarchie & Stimmpräsenz – 17.09.2026

## Änderungen

- **TCP-Keepalive & Session-Recycling:** `HighFidelityTTSClient` nutzt nun `aiohttp.TCPConnector(keepalive_timeout=15.0)`. Microsofts stilles Trennen von Idle-Sockets nach 30 Sekunden führt bei längeren Vorlesepausen nicht mehr zu Socket-Timeouts. Bei Fehlern wird die Session sauber zurückgesetzt.
- **3-stufige Retry-Schleife:** In `playback.py` fängt ein automatischer Retry mit exponentiellem Backoff (`0.5s`, `1.0s`) transiente Netzwerk- und Latenzspitzen vor dem Abbruch ab. Timeouts auf 35s/40s angehoben.
- **Doppelpunkt-Prosodie & Ankündigungspausen:**
  - `text_cleaner.py`: In nummerierten Aufzählungen (`1. Schritt: ...`, `2. Quartal: ...`) bleibt der Doppelpunkt erhalten statt durch ein Komma ersetzt zu werden.
  - `high_fidelity_tts.py`: Doppelpunkte im Fließtext erhalten vor der Synthese einen prosodischen Zeilenumbruch, wodurch Edge TTS eine natürliche, rhetorische Ankündigungskadenz erzeugt.
  - `audio_player.py`: `calculate_adaptive_pause` implementiert eine strikte Pausenhierarchie: Absatz (`0.52s`) > Doppelpunkt-Absatz (`0.42s`) > Doppelpunkt (`0.35s`) > Satzende (`0.20s`) > Semikolon/Klammer (`0.18s`) > Komma (`0.10s`) > Wortgrenze (`0.08s`).
- **Studio-Warmth-Klangprofil:** Ein gezielter Vocal-Presence-Filter (+1.4 dB bei 3200 Hz) und Anhebung des HighShelf-Filters von 7500 Hz (-1.5 dB) auf 8500 Hz (-0.8 dB) beseitigen den dumpfen Schleier und sorgen für klare Sprachverständlichkeit.

## Nachweise

- **47 automatisierte Tests bestanden:** Alle 40 bisherigen Tests sowie 7 neue Regressionstests in `tests/test_audit_fixes.py` (TCP-Keepalive, Session-Cleanup, Retry bei Timeout, Doppelpunkt-Erhaltung, Pausenhierarchie, EQ-Präsenz).
- **Echter Hardware-Audiotest:** `tests/audio_quality_check.py` erfolgreich auf `Speaker (Realtek(R) Audio)` mit 1491 Buffer-Writes, 0 Buffer-Underflows und fehlerfreier Online-Synthese über alle Geschwindigkeiten (0.7x bis 2.0x).
- **UI- & Clipboard-Smoke-Tests:** Unverändert fehlerfrei.

---

# Verbesserte Vorleseerfahrung – 14.09.2026

## Änderungen

- Adaptive Startreserve von 2,5 bis 12 Sekunden anhand gemessener Ladezeit, gerechnet bei 2×. Lange erste Abschnitte starten ohne Warten auf den zweiten Abruf. Maximal vier gepufferte Abschnitte und zusätzliche zeitliche Begrenzung des Vorabrufs.
- „Lädt nach …“ bei leerem Puffer; fortlaufende Stille erhält den Audiostream. „Fertig“ folgt erst nach dem Leerlaufen des Ausgabepuffers.
- Live-Tempo: 80 ms Sammlung schneller Reglerbewegungen, Umschaltung bevorzugt in einer leisen Passage, maximal 350 ms Wartezeit nach abgeschlossener Berechnung, 10 ms Überblendung. Währenddessen läuft das bisherige Tempo weiter. Bei der Vorbereitung wird ein zwischenzeitlich geändertes Tempo bereits berücksichtigt.
- Das bewährte Standardklangprofil bleibt erhalten. Weiche Spitzenbegrenzung ersetzt hartes Clipping bei hohen Pegeln. Ungültige Audio-/Reglerwerte werden abgefangen; Effektverarbeitung überholter und neuer Aufträge ist gegeneinander gesperrt.
- PDF-Zeilenumbrüche erzeugen keine künstlichen Satzpunkte mehr. Explizite Listen/Überschriften bleiben getrennt. HTML-Zeichenreferenzen und Zahlenvergleiche werden verständlich gesprochen, Satzpunkte nach Einheiten bleiben erhalten. Ordinaldaten und Initialen werden vor Satztrennung geschützt.
- Mini-Player mit Status, Abschnittsfortschritt und Tooltips ohne Fokusübernahme. Deaktivierte Pause-/Stopp-Tasten im Leerlauf, konsistente Pausen-/Nachladeanzeigen und Tray-Status. Rückstellung bei 1,05× korrigiert; Stummschaltung behält den vorherigen Pegel.
- Helle/dunkle/System-Darstellung wählbar; Strg + Enter im Texteingabefeld. Weniger redundante Regler-/Icon-Aktualisierungen. Keine neuen Abhängigkeiten.

## Nachweise

- **40 automatisierte Tests bestanden.** Zusätzlich zu den bisherigen Tests: adaptive Startfreigabe, begrenzter Vorabruf kurzer Abschnitte, Nachladen ohne Statusflut, Fertigmeldung nach Audioende, weiche Pegelgrenze, Tempowechsel an Sprechpausen, vorbereitete Tempokorrektur und schwierige Textformen.
- Erweiterter Windows-UI-Test bestanden: Tray-Start, inaktive Tasten, synchronisierte Regler, 1,05×-Rückstellung, Stummschaltung/Wiederherstellung, Fortschritt, Pause/Nachladen/Weiter, Ein-/Ausklappen, Tooltips und Darstellungswechsel. Vorschauen des Mini-Players, der Einstellungen und des Tooltips visuell geprüft.
- Online-Test mit synthetischem deutschem Text bei 0,7× bis 2× erfolgreich. Erneuter stummer Test am Bluetooth-Ausgabegerät: drei Abschnitte, 1401 Schreibzugriffe, mehrere Tempoänderungen, **0 Pufferunterläufe**. Messwerte in `tests/artifacts/smooth/measurements.json`.
- Stand vor dieser Runde: die gesicherten Dateien in `tests/artifacts/before_experience/`.

## Einordnung

Der Benutzer hat die Hörqualität der vorherigen Klangüberarbeitung als deutlich besser bestätigt. Die aktuelle Runde wurde technisch und visuell geprüft, nicht subjektiv abgehört. Der Treibertest gibt Stille aus und bewertet keine akustischen Bluetooth-Artefakte. Lange Netzwerkausfälle oder dauerhaft zu langsame Synthese können weiterhin hörbare Nachladepausen verursachen. Der Fortschrittsbalken zählt Abschnitte, keine sekundengenaue Hörposition. Regelbasierte Textaufbereitung bleibt bei ungewöhnlichen Schreibweisen fehlbar.

---

# Audioüberarbeitung – 14.09.2026

- Satzkontext, Klammern und Zitate bleiben zusammen; bis zu 80 Wörter je Anfrage, Absätze bleiben getrennt.
- Native Sprechgeschwindigkeit statt dauernder lokaler Zeitdehnung. Neue Anfragen übernehmen den Reglerwert. Bereits gepuffertes Audio reagiert asynchron mit 10 ms Überblendung. Während der Berechnung läuft das bisherige Tempo weiter.
- Klangaufbereitung im Vorabruf, zwei Abschnitte Startreserve, ein Audiostream je Auftrag.
- Standardprofil „Warm“ mit dezenter Filterung ohne Kompressor/Limiter. Es war kein expliziter Hall aktiv; subjektiver Nachhall wurde nicht gemessen.
- Schonenderes Trimmen mit 75 ms Schutzrand erhält leise Anlaute/Ausklänge.
- Bluetooth-Treiber meldete bereits beim ersten Schreibzugriff einen Unterlauf, auch bei reinem Stille-Test ohne TTS/DSP. Deshalb 100 ms Stille vor der Sprache; Startmeldungen und Unterläufe während der Sprache werden getrennt erfasst.

## Neue Nachweise

- 25 Tests bestanden: Satzkontext, Absätze, Wortgrenzen, leise Konsonanten, native Tempi ohne unnötiges DSP, Stream-Wiederverwendung, Vorpufferung, Netzwerkfehler, Abbruch, Pause/Weiter und schnelle Tempoänderungen.
- 27 Pakete ohne Abhängigkeitskonflikte.
- Erneuter Test am Windows-Ausgabegerät „Kopfhörer (CX Plus True Wireless)“: drei Abschnitte, 1398 Schreibzugriffe, Live-Wechsel zwischen 0,7× und 2×, null Unterläufe während der Ausgabe, null Startunterläufe in diesem Durchlauf. Vorheriger Fehler und isolierte Startdiagnose wurden nicht als bestandene Tests gewertet.
- Online-Hörproben bei 0,7× / 1× / 1,25× / 1,5× / 2×: 25,927 / 18,184 / 14,570 / 12,167 / 9,166 Sekunden. Spitzenpegel unter 0,827, kein Clipping in diesen gespeicherten Proben.
- Reproduzierbarer Online-/Gerätetest: `tests/audio_quality_check.py`. Hörproben und Messwerte: `tests/artifacts/smooth/`.
- Vorheriger Quellstand: `tests/artifacts/before_smooth/`.

## Grenzen der Audioprüfung

Die Proben wurden technisch geprüft, aber nicht subjektiv abgehört. Die Geräteprüfung gibt absichtlich Stille aus und prüft Treiber/Pufferverhalten, nicht die akustische Bluetooth-Übertragung. Lange Netzwerkausfälle, andere Geräte und hohe Systemlast können weiterhin Unterbrechungen verursachen. Lokale Live-Tempokorrektur kann Artefakte erzeugen; bei konstantem Tempo entfällt sie vollständig. Die Vorpufferung verlängert die Startzeit.

API-Abgleich: [Pedalboard 0.9.25](https://spotify.github.io/pedalboard/reference/pedalboard.html#pedalboard.time_stretch) und [native Geschwindigkeit in edge-tts](https://github.com/rany2/edge-tts/discussions/91), zusätzlich lokal installierte Signaturen geprüft.

---

# Frühere Abschlussprüfung – 12.09.2026

## Umgesetzt

- Desktop und vorhandener Windows-Autostart verwenden denselben neu kompilierten GUI-Launcher.
- Kein PE-Patch; die bestehende Python-Installation bleibt binär unverändert.
- Standardstart im Tray. Einstellungen nur auf ausdrücklichen Aufruf.
- Minimaler Mini-Player mit zwei Reglern und Symboltasten; eingeklappt bleibt nur
  eine 40-Pixel-Schaltfläche am rechten unteren Bildschirmrand.
- Asynchrone Tempoberechnung bei laufender Wiedergabe, ohne beabsichtigte Tonhöhenänderung.
- Kürzere, differenzierte Pausen an Doppelpunkten, Einschüben, Zitaten und Satzgrenzen.
- Getrennte Abbruchsignale, begrenzter Vorabruf, Abbruch laufender Synthesen, UI-Ereigniswarteschlange.
- Frische Textauswahl statt altem Clipboard-Fallback; unabhängige Formatkopien und atomar geprüfte Wiederherstellung.
- Korrektur gruppierter Dezimalzahlen und zuverlässige Wortobergrenze.
- Validierte, atomare Konfiguration; rotierende Fehlerprotokolle; festgehaltene Abhängigkeiten.
- Unbenötigte Batch-/VBScript-Starter entfernt; Komponenten und Dokumentation vereinfacht.

## Nachweise

| Prüfung | Ergebnis |
|---|---|
| 15 Regressionstests | Bestanden |
| Abhängigkeiten (`uv pip check`) | 27 Pakete, keine Konflikte |
| Verdeckter UI-Start und sichtbares Tray-Symbol | Bestanden |
| Einstellungen und Mini-Player | Automatisch bedient, Screenshots visuell geprüft |
| Synchronisierte Regler und Mini-Player-Ausblenden | Bestanden |
| Echte Windows-Zwischenablage mit kontrolliertem Kopieren im eigenen Textfeld | Auswahl und Wiederherstellung bestanden |
| Online-Sprachdienst | Audio erfolgreich erzeugt |
| Windows-Audiotreiber | Ausgabe mit stummem Test erfolgreich |
| Tonhöhe bei 1,5× Tempo | 220-Hz-Testsignal innerhalb der Testtoleranz erhalten |
| Desktop-Verknüpfung, einschließlich zweier weiterer Starts | Ein Anwendungsprozess; zusätzlicher Python-Umgebungslauncher ist normal |
| Laufzeitprotokoll beim Desktop-Start | `Konsole=False; Fenster=withdrawn` |

Die neue Anwendung läuft nach der Prüfung im Infobereich.

## Grenzen der Prüfung

- Globale Auswahlübernahme in Word, Browsern und PDF-Programmen wurde nicht automatisiert durchgespielt. Windows verweigerte dem Testfenster die Vordergrundübernahme; der Test verwendet daher gezielt dessen eigenen Kopierbefehl.
- Die Hörqualität und Betonung wurden nicht subjektiv bewertet. Eine erzeugte Hörprobe liegt unter `tests/artifacts/hoerprobe.wav`.
- Verhalten bei mehreren Monitoren, anderen DPI-Werten und verschiedenen Audiogeräten muss auf den jeweiligen Geräten geprüft werden.
- Bestimmte alte/spezielle Zwischenablageformate werden vorsorglich nicht kopiert; der Vorgang bricht dann vor einer Änderung ab.

Vor den Änderungen wurden die ursprünglichen Projektdateien in
`../local_tts_reader_backup_20260912_001504` gesichert. Die virtuelle Umgebung ist
über `requirements.lock` reproduzierbar; das Backup enthält die alten Projektdateien,
nicht eine vollständige Kopie der alten Python-Umgebung.

"""German speech normalization and context-preserving, bounded request splitting.

Rules preserve paragraph structure while joining copied line wraps.
They are deterministic substitutions, not semantic text interpretation.
"""

import re
from html import unescape
from typing import List, Tuple

# Comprehensive Emoji & Unicode symbol pattern
EMOJI_PATTERN = re.compile(
    r'[\U00010000-\U0010ffff]'   # SMP emojis
    r'|[\u2600-\u27BF]'           # Misc symbols & dingbats (e.g. 🛠, ✂, ✈, ✉, ✌, ✨, ❌, ➔)
    r'|[\u2300-\u23FF]'           # Misc technical (e.g. ⌚, ⌛, ⏩, ⏪, ⏹)
    r'|[\u2B50-\u2B55]'           # Stars and circles
    r'|[\u200D\uFE0E\uFE0F]'      # Zero-width joiner, variation selectors
    r'|[•▪▫►▶✓✔★☆●○👉🛠🖥🎛🎙🔊⏹]'  # Common explicit symbols
)

# Comprehensive expansions of German abbreviations (everyday, legal, academic, administrative)
ABBREVIATION_EXPANSIONS = [
    # Multi-word & everyday
    (r'\bz\.\s*b\.(?=\s|$)', 'zum Beispiel'),
    (r'\bz\.\s*b(?=\s|$)', 'zum Beispiel'),
    (r'\bd\.\s*h\.(?=\s|$)', 'das heißt'),
    (r'\bd\.\s*h(?=\s|$)', 'das heißt'),
    (r'\bu\.\s*a\.(?=\s|$)', 'unter anderem'),
    (r'\bu\.\s*a(?=\s|$)', 'unter anderem'),
    (r'\bu\.\s*s\.\s*w\.(?=\s|$)', 'und so weiter'),
    (r'\busw\.(?=\s|$)', 'und so weiter'),
    (r'\busw\b(?=\s|$)', 'und so weiter'),
    (r'\bbzw\.(?=\s|$)', 'beziehungsweise'),
    (r'\bbzw\b(?=\s|$)', 'beziehungsweise'),
    (r'\be\.\s*v\.(?=\s|$)', 'eingetragener Verein'),
    (r'\bca\.(?=\s|$)', 'circa'),
    (r'\bca\b(?=\s+\d)', 'circa'),
    (r'\binkl\.(?=\s|$)', 'inklusive'),
    (r'\binkl\b(?=\s|$)', 'inklusive'),
    (r'\bexkl\.(?=\s|$)', 'exklusive'),
    (r'\bexkl\b(?=\s|$)', 'exklusive'),
    (r'\bevtl\.(?=\s|$)', 'eventuell'),
    (r'\bggf\.(?=\s|$)', 'gegebenenfalls'),
    (r'\bbspw\.(?=\s|$)', 'beispielsweise'),
    (r'\bbsp\.(?=\s|$)', 'Beispiel'),
    (r'\bsog\.(?=\s|$)', 'sogenannte'),
    (r'\bsog\.n\.(?=\s|$)', 'sogenannten'),
    (r'\bbzgl\.(?=\s|$)', 'bezüglich'),
    (r'\bm\.e\.(?=\s|$)', 'meines Erachtens'),
    (r'\bo\.g\.(?=\s|$)', 'oben genannt'),
    (r'\bu\.ä\.(?=\s|$)', 'und ähnliches'),
    (r'\bu\.a\.m\.(?=\s|$)', 'und andere mehr'),
    (r'\bv\.a\.(?=\s|$)', 'vor allem'),
    (r'\bvgl\.(?=\s|$)', 'vergleiche'),
    (r'\bz\.t\.(?=\s|$)', 'zum Teil'),
    (r'\bz\.zt\.(?=\s|$)', 'zur Zeit'),
    (r'\bz\.z\.(?=\s|$)', 'zur Zeit'),
    (r'\betc\.\s*pp\.(?=\s|$)', 'et cetera'),
    (r'\betc\.(?=\s|$)', 'et cetera'),
    (r'\bgem\.(?=\s|$)', 'gemäß'),
    (r'\blt\.(?=\s|$)', 'laut'),
    (r'\bff\.(?=\s|$)', 'fortfolgende'),
    (r'\bvs\.(?=\s|$)', 'versus'),
    (r'\bi\.d\.r\.(?=\s|$)', 'in der Regel'),
    (r'\bu\.u\.(?=\s|$)', 'unter Umständen'),
    (r'\bz\.h\.(?=\s|$)', 'zu Händen'),
    (r'\bz\.hd\.(?=\s|$)', 'zu Händen'),
    (r'\bm\.w\.n\.(?=\s|$)', 'mit weiteren Nachweisen'),
    (r'\ba\.a\.o\.(?=\s|$)', 'am angegebenen Ort'),
    (r'\bi\.v\.m\.(?=\s|$)', 'in Verbindung mit'),
    (r'\bi\.s\.v\.(?=\s|$)', 'im Sinne von'),
    (r'\bi\.s\.d\.(?=\s|$)', 'im Sinne des'),
    (r'\bi\.a\.(?=\s|$)', 'im Auftrag'),
    (r'\bi\.v\.(?=\s|$)', 'in Vertretung'),
    (r'\bdgl\.(?=\s|$)', 'dergleichen'),
    (r'\bo\.ä\.(?=\s|$)', 'oder ähnliches'),
    (r'\babb\.(?=\s|$)', 'Abbildung'),
    (r'\btab\.(?=\s*\d)', 'Tabelle'),  # only "Tab. 3"; "Browser-Tab." is the English word
    (r'\bkap\.(?=\s|$)', 'Kapitel'),
    (r'\bbd\.(?=\s|$)', 'Band'),
    (r'\bbde\.(?=\s|$)', 'Bände'),
    (r'\bpos\.(?=\s|$)', 'Position'),
    (r'\bjh\.(?=\s|$)', 'Jahrhundert'),
    (r'\bjhr\.(?=\s|$)', 'Jahrhundert'),
    (r'\bv\.\s*chr\.(?=\s|$)', 'vor Christus'),
    (r'\bn\.\s*chr\.(?=\s|$)', 'nach Christus'),
    (r'\bmax\.(?=\s|$)', 'maximal'),
    (r'\bmind\.(?=\s|$)', 'mindestens'),
    (r'\bmin\.(?=\s*(?:\d|$|und|oder|bis))', 'mindestens'),
    (r'\babzgl\.(?=\s|$)', 'abzüglich'),
    (r'\bzzgl\.(?=\s|$)', 'zuzüglich'),
    (r'\bmwst\.(?=\s|$)', 'Mehrwertsteuer'),
    (r'\bust\.(?=\s|$)', 'Umsatzsteuer'),
    (r'\btel\.(?=\s|$)', 'Telefon'),
    (r'\bgeb\.(?=\s|$)', 'geboren'),
    (r'\bgest\.(?=\s|$)', 'gestorben'),
    (r'\bhrsg\.(?=\s|$)', 'Herausgeber'),
    (r'\bred\.(?=\s|$)', 'Redaktion'),

    # Titles & Forms of Address
    (r'\bdr\.(?=\s|$)', 'Doktor'),
    (r'\bprof\.(?=\s|$)', 'Professor'),
    (r'\bdipl\.\s*ing\.(?=\s|$)', 'Diplom-Ingenieur'),
    (r'\bdipl\.(?=\s|$)', 'Diplom'),
    (r'\bing\.(?=\s|$)', 'Ingenieur'),
    (r'\bmr\.(?=\s|$)', 'Mister'),
    (r'\bms\.(?=\s|$)', 'Misses'),
    (r'\bmrs\.(?=\s|$)', 'Misses'),
    (r'\bst\.\s+(?=[A-ZÄÖÜ])', 'Sankt '),

    # Administrative & Units
    (r'\bnr\.(?=\s|$)', 'Nummer'),
    (r'\babs\.(?=\s|$)', 'Absatz'),
    (r'\bart\.(?=\s|$)', 'Artikel'),
    (r'\b(\w{2,})str\.(?=\s|$)', r'\1straße'),
    (r'\bstr\.(?=\s|$)', 'Straße'),
    (r'\bstd\.(?=\s|$)', 'Stunden'),
    (r'\bsek\.(?=\s|$)', 'Sekunden'),
    (r'\bmio\.(?=\s|$)', 'Millionen'),
    (r'\bmio\b(?=\s|$)', 'Millionen'),
    (r'\bmrd\.(?=\s|$)', 'Milliarden'),
    (r'\bmrd\b(?=\s|$)', 'Milliarden'),
]

# Tech acronyms: spaced out so TTS spells them letter-by-letter naturally
ACRONYMS = [
    (r'\bAI\b', 'A I'),
    (r'\bKI\b', 'K I'),
    (r'\bAGI\b', 'A G I'),
    (r'\bAPI\b', 'A P I'),
    (r'\bUI\b', 'U I'),
    (r'\bGUI\b', 'G U I'),
    (r'\bCLI\b', 'C L I'),
    (r'\bPDF\b', 'P D F'),
    (r'\bURL\b', 'U R L'),
    (r'\bFAQ\b', 'F A Q'),
    (r'\bIT\b', 'I T'),
    (r'\bCPU\b', 'C P U'),
    (r'\bGPU\b', 'G P U'),
    (r'\bRAM\b', 'R A M'),
    (r'\bVRAM\b', 'V R A M'),
    (r'\bHTML\b', 'H T M L'),
    (r'\bCSS\b', 'C S S'),
    (r'\bSQL\b', 'S Q L'),
    (r'\bXML\b', 'X M L'),
    (r'\bCSV\b', 'C S V'),
    (r'\bUSB\b', 'U S B'),
    (r'\bWLAN\b', 'W LAN'),
    (r'\bLAN\b', 'L A N'),
    (r'\bSSD\b', 'S S D'),
    (r'\bHDD\b', 'H D D'),
    (r'\bTTS\b', 'T T S'),
    (r'\bSDK\b', 'S D K'),
    (r'\bIDE\b', 'I D E'),
    (r'\bDSP\b', 'D S P'),
    (r'\bEQ\b', 'E Q'),
    (r'\bIPC\b', 'I P C'),
    (r'\bPID\b', 'P I D'),
    (r'\bHUD\b', 'H U D'),
    (r'\bIP\b', 'I P'),
    (r'\bDNS\b', 'D N S'),
    (r'\bTCP\b', 'T C P'),
    (r'\bUDP\b', 'U D P'),
    (r'\bHTTP\b', 'H T T P'),
    (r'\bHTTPS\b', 'H T T P S'),
    (r'\bSSH\b', 'S S H'),
    (r'\bSSL\b', 'S S L'),
    (r'\bTLS\b', 'T L S'),
    (r'\bVPN\b', 'V P N'),
    (r'\bLLM\b', 'L L M'),
    (r'\bNLP\b', 'N L P'),
    (r'\bML\b', 'M L'),
    (r'\bDL\b', 'D L'),
    (r'\bIoT\b', 'I o T'),
    (r'\bGmbH\b', 'G m b H'),
    (r'\bGbR\b', 'G b R'),
    (r'\bOHG\b', 'O H G'),
    (r'\bKGaA\b', 'K G a A'),
    (r'\bAG\b', 'A G'),
    (r'\bBGB\b', 'B G B'),
    (r'\bStGB\b', 'S t G B'),
    (r'\bDSGVO\b', 'D S G V O'),
    (r'\bAGB\b', 'A G B'),
    (r'\bHGB\b', 'H G B'),
    (r'\bStVO\b', 'S t V O'),
    (r'\bKfz\b', 'Kraftfahrzeug'),
    (r'\bLKW\b', 'L K W'),
    (r'\bLkw\b', 'L K W'),
    (r'\bPKW\b', 'P K W'),
    (r'\bPkw\b', 'P K W'),
    (r'\bÖPNV\b', 'Ö P N V'),
    (r'\bICE\b', 'I C E'),
    (r'\bDB\b', 'D B'),
    (r'\bGEZ\b', 'G E Z'),
    (r'\bWG\b', 'W G'),
    (r'\bWC\b', 'W C'),
    (r'\bPLZ\b', 'P L Z'),
    (r'\bIBAN\b', 'I B A N'),
    (r'\bBIC\b', 'B I C'),
    (r'\bSOTA\b', 'State of the Art'),
]

# Spoken numbers for list headers (comma instead of colon for natural prosody)
NUM_TO_WORD = {
    '1': 'Erstens', '2': 'Zweitens', '3': 'Drittens', '4': 'Viertens',
    '5': 'Fünftens', '6': 'Sechstens', '7': 'Siebtens', '8': 'Achtens',
    '9': 'Neuntens', '10': 'Zehntens', '11': 'Elftens', '12': 'Zwölftens',
    '13': 'Dreizehntens', '14': 'Vierzehntens', '15': 'Fünfzehntens',
    '16': 'Sechzehntens', '17': 'Siebzehntens', '18': 'Achtzehntens',
    '19': 'Neunzehntens', '20': 'Zwanzigstens'
}

ORDINAL_MASC = {
    '1': 'Erster', '2': 'Zweiter', '3': 'Dritter', '4': 'Vierter',
    '5': 'Fünfter', '6': 'Sechster', '7': 'Siebter', '8': 'Achter',
    '9': 'Neunter', '10': 'Zehnter'
}

MONTHS = {'januar', 'februar', 'märz', 'maerz', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'dezember'}

DAY_MAP = {
    'mo': 'Montag', 'di': 'Dienstag', 'mi': 'Mittwoch',
    'do': 'Donnerstag', 'fr': 'Freitag', 'sa': 'Samstag', 'so': 'Sonntag',
    'montag': 'Montag', 'dienstag': 'Dienstag', 'mittwoch': 'Mittwoch',
    'donnerstag': 'Donnerstag', 'freitag': 'Freitag', 'samstag': 'Samstag', 'sonntag': 'Sonntag'
}

MONTH_MAP = {
    'jan': 'Januar', 'feb': 'Februar', 'mär': 'März', 'maer': 'März',
    'apr': 'April', 'mai': 'Mai', 'jun': 'Juni', 'jul': 'Juli',
    'aug': 'August', 'sep': 'September', 'okt': 'Oktober', 'nov': 'November', 'dez': 'Dezember',
    'januar': 'Januar', 'februar': 'Februar', 'märz': 'März', 'april': 'April',
    'juni': 'Juni', 'juli': 'Juli', 'august': 'August', 'september': 'September',
    'oktober': 'Oktober', 'november': 'November', 'dezember': 'Dezember'
}

# Per-unit mapping for slashes (e.g. /Woche -> pro Woche, /Monat -> pro Monat)
PER_UNIT_MAP = {
    'woche': 'Woche', 'wochen': 'Woche',
    'monat': 'Monat', 'monate': 'Monat', 'monaten': 'Monat',
    'jahr': 'Jahr', 'jahre': 'Jahr', 'jahren': 'Jahr',
    'tag': 'Tag', 'tage': 'Tag', 'tagen': 'Tag',
    'stunde': 'Stunde', 'stunden': 'Stunde', 'std': 'Stunde', 'h': 'Stunde',
    'minute': 'Minute', 'minuten': 'Minute', 'min': 'Minute',
    'sekunde': 'Sekunde', 'sekunden': 'Sekunde', 'sek': 'Sekunde', 's': 'Sekunde',
    'quartal': 'Quartal', 'person': 'Person', 'personen': 'Person',
    'kopf': 'Kopf', 'stück': 'Stück', 'stk': 'Stück',
    'haushalt': 'Haushalt', 'haushalte': 'Haushalt',
    'nutzer': 'Nutzer', 'user': 'Nutzer', 'kunde': 'Kunde', 'kunden': 'Kunde',
    'fahrt': 'Fahrt', 'fahrten': 'Fahrt', 'sitzung': 'Sitzung',
    'einheit': 'Einheit', 'einheiten': 'Einheit',
    'seite': 'Seite', 'seiten': 'Seite', 'blatt': 'Blatt',
    'km': 'Kilometer', 'kilometer': 'Kilometer',
    'm': 'Meter', 'meter': 'Meter',
    'm²': 'Quadratmeter', 'qm': 'Quadratmeter', 'm³': 'Kubikmeter',
    'kg': 'Kilogramm', 'kilo': 'Kilogramm', 'kilogramm': 'Kilogramm',
    'g': 'Gramm', 'gramm': 'Gramm',
    'liter': 'Liter', 'l': 'Liter',
    'kwh': 'Kilowattstunde', 'kilowattstunde': 'Kilowattstunde',
    'portion': 'Portion', 'portionen': 'Portion',
    'flasche': 'Flasche', 'flaschen': 'Flasche',
    'dose': 'Dose', 'dosen': 'Dose',
    'anwendung': 'Anwendung', 'anwendungen': 'Anwendung'
}

# Roman numerals in headings
ROMAN_TO_NUM = {
    'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5',
    'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10'
}

DOT_PLACEHOLDER = "__DOT__"

# Line-start list markers: Markdown, typographic bullets, Word's private-use symbol bullets.
_BULLET = re.compile(r'^(?:[-*+•▪◦·‣–-][ \t]+|o\t)(?=\S)')
_NUMBERED = re.compile(r'^\d{1,2}[.)][ \t]+\S')
_TABLE_RULE = re.compile(r'^:?-{2,}:?$')
# A line ending in one of these continues on the next line (copied line wrap).
_JOINERS = frozenset(
    'der die das den dem des ein eine einen einem einer eines und oder aber sowie mit von vom zu '
    'zur zum für auf in im an am bei nach über unter aus wie als dass ob wenn weil sich nicht auch '
    'noch so sehr nur bis durch gegen ohne um the a an of to and or with for'.split())


def _table_row(line):
    if line.startswith('|') and line.endswith('|') and len(line) > 1:
        return [cell.strip() for cell in line[1:-1].split('|')]
    if '\t' in line and not _BULLET.match(line) and not _NUMBERED.match(line):
        cells = [cell.strip() for cell in line.split('\t')]
        if sum(1 for cell in cells if cell) >= 2:
            return cells
    return None


def _sentence(text):
    text = text.strip()
    return text + ('' if text.endswith(('.', '!', '?', ':', ';')) else '.')


def _table_sentences(rows):
    """With a header every value is named by its column ("Betrag: 800 Euro."), so a column
    name never runs into its value; without one, a row reads "Miete: 800 Euro, 40 Prozent."."""
    header = None
    if len(rows) > 1 and all(_TABLE_RULE.match(cell) for cell in rows[1] if cell):
        header, rows = rows[0], rows[2:]
    elif len(rows) > 2 and all(rows[0]) and not any(re.search(r'\d', cell) for cell in rows[0]):
        header, rows = rows[0], rows[1:]
    rows = [row for row in rows if not all(_TABLE_RULE.match(cell) or not cell for cell in row)]
    sentences = []
    for row in rows:
        if header:
            names = header + [''] * len(row)
            sentences.extend(_sentence(f'{name}: {value}' if name else value)
                             for name, value in zip(names, row) if value)
            continue
        label, values = row[0], [value for value in row[1:] if value]
        if label and values:
            sentences.append(_sentence(f'{label}: {", ".join(values)}'))
        elif label or values:
            sentences.append(_sentence(label or ', '.join(values)))
    return sentences


def _structure(text):
    """Turn line structure into punctuation before lines are joined.

    A copied line break is either a wrap inside a sentence (PDF, narrow windows) or a boundary
    the page showed by layout alone: headings, list items, table rows. Wrapped lines run to
    about the width of the longest line or end in a word like "und"; boundaries are shorter.
    Headings and tables are set apart like paragraphs.
    """
    lines = [line.strip() for line in text.split('\n')]
    widths = [len(line) for line in lines if line and _table_row(line) is None]
    longest = max(widths, default=0)

    def is_long(line):
        return longest >= 30 and len(line) >= .7 * longest

    def wraps(line, following):
        last = line.split()[-1].lower()
        # Narrow columns: every line is about as wide as the widest and the sentence goes on.
        filled = len(line) >= .7 * longest and following[:1].islower()
        return line.endswith((',', '-')) or last in _JOINERS or is_long(line) or filled

    out = []  # [text, separator after it, kind]

    def boundary():
        if out:
            out[-1][1] = '\n\n'

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line or re.match(r'^(?:[-*_]\s*){3,}$', line):
            boundary()
            i += 1
            continue
        if line.startswith('```'):
            i += 1
            continue
        if _table_row(line) is not None:
            rows = []
            while i < len(lines) and lines[i] and (row := _table_row(lines[i])) is not None:
                rows.append(row)
                i += 1
            boundary()
            out.extend([sentence, '\n', 'row'] for sentence in _table_sentences(rows))
            boundary()
            continue
        line = re.sub(r'^>\s*', '', line)
        following = next((l for l in lines[i + 1:] if l), '')
        heading = re.match(r'^#{1,6}[ \t]+(.+)', line)
        bullet = _BULLET.match(line)
        if heading:
            boundary()
            out.append([_sentence(heading.group(1)), '\n\n', 'heading'])
        elif bullet or _NUMBERED.match(line):
            out.append([_sentence(line[bullet.end():] if bullet else line), '\n', 'item'])
        elif line.endswith(('.', '!', '?', ':', ';')) or re.search(r'[.!?]["“”»)\]]$', line):
            out.append([line, '\n', 'prose'])
        elif wraps(line, following):
            out.append([line, ' ', 'prose'])
        else:
            # A short line without punctuation: a heading, caption or list item on its own line.
            if out and out[-1][1] == '\n' and out[-1][2] == 'prose' and not out[-1][0].endswith(':'):
                boundary()  # it starts a new section after running text
            starts_section = (is_long(following) or _table_row(following) is not None
                              or following.startswith('#') or bool(_BULLET.match(following)))
            # Title directly above a subheading: both are headings, not a two-item list.
            # A table caption stands apart even right after a list.
            if _table_row(following) is not None or (
                    starts_section and out and out[-1][2] == 'short' and out[-1][1] == '\n'
                    and (len(out) == 1 or out[-2][1] == '\n\n')):
                boundary()
            out.append([_sentence(line), '\n\n' if starts_section else '\n', 'short'])
        i += 1
    return ''.join(text + separator for text, separator, _ in out)


def clean_text(text: str) -> str:
    """Cleans and normalizes raw text into fluid, highly natural spoken German."""
    if not text:
        return ""

    text = unescape(text).replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\u00a0', ' ').replace('\u202f', ' ').replace('\u200b', '')

    # 1. Strip soft hyphens
    text = text.replace("\xad", "")

    # 2. Fix hyphenated line breaks (e.g. "Geschwindig-\nkeit" -> "Geschwindigkeit")
    text = re.sub(r'(\w+)-[ \t]*\n[ \t]*(\w+)', r'\1\2', text)

    # Headings, list items and table rows get their boundaries; ordinary line wraps do not.
    text = _structure(text)

    # 3. Strip Wikipedia citations [1], [2], [14]
    text = re.sub(r'\[\d+\]', '', text)

    # 4. Strip all emojis and symbol decorations
    text = EMOJI_PATTERN.sub('', text)

    # 5. Strip markdown formatting & links
    text = re.sub(r'(?m)^\s*#{1,6}\s*', '', text)           # Markdown headers
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)      # Bold / Italic
    text = re.sub(r'`(.*?)`', r'\1', text)                  # Inline code
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)   # Links [text](url) -> text
    text = re.sub(r'(?i)\b(?:unter|auf|siehe|link:?)\s+https?://\S+', '', text) # Preposition + URL
    text = re.sub(r'https?://\S+', '', text)                # Remaining raw URLs removed
    text = re.sub(r'(?m)^\s*[-*•]\s+', '', text)            # Bullet points

    # 6. Colloquials, Fractions & Common Slang Numbers
    text = re.sub(r'\b24/7\b', 'vierundzwanzig sieben', text)
    text = re.sub(r'\b1/2\b', 'ein halb', text)
    text = re.sub(r'\b1/4\b', 'ein viertel', text)
    text = re.sub(r'\b3/4\b', 'drei viertel', text)
    text = re.sub(r'\b1/3\b', 'ein drittel', text)
    text = re.sub(r'\b2/3\b', 'zwei drittel', text)

    # 7. Convert ISO dates (2026-09-10) to spoken German date structure (10.09.2026)
    text = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b', r'\3.\2.\1', text)

    # 8. Legal, Book & Version References
    text = re.sub(r'§§\s*(\d+)', r'Paragraphen \1', text)
    text = re.sub(r'§\s*(\d+)', r'Paragraph \1', text)
    text = re.sub(r'§', 'Paragraph ', text)
    text = re.sub(r'\b[sS]\.\s*(\d+)', r'Seite \1', text)
    text = re.sub(r'\bpp?\.\s*(\d+)', r'Seite \1', text)
    text = re.sub(r'\b(\d+)\s+ff\.(?=\s|$)', r'\1 fortfolgende', text)
    text = re.sub(r'\b(\d+)\s+f\.(?=\s|$)', r'\1 folgende', text)
    text = re.sub(r'(?i)\bv(\d+(?:\.\d+)+)\b', r'Version \1', text)

    # 9. Multipliers & Frequencies with slash: e.g. 2–3×/Woche, 3x/Monat -> 'mal pro Woche'
    def _repl_times_slash(m):
        raw_u = m.group(1).lower()
        u = PER_UNIT_MAP.get(raw_u, m.group(1))
        return f' mal pro {u}'
    text = re.sub(r'(?<=\d)\s*[xX*×]\s*/\s*([a-zA-ZäöüÄÖÜ²³]+)', _repl_times_slash, text)

    # 10. Per-Unit Slashes with Currencies and Quantities: e.g. 5–12 €/Monat, 25 €/h, 30 Cent/kWh
    def _repl_curr_slash(m):
        raw_curr = m.group(1)
        curr = 'Euro' if raw_curr == '€' else ('Dollar' if raw_curr == '$' else ('Schweizer Franken' if raw_curr == 'CHF' else ('Pfund' if raw_curr == '£' else ('Yen' if raw_curr == '¥' else raw_curr))))
        raw_u = m.group(2).lower()
        u = PER_UNIT_MAP.get(raw_u, m.group(2))
        return f'{curr} pro {u}'
    text = re.sub(r'(€|\$|£|¥|CHF)\s*/\s*([a-zA-ZäöüÄÖÜ²³]+)', _repl_curr_slash, text)

    def _repl_unit_slash(m):
        prefix = m.group(1)
        raw_u = m.group(2).lower()
        u = PER_UNIT_MAP.get(raw_u, m.group(2))
        return f'{prefix} pro {u}'
    text = re.sub(r'\b(Euro|Dollar|Cent|ct|Liter|Kilogramm|kg|Kilometer|km|Stück|kWh)\s*/\s*([a-zA-ZäöüÄÖÜ²³]+)', _repl_unit_slash, text)
    text = re.sub(r'/\s*(\d+)\s*km\b', r' pro \1 Kilometer', text)
    text = re.sub(r'/\s*(\d+)\s*(?:qm|m²)\b', r' pro \1 Quadratmeter', text)

    # Direct number slash with per-unit: e.g. 2/Woche -> 2 pro Woche
    def _repl_num_slash(m):
        num = m.group(1)
        raw_u = m.group(2).lower()
        if raw_u in PER_UNIT_MAP:
            return f'{num} pro {PER_UNIT_MAP[raw_u]}'
        return m.group(0)
    text = re.sub(r'(\d+)\s*/\s*([a-zA-ZäöüÄÖÜ²³]+)', _repl_num_slash, text)

    text = re.sub(r'(?<=\d)\s*>\s*(?=\d)', ' größer als ', text)
    text = re.sub(r'(?<=\d)\s*<\s*(?=\d)', ' kleiner als ', text)

    # 11. UI Breadcrumbs / Menus: e.g. "Datei > Einstellungen > Audio" -> "Datei, dann Einstellungen, dann Audio"
    text = re.sub(r'(?<=\w)\s*>\s*(?=[A-ZÄÖÜ\w])', ', dann ', text)

    # 12. Math Operators & Dimension Multipliers (e.g. 1920x1080 -> '1920 mal 1080', 3x -> '3 mal')
    # Year spans are not divisions: 2024/25 -> '2024 bis 25'
    text = re.sub(r'\b((?:19|20)\d{2})/((?:19|20)?\d{2})\b', r'\1 bis \2', text)
    text = re.sub(r'(?<=\d)\s*[xX*×]\s*(?=\d)', ' mal ', text)
    text = re.sub(r'(?<=\d)\s*[xX]\b', ' mal', text)
    text = re.sub(r'(?<=\d)\s*\+\s*(?=\d)', ' plus ', text)
    text = re.sub(r'(?<=\d)\s*-\s*(?=\d)\s*=', ' minus ', text)
    text = re.sub(r'(?<=\d)\s*[/÷]\s*(?=\d)', ' geteilt durch ', text)
    text = re.sub(r'(?<=\d)\s*=\s*(?=\d)', ' gleich ', text)
    text = re.sub(r'\s*≈\s*', ' ungefähr gleich ', text)
    text = re.sub(r'\s*≠\s*', ' ungleich ', text)
    text = re.sub(r'\s*±\s*', ' plus minus ', text)

    # 13. Number Ranges with Hyphens / Dashes (e.g. 98–99, 10-20, 1. - 3.) -> '... bis ...'
    # 13a. Preceded by 'zwischen': 'zwischen 10-20' -> 'zwischen 10 und 20'
    text = re.sub(
        r'(?i)\b(zwischen)\s+(\d{1,4}(?:[.,]\d+)?\.?)\s*[-–—]\s*(\d{1,4}(?:[.,]\d+)?\.?)',
        r'\1 \2 und \3',
        text
    )
    # 13b. General numeric range: 98–99, 10 - 20, 1. - 3.
    text = re.sub(
        r'(?<!\w)(\d{1,4}(?:[.,]\d+)?\.?)\s*[-–—]\s*(\d{1,4}(?:[.,]\d+)?\.?)(?!\s*=\s*\d)(?!\w)',
        r'\1 bis \2',
        text
    )
    # 13c. Day & Month Ranges (e.g. Mo - Fr -> 'Montag bis Freitag', Jan - Mär -> 'Januar bis März')
    def _repl_day_range(m):
        d1 = DAY_MAP.get(m.group(1).lower().rstrip('.'), m.group(1))
        d2 = DAY_MAP.get(m.group(2).lower().rstrip('.'), m.group(2))
        return f"{d1} bis {d2}"
    text = re.sub(r'(?i)\b(Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\.?\s*[-–—]\s*(Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\.?', _repl_day_range, text)

    def _repl_month_range(m):
        m1 = MONTH_MAP.get(m.group(1).lower().rstrip('.'), m.group(1))
        m2 = MONTH_MAP.get(m.group(2).lower().rstrip('.'), m.group(2))
        return f"{m1} bis {m2}"
    text = re.sub(r'(?i)\b(Jan|Feb|Mär|Maer|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\.?\s*[-–—]\s*(Jan|Feb|Mär|Maer|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\.?', _repl_month_range, text)

    # Remove grouping dots from the complete number before any word expansion.
    # Dates (10.09.2026) and decimal dots (3.5) are not grouped thousands.
    text = re.sub(r'(?<![\w.])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d.])',
                  lambda m: m.group(0).replace('.', ''), text)

    # 15. Clean compound word hyphens with numbers (e.g. '32-Bit' -> '32 Bit', '24-Stunden' -> '24 Stunden')
    text = re.sub(r'(?<=\d)-(?=[a-zA-ZäöüÄÖÜ])', ' ', text)

    # 16. Comprehensive Measurement & Data Units (Numeric Prefix & Singular/Plural)
    # Frequencies & Audio
    text = re.sub(r'(\d+)\s*(?:kHz|khz|KHz)\b', r'\1 Kilohertz', text)
    text = re.sub(r'(\d+)\s*(?:MHz|mhz)\b', r'\1 Megahertz', text)
    text = re.sub(r'(\d+)\s*(?:GHz|ghz)\b', r'\1 Gigahertz', text)
    text = re.sub(r'(\d+)\s*(?:THz|thz)\b', r'\1 Terahertz', text)
    text = re.sub(r'(\d+)\s*(?:Hz|hz)\b', r'\1 Hertz', text)
    text = re.sub(r'(\d+)\s*dBFS\b', r'\1 Dezibel', text)
    text = re.sub(r'(\d+)\s*dB\b', r'\1 Dezibel', text)

    # Data & Transfer
    text = re.sub(r'(\d+)\s*(?:fps|FPS)\b', r'\1 Frames pro Sekunde', text)
    text = re.sub(r'(\d+)\s*px\b', r'\1 Pixel', text)
    text = re.sub(r'(\d+)\s*(?:kbps|kbit/s)\b', r'\1 Kilobit pro Sekunde', text)
    text = re.sub(r'(\d+)\s*(?:Mbps|Mbit/s)\b', r'\1 Megabit pro Sekunde', text)
    text = re.sub(r'(\d+)\s*(?:Gbps|Gbit/s)\b', r'\1 Gigabit pro Sekunde', text)
    text = re.sub(r'(\d+)\s*kbit\b', r'\1 Kilobit', text)
    text = re.sub(r'(\d+)\s*Mbit\b', r'\1 Megabit', text)
    text = re.sub(r'(\d+)\s*Gbit\b', r'\1 Gigabit', text)
    text = re.sub(r'(\d+)\s*GB\b', r'\1 Gigabyte', text)
    text = re.sub(r'(\d+)\s*MB\b', r'\1 Megabyte', text)
    text = re.sub(r'(\d+)\s*(?:KB|kB)\b', r'\1 Kilobyte', text)
    text = re.sub(r'(\d+)\s*TB\b', r'\1 Terabyte', text)
    text = re.sub(r'(\d+)\s*PB\b', r'\1 Petabyte', text)

    # Time Units (Singular & Plural)
    text = re.sub(r'\b1\s*ms\b', '1 Millisekunde', text)
    text = re.sub(r'(\d+)\s*ms\b', r'\1 Millisekunden', text)
    text = re.sub(r'\b1\s*µs\b', '1 Mikrosekunde', text)
    text = re.sub(r'(\d+)\s*µs\b', r'\1 Mikrosekunden', text)
    text = re.sub(r'\b1\s*ns\b', '1 Nanosekunde', text)
    text = re.sub(r'(\d+)\s*ns\b', r'\1 Nanosekunden', text)
    text = re.sub(r'\b1\s*(?:sek|sec|s)\b', '1 Sekunde', text)
    text = re.sub(r'(\d+)\s*(?:sek|sec|s)\b', r'\1 Sekunden', text)
    text = re.sub(r'\b1\s*min\b', '1 Minute', text)
    text = re.sub(r'(\d+)\s*min\b', r'\1 Minuten', text)
    text = re.sub(r'\b1\s*(?:std|h)\b', '1 Stunde', text)
    text = re.sub(r'(\d+)\s*(?:std|h)\b', r'\1 Stunden', text)
    text = re.sub(r'\b1\s*d\b', '1 Tag', text)
    text = re.sub(r'(\d+)\s*d\b', r'\1 Tage', text)

    # Physical Dimensions & Weights
    text = re.sub(r'(\d+)\s*km/h\b', r'\1 Kilometer pro Stunde', text)
    text = re.sub(r'(\d+)\s*m/s\b', r'\1 Meter pro Sekunde', text)
    text = re.sub(r'(\d+)\s*m²\b', r'\1 Quadratmeter', text)
    text = re.sub(r'(\d+)\s*qm\b', r'\1 Quadratmeter', text)
    text = re.sub(r'(\d+)\s*m³\b', r'\1 Kubikmeter', text)
    text = re.sub(r'(\d+)\s*kg\b', r'\1 Kilogramm', text)
    text = re.sub(r'(\d+)\s*km\b', r'\1 Kilometer', text)
    text = re.sub(r'(\d+)\s*cm\b', r'\1 Zentimeter', text)
    text = re.sub(r'(\d+)\s*mm\b', r'\1 Millimeter', text)
    text = re.sub(r'(\d+)\s*nm\b', r'\1 Nanometer', text)
    text = re.sub(r'(\d+)\s*µm\b', r'\1 Mikrometer', text)
    text = re.sub(r'(\d+)\s*mg\b', r'\1 Milligramm', text)
    text = re.sub(r'(\d+)\s*µg\b', r'\1 Mikrogramm', text)
    text = re.sub(r'\b1\s*t\b', '1 Tonne', text)
    text = re.sub(r'(\d+)\s*t\b', r'\1 Tonnen', text)
    text = re.sub(r'(\d+)\s*l\b', r'\1 Liter', text)
    text = re.sub(r'(\d+)\s*ml\b', r'\1 Milliliter', text)
    text = re.sub(r'(\d+)\s*m\b', r'\1 Meter', text)
    text = re.sub(r'(\d+)\s*g\b', r'\1 Gramm', text)

    # Energy & Electrical
    text = re.sub(r'\b1\s*kWh\b', '1 Kilowattstunde', text)
    text = re.sub(r'(\d+)\s*kWh\b', r'\1 Kilowattstunden', text)
    text = re.sub(r'\b1\s*MWh\b', '1 Megawattstunde', text)
    text = re.sub(r'(\d+)\s*MWh\b', r'\1 Megawattstunden', text)
    text = re.sub(r'\b1\s*Wh\b', '1 Wattstunde', text)
    text = re.sub(r'(\d+)\s*Wh\b', r'\1 Wattstunden', text)
    text = re.sub(r'(\d+)\s*mAh\b', r'\1 Milliamperestunden', text)
    text = re.sub(r'(\d+)\s*Ah\b', r'\1 Amperestunden', text)
    text = re.sub(r'(\d+)\s*kW\b', r'\1 Kilowatt', text)
    text = re.sub(r'(\d+)\s*MW\b', r'\1 Megawatt', text)
    text = re.sub(r'(\d+)\s*GW\b', r'\1 Gigawatt', text)
    text = re.sub(r'(\d+)\s*W\b', r'\1 Watt', text)
    text = re.sub(r'(\d+)\s*V\b', r'\1 Volt', text)
    text = re.sub(r'(\d+)\s*A\b', r'\1 Ampere', text)
    text = re.sub(r'(\d+)\s*bar\b', r'\1 Bar', text)
    text = re.sub(r'(\d+)\s*hPa\b', r'\1 Hektopascal', text)
    text = re.sub(r'(\d+)\s*°C\b', r'\1 Grad Celsius', text)
    text = re.sub(r'(\d+)\s*°F\b', r'\1 Grad Fahrenheit', text)
    text = re.sub(r'(\d+)\s*°(?!\w)', r'\1 Grad', text)
    text = re.sub(r'(\d+)\s*K\b', r'\1 Kelvin', text)

    # Currencies & Percentages
    text = re.sub(r'(\d+)\s*€', r'\1 Euro', text)
    text = re.sub(r'(\d+)\s*\$', r'\1 Dollar', text)
    text = re.sub(r'(\d+)\s*CHF\b', r'\1 Schweizer Franken', text)
    text = re.sub(r'(\d+)\s*£', r'\1 Pfund', text)
    text = re.sub(r'(\d+)\s*¥', r'\1 Yen', text)
    text = re.sub(r'(\d+)\s*ct\b', r'\1 Cent', text)
    text = re.sub(r'(\d+)\s*%', r'\1 Prozent', text)
    text = re.sub(r'(\d+)\s*‰', r'\1 Promille', text)

    # 17. Standalone Units (when mentioned as pure terms: "Dauer in ms", "Abtastrate in kHz")
    text = re.sub(r'\b(?:kHz|khz|KHz)\b', 'Kilohertz', text)
    text = re.sub(r'\b(?:MHz|mhz)\b', 'Megahertz', text)
    text = re.sub(r'\b(?:GHz|ghz)\b', 'Gigahertz', text)
    text = re.sub(r'\b(?:THz|thz)\b', 'Terahertz', text)
    text = re.sub(r'\bHz\b', 'Hertz', text)
    text = re.sub(r'\bms\b', 'Millisekunden', text)
    text = re.sub(r'\bµs\b', 'Mikrosekunden', text)
    text = re.sub(r'\bns\b', 'Nanosekunden', text)
    text = re.sub(r'\bdBFS\b', 'Dezibel', text)
    text = re.sub(r'\bdB\b', 'Dezibel', text)
    text = re.sub(r'\bkbit/s\b', 'Kilobit pro Sekunde', text)
    text = re.sub(r'\bMbit/s\b', 'Megabit pro Sekunde', text)
    text = re.sub(r'\bGbit/s\b', 'Gigabit pro Sekunde', text)
    text = re.sub(r'\bkWh\b', 'Kilowattstunden', text)
    text = re.sub(r'\bMWh\b', 'Megawattstunden', text)
    text = re.sub(r'\bmAh\b', 'Milliamperestunden', text)
    text = re.sub(r'\bkm/h\b', 'Kilometer pro Stunde', text)
    text = re.sub(r'\bm/s\b', 'Meter pro Sekunde', text)

    # 18. Email Addresses: e.g. kontakt@firma.de -> 'kontakt at firma punkt de'
    def _repl_email(m):
        user = m.group(1).replace('.', ' punkt ')
        domain = m.group(2).replace('.', ' punkt ')
        return f"{user} at {domain}"
    text = re.sub(r'\b([a-zA-Z0-9_.+-]+)@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b', _repl_email, text)

    # 19. Slashes in alternatives (und/oder -> und oder, Er/Sie -> Er oder Sie)
    text = re.sub(r'\bund/oder\b', 'und oder', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(sowohl/als auch)\b', 'sowohl als auch', text, flags=re.IGNORECASE)
    def _repl_slash_alt(m):
        w1, w2 = m.group(1), m.group(2)
        if w2.lower() == 'oder':
            return f"{w1} oder"
        return f"{w1} oder {w2}"
    text = re.sub(r'(\b\w+)/(\w+\b)', _repl_slash_alt, text)

    # 20. Remaining Em-dash and en-dash -> Gedankenstrich (natural rhetorical pause)
    text = re.sub(r'\s*[—–]\s*', ' – ', text)
    text = re.sub(r'\s+-\s+', ' – ', text)

    # 21. Code & Technical Identifiers Humanizer (Eliminate "Unterstrich", "Punkt py", "Klammer auf/zu")
    # 21a. Function call empty parentheses: e.g. main() -> main
    text = re.sub(r'(\b[a-zA-Z_]\w*)\(\)', r'\1', text)

    # 21b. Common file extensions in technical text: e.g. main_app.py -> main_app.
    # JavaScript frameworks named "X.js" are product names, not files: Node.js -> Node JS.
    text = re.sub(r'\b(Node|Vue|Next|Nuxt|Express|Three|Chart|Deno)\.js\b', r'\1 JS', text)
    common_exts = r'([a-zA-Z0-9_-]+)\.(?:py|js|ts|tsx|jsx|html|css|json|md|txt|csv|bat|sh|exe|dll|zip|png|jpg|jpeg|svg|xml|yaml|yml|sql|pdf|docx?|xlsx?|pptx?)\b'
    text = re.sub(common_exts, r'\1', text, flags=re.IGNORECASE)

    # 21c. File and directory path slashes: e.g. C:\Users\Max -> Laufwerk C, Users, Max
    text = re.sub(r'\b([A-Za-z]):\\', r'Laufwerk \1, ', text)
    path_part = r'([a-zA-Z0-9_-]+)[\\/]([a-zA-Z0-9_-]+)'
    while re.search(path_part, text):
        text = re.sub(path_part, r'\1, \2', text)

    # 21d. Underscores in identifiers & snake_case (Eliminates the robotic "Unterstrich")
    text = re.sub(r'(?<=\w)_(?=\w)', ' ', text)
    text = re.sub(r'(^|[\s(\[{"\'])_+', r'\1', text)
    text = re.sub(r'_+([\s)\]}"\'.,:;!?]|$)', r'\1', text)
    text = re.sub(r'_+', ' ', text)

    # 21f. Code operators to natural spoken German
    text = re.sub(r'\s*->\s*', ' ergibt ', text)
    text = re.sub(r'\s*=>\s*', ' ergibt ', text)
    text = re.sub(r'\s*==\s*', ' ist gleich ', text)
    text = re.sub(r'\s*!=\s*', ' ungleich ', text)
    text = re.sub(r'\s*>=\s*', ' größer gleich ', text)
    text = re.sub(r'\s*<=\s*', ' kleiner gleich ', text)

    # 22. Intelligent List & Ordinal Normalization (no falling-pitch stutter)
    def _repl_list_item(match):
        prefix = match.group(1)
        num = match.group(2)
        rest = match.group(3).rstrip()
        # Each item ends its own phrase, otherwise joined lines run into one another.
        if not rest.endswith(('.', '!', '?', ':', ';')):
            rest += '.'
        tokens = rest.split()
        first_word = tokens[0].rstrip(':,.;').lower() if tokens else ''
        # Protect dates: "1. Mai"
        if first_word in MONTHS:
            return match.group(0)
        # Ordinal nouns: "1. Schritt", "2. Punkt", "1. Kapitel"
        if first_word in ('schritt', 'punkt', 'teil', 'abschnitt', 'kapitel', 'phase', 'platz', 'rang'):
            ord_w = ORDINAL_MASC.get(num, f'{num}.')
            has_colon = bool(re.match(r'^[A-Za-zäöüÄÖÜß]+[ \t]*:', rest))
            clean_rest = re.sub(r'^[A-Za-zäöüÄÖÜß]+[:,\s]*', '', rest)
            sep = ':' if has_colon else ','
            return f'{prefix}{ord_w} {first_word.capitalize()}{sep} {clean_rest}'
        # Quartal: "1. Quartal" -> "Erstes Quartal"
        if first_word == 'quartal':
            has_colon = bool(re.match(r'^quartal[ \t]*:', rest, flags=re.IGNORECASE))
            clean_rest = re.sub(r'^quartal[:,\s]*', '', rest, flags=re.IGNORECASE)
            ord_w = 'Erstes' if num == '1' else ('Zweites' if num == '2' else ('Drittes' if num == '3' else 'Viertes'))
            sep = ':' if has_colon else ','
            return f'{prefix}{ord_w} Quartal{sep} {clean_rest}'
        # General list item: use comma for continuous, fluid melody
        word = NUM_TO_WORD.get(num, f'Punkt {num}')
        return f'{prefix}{word}, {rest}'

    text = re.sub(r'(?m)(^|\n|\s{2,})(\d{1,2})\.\s+([^\n]+)', _repl_list_item, text)

    # 23. Roman numerals in chapters / parts (e.g. "Kapitel IV" -> "Kapitel 4")
    def _repl_roman(match):
        prefix = match.group(1)
        roman = match.group(2).upper()
        num = ROMAN_TO_NUM.get(roman, roman)
        return f'{prefix} {num}'
    text = re.sub(r'(?i)\b(Kapitel|Teil|Abschnitt|Band)\s+([IVXLCDM]+)\b', _repl_roman, text)

    # 24. Naturalize German abbreviations into full spoken words.
    # An abbreviation dot at the end of a line or text also ends the sentence; keep it.
    # Phrase-closing abbreviations (usw., MwSt.) before a capital start a new sentence.
    closing = ('und so weiter', 'et cetera', 'Mehrwertsteuer', 'Umsatzsteuer', 'und ähnliches',
               'oder ähnliches', 'und andere mehr', 'dergleichen', 'fortfolgende')
    def _expand(repl):
        def apply(m):
            value = m.expand(repl)
            rest = m.string[m.end():]
            ends = m.group(0).rstrip().endswith('.') and (
                rest[:1] in ('', '\n')
                or (value in closing and re.match(r'[ \t]+[A-ZÄÖÜ]', rest)))
            return value + '.' if ends and not value.endswith('.') else value
        return apply
    for pattern, repl in ABBREVIATION_EXPANSIONS:
        text = re.sub(pattern, _expand(repl), text, flags=re.IGNORECASE)

    # 25. Tech acronyms letter-spacing
    for pattern, repl in ACRONYMS:
        text = re.sub(pattern, repl, text)

    # 25b. Split CamelCase & PascalCase into natural words (e.g. AudioPlayer -> Audio Player).
    # Runs after 24/25 so mixed-case abbreviations (GmbH, MwSt., StGB) are expanded intact.
    text = re.sub(r'([a-zäöü])([A-ZÄÖÜ])', r'\1 \2', text)
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)
    # Acronyms freed from identifiers (MyAPIClient -> My API Client) get spaced too.
    for pattern, repl in ACRONYMS:
        text = re.sub(pattern, repl, text)

    # 26. Normalize quotes and Ampersands
    text = re.sub(r'\s*&\s*', ' und ', text)
    text = re.sub(r'[„“”«»"]', '"', text)

    # 27. Clean multiple punctuation
    text = re.sub(r':{2,}', ':', text)
    text = re.sub(r'\?{2,}', '?', text)
    text = re.sub(r'!{2,}', '!', text)

    # Paragraphs are meaningful; a single copied line break is not a sentence end.
    text = re.sub(r':\s*\n+', ':\n\n', text)
    text = re.sub(r'([^.!?:;,\n])[ \t]*\n[ \t]*\n', r'\1.\n\n', text)

    # 29. Preserve paragraph markers while collapsing whitespace
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()


# English words the German voices read the German way when glued to a hyphen
# ("Tray-Symbol" sounded like "Dreh-Symbol"); with a space they are read in English.
# Checked with Whisper on 2026-10-27. Only the text sent to the voice changes.
ENGLISH_PARTS = (
    "account", "agent", "app", "backup", "blog", "board", "browser", "button", "cache", "call", "chat",
    "chatbot", "clip", "clipboard", "cloud", "coaching", "code", "community", "container", "content",
    "cookie", "dashboard", "deadline", "deployment", "desktop", "developer", "download", "feature",
    "feedback", "file", "game", "hotkey", "home", "homepage", "laptop", "link", "live", "login", "manager",
    "meeting", "mindset", "mobile", "online", "password", "payment", "player", "plug", "plugin", "post",
    "pricing", "queue", "screen", "server", "setup", "shop", "shortcut", "smart", "social", "software",
    "stakeholder", "stream", "team", "tool", "tools", "touch", "tray", "update", "upload", "user", "web",
    "widget", "workflow", "workspace",
)
_ENGLISH = "|".join(ENGLISH_PARTS)
_ENGLISH_HYPHEN = re.compile(rf"(?i)\b({_ENGLISH})-(?=\w)|(?<=\w)-({_ENGLISH})\b")


# Spellings the German voices pronounce like the English word. Each was spoken alone by
# Killian, Katja and Conrad and recognized as the English word by Whisper (English mode)
# in 3 of 3 cases on 2026-10-27; the original spelling sounded German ("Lock in", "Shortcode").
# "Tray" has no such spelling: every variant was heard as "drei".
# Developer words, measured the same way on 2026-10-27 (patterns match the text after clean_text,
# e.g. "macOS" -> "mac OS", "OpenAI" -> "Open A I"). Marked 2/3: Killian and one more voice.
# No spelling worked for Merge, Bug, Bugfix, Thread, Async and Await; "Build" already sounds like "Bild".
RESPELLINGS = [
    (re.compile(r"\bclipboard(s?)\b", re.IGNORECASE), r"Clip Board\1"),
    (re.compile(r"\blogin(s?)\b", re.IGNORECASE), r"Logginn\1"),
    (re.compile(r"\bshortcut(s?)\b", re.IGNORECASE), r"Shortkatt\1"),
    (re.compile(r"\bcache\b", re.IGNORECASE), "Kässch"),
    (re.compile(r"\breadme\b", re.IGNORECASE), "Riedmi"),
    (re.compile(r"\bEleven ?Labs\b", re.IGNORECASE), "Ilewen Läbs"),
    (re.compile(r"\brebase\b", re.IGNORECASE), "Ribäis"),
    (re.compile(r"\bwebhook(s?)\b", re.IGNORECASE), r"Web Hook\1"),
    (re.compile(r"\bbackend(s?)\b", re.IGNORECASE), r"Bäck End\1"),
    (re.compile(r"\bdebugging\b", re.IGNORECASE), "Dibagging"),
    (re.compile(r"\bworkspace(s?)\b", re.IGNORECASE), r"Work Space\1"),
    (re.compile(r"\bJSON\b", re.IGNORECASE), "Jason"),
    (re.compile(r"\bmac ?OS\b", re.IGNORECASE), "Mäk OS"),
    (re.compile(r"\b(?i:open) ?A ?I\b"), "Open Eh Ei"),
    (re.compile(r"\bgemini\b", re.IGNORECASE), "Dschemmini"),
    (re.compile(r"\bJS\b"), "Dschäi Es"),
    (re.compile(r"\bcommits\b", re.IGNORECASE), "Kommitts"),         # 2/3
    (re.compile(r"\bchange ?log(s?)\b", re.IGNORECASE), r"Change Log\1"),  # 2/3, as the English voice
    (re.compile(r"\barray(s?)\b", re.IGNORECASE), r"Ärräi\1"),        # 2/3
    (re.compile(r"\bYAML\b", re.IGNORECASE), "Jammel"),               # 2/3
    (re.compile(r"\bwhisper\b", re.IGNORECASE), "Uisper"),            # 2/3
    # Everyday business and tech terms, measured the same way on 2026-11-18 (tests/english_terms_check.py:
    # 97 of 128 common terms were already fine). Not solved: Sales, Prompts, Tracking; "Code" keeps the
    # usual German "Kohd". "Budget" stays French-German on purpose.
    (re.compile(r"\bcall(s?)\b", re.IGNORECASE), r"Kholl\1"),
    (re.compile(r"\bdeadline(s?)\b", re.IGNORECASE), r"Dedd Lain\1"),
    (re.compile(r"\bmanager(s?)\b", re.IGNORECASE), r"Männidschr\1"),
    (re.compile(r"\bstakeholder\b", re.IGNORECASE), "Stäik Holder"),  # Whisper: the homophone "Steakholder"
    (re.compile(r"\bcoaching\b", re.IGNORECASE), "Koutsching"),
    (re.compile(r"\bforecast(s?)\b", re.IGNORECASE), r"Fore Cast\1"),
    (re.compile(r"\bpricing\b", re.IGNORECASE), "Preissing"),
    (re.compile(r"\bmindset(s?)\b", re.IGNORECASE), r"Maindset\1"),
    (re.compile(r"\bsoftware\b", re.IGNORECASE), "Softwär"),
    (re.compile(r"\bpassword(s?)\b", re.IGNORECASE), r"Passwörd\1"),
    (re.compile(r"\bhomepage(s?)\b", re.IGNORECASE), r"Houmpeidsch\1"),
    (re.compile(r"\bserver(s?)\b", re.IGNORECASE), r"Sörwer\1"),
    (re.compile(r"\bapps\b", re.IGNORECASE), "Äps"),                  # 2/3
    (re.compile(r"\bpayments\b", re.IGNORECASE), "Peymends"),
    (re.compile(r"\bpayment\b", re.IGNORECASE), "Peyment"),
    (re.compile(r"\blibrary\b", re.IGNORECASE), "Laibräri"),
    (re.compile(r"\bbranch\b", re.IGNORECASE), "Bräntsch"),
    (re.compile(r"\bdeployment(s?)\b", re.IGNORECASE), r"Diploiment\1"),
    (re.compile(r"\bdeveloper(s?)\b", re.IGNORECASE), r"Diwellopper\1"),
    (re.compile(r"\bcoding\b", re.IGNORECASE), "Kouding"),
    (re.compile(r"\bcontainer(s?)\b", re.IGNORECASE), r"Kontäiner\1"),
    (re.compile(r"\bplug ?-?in(s?)\b", re.IGNORECASE), r"Plagin\1"),
    (re.compile(r"\blatency\b", re.IGNORECASE), "Leytenssi"),
    (re.compile(r"\bchat ?bot\b", re.IGNORECASE), "Tschett Bott"),   # plurals of these three: no spelling worked
    (re.compile(r"\buse[ -]?case\b", re.IGNORECASE), "Jus Käis"),
    (re.compile(r"\bagents\b", re.IGNORECASE), "Ejtschents"),
    (re.compile(r"\bagent\b", re.IGNORECASE), "Ejtschent"),          # 2/3
]


def speakable(text: str) -> str:
    """Text as sent to the voice: hyphens next to English words become spaces and a few
    English words get a spelling the German voices pronounce correctly."""
    text = _ENGLISH_HYPHEN.sub(lambda m: f"{m.group(1)} " if m.group(1) else f" {m.group(2)}", text)
    for pattern, spelling in RESPELLINGS:
        text = pattern.sub(spelling, text)
    return text


def split_sentences(text: str, max_chunk_words: int = 80) -> List[str]:
    """Keep sentence context and punctuation; bound requests at natural boundaries."""
    units = split_units(text, max_chunk_words)
    return [' '.join(units[start:end]) for start, end in group_ranges(units, max_chunk_words)]


def group_ranges(units: List[str], max_chunk_words: int = 80) -> List[Tuple[int, int]]:
    """Join consecutive sentences into requests; a paragraph end always closes one."""
    ranges, words = [], 0
    for index, unit in enumerate(units):
        count = len(unit.split())
        if ranges and not units[index - 1].endswith('\n\n') and words + count <= max_chunk_words:
            ranges[-1] = (ranges[-1][0], index + 1)
            words += count
        else:
            ranges.append((index, index + 1))
            words = count
    return ranges


def split_units(text: str, max_chunk_words: int = 80) -> List[str]:
    """Spoken sentences (long ones cut at commas); the navigation and display unit."""
    if max_chunk_words < 1:
        raise ValueError("max_chunk_words must be positive")
    cleaned = clean_text(text)
    if not cleaned:
        return []
    cleaned = re.sub(r'(?<=\d)\.(?=\d)', DOT_PLACEHOLDER, cleaned)
    cleaned = re.sub(r'\b(\d{1,2}|[A-ZÄÖÜ])\.(?=\s+[A-Za-zÄÖÜäöü])',
                     lambda m: m.group(1) + DOT_PLACEHOLDER, cleaned)
    parts, buffer = [], []

    def flush(mark=""):
        value = ''.join(buffer).strip()
        buffer.clear()
        if value and re.search(r'\w', value):
            parts.append(value + mark)
        elif mark and parts and mark == "\n\n":
            parts[-1] = parts[-1].rstrip() + mark

    for index, char in enumerate(cleaned):
        following = cleaned[index + 1] if index + 1 < len(cleaned) else ''
        if char == '\n':
            flush('\n\n')
        elif ((char in '.!?' and following.isspace()) or
              (char in '\"»”' and index and cleaned[index - 1] in '.!?'
               and following.isspace())):
            buffer.append(char)
            flush()
        else:
            buffer.append(char)
    flush()

    chunks = []
    for part in parts:
        paragraph = part.endswith('\n\n')
        words = part.strip().replace(DOT_PLACEHOLDER, '.').split()
        while len(words) > max_chunk_words:
            # Prefer a comma boundary without letting any unsplit run exceed the limit.
            cut = max_chunk_words
            for i in range(max_chunk_words - 1, max(0, max_chunk_words // 2 - 1), -1):
                if words[i].endswith(','):
                    cut = i + 1
                    break
            chunk = ' '.join(words[:cut])
            chunks.append(chunk if chunk.endswith(',') else chunk + ',')
            words = words[cut:]
        if words:
            chunks.append(' '.join(words) + ('\n\n' if paragraph else ''))
    return chunks

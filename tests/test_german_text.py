import unittest

from settings import VOICES, validate
from text_cleaner import clean_text, split_sentences


class GermanTextTests(unittest.TestCase):
    def test_mixed_case_abbreviations_stay_intact(self):
        self.assertIn('Mehrwertsteuer', clean_text('Preis inkl. MwSt. Danach mehr.'))
        self.assertIn('G m b H', clean_text('Die XY GmbH meldet Gewinne.'))
        self.assertIn('S t G B', clean_text('Laut StGB gilt das.'))
        self.assertIn('My A P I Client', clean_text('Der MyAPIClient läuft.'))

    def test_abbreviation_keeps_sentence_end(self):
        self.assertEqual(split_sentences('Preis inkl. MwSt. Danach mehr.')[0],
                         'Preis inklusive Mehrwertsteuer. Danach mehr.')
        self.assertTrue(clean_text('Wir sehen uns usw.').endswith('und so weiter.'))
        self.assertIn('Doktor Müller', clean_text('Herr Dr. Müller kam.'))

    def test_street_suffix_and_year_span(self):
        self.assertIn('Hauptstraße 12', clean_text('Hauptstr. 12 in München.'))
        self.assertIn('2024 bis 25', clean_text('Saison 2024/25.'))
        self.assertIn('10 geteilt durch 5', clean_text('Rechne 10/5.'))

    def test_numbered_list_items_stay_separate(self):
        self.assertEqual(clean_text('1. Einkaufen\n2. Kochen'), 'Erstens, Einkaufen. Zweitens, Kochen.')

    def test_windows_path_is_read_as_parts(self):
        self.assertEqual(clean_text(r'Liegt in C:\Users\Max\bericht.pdf'),
                         'Liegt in Laufwerk C, Users, Max, bericht')


class VoiceTests(unittest.TestCase):
    def test_retired_voice_falls_back_to_default(self):
        self.assertNotIn('de-DE-RalfNeural', VOICES)
        self.assertNotIn('de-DE-SeraphinaMultilingualNeural', VOICES)  # unreliable at the service
        self.assertEqual(validate({'voice': 'de-DE-RalfNeural'})['voice'], 'de-DE-KillianNeural')
        self.assertEqual(validate({'voice': 'de-AT-JonasNeural'})['voice'], 'de-AT-JonasNeural')


if __name__ == '__main__':
    unittest.main()


class SpeakableTests(unittest.TestCase):
    def test_english_hyphen_compounds_get_a_space_for_the_voice(self):
        from text_cleaner import speakable
        self.assertEqual(speakable('Das Tray-Symbol öffnet das Tray-Menü.'), 'Das Tray Symbol öffnet das Tray Menü.')
        self.assertEqual(speakable('Der Download-Link im Browser-Tab.'), 'Der Download Link im Browser Tab.')
        self.assertEqual(speakable('Die E-Mail und das Open-Source-Projekt.'), 'Die E-Mail und das Open-Source-Projekt.')
        self.assertEqual(speakable('Baden-Württemberg'), 'Baden-Württemberg')

    def test_tab_is_only_tabelle_before_a_number(self):
        self.assertTrue(clean_text('Siehe Tab. 3.').startswith('Siehe Tabelle 3'))
        self.assertTrue(clean_text('Im Browser-Tab.').endswith('Browser-Tab.'))


class RespellingTests(unittest.TestCase):
    def test_measured_spellings_reach_the_voice_only(self):
        from text_cleaner import speakable
        self.assertEqual(speakable('Die Login-Seite.'), 'Die Logginn Seite.')
        self.assertEqual(speakable('Zwei Shortcuts im Clipboard.'), 'Zwei Shortkatts im Clip Board.')
        self.assertEqual(speakable('Leere den Cache.'), 'Leere den Kässch.')
        self.assertEqual(clean_text('Leere den Cache.'), 'Leere den Cache.')  # display unchanged

    def test_developer_words_after_cleaning(self):
        from text_cleaner import speakable
        say = lambda text: speakable(clean_text(text))
        self.assertEqual(say('Lies die README.md und den Changelog.'), 'Lies die Riedmi und den Change Log.')
        self.assertEqual(say('ElevenLabs und OpenAI liefern JSON.'), 'Ilewen Läbs und Open Eh Ei liefern Jason.')
        self.assertEqual(say('Unter macOS läuft Node.js.'), 'Unter Mäk OS läuft Node Dschäi Es.')
        self.assertEqual(say('Der Webhook im Backend nach dem Rebase.'), 'Der Web Hook im Bäck End nach dem Ribäis.')

    def test_business_terms_and_german_lookalikes(self):
        from text_cleaner import speakable
        say = lambda text: speakable(clean_text(text))
        self.assertEqual(say('Die Deadline fürs Software-Update.'), 'Die Dedd Lain fürs Softwär Update.')
        self.assertEqual(say('Der Agent ruft zwei Plug-ins auf.'), 'Der Ejtschent ruft zwei Plagins auf.')
        # German words that merely start like the English ones stay untouched.
        self.assertEqual(say('Die Agenten der Branche und Managerinnen.'),
                         'Die Agenten der Branche und Managerinnen.')

    def test_js_frameworks_are_not_file_names(self):
        self.assertEqual(clean_text('Mit Vue.js und Next.js.'), 'Mit Vue JS und Next JS.')
        self.assertEqual(clean_text('Die Datei main.js.'), 'Die Datei main.')

import unittest

from chatgpt_surface import installed_chatgpt_target, explicit_browser_requested


class ChatGPTSurfaceTests(unittest.TestCase):
    def test_spanish_review_pr_routes_to_installed_app(self):
        seen = []
        def lookup(name):
            seen.append(name)
            return 'ChatGPT' if name.lower() == 'chatgpt' else ''
        self.assertEqual(installed_chatgpt_target('dile a ChatGPT que revise el PR 202 de GameHub Ultra en GitHub', lookup), 'ChatGPT')
        self.assertEqual(seen, ['ChatGPT'])

    def test_english_voice_request(self):
        self.assertEqual(installed_chatgpt_target('tell ChatGPT to review pull request 202', lambda _: 'ChatGPT'), 'ChatGPT')

    def test_missing_app_falls_back_to_web(self):
        self.assertEqual(installed_chatgpt_target('abre ChatGPT', lambda _: ''), '')

    def test_article_mentions_are_not_app_commands(self):
        def fail(_):
            raise AssertionError('lookup must not run')
        self.assertEqual(installed_chatgpt_target('search for a ChatGPT news article', fail), '')

    def test_installed_lookup_failure_degrades_safely(self):
        def fail(_):
            raise OSError('Windows launcher failed')
        self.assertEqual(installed_chatgpt_target('abre chatgpt', fail), '')

    def test_spanish_explicit_browser(self):
        self.assertTrue(explicit_browser_requested('en el navegador dile a ChatGPT que revise un PR'))
        self.assertTrue(explicit_browser_requested('abre ChatGPT en Chrome'))
        self.assertFalse(explicit_browser_requested('dile a ChatGPT que revise el PR'))

    def test_mentions_inside_quoted_text_are_not_commands(self):
        self.assertEqual(installed_chatgpt_target('escribe "dile a chatgpt" en notepad', lambda _: 'ChatGPT'), '')


if __name__ == '__main__':
    unittest.main()

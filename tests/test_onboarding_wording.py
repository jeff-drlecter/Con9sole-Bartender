import unittest
from copy import deepcopy
from features.onboarding_wording import neutralize_prompts, LANGUAGE_TITLE, LEGACY_LANGUAGE_TITLE


class OnboardingCopyTests(unittest.TestCase):
    def test_required_game_question_does_not_regress_to_optional_copy(self):
        prompts = [dict(id='1279023252903301224', title='required', required=True,
                        options=[dict(id='skip', title='暫不選擇／找不到想玩的遊戲', description='keep')])]
        result = neutralize_prompts(prompts)
        self.assertIn('必選', result[0]['title'])
        self.assertTrue(result[0]['required'])
        self.assertEqual(result[0]['options'], prompts[0]['options'])

    def test_only_copy_changes_and_idempotent(self):
        prompts = [dict(id='1426676369567387821',title='想唔想加入公海吹水區？',single_select=True,required=True,in_onboarding=True,type=0,
            options=[dict(id='answer123',title='暫時唔加入',description='舊說明',role_ids=['no-offtopic'],channel_ids=[],emoji=dict(name='🚱'))])]
        original = deepcopy(prompts)
        result = neutralize_prompts(prompts)
        self.assertEqual(prompts, original)
        self.assertEqual(result[0]['title'], '你想加入綜合聊天區嗎？（可隨時更改）')
        self.assertEqual(result[0]['options'][0]['title'], '暫時不加入')
        for p in (result, original):
            for prompt in p:
                prompt.pop('title')
                for option in prompt['options']:
                    option.pop('title'); option.pop('description')
        self.assertEqual(result, original)
        once = neutralize_prompts(prompts)
        self.assertEqual(neutralize_prompts(once), once)

    def test_legacy_language_renamed_without_new_prompt(self):
        prompts = [dict(id='existing-language-id',title=LEGACY_LANGUAGE_TITLE,options=[dict(id='answer-id',title='香港語境',description='old',role_ids=['hk'])])]
        result = neutralize_prompts(prompts)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], LANGUAGE_TITLE)
        self.assertEqual(result[0]['id'], 'existing-language-id')
        self.assertEqual(result[0]['options'][0]['id'], 'answer-id')
        self.assertEqual(result[0]['options'][0]['role_ids'], ['hk'])

    def test_unknown_prompt_and_game_names_untouched(self):
        prompts = [dict(id='custom', title='我嘅自訂問題', options=[dict(id='a',title='只睇台',description='custom')]),
                   dict(id='1279023252903301224',title='old',options=[dict(id='game',title='EA Sports FC27',description='game')])]
        result = neutralize_prompts(prompts)
        self.assertEqual(result[0], prompts[0])
        self.assertEqual(result[1]['options'], prompts[1]['options'])

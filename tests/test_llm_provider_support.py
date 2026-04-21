import unittest

from marten_runtime.config.providers_loader import ProviderConfig
from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages,
    extract_openai_usage,
    parse_tool_arguments,
    resolve_base_url,
)


class LLMProviderSupportTests(unittest.TestCase):
    def test_parse_tool_arguments_accepts_fenced_json(self) -> None:
        self.assertEqual(parse_tool_arguments('```json {"a": 1} ```'), {"a": 1})

    def test_extract_openai_usage_reads_nested_details(self) -> None:
        usage = extract_openai_usage(
            {
                'usage': {
                    'prompt_tokens': 10,
                    'completion_tokens': 5,
                    'prompt_tokens_details': {'cached_tokens': 3},
                    'completion_tokens_details': {'reasoning_tokens': 2},
                }
            },
            provider_name='openai',
            model_name='gpt-test',
        )
        assert usage is not None
        self.assertEqual(usage.total_tokens, 15)
        self.assertEqual(usage.cached_input_tokens, 3)
        self.assertEqual(usage.reasoning_output_tokens, 2)

    def test_collapse_system_messages_merges_adjacent_system_chunks(self) -> None:
        collapsed = collapse_system_messages([
            {'role': 'system', 'content': 'A'},
            {'role': 'system', 'content': 'B'},
            {'role': 'user', 'content': 'hi'},
        ])
        self.assertEqual(collapsed[0], {'role': 'system', 'content': 'A\n\nB'})
        self.assertEqual(collapsed[1]['role'], 'user')

    def test_resolve_base_url_prefers_provider_specific_env_override(self) -> None:
        provider = ProviderConfig(
            adapter="openai_compat",
            base_url="https://base",
            api_key_env="MINIMAX_API_KEY",
            supports_responses_api=False,
            supports_responses_streaming=False,
            supports_chat_completions=True,
        )
        self.assertEqual(
            resolve_base_url(provider=provider, env={'MINIMAX_API_BASE': 'https://override'}),
            'https://override',
        )

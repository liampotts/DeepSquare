from .llm_client import LLMClient, build_move_prompt, extract_move_uci, post_json


class AnthropicClient(LLMClient):
    def __init__(self, api_key, model, timeout=15):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        if not self.api_key:
            raise RuntimeError('ANTHROPIC_API_KEY is missing')

        prompt = build_move_prompt(fen, legal_moves_uci, side_to_move, pgn_context)
        payload = {
            'model': self.model,
            'max_tokens': 120,
            'system': 'You are a chess move selector. Output JSON only.',
            'messages': [
                {'role': 'user', 'content': prompt},
            ],
        }
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
        }
        response = post_json(
            url='https://api.anthropic.com/v1/messages',
            headers=headers,
            payload=payload,
            timeout=self.timeout,
        )
        content_parts = response.get('content', [])
        text_chunks = [part.get('text', '') for part in content_parts if isinstance(part, dict)]
        content = '\n'.join(text_chunks)
        move_uci = extract_move_uci(content)
        if not move_uci:
            raise RuntimeError('Anthropic response did not include move_uci')
        return move_uci

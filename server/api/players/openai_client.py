from .llm_client import LLMClient, build_move_prompt, extract_move_uci, post_json


class OpenAIClient(LLMClient):
    def __init__(self, api_key, model, timeout=15):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        if not self.api_key:
            raise RuntimeError('OPENAI_API_KEY is missing')

        prompt = build_move_prompt(fen, legal_moves_uci, side_to_move, pgn_context)
        payload = {
            'model': self.model,
            'temperature': 0.1,
            'messages': [
                {'role': 'system', 'content': 'You are a chess move selector. Output JSON only.'},
                {'role': 'user', 'content': prompt},
            ],
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
        }
        response = post_json(
            url='https://api.openai.com/v1/chat/completions',
            headers=headers,
            payload=payload,
            timeout=self.timeout,
        )
        content = (
            response.get('choices', [{}])[0]
            .get('message', {})
            .get('content', '')
        )
        move_uci = extract_move_uci(content)
        if not move_uci:
            raise RuntimeError('OpenAI response did not include move_uci')
        return move_uci

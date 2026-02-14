from urllib.parse import quote

from .llm_client import LLMClient, build_move_prompt, extract_move_uci, post_json


class GeminiClient(LLMClient):
    def __init__(self, api_key, model, timeout=15):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        if not self.api_key:
            raise RuntimeError('GEMINI_API_KEY is missing')

        prompt = build_move_prompt(fen, legal_moves_uci, side_to_move, pgn_context)
        payload = {
            'contents': [
                {
                    'parts': [
                        {'text': prompt},
                    ]
                }
            ],
            'generationConfig': {'temperature': 0.1},
        }
        model_path = quote(self.model, safe='')
        response = post_json(
            url=(
                'https://generativelanguage.googleapis.com/'
                f'v1beta/models/{model_path}:generateContent?key={self.api_key}'
            ),
            headers={},
            payload=payload,
            timeout=self.timeout,
        )
        candidates = response.get('candidates', [])
        parts = []
        if candidates:
            parts = candidates[0].get('content', {}).get('parts', [])
        text_chunks = [part.get('text', '') for part in parts if isinstance(part, dict)]
        content = '\n'.join(text_chunks)
        move_uci = extract_move_uci(content)
        if not move_uci:
            raise RuntimeError('Gemini response did not include move_uci')
        return move_uci

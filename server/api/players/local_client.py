from .llm_client import LLMClient, build_move_prompt, extract_move_uci, post_json


class LocalClient(LLMClient):
    def __init__(self, model, base_url='http://127.0.0.1:11434', timeout=15):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        prompt = build_move_prompt(fen, legal_moves_uci, side_to_move, pgn_context)
        payload = {
            'model': self.model,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            'options': {'temperature': 0.1},
        }
        response = post_json(
            url=f'{self.base_url}/api/generate',
            headers={},
            payload=payload,
            timeout=self.timeout,
        )

        content = response.get('response', '')
        move_uci = extract_move_uci(content)
        if not move_uci:
            raise RuntimeError('Local model response did not include move_uci')
        return move_uci

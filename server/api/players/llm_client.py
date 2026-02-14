import json
import re
from abc import ABC, abstractmethod
from urllib import error, request


class LLMClient(ABC):
    @abstractmethod
    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        pass


def post_json(url, headers, payload, timeout):
    req = request.Request(
        url=url,
        data=json.dumps(payload).encode('utf-8'),
        headers={**headers, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'LLM HTTP error {exc.code}: {body}') from exc
    except error.URLError as exc:
        raise RuntimeError(f'LLM network error: {exc.reason}') from exc


def extract_move_uci(text):
    if not text:
        return None

    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict) and isinstance(parsed.get('move_uci'), str):
            return parsed['move_uci'].strip().lower()
    except json.JSONDecodeError:
        pass

    json_match = re.search(r'\{[^{}]*"move_uci"\s*:\s*"([a-h][1-8][a-h][1-8][qrbn]?)"[^{}]*\}', stripped, re.IGNORECASE)
    if json_match:
        return json_match.group(1).lower()

    uci_match = re.search(r'\b([a-h][1-8][a-h][1-8][qrbn]?)\b', stripped, re.IGNORECASE)
    if uci_match:
        return uci_match.group(1).lower()

    return None


def build_move_prompt(fen, legal_moves_uci, side_to_move, pgn_context=''):
    side = 'white' if side_to_move == 'w' else 'black'
    pgn_text = pgn_context.strip() or '(none)'
    return (
        'You are playing chess.\n'
        f'Side to move: {side}\n'
        f'FEN: {fen}\n'
        f'PGN so far: {pgn_text}\n'
        f'Legal moves (UCI): {", ".join(legal_moves_uci)}\n'
        'Choose exactly one move from the legal list.\n'
        'Respond with strict JSON only: {"move_uci":"<uci_from_legal_list>"}'
    )

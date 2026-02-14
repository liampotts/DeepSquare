from unittest.mock import patch

import chess
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Game
from .players.llm_player import LLMPlayer
from .players.openai_client import OpenAIClient
from .players.anthropic_client import AnthropicClient
from .players.gemini_client import GeminiClient
from .players.local_client import LocalClient


class FakeLLMClient:
    def __init__(self, response_move):
        self.response_move = response_move

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        return self.response_move


@override_settings(
    LLM_FEATURE_ENABLED=True,
    OPENAI_API_KEY='test-openai-key',
    ANTHROPIC_API_KEY='test-anthropic-key',
    GEMINI_API_KEY='test-gemini-key',
    LOCAL_LLM_ENABLED=True,
    LLM_ALLOWED_MODELS_OPENAI=['gpt-4.1-mini'],
    LLM_ALLOWED_MODELS_ANTHROPIC=['claude-3-5-sonnet-latest'],
    LLM_ALLOWED_MODELS_GEMINI=['gemini-1.5-pro'],
    LLM_ALLOWED_MODELS_LOCAL=['llama3.1:8b'],
    LLM_ADVANCED_CUSTOM_MODEL_ENABLED=True,
)
class GameApiTests(APITestCase):
    def create_game(self, **overrides):
        payload = {
            'white_player_type': 'human',
            'black_player_type': 'human',
        }
        payload.update(overrides)
        response = self.client.post(reverse('game-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def create_llm_game_payload(self, provider='openai', model='gpt-4.1-mini', custom_model=''):
        return {
            'white_player_type': 'human',
            'black_player_type': 'llm',
            'black_player_config': {
                'provider': provider,
                'model': model,
                'custom_model': custom_model,
            },
        }

    def test_create_game_returns_start_state_and_legal_moves(self):
        response_data = self.create_game()
        self.assertIn('legal_moves', response_data)
        self.assertGreater(len(response_data['legal_moves']), 0)
        self.assertIn('e2e4', response_data['legal_moves'])
        self.assertEqual(
            response_data['fen'],
            'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        )

    def test_valid_move_updates_fen_and_pgn(self):
        response_data = self.create_game()
        move_url = reverse('game-move', kwargs={'pk': response_data['id']})

        response = self.client.post(move_url, {'move_uci': 'e2e4'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('e4', response.data['pgn'])
        self.assertIn('4P3', response.data['fen'])
        self.assertEqual(response.data['fen'].split(' ')[1], 'b')

    def test_illegal_move_returns_structured_error_and_does_not_mutate(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data['id'])
        original_fen = game.fen
        original_pgn = game.pgn
        move_url = reverse('game-move', kwargs={'pk': game.id})

        response = self.client.post(move_url, {'move_uci': 'e2e5'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Illegal move')
        self.assertEqual(response.data['code'], 'illegal_move')
        self.assertEqual(response.data['move_uci'], 'e2e5')
        self.assertIn('e2e4', response.data['legal_moves'])

        game.refresh_from_db()
        self.assertEqual(game.fen, original_fen)
        self.assertEqual(game.pgn, original_pgn)

    def test_malformed_uci_returns_invalid_uci_error(self):
        response_data = self.create_game()
        move_url = reverse('game-move', kwargs={'pk': response_data['id']})

        response = self.client.post(move_url, {'move_uci': 'bad'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Invalid UCI format')
        self.assertEqual(response.data['code'], 'invalid_uci')

    def test_move_after_game_over_is_rejected(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data['id'])
        game.is_game_over = True
        game.save(update_fields=['is_game_over'])
        move_url = reverse('game-move', kwargs={'pk': game.id})

        response = self.client.post(move_url, {'move_uci': 'e2e4'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Game is already over')
        self.assertEqual(response.data['code'], 'game_over')

    def test_promotion_move_is_accepted_and_recorded(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data['id'])
        game.fen = '7k/P7/8/8/8/8/8/7K w - - 0 1'
        game.pgn = ''
        game.is_game_over = False
        game.winner = None
        game.save(update_fields=['fen', 'pgn', 'is_game_over', 'winner'])

        move_url = reverse('game-move', kwargs={'pk': game.id})
        response = self.client.post(move_url, {'move_uci': 'a7a8q'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('a8=Q', response.data['pgn'])
        self.assertTrue(response.data['fen'].startswith('Q6k/8/8/8/8/8/8/7K'))

    def test_create_llm_game_with_valid_provider_model(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='openai', model='gpt-4.1-mini'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['black_player_type'], 'llm')
        self.assertEqual(response.data['black_player_config']['provider'], 'openai')
        self.assertEqual(response.data['black_player_config']['model'], 'gpt-4.1-mini')

    def test_invalid_llm_provider_rejected(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='invalid-provider', model='x'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'llm_provider_invalid')

    def test_create_llm_game_with_local_provider_model(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='local', model='llama3.1:8b'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['black_player_type'], 'llm')
        self.assertEqual(response.data['black_player_config']['provider'], 'local')
        self.assertEqual(response.data['black_player_config']['model'], 'llama3.1:8b')

    def test_non_allowlisted_model_rejected_without_custom_override(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='openai', model='gpt-non-allowlisted'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'llm_model_not_allowed')

    def test_non_allowlisted_model_allowed_with_advanced_custom_override(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(
                provider='openai',
                model='gpt-4.1-mini',
                custom_model='gpt-custom-experimental',
            ),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['black_player_config']['custom_model'], 'gpt-custom-experimental')

    @override_settings(OPENAI_API_KEY='')
    def test_missing_provider_key_is_rejected(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='openai', model='gpt-4.1-mini'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'llm_provider_not_configured')

    @override_settings(LOCAL_LLM_ENABLED=False)
    def test_local_provider_is_rejected_when_not_enabled(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='local', model='llama3.1:8b'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'llm_provider_not_configured')

    def test_ai_options_endpoint_returns_server_allowlists(self):
        response = self.client.get(reverse('ai-options'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('openai', response.data['providers'])
        self.assertIn('anthropic', response.data['providers'])
        self.assertIn('gemini', response.data['providers'])
        self.assertIn('local', response.data['providers'])
        self.assertEqual(response.data['advanced_custom_model_enabled'], True)

    @override_settings(LOCAL_LLM_ENABLED=False)
    def test_ai_options_endpoint_hides_local_when_disabled(self):
        response = self.client.get(reverse('ai-options'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('local', response.data['providers'])

    @patch('api.views.GameViewSet._build_llm_client', return_value=FakeLLMClient('e7e5'))
    def test_move_triggers_llm_reply_for_llm_games(self, _mock_client):
        create_response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(provider='openai', model='gpt-4.1-mini'),
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        move_url = reverse('game-move', kwargs={'pk': create_response.data['id']})
        response = self.client.post(move_url, {'move_uci': 'e2e4'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # White move + automatic black LLM reply should both be in the PGN sequence.
        self.assertIn('e4', response.data['pgn'])
        self.assertIn('e5', response.data['pgn'])
        self.assertEqual(response.data['fen'].split(' ')[1], 'w')


class LLMPlayerTests(SimpleTestCase):
    def test_llm_player_falls_back_to_deterministic_legal_move(self):
        board = chess.Board()
        player = LLMPlayer(
            name='LLM Test',
            client=FakeLLMClient('z9z9'),
            color=chess.BLACK,
            max_attempts=3,
        )
        move = player.get_move(board)

        legal_uci = sorted(m.uci() for m in board.legal_moves)
        self.assertEqual(move.uci(), legal_uci[0])


class ProviderClientTests(SimpleTestCase):
    @patch('api.players.openai_client.post_json')
    def test_openai_client_parses_move(self, post_json_mock):
        post_json_mock.return_value = {
            'choices': [
                {'message': {'content': '{"move_uci":"e7e5"}'}},
            ]
        }
        client = OpenAIClient(api_key='test', model='gpt-4.1-mini')
        move = client.choose_move_uci(
            fen=chess.STARTING_FEN,
            legal_moves_uci=['e7e5', 'c7c5'],
            side_to_move='b',
        )
        self.assertEqual(move, 'e7e5')

    @patch('api.players.anthropic_client.post_json')
    def test_anthropic_client_parses_move(self, post_json_mock):
        post_json_mock.return_value = {
            'content': [
                {'type': 'text', 'text': '{"move_uci":"c7c5"}'},
            ]
        }
        client = AnthropicClient(api_key='test', model='claude-3-5-sonnet-latest')
        move = client.choose_move_uci(
            fen=chess.STARTING_FEN,
            legal_moves_uci=['e7e5', 'c7c5'],
            side_to_move='b',
        )
        self.assertEqual(move, 'c7c5')

    @patch('api.players.gemini_client.post_json')
    def test_gemini_client_parses_move(self, post_json_mock):
        post_json_mock.return_value = {
            'candidates': [
                {
                    'content': {
                        'parts': [{'text': '{"move_uci":"g8f6"}'}],
                    }
                }
            ]
        }
        client = GeminiClient(api_key='test', model='gemini-1.5-pro')
        move = client.choose_move_uci(
            fen=chess.STARTING_FEN,
            legal_moves_uci=['g8f6', 'e7e5'],
            side_to_move='b',
        )
        self.assertEqual(move, 'g8f6')

    @patch('api.players.local_client.post_json')
    def test_local_client_parses_move(self, post_json_mock):
        post_json_mock.return_value = {
            'response': '{"move_uci":"e7e5"}',
        }
        client = LocalClient(model='llama3.1:8b', base_url='http://127.0.0.1:11434')
        move = client.choose_move_uci(
            fen=chess.STARTING_FEN,
            legal_moves_uci=['e7e5', 'c7c5'],
            side_to_move='b',
        )
        self.assertEqual(move, 'e7e5')

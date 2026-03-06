from unittest.mock import patch

import chess
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ArenaRun, Game
from .analysis import AnalysisTooShortError, AnalysisUnavailableError, GameAnalysisService
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


class FakeSequenceLLMClient:
    def __init__(self, moves):
        self.moves = list(moves)
        self.index = 0

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        if self.index >= len(self.moves):
            return self.moves[-1]
        move = self.moves[self.index]
        self.index += 1
        return move


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
    ANALYSIS_FIXTURE = {
        'game_id': 999,
        'analysis_profile': 'balanced',
        'analyzed_plies': 10,
        'white': {
            'estimated_elo': 1720,
            'accuracy_percent': 81,
            'avg_centipawn_loss': 54,
            'move_counts': {
                'best': 2,
                'good': 2,
                'inaccuracy': 1,
                'mistake': 0,
                'blunder': 0,
            },
        },
        'black': {
            'estimated_elo': 1640,
            'accuracy_percent': 76,
            'avg_centipawn_loss': 68,
            'move_counts': {
                'best': 1,
                'good': 3,
                'inaccuracy': 1,
                'mistake': 0,
                'blunder': 0,
            },
        },
        'key_moves': [
            {
                'ply': 4,
                'side': 'black',
                'san': 'Nc6',
                'uci': 'b8c6',
                'category': 'inaccuracy',
                'cp_loss': 67,
                'eval_before_cp': 22,
                'eval_after_cp': 89,
                'commentary': 'Small but meaningful loss of evaluation compared to the top engine line.',
            }
        ],
        'turning_points': [
            {
                'ply': 7,
                'side': 'white',
                'san': 'd4',
                'swing_cp': 120,
                'commentary': 'This move produced one of the largest evaluation swings in the game.',
            }
        ],
        'summary': 'Detailed narrative summary.',
        'reliability': {'sufficient_sample': True, 'note': 'Performance Elo estimate for this game only.'},
    }

    def create_game(self, **overrides):
        payload = {
            'white_player_type': 'human',
            'black_player_type': 'human',
        }
        payload.update(overrides)
        response = self.client.post(reverse('game-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def create_llm_game_payload(
        self,
        provider='openai',
        model='gpt-4.1-mini',
        custom_model='',
        ttc_policy=None,
    ):
        config = {
            'provider': provider,
            'model': model,
            'custom_model': custom_model,
        }
        if ttc_policy is not None:
            config['ttc_policy'] = ttc_policy
        return {
            'white_player_type': 'human',
            'black_player_type': 'llm',
            'black_player_config': config,
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
        self.assertEqual(response.data['black_player_config']['ttc_policy']['name'], 'baseline')

    def test_create_llm_game_with_ttc_policy(self):
        response = self.client.post(
            reverse('game-list'),
            self.create_llm_game_payload(
                provider='openai',
                model='gpt-4.1-mini',
                ttc_policy={'name': 'self_consistency', 'samples': 5},
            ),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['black_player_config']['ttc_policy']['name'], 'self_consistency')
        self.assertEqual(response.data['black_player_config']['ttc_policy']['samples'], 5)

    def test_create_llm_vs_llm_game(self):
        payload = {
            'white_player_type': 'llm',
            'black_player_type': 'llm',
            'white_player_config': {
                'provider': 'openai',
                'model': 'gpt-4.1-mini',
                'custom_model': 'white-model',
            },
            'black_player_config': {
                'provider': 'openai',
                'model': 'gpt-4.1-mini',
                'custom_model': 'black-model',
            },
        }
        response = self.client.post(reverse('game-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['white_player_type'], 'llm')
        self.assertEqual(response.data['black_player_type'], 'llm')
        self.assertEqual(response.data['white_player_config']['custom_model'], 'white-model')
        self.assertEqual(response.data['black_player_config']['custom_model'], 'black-model')

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

    @patch('api.views.GameViewSet._build_llm_client')
    def test_autoplay_advances_llm_vs_llm_game(self, build_client_mock):
        def client_factory(provider, model):
            if model == 'white-model':
                return FakeSequenceLLMClient(['e2e4', 'g1f3'])
            return FakeSequenceLLMClient(['e7e5', 'b8c6'])

        build_client_mock.side_effect = client_factory
        create_response = self.client.post(
            reverse('game-list'),
            {
                'white_player_type': 'llm',
                'black_player_type': 'llm',
                'white_player_config': {
                    'provider': 'openai',
                    'model': 'gpt-4.1-mini',
                    'custom_model': 'white-model',
                },
                'black_player_config': {
                    'provider': 'openai',
                    'model': 'gpt-4.1-mini',
                    'custom_model': 'black-model',
                },
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        autoplay_url = reverse('game-autoplay', kwargs={'pk': create_response.data['id']})
        response = self.client.post(autoplay_url, {'max_plies': 4}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['autoplay_plies'], 2)
        self.assertIn('e4', response.data['pgn'])
        self.assertIn('e5', response.data['pgn'])

    @patch('api.views.build_llm_client')
    def test_arena_simulate_runs_batch_games(self, build_client_mock):
        def client_factory(provider, model):
            if model == 'player-a-model':
                return FakeSequenceLLMClient(['e2e4', 'g1f3'])
            return FakeSequenceLLMClient(['e7e5', 'b8c6'])

        build_client_mock.side_effect = client_factory

        payload = {
            'num_games': 10,
            'max_plies': 6,
            'alternate_colors': True,
            'player_a': {
                'provider': 'local',
                'model': 'llama3.1:8b',
                'custom_model': 'player-a-model',
                'ttc_policy': {'name': 'baseline'},
            },
            'player_b': {
                'provider': 'local',
                'model': 'llama3.1:8b',
                'custom_model': 'player-b-model',
                'ttc_policy': {'name': 'self_consistency', 'samples': 3},
            },
        }
        response = self.client.post(reverse('arena-simulate'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['num_games'], 10)
        self.assertEqual(len(response.data['games']), 10)
        total_a = (
            response.data['player_a']['wins']
            + response.data['player_a']['losses']
            + response.data['player_a']['draws']
        )
        self.assertEqual(total_a, 10)
        self.assertIn('summary', response.data)
        self.assertIn('avg_plies', response.data['summary'])
        self.assertIn('avg_attempts_per_move', response.data['player_a'])

    @patch('api.views.build_llm_client')
    def test_arena_runs_create_sync_and_fetch_detail(self, build_client_mock):
        def client_factory(provider, model):
            if model == 'player-a-model':
                return FakeSequenceLLMClient(['e2e4', 'g1f3', 'f1c4'])
            return FakeSequenceLLMClient(['e7e5', 'b8c6', 'g8f6'])

        build_client_mock.side_effect = client_factory

        payload = {
            'run_async': False,
            'num_games': 4,
            'max_plies': 8,
            'alternate_colors': True,
            'player_a': {
                'provider': 'local',
                'model': 'llama3.1:8b',
                'custom_model': 'player-a-model',
                'ttc_policy': {'name': 'baseline'},
            },
            'player_b': {
                'provider': 'local',
                'model': 'llama3.1:8b',
                'custom_model': 'player-b-model',
                'ttc_policy': {'name': 'uncertainty_fallback', 'samples': 3},
            },
        }
        create_response = self.client.post(reverse('arena-runs'), payload, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['status'], 'completed')
        self.assertNotIn('games', create_response.data['result'])

        detail_response = self.client.get(
            reverse('arena-run-detail', kwargs={'run_id': create_response.data['id']}) + '?include_games=1'
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['status'], 'completed')
        self.assertEqual(detail_response.data['result']['num_games'], 4)
        self.assertEqual(len(detail_response.data['result']['games']), 4)

    def test_arena_rejects_non_local_provider(self):
        payload = {
            'num_games': 2,
            'max_plies': 12,
            'alternate_colors': True,
            'player_a': {
                'provider': 'openai',
                'model': 'gpt-4.1-mini',
                'custom_model': '',
                'ttc_policy': {'name': 'baseline'},
            },
            'player_b': {
                'provider': 'local',
                'model': 'llama3.1:8b',
                'custom_model': '',
                'ttc_policy': {'name': 'baseline'},
            },
        }
        response = self.client.post(reverse('arena-simulate'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'arena_local_only')

    def test_arena_runs_list_and_not_found(self):
        run1 = ArenaRun.objects.create(
            status='completed',
            config={'num_games': 2},
            result={'num_games': 2, 'games': [{'game_index': 1}, {'game_index': 2}]},
        )
        ArenaRun.objects.create(
            status='failed',
            config={'num_games': 1},
            result={},
            error='boom',
        )

        list_response = self.client.get(reverse('arena-runs') + '?limit=1')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data['runs']), 1)
        self.assertNotIn('games', list_response.data['runs'][0].get('result', {}))

        detail_response = self.client.get(
            reverse('arena-run-detail', kwargs={'run_id': run1.id}) + '?include_games=1'
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertIn('games', detail_response.data.get('result', {}))

        missing_response = self.client.get(reverse('arena-run-detail', kwargs={'run_id': 999999}))
        self.assertEqual(missing_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing_response.data['code'], 'arena_run_not_found')

    @patch('api.views.GameAnalysisService.analyze_game')
    def test_analysis_happy_path_returns_expected_shape(self, analyze_mock):
        game = self.create_game()
        analyze_mock.return_value = {**self.ANALYSIS_FIXTURE, 'game_id': game['id']}

        response = self.client.get(reverse('game-analysis', kwargs={'pk': game['id']}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['game_id'], game['id'])
        self.assertIn('white', response.data)
        self.assertIn('black', response.data)
        self.assertIn('key_moves', response.data)
        self.assertIn('turning_points', response.data)
        self.assertIn('summary', response.data)

    @patch(
        'api.views.GameAnalysisService.analyze_game',
        side_effect=AnalysisTooShortError(min_plies=8, analyzed_plies=4),
    )
    def test_analysis_too_short_returns_structured_error(self, _analyze_mock):
        game = self.create_game()
        response = self.client.get(reverse('game-analysis', kwargs={'pk': game['id']}))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Not enough moves to analyze')
        self.assertEqual(response.data['code'], 'analysis_too_short')
        self.assertEqual(response.data['min_plies'], 8)

    @patch(
        'api.views.GameAnalysisService.analyze_game',
        side_effect=AnalysisUnavailableError('Stockfish engine unavailable'),
    )
    def test_analysis_unavailable_maps_to_503(self, _analyze_mock):
        game = self.create_game()
        response = self.client.get(reverse('game-analysis', kwargs={'pk': game['id']}))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error'], 'Analysis engine unavailable')
        self.assertEqual(response.data['code'], 'analysis_unavailable')

    @patch('api.views.GameAnalysisService.analyze_game', side_effect=RuntimeError('boom'))
    def test_analysis_unexpected_failure_maps_to_500(self, _analyze_mock):
        game = self.create_game()
        response = self.client.get(reverse('game-analysis', kwargs={'pk': game['id']}))

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['error'], 'Failed to analyze game')
        self.assertEqual(response.data['code'], 'analysis_failed')

    @patch('api.views.GameAnalysisService.analyze_game')
    def test_analysis_does_not_mutate_game_state(self, analyze_mock):
        game_data = self.create_game()
        game = Game.objects.get(pk=game_data['id'])
        original = {
            'fen': game.fen,
            'pgn': game.pgn,
            'is_game_over': game.is_game_over,
            'winner': game.winner,
        }
        analyze_mock.return_value = {**self.ANALYSIS_FIXTURE, 'game_id': game.id}

        response = self.client.get(reverse('game-analysis', kwargs={'pk': game.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        game.refresh_from_db()
        self.assertEqual(game.fen, original['fen'])
        self.assertEqual(game.pgn, original['pgn'])
        self.assertEqual(game.is_game_over, original['is_game_over'])
        self.assertEqual(game.winner, original['winner'])

    @patch('api.views.GameAnalysisService.analyze_game')
    def test_analysis_endpoint_available_for_all_modes(self, analyze_mock):
        analyze_mock.return_value = self.ANALYSIS_FIXTURE

        games = [
            self.create_game(black_player_type='human'),
            self.create_game(black_player_type='stockfish'),
            self.client.post(
                reverse('game-list'),
                self.create_llm_game_payload(provider='openai', model='gpt-4.1-mini'),
                format='json',
            ).data,
        ]

        for game_data in games:
            response = self.client.get(reverse('game-analysis', kwargs={'pk': game_data['id']}))
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('white', response.data)
            self.assertIn('black', response.data)


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


class GameAnalysisServiceMathTests(SimpleTestCase):
    def test_move_categories_follow_thresholds(self):
        service = GameAnalysisService()

        self.assertEqual(service._categorize_move(0), 'best')
        self.assertEqual(service._categorize_move(20), 'best')
        self.assertEqual(service._categorize_move(21), 'good')
        self.assertEqual(service._categorize_move(50), 'good')
        self.assertEqual(service._categorize_move(51), 'inaccuracy')
        self.assertEqual(service._categorize_move(100), 'inaccuracy')
        self.assertEqual(service._categorize_move(101), 'mistake')
        self.assertEqual(service._categorize_move(200), 'mistake')
        self.assertEqual(service._categorize_move(201), 'blunder')

    def test_side_metrics_expose_elo_accuracy_and_counts(self):
        service = GameAnalysisService()
        move_reports = [
            {'side': 'white', 'cp_loss': 10, 'category': 'best'},
            {'side': 'white', 'cp_loss': 40, 'category': 'good'},
            {'side': 'white', 'cp_loss': 120, 'category': 'mistake'},
            {'side': 'black', 'cp_loss': 30, 'category': 'good'},
            {'side': 'black', 'cp_loss': 250, 'category': 'blunder'},
        ]

        white = service._build_side_metrics('white', move_reports)
        black = service._build_side_metrics('black', move_reports)

        self.assertIn('estimated_elo', white)
        self.assertIn('accuracy_percent', white)
        self.assertIn('avg_centipawn_loss', white)
        self.assertEqual(white['move_counts']['best'], 1)
        self.assertEqual(white['move_counts']['mistake'], 1)
        self.assertEqual(black['move_counts']['blunder'], 1)

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

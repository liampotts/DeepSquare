from decimal import Decimal
from unittest.mock import patch

import chess
from django.test import SimpleTestCase

from .arena import ArenaRunCanceled, ArenaSimulationService
from .players.ttc_policy import TTCPolicyEngine


class SequenceClient:
    def __init__(self, moves):
        self.moves = list(moves)
        self.index = 0

    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        if not self.moves:
            return legal_moves_uci[0]

        if self.index >= len(self.moves):
            move = self.moves[-1]
        else:
            move = self.moves[self.index]
            self.index += 1

        if move == '__first_legal__':
            return legal_moves_uci[0]
        return move


class FirstLegalClient:
    def choose_move_uci(self, fen, legal_moves_uci, side_to_move, pgn_context=''):
        return legal_moves_uci[0]


class TTCPolicyEngineTests(SimpleTestCase):
    def test_self_consistency_selects_majority_move(self):
        engine = TTCPolicyEngine(name='self_consistency', samples=3)
        primary_client = SequenceClient(['e2e4', 'd2d4', 'e2e4'])

        result = engine.choose_move(
            primary_client=primary_client,
            legal_moves_uci=['e2e4', 'd2d4', 'g1f3'],
            fen=chess.STARTING_FEN,
            side_to_move='w',
        )

        self.assertEqual(result.move_uci, 'e2e4')
        self.assertEqual(result.attempts, 3)
        self.assertFalse(result.used_fallback)
        self.assertEqual(result.trace['policy'], 'self_consistency')
        self.assertEqual(result.trace['candidate_counts'], {'e2e4': 2, 'd2d4': 1})

    def test_uncertainty_fallback_uses_fallback_client_when_agreement_is_low(self):
        engine = TTCPolicyEngine(
            name='uncertainty_fallback',
            samples=3,
            agreement_threshold=0.8,
        )
        primary_client = SequenceClient(['e2e4', 'd2d4', 'g1f3'])
        fallback_client = SequenceClient(['c2c4'])

        result = engine.choose_move(
            primary_client=primary_client,
            fallback_client=fallback_client,
            legal_moves_uci=['e2e4', 'd2d4', 'g1f3', 'c2c4'],
            fen=chess.STARTING_FEN,
            side_to_move='w',
        )

        self.assertEqual(result.move_uci, 'c2c4')
        self.assertEqual(result.attempts, 4)
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.trace['fallback_reason'], 'low_agreement')
        self.assertAlmostEqual(result.trace['agreement_ratio'], 0.3333, places=4)

    def test_verifier_policy_uses_verifier_choice(self):
        engine = TTCPolicyEngine(name='verifier', samples=2, max_attempts=2)
        primary_client = SequenceClient(['e2e4', 'd2d4'])
        verifier_client = SequenceClient(['d2d4'])

        result = engine.choose_move(
            primary_client=primary_client,
            verifier_client=verifier_client,
            legal_moves_uci=['e2e4', 'd2d4', 'g1f3'],
            fen=chess.STARTING_FEN,
            side_to_move='w',
        )

        self.assertEqual(result.move_uci, 'd2d4')
        self.assertEqual(result.attempts, 3)
        self.assertFalse(result.used_fallback)
        self.assertTrue(result.trace['used_verifier'])
        self.assertEqual(sorted(result.trace['candidate_moves']), ['d2d4', 'e2e4'])


class ArenaSimulationServiceTests(SimpleTestCase):
    @staticmethod
    def _config(provider, model, ttc_policy, custom_model=''):
        return {
            'provider': provider,
            'model': model,
            'custom_model': custom_model,
            'ttc_policy': ttc_policy,
        }

    def test_run_aggregates_attempts_fallbacks_cost_and_latency(self):
        client_map = {
            'gpt-4.1-mini-player-a': SequenceClient(['e2e4']),
            'gpt-4.1-mini-player-b-primary': SequenceClient(['e7e5', 'c7c5', 'e7e5']),
            'gpt-4.1-mini-player-b-fallback': SequenceClient(['e7e5']),
        }

        def build_llm_client(provider, model):
            return client_map[model]

        service = ArenaSimulationService(build_llm_client=build_llm_client)
        player_a = self._config(
            provider='openai',
            model='gpt-4.1-mini',
            custom_model='gpt-4.1-mini-player-a',
            ttc_policy={'name': 'baseline', 'max_attempts': 1},
        )
        player_b = self._config(
            provider='openai',
            model='gpt-4.1-mini',
            custom_model='gpt-4.1-mini-player-b-primary',
            ttc_policy={
                'name': 'uncertainty_fallback',
                'samples': 3,
                'agreement_threshold': 0.9,
                'fallback_provider': 'openai',
                'fallback_model': 'gpt-4.1-mini-player-b-fallback',
            },
        )

        with patch(
            'api.arena.time.monotonic',
            side_effect=[
                Decimal('0.00'),
                Decimal('0.10'),
                Decimal('0.12'),
                Decimal('0.20'),
                Decimal('0.23'),
                Decimal('0.50'),
            ],
        ):
            result = service.run(
                player_a_config=player_a,
                player_b_config=player_b,
                num_games=1,
                max_plies=2,
                alternate_colors=False,
            )

        self.assertEqual(result['player_a']['moves_played'], 1)
        self.assertEqual(result['player_a']['avg_attempts_per_move'], 1.0)
        self.assertEqual(result['player_a']['fallback_rate'], 0.0)
        self.assertEqual(result['player_a']['avg_latency_ms'], 20)
        self.assertEqual(result['player_a']['estimated_cost_usd'], 0.0001)

        self.assertEqual(result['player_b']['moves_played'], 1)
        self.assertEqual(result['player_b']['avg_attempts_per_move'], 4.0)
        self.assertEqual(result['player_b']['fallback_rate'], 1.0)
        self.assertEqual(result['player_b']['avg_latency_ms'], 30)
        self.assertEqual(result['player_b']['estimated_cost_usd'], 0.0004)

        self.assertEqual(result['games'][0]['black_move_stats']['fallback_moves'], 1)
        self.assertEqual(result['games'][0]['black_move_stats']['attempts'], 4)
        self.assertEqual(result['games'][0]['duration_ms'], 500)

    def test_run_alternates_colors_across_games(self):
        def build_llm_client(provider, model):
            return FirstLegalClient()

        service = ArenaSimulationService(build_llm_client=build_llm_client)
        player_a = self._config(
            provider='local',
            model='llama3.1:8b',
            custom_model='player-a',
            ttc_policy={'name': 'baseline'},
        )
        player_b = self._config(
            provider='local',
            model='llama3.1:8b',
            custom_model='player-b',
            ttc_policy={'name': 'baseline'},
        )

        result = service.run(
            player_a_config=player_a,
            player_b_config=player_b,
            num_games=2,
            max_plies=2,
            alternate_colors=True,
        )

        self.assertEqual(result['games'][0]['white'], 'player_a')
        self.assertEqual(result['games'][0]['black'], 'player_b')
        self.assertEqual(result['games'][1]['white'], 'player_b')
        self.assertEqual(result['games'][1]['black'], 'player_a')
        self.assertEqual(result['player_a']['moves_played'], 2)
        self.assertEqual(result['player_b']['moves_played'], 2)

    def test_run_reports_progress_snapshots(self):
        progress_updates = []

        def build_llm_client(provider, model):
            return FirstLegalClient()

        service = ArenaSimulationService(build_llm_client=build_llm_client)
        player_a = self._config(
            provider='local',
            model='llama3.1:8b',
            custom_model='player-a',
            ttc_policy={'name': 'baseline'},
        )
        player_b = self._config(
            provider='local',
            model='qwen3:8b',
            custom_model='player-b',
            ttc_policy={'name': 'baseline'},
        )

        result = service.run(
            player_a_config=player_a,
            player_b_config=player_b,
            num_games=2,
            max_plies=2,
            alternate_colors=False,
            progress_callback=lambda snapshot: progress_updates.append(snapshot),
        )

        self.assertEqual(progress_updates[0]['progress']['completed_games'], 0)
        self.assertIsNone(progress_updates[0]['progress']['current_game'])
        self.assertEqual(progress_updates[-1]['progress']['completed_games'], 2)
        self.assertEqual(progress_updates[-1]['progress']['percent_complete'], 1.0)
        self.assertTrue(progress_updates[-1]['progress']['is_complete'])
        self.assertEqual(progress_updates[-1]['progress']['current_game']['game_index'], 2)
        self.assertEqual(progress_updates[-1]['progress']['current_game']['plies'], 2)
        self.assertTrue(
            any(
                snapshot['progress']['current_game']
                and snapshot['progress']['current_game']['game_index'] == 1
                and snapshot['progress']['current_game']['plies'] == 1
                for snapshot in progress_updates
            )
        )
        self.assertEqual(result['progress']['completed_games'], 2)
        self.assertEqual(result['progress']['total_games'], 2)

    def test_run_can_be_canceled_mid_game(self):
        progress_updates = []
        stop_checks = {'count': 0}

        def build_llm_client(provider, model):
            return FirstLegalClient()

        def should_stop():
            stop_checks['count'] += 1
            return stop_checks['count'] >= 3

        service = ArenaSimulationService(build_llm_client=build_llm_client)
        player_a = self._config(
            provider='local',
            model='llama3.1:8b',
            custom_model='player-a',
            ttc_policy={'name': 'baseline'},
        )
        player_b = self._config(
            provider='local',
            model='qwen3:8b',
            custom_model='player-b',
            ttc_policy={'name': 'baseline'},
        )

        with self.assertRaises(ArenaRunCanceled) as exc:
            service.run(
                player_a_config=player_a,
                player_b_config=player_b,
                num_games=2,
                max_plies=4,
                alternate_colors=False,
                progress_callback=lambda snapshot: progress_updates.append(snapshot),
                should_stop=should_stop,
            )

        self.assertEqual(exc.exception.partial_result['progress']['completed_games'], 0)
        self.assertEqual(exc.exception.partial_result['progress']['current_game']['plies'], 1)
        self.assertFalse(exc.exception.partial_result['progress']['is_complete'])
        self.assertTrue(progress_updates)

import time

import chess

from .players.llm_player import LLMPlayer


class ArenaRunCanceled(Exception):
    def __init__(self, partial_result):
        super().__init__('Arena run canceled')
        self.partial_result = partial_result


def _estimate_cost_per_call_usd(provider, model):
    provider_key = (provider or '').strip().lower()
    model_key = (model or '').strip().lower()

    if provider_key == 'local':
        return 0.0

    if provider_key == 'openai':
        if 'gpt-4.1' in model_key or 'gpt-4o' in model_key:
            return 0.00009
        return 0.00003

    if provider_key == 'anthropic':
        if 'sonnet' in model_key:
            return 0.00008
        return 0.00003

    if provider_key == 'gemini':
        if 'pro' in model_key:
            return 0.00005
        return 0.00002

    return 0.00003


def _round4(value):
    return round(float(value), 4)


class ArenaSimulationService:
    def __init__(self, build_llm_client):
        self.build_llm_client = build_llm_client

    def run(
        self,
        *,
        player_a_config,
        player_b_config,
        num_games,
        max_plies,
        alternate_colors=True,
        progress_callback=None,
        should_stop=None,
    ):
        aggregate = {
            'player_a': self._init_player_stats(),
            'player_b': self._init_player_stats(),
            'games': [],
            'total_plies': 0,
        }
        current_game = None

        if progress_callback is not None:
            progress_callback(
                self._finalize_result(
                    aggregate=aggregate,
                    completed_games=0,
                    total_games=num_games,
                    max_plies=max_plies,
                    alternate_colors=alternate_colors,
                    current_game=None,
                )
            )

        for game_index in range(num_games):
            if should_stop is not None and should_stop():
                raise ArenaRunCanceled(
                    self._finalize_result(
                        aggregate=aggregate,
                        completed_games=game_index,
                        total_games=num_games,
                        max_plies=max_plies,
                        alternate_colors=alternate_colors,
                        current_game=current_game,
                    )
                )

            if alternate_colors and game_index % 2 == 1:
                white_label = 'player_b'
                black_label = 'player_a'
                white_config = player_b_config
                black_config = player_a_config
            else:
                white_label = 'player_a'
                black_label = 'player_b'
                white_config = player_a_config
                black_config = player_b_config

            if progress_callback is not None:
                progress_callback(
                    self._finalize_result(
                        aggregate=aggregate,
                        completed_games=game_index,
                        total_games=num_games,
                        max_plies=max_plies,
                        alternate_colors=alternate_colors,
                        current_game=self._serialize_current_game(
                            board=chess.Board(),
                            game_index=game_index + 1,
                            white_label=white_label,
                            black_label=black_label,
                            pgn_text='',
                            plies=0,
                        ),
                    )
                )

            game_result = self._run_single_game(
                white_config=white_config,
                black_config=black_config,
                white_label=white_label,
                black_label=black_label,
                game_index=game_index + 1,
                max_plies=max_plies,
                game_progress_callback=(
                    (lambda current_game, completed_games=game_index: progress_callback(
                        self._finalize_result(
                            aggregate=aggregate,
                            completed_games=completed_games,
                            total_games=num_games,
                            max_plies=max_plies,
                            alternate_colors=alternate_colors,
                            current_game=current_game,
                        )
                    ))
                    if progress_callback is not None
                    else None
                ),
                should_stop=should_stop,
            )
            if game_result.get('canceled'):
                raise ArenaRunCanceled(
                    self._finalize_result(
                        aggregate=aggregate,
                        completed_games=game_index,
                        total_games=num_games,
                        max_plies=max_plies,
                        alternate_colors=alternate_colors,
                        current_game=game_result['current_game'],
                    )
                )
            current_game = game_result['current_game']

            aggregate['games'].append(
                {
                    'game_index': game_index + 1,
                    'white': white_label,
                    'black': black_label,
                    'winner': game_result['winner'],
                    'plies': game_result['plies'],
                    'duration_ms': game_result['duration_ms'],
                    'fen': current_game['fen'],
                    'pgn': current_game['pgn'],
                    'turn': current_game['turn'],
                    'is_game_over': current_game['is_game_over'],
                    'white_move_stats': game_result['white_move_stats'],
                    'black_move_stats': game_result['black_move_stats'],
                }
            )

            aggregate['total_plies'] += game_result['plies']
            self._update_scoreboard(aggregate, game_result['winner_label'])
            self._apply_move_stats(aggregate[white_label], game_result['white_move_stats'])
            self._apply_move_stats(aggregate[black_label], game_result['black_move_stats'])

            if progress_callback is not None:
                progress_callback(
                    self._finalize_result(
                        aggregate=aggregate,
                        completed_games=game_index + 1,
                        total_games=num_games,
                        max_plies=max_plies,
                        alternate_colors=alternate_colors,
                        current_game=current_game,
                    )
                )

        return self._finalize_result(
            aggregate=aggregate,
            completed_games=num_games,
            total_games=num_games,
            max_plies=max_plies,
            alternate_colors=alternate_colors,
            current_game=current_game,
        )

    def _run_single_game(
        self,
        *,
        white_config,
        black_config,
        white_label,
        black_label,
        game_index,
        max_plies,
        game_progress_callback=None,
        should_stop=None,
    ):
        board = chess.Board()
        plies = 0
        pgn_text = ''
        started = time.monotonic()

        white_player = self._build_player(white_config, chess.WHITE)
        black_player = self._build_player(black_config, chess.BLACK)

        white_stats = self._init_game_move_stats(white_config)
        black_stats = self._init_game_move_stats(black_config)

        while not board.is_game_over(claim_draw=True) and plies < max_plies:
            if should_stop is not None and should_stop():
                return {
                    'canceled': True,
                    'current_game': self._serialize_current_game(
                        board=board,
                        game_index=game_index,
                        white_label=white_label,
                        black_label=black_label,
                        pgn_text=pgn_text,
                        plies=plies,
                    ),
                }

            player = white_player if board.turn == chess.WHITE else black_player
            stats = white_stats if board.turn == chess.WHITE else black_stats

            move_started = time.monotonic()
            move = player.get_move(board)
            move_latency_ms = int((time.monotonic() - move_started) * 1000)

            if move not in board.legal_moves:
                break

            pgn_text = self._append_san_to_pgn_text(pgn_text, board, move)
            board.push(move)
            plies += 1
            self._record_move_stats(stats, player, move_latency_ms)

            if game_progress_callback is not None:
                game_progress_callback(
                    self._serialize_current_game(
                        board=board,
                        game_index=game_index,
                        white_label=white_label,
                        black_label=black_label,
                        pgn_text=pgn_text,
                        plies=plies,
                    )
                )

        winner = self._winner_from_board(board)
        if winner == 'white':
            winner_label = white_label
        elif winner == 'black':
            winner_label = black_label
        else:
            winner_label = 'draw'

        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            'canceled': False,
            'winner': winner,
            'winner_label': winner_label,
            'plies': plies,
            'duration_ms': duration_ms,
            'current_game': self._serialize_current_game(
                board=board,
                game_index=game_index,
                white_label=white_label,
                black_label=black_label,
                pgn_text=pgn_text,
                plies=plies,
            ),
            'white_move_stats': self._finalize_game_move_stats(white_stats),
            'black_move_stats': self._finalize_game_move_stats(black_stats),
        }

    def _build_player(self, config, color):
        primary_model = (config.get('custom_model') or config.get('model') or '').strip()
        primary_client = self.build_llm_client(config['provider'], primary_model)

        ttc_policy = config.get('ttc_policy') or {}
        verifier_client = self._build_aux_client(
            provider=ttc_policy.get('verifier_provider'),
            model=ttc_policy.get('verifier_model'),
        )
        fallback_client = self._build_aux_client(
            provider=ttc_policy.get('fallback_provider'),
            model=ttc_policy.get('fallback_model'),
        )

        return LLMPlayer(
            name=f"{config['provider']}:{primary_model}",
            client=primary_client,
            color=color,
            max_attempts=ttc_policy.get('max_attempts', 3),
            ttc_policy=ttc_policy,
            verifier_client=verifier_client,
            fallback_client=fallback_client,
        )

    def _build_aux_client(self, *, provider, model):
        if not provider or not model:
            return None
        return self.build_llm_client(provider, model)

    def _winner_from_board(self, board):
        if not board.is_game_over(claim_draw=True):
            return 'draw'

        outcome = board.outcome(claim_draw=True)
        if outcome is None or outcome.winner is None:
            return 'draw'

        return 'white' if outcome.winner == chess.WHITE else 'black'

    def _update_scoreboard(self, aggregate, winner_label):
        if winner_label == 'draw':
            aggregate['player_a']['draws'] += 1
            aggregate['player_b']['draws'] += 1
            return

        if winner_label == 'player_a':
            aggregate['player_a']['wins'] += 1
            aggregate['player_b']['losses'] += 1
            return

        aggregate['player_b']['wins'] += 1
        aggregate['player_a']['losses'] += 1

    def _init_player_stats(self):
        return {
            'wins': 0,
            'losses': 0,
            'draws': 0,
            'moves_played': 0,
            'total_attempts': 0,
            'fallback_moves': 0,
            'total_latency_ms': 0,
            'estimated_cost_usd': 0.0,
        }

    def _init_game_move_stats(self, config):
        model = (config.get('custom_model') or config.get('model') or '').strip()
        provider = config.get('provider')
        return {
            'provider': provider,
            'model': model,
            'policy': (config.get('ttc_policy') or {}).get('name', 'baseline'),
            'moves': 0,
            'attempts': 0,
            'fallback_moves': 0,
            'latency_ms': 0,
            'estimated_cost_usd': 0.0,
            'per_call_cost_usd': _estimate_cost_per_call_usd(provider, model),
        }

    def _record_move_stats(self, stats, player, latency_ms):
        attempts = max(1, int(getattr(player, 'last_attempt_count', 1) or 1))
        used_fallback = bool(getattr(player, 'used_fallback', False))

        stats['moves'] += 1
        stats['attempts'] += attempts
        stats['latency_ms'] += latency_ms
        stats['estimated_cost_usd'] += attempts * stats['per_call_cost_usd']
        if used_fallback:
            stats['fallback_moves'] += 1

    def _finalize_game_move_stats(self, stats):
        moves = stats['moves']
        avg_latency_ms = (stats['latency_ms'] / moves) if moves else 0.0
        avg_attempts = (stats['attempts'] / moves) if moves else 0.0
        fallback_rate = (stats['fallback_moves'] / moves) if moves else 0.0
        return {
            'provider': stats['provider'],
            'model': stats['model'],
            'policy': stats['policy'],
            'moves': moves,
            'attempts': stats['attempts'],
            'avg_attempts_per_move': _round4(avg_attempts),
            'fallback_moves': stats['fallback_moves'],
            'fallback_rate': _round4(fallback_rate),
            'avg_latency_ms': int(round(avg_latency_ms)),
            'estimated_cost_usd': _round4(stats['estimated_cost_usd']),
        }

    def _apply_move_stats(self, aggregate_player_stats, move_stats):
        aggregate_player_stats['moves_played'] += move_stats['moves']
        aggregate_player_stats['total_attempts'] += move_stats['attempts']
        aggregate_player_stats['fallback_moves'] += move_stats['fallback_moves']
        aggregate_player_stats['total_latency_ms'] += move_stats['avg_latency_ms'] * move_stats['moves']
        aggregate_player_stats['estimated_cost_usd'] += move_stats['estimated_cost_usd']

    def _append_san_to_pgn_text(self, pgn_text, board, move):
        san = board.san(move)
        if board.turn == chess.WHITE:
            return f'{pgn_text}{board.fullmove_number}. {san} '
        return f'{pgn_text}{san} '

    def _serialize_current_game(self, *, board, game_index, white_label, black_label, pgn_text, plies):
        is_game_over = board.is_game_over(claim_draw=True)
        winner = self._winner_from_board(board) if is_game_over else None
        return {
            'game_index': game_index,
            'white': white_label,
            'black': black_label,
            'fen': board.fen(),
            'pgn': pgn_text.strip(),
            'plies': plies,
            'turn': 'white' if board.turn == chess.WHITE else 'black',
            'is_game_over': is_game_over,
            'winner': winner,
        }

    def _finalize_result(self, *, aggregate, completed_games, total_games, max_plies, alternate_colors, current_game):
        player_a = self._finalize_player_stats(aggregate['player_a'], completed_games)
        player_b = self._finalize_player_stats(aggregate['player_b'], completed_games)
        decisive_games = player_a['wins'] + player_b['wins']
        draws = player_a['draws']
        avg_plies = (aggregate['total_plies'] / completed_games) if completed_games else 0.0
        latest_game = aggregate['games'][-1] if aggregate['games'] else None
        return {
            'num_games': total_games,
            'max_plies': max_plies,
            'alternate_colors': alternate_colors,
            'progress': {
                'completed_games': completed_games,
                'total_games': total_games,
                'remaining_games': max(total_games - completed_games, 0),
                'percent_complete': _round4(completed_games / total_games) if total_games else 0.0,
                'is_complete': completed_games >= total_games if total_games else True,
                'current_game': current_game,
                'latest_game': (
                    {
                        'game_index': latest_game['game_index'],
                        'winner': latest_game['winner'],
                        'plies': latest_game['plies'],
                        'duration_ms': latest_game['duration_ms'],
                    }
                    if latest_game
                    else None
                ),
            },
            'player_a': player_a,
            'player_b': player_b,
            'summary': {
                'avg_plies': _round4(avg_plies),
                'decisive_rate': _round4(decisive_games / completed_games) if completed_games else 0.0,
                'draw_rate': _round4(draws / completed_games) if completed_games else 0.0,
            },
            'games': aggregate['games'],
        }

    def _finalize_player_stats(self, stats, num_games):
        moves = stats['moves_played']
        avg_attempts = (stats['total_attempts'] / moves) if moves else 0.0
        avg_latency = (stats['total_latency_ms'] / moves) if moves else 0.0
        fallback_rate = (stats['fallback_moves'] / moves) if moves else 0.0
        win_rate = (stats['wins'] / num_games) if num_games else 0.0
        score = (stats['wins'] + (0.5 * stats['draws'])) / num_games if num_games else 0.0
        return {
            'wins': stats['wins'],
            'losses': stats['losses'],
            'draws': stats['draws'],
            'win_rate': _round4(win_rate),
            'score': _round4(score),
            'moves_played': moves,
            'avg_attempts_per_move': _round4(avg_attempts),
            'fallback_rate': _round4(fallback_rate),
            'avg_latency_ms': int(round(avg_latency)),
            'estimated_cost_usd': _round4(stats['estimated_cost_usd']),
        }

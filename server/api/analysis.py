import io
import shutil

import chess
import chess.engine
import chess.pgn
from django.conf import settings


class AnalysisTooShortError(Exception):
    def __init__(self, min_plies, analyzed_plies):
        super().__init__('Not enough moves to analyze')
        self.min_plies = min_plies
        self.analyzed_plies = analyzed_plies


class AnalysisUnavailableError(Exception):
    pass


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


class GameAnalysisService:
    CATEGORY_THRESHOLDS = (
        ('best', 20),
        ('good', 50),
        ('inaccuracy', 100),
        ('mistake', 200),
    )

    def __init__(self):
        self.profile = settings.ANALYSIS_PROFILE_DEFAULT
        self.min_plies = settings.ANALYSIS_MIN_PLIES
        self.max_plies = settings.ANALYSIS_MAX_PLIES
        self.time_limit = settings.ANALYSIS_TIME_LIMIT_SECONDS_BALANCED
        self.key_moves_limit = settings.ANALYSIS_KEY_MOVES_LIMIT
        self.turning_points_limit = settings.ANALYSIS_TURNING_POINTS_LIMIT
        self.engine_path = self._resolve_engine_path()

    def analyze_game(self, game):
        moves = self._extract_moves(game)
        if len(moves) < self.min_plies:
            raise AnalysisTooShortError(min_plies=self.min_plies, analyzed_plies=len(moves))

        moves = moves[: self.max_plies]
        move_reports = []
        engine = None

        try:
            engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            board = chess.Board()

            for ply, move in enumerate(moves, start=1):
                if move not in board.legal_moves:
                    break

                mover_is_white = board.turn == chess.WHITE
                side = 'white' if mover_is_white else 'black'
                san = board.san(move)

                eval_before_cp = self._evaluate_white_cp(engine, board)
                board.push(move)
                eval_after_cp = self._evaluate_white_cp(engine, board)

                if mover_is_white:
                    best_for_mover = eval_before_cp
                    played_for_mover = eval_after_cp
                    improvement_cp = eval_after_cp - eval_before_cp
                else:
                    best_for_mover = -eval_before_cp
                    played_for_mover = -eval_after_cp
                    improvement_cp = eval_before_cp - eval_after_cp

                cp_loss = max(0, best_for_mover - played_for_mover)
                category = self._categorize_move(cp_loss)
                swing_cp = eval_after_cp - eval_before_cp

                move_reports.append(
                    {
                        'ply': ply,
                        'side': side,
                        'san': san,
                        'uci': move.uci(),
                        'cp_loss': int(round(cp_loss)),
                        'category': category,
                        'eval_before_cp': int(round(eval_before_cp)),
                        'eval_after_cp': int(round(eval_after_cp)),
                        'swing_cp': int(round(swing_cp)),
                        'improvement_cp': int(round(improvement_cp)),
                    }
                )
        except FileNotFoundError as exc:
            raise AnalysisUnavailableError('Stockfish binary not found') from exc
        except chess.engine.EngineError as exc:
            raise AnalysisUnavailableError('Stockfish engine error') from exc
        except chess.engine.EngineTerminatedError as exc:
            raise AnalysisUnavailableError('Stockfish engine terminated unexpectedly') from exc
        finally:
            if engine is not None:
                try:
                    engine.quit()
                except Exception:
                    pass

        if len(move_reports) < self.min_plies:
            raise AnalysisTooShortError(min_plies=self.min_plies, analyzed_plies=len(move_reports))

        white_metrics = self._build_side_metrics('white', move_reports)
        black_metrics = self._build_side_metrics('black', move_reports)
        key_moves = self._build_key_moves(move_reports)
        turning_points = self._build_turning_points(move_reports)
        summary = self._build_summary(move_reports, white_metrics, black_metrics, key_moves, turning_points)

        return {
            'game_id': game.id,
            'analysis_profile': self.profile,
            'analyzed_plies': len(move_reports),
            'white': white_metrics,
            'black': black_metrics,
            'key_moves': key_moves,
            'turning_points': turning_points,
            'summary': summary,
            'reliability': {
                'sufficient_sample': len(move_reports) >= self.min_plies,
                'note': 'Performance Elo estimate for this game only.',
            },
        }

    def _extract_moves(self, game):
        pgn_text = (game.pgn or '').strip()
        if not pgn_text:
            return []

        parsed_game = chess.pgn.read_game(io.StringIO(pgn_text))
        if parsed_game is None:
            return []

        return list(parsed_game.mainline_moves())

    def _resolve_engine_path(self):
        engine_path = shutil.which('stockfish')
        if engine_path:
            return engine_path
        return '/opt/homebrew/bin/stockfish'

    def _evaluate_white_cp(self, engine, board):
        info = engine.analyse(board, chess.engine.Limit(time=self.time_limit))
        score = info.get('score')
        if score is None:
            return 0
        cp = score.pov(chess.WHITE).score(mate_score=10000)
        if cp is None:
            return 0
        return cp

    def _categorize_move(self, cp_loss):
        for category, threshold in self.CATEGORY_THRESHOLDS:
            if cp_loss <= threshold:
                return category
        return 'blunder'

    def _build_side_metrics(self, side, move_reports):
        side_moves = [move for move in move_reports if move['side'] == side]
        cp_losses = [move['cp_loss'] for move in side_moves]
        avg_cpl = int(round(sum(cp_losses) / len(cp_losses))) if cp_losses else 0

        move_counts = {
            'best': 0,
            'good': 0,
            'inaccuracy': 0,
            'mistake': 0,
            'blunder': 0,
        }
        for move in side_moves:
            move_counts[move['category']] += 1

        accuracy_percent = _clamp(int(round(100 - (0.35 * avg_cpl))), 0, 100)
        estimated_elo = _clamp(int(round(2800 - (14 * avg_cpl))), 600, 2800)

        return {
            'estimated_elo': estimated_elo,
            'accuracy_percent': accuracy_percent,
            'avg_centipawn_loss': avg_cpl,
            'move_counts': move_counts,
        }

    def _build_key_moves(self, move_reports):
        severe_moves = [move for move in move_reports if move['category'] in {'inaccuracy', 'mistake', 'blunder'}]
        severe_moves.sort(key=lambda move: move['cp_loss'], reverse=True)

        key_moves = severe_moves[: self.key_moves_limit]
        included_plies = {move['ply'] for move in key_moves}

        best_candidates = [
            move for move in move_reports if move['category'] == 'best' and move['improvement_cp'] > 0
        ]
        best_candidates.sort(key=lambda move: move['improvement_cp'], reverse=True)
        for move in best_candidates:
            if move['ply'] in included_plies:
                continue
            if len(key_moves) >= self.key_moves_limit:
                key_moves[-1] = move
            else:
                key_moves.append(move)
            break

        key_moves.sort(key=lambda move: (move['cp_loss'], move['improvement_cp']), reverse=True)
        return [self._format_key_move(move) for move in key_moves[: self.key_moves_limit]]

    def _format_key_move(self, move):
        if move['category'] == 'best':
            commentary = 'High-quality move that improved the position and kept strong practical chances.'
        elif move['category'] == 'good':
            commentary = 'Solid move that stayed close to the engine preference.'
        elif move['category'] == 'inaccuracy':
            commentary = 'Small but meaningful loss of evaluation compared to the top engine line.'
        elif move['category'] == 'mistake':
            commentary = 'Major inaccuracy that shifted momentum toward the opponent.'
        else:
            commentary = 'Critical blunder that created a large evaluation swing.'

        return {
            'ply': move['ply'],
            'side': move['side'],
            'san': move['san'],
            'uci': move['uci'],
            'category': move['category'],
            'cp_loss': move['cp_loss'],
            'eval_before_cp': move['eval_before_cp'],
            'eval_after_cp': move['eval_after_cp'],
            'commentary': commentary,
        }

    def _build_turning_points(self, move_reports):
        sign_flips = []
        for move in move_reports:
            before = move['eval_before_cp']
            after = move['eval_after_cp']
            if before == 0 or after == 0:
                continue
            if (before > 0 > after) or (before < 0 < after):
                sign_flips.append(move)

        swing_ranked = sorted(move_reports, key=lambda move: abs(move['swing_cp']), reverse=True)

        selected = []
        seen = set()
        for move in sign_flips + swing_ranked:
            if move['ply'] in seen:
                continue
            selected.append(move)
            seen.add(move['ply'])
            if len(selected) >= self.turning_points_limit:
                break

        return [self._format_turning_point(move) for move in selected]

    def _format_turning_point(self, move):
        swing = abs(move['swing_cp'])
        before = move['eval_before_cp']
        after = move['eval_after_cp']

        if before >= 0 and after < 0:
            commentary = 'This move flipped the evaluation from White advantage to Black advantage.'
        elif before <= 0 and after > 0:
            commentary = 'This move flipped the evaluation from Black advantage to White advantage.'
        else:
            commentary = 'This move produced one of the largest evaluation swings in the game.'

        return {
            'ply': move['ply'],
            'side': move['side'],
            'san': move['san'],
            'swing_cp': swing,
            'commentary': commentary,
        }

    def _build_summary(self, move_reports, white_metrics, black_metrics, key_moves, turning_points):
        last_eval = move_reports[-1]['eval_after_cp'] if move_reports else 0
        if last_eval > 75:
            final_phase = 'White finished with a stable edge.'
        elif last_eval < -75:
            final_phase = 'Black finished with a stable edge.'
        else:
            final_phase = 'The final phase stayed dynamically balanced.'

        top_key = key_moves[0] if key_moves else None
        top_turn = turning_points[0] if turning_points else None

        lines = [
            (
                f"White played at an estimated {white_metrics['estimated_elo']} level with "
                f"{white_metrics['accuracy_percent']}% accuracy "
                f"(avg CPL {white_metrics['avg_centipawn_loss']})."
            ),
            (
                f"Black played at an estimated {black_metrics['estimated_elo']} level with "
                f"{black_metrics['accuracy_percent']}% accuracy "
                f"(avg CPL {black_metrics['avg_centipawn_loss']})."
            ),
        ]

        if top_key:
            lines.append(
                f"Key move #{top_key['ply']} ({top_key['side']}) {top_key['san']} was classified as "
                f"{top_key['category']} with a {top_key['cp_loss']} centipawn impact."
            )

        if top_turn:
            lines.append(
                f"The main turning point came on move #{top_turn['ply']} ({top_turn['side']}) {top_turn['san']}, "
                f"creating a {top_turn['swing_cp']} centipawn swing."
            )

        lines.append(final_phase)
        lines.append('This report estimates game performance only and does not represent account rating.')
        return ' '.join(lines)

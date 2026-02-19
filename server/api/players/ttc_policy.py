from collections import Counter
from dataclasses import dataclass


SUPPORTED_TTC_POLICIES = {
    'baseline',
    'self_consistency',
    'verifier',
    'uncertainty_fallback',
}


@dataclass
class TTCPolicyResult:
    move_uci: str
    attempts: int
    used_fallback: bool
    trace: dict


class TTCPolicyEngine:
    def __init__(
        self,
        name='baseline',
        samples=3,
        max_attempts=3,
        agreement_threshold=0.67,
    ):
        self.name = name if name in SUPPORTED_TTC_POLICIES else 'baseline'
        self.samples = max(1, int(samples))
        self.max_attempts = max(1, int(max_attempts))
        self.agreement_threshold = float(agreement_threshold)

    @classmethod
    def from_config(cls, config, max_attempts=3):
        policy = config or {}
        return cls(
            name=policy.get('name', 'baseline'),
            samples=policy.get('samples', 3),
            max_attempts=policy.get('max_attempts', max_attempts),
            agreement_threshold=policy.get('agreement_threshold', 0.67),
        )

    def choose_move(
        self,
        *,
        primary_client,
        legal_moves_uci,
        fen,
        side_to_move,
        pgn_context='',
        verifier_client=None,
        fallback_client=None,
    ):
        legal = sorted(legal_moves_uci)
        default_move = legal[0]

        if self.name == 'self_consistency':
            return self._self_consistency(
                primary_client=primary_client,
                fallback_client=fallback_client,
                legal_moves_uci=legal,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
                default_move=default_move,
            )

        if self.name == 'verifier':
            return self._verifier(
                primary_client=primary_client,
                verifier_client=verifier_client,
                legal_moves_uci=legal,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
                default_move=default_move,
            )

        if self.name == 'uncertainty_fallback':
            return self._uncertainty_fallback(
                primary_client=primary_client,
                fallback_client=fallback_client,
                legal_moves_uci=legal,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
                default_move=default_move,
            )

        return self._baseline(
            primary_client=primary_client,
            fallback_client=fallback_client,
            legal_moves_uci=legal,
            fen=fen,
            side_to_move=side_to_move,
            pgn_context=pgn_context,
            default_move=default_move,
        )

    def _baseline(
        self,
        *,
        primary_client,
        fallback_client,
        legal_moves_uci,
        fen,
        side_to_move,
        pgn_context,
        default_move,
    ):
        attempts = 0
        for _ in range(self.max_attempts):
            attempts += 1
            move = self._try_move(
                primary_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move:
                return TTCPolicyResult(
                    move_uci=move,
                    attempts=attempts,
                    used_fallback=False,
                    trace={
                        'policy': 'baseline',
                        'attempts': attempts,
                    },
                )

        if fallback_client is not None:
            attempts += 1
            move = self._try_move(
                fallback_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move:
                return TTCPolicyResult(
                    move_uci=move,
                    attempts=attempts,
                    used_fallback=True,
                    trace={
                        'policy': 'baseline',
                        'attempts': attempts,
                        'fallback_reason': 'primary_failed',
                    },
                )

        return TTCPolicyResult(
            move_uci=default_move,
            attempts=attempts,
            used_fallback=True,
            trace={
                'policy': 'baseline',
                'attempts': attempts,
                'fallback_reason': 'deterministic_legal_default',
            },
        )

    def _self_consistency(
        self,
        *,
        primary_client,
        fallback_client,
        legal_moves_uci,
        fen,
        side_to_move,
        pgn_context,
        default_move,
    ):
        attempts = 0
        candidates = []

        for _ in range(self.samples):
            attempts += 1
            move = self._try_move(
                primary_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move:
                candidates.append(move)

        if candidates:
            counts = Counter(candidates)
            selected_move, selected_votes = sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[0]
            return TTCPolicyResult(
                move_uci=selected_move,
                attempts=attempts,
                used_fallback=False,
                trace={
                    'policy': 'self_consistency',
                    'attempts': attempts,
                    'candidate_counts': dict(counts),
                    'selected_votes': selected_votes,
                    'selected_move': selected_move,
                },
            )

        if fallback_client is not None:
            attempts += 1
            move = self._try_move(
                fallback_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move:
                return TTCPolicyResult(
                    move_uci=move,
                    attempts=attempts,
                    used_fallback=True,
                    trace={
                        'policy': 'self_consistency',
                        'attempts': attempts,
                        'fallback_reason': 'no_valid_candidates',
                    },
                )

        return TTCPolicyResult(
            move_uci=default_move,
            attempts=attempts,
            used_fallback=True,
            trace={
                'policy': 'self_consistency',
                'attempts': attempts,
                'fallback_reason': 'deterministic_legal_default',
            },
        )

    def _verifier(
        self,
        *,
        primary_client,
        verifier_client,
        legal_moves_uci,
        fen,
        side_to_move,
        pgn_context,
        default_move,
    ):
        attempts = 0
        unique_candidates = []
        seen = set()
        max_calls = max(self.samples * 2, self.max_attempts)

        for _ in range(max_calls):
            if len(unique_candidates) >= self.samples:
                break
            attempts += 1
            move = self._try_move(
                primary_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move and move not in seen:
                seen.add(move)
                unique_candidates.append(move)

        if not unique_candidates:
            return TTCPolicyResult(
                move_uci=default_move,
                attempts=attempts,
                used_fallback=True,
                trace={
                    'policy': 'verifier',
                    'attempts': attempts,
                    'fallback_reason': 'no_valid_candidates',
                },
            )

        if len(unique_candidates) == 1:
            return TTCPolicyResult(
                move_uci=unique_candidates[0],
                attempts=attempts,
                used_fallback=False,
                trace={
                    'policy': 'verifier',
                    'attempts': attempts,
                    'candidate_moves': unique_candidates,
                    'selected_move': unique_candidates[0],
                },
            )

        if verifier_client is not None:
            attempts += 1
            verified_move = self._try_move(
                verifier_client,
                legal_moves_uci=sorted(unique_candidates),
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if verified_move in seen:
                return TTCPolicyResult(
                    move_uci=verified_move,
                    attempts=attempts,
                    used_fallback=False,
                    trace={
                        'policy': 'verifier',
                        'attempts': attempts,
                        'candidate_moves': unique_candidates,
                        'selected_move': verified_move,
                        'used_verifier': True,
                    },
                )

        selected_move = sorted(unique_candidates)[0]
        return TTCPolicyResult(
            move_uci=selected_move,
            attempts=attempts,
            used_fallback=True,
            trace={
                'policy': 'verifier',
                'attempts': attempts,
                'candidate_moves': unique_candidates,
                'selected_move': selected_move,
                'fallback_reason': 'verifier_unavailable_or_invalid',
            },
        )

    def _uncertainty_fallback(
        self,
        *,
        primary_client,
        fallback_client,
        legal_moves_uci,
        fen,
        side_to_move,
        pgn_context,
        default_move,
    ):
        attempts = 0
        candidates = []

        for _ in range(self.samples):
            attempts += 1
            move = self._try_move(
                primary_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if move:
                candidates.append(move)

        if candidates:
            counts = Counter(candidates)
            selected_move, selected_votes = sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[0]
            agreement_ratio = selected_votes / len(candidates)

            if agreement_ratio >= self.agreement_threshold:
                return TTCPolicyResult(
                    move_uci=selected_move,
                    attempts=attempts,
                    used_fallback=False,
                    trace={
                        'policy': 'uncertainty_fallback',
                        'attempts': attempts,
                        'candidate_counts': dict(counts),
                        'agreement_ratio': round(agreement_ratio, 4),
                        'selected_move': selected_move,
                    },
                )

            if fallback_client is not None:
                attempts += 1
                fallback_move = self._try_move(
                    fallback_client,
                    legal_moves_uci=legal_moves_uci,
                    fen=fen,
                    side_to_move=side_to_move,
                    pgn_context=pgn_context,
                )
                if fallback_move:
                    return TTCPolicyResult(
                        move_uci=fallback_move,
                        attempts=attempts,
                        used_fallback=True,
                        trace={
                            'policy': 'uncertainty_fallback',
                            'attempts': attempts,
                            'candidate_counts': dict(counts),
                            'agreement_ratio': round(agreement_ratio, 4),
                            'fallback_reason': 'low_agreement',
                            'selected_move': fallback_move,
                        },
                    )

            return TTCPolicyResult(
                move_uci=selected_move,
                attempts=attempts,
                used_fallback=False,
                trace={
                    'policy': 'uncertainty_fallback',
                    'attempts': attempts,
                    'candidate_counts': dict(counts),
                    'agreement_ratio': round(agreement_ratio, 4),
                    'selected_move': selected_move,
                },
            )

        if fallback_client is not None:
            attempts += 1
            fallback_move = self._try_move(
                fallback_client,
                legal_moves_uci=legal_moves_uci,
                fen=fen,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
            if fallback_move:
                return TTCPolicyResult(
                    move_uci=fallback_move,
                    attempts=attempts,
                    used_fallback=True,
                    trace={
                        'policy': 'uncertainty_fallback',
                        'attempts': attempts,
                        'fallback_reason': 'no_valid_candidates',
                        'selected_move': fallback_move,
                    },
                )

        return TTCPolicyResult(
            move_uci=default_move,
            attempts=attempts,
            used_fallback=True,
            trace={
                'policy': 'uncertainty_fallback',
                'attempts': attempts,
                'fallback_reason': 'deterministic_legal_default',
                'selected_move': default_move,
            },
        )

    def _try_move(self, client, *, legal_moves_uci, fen, side_to_move, pgn_context=''):
        if client is None:
            return None

        try:
            move_uci = client.choose_move_uci(
                fen=fen,
                legal_moves_uci=legal_moves_uci,
                side_to_move=side_to_move,
                pgn_context=pgn_context,
            )
        except Exception:
            return None

        if move_uci in legal_moves_uci:
            return move_uci
        return None

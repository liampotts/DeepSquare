from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Game


class GameApiTests(APITestCase):
    def create_game(self, **overrides):
        payload = {
            "white_player_type": "human",
            "black_player_type": "human",
        }
        payload.update(overrides)
        response = self.client.post(reverse("game-list"), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def test_create_game_returns_start_state_and_legal_moves(self):
        response_data = self.create_game()
        self.assertIn("legal_moves", response_data)
        self.assertGreater(len(response_data["legal_moves"]), 0)
        self.assertIn("e2e4", response_data["legal_moves"])
        self.assertEqual(
            response_data["fen"],
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        )

    def test_valid_move_updates_fen_and_pgn(self):
        response_data = self.create_game()
        move_url = reverse("game-move", kwargs={"pk": response_data["id"]})

        response = self.client.post(move_url, {"move_uci": "e2e4"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("e4", response.data["pgn"])
        self.assertIn("4P3", response.data["fen"])
        self.assertEqual(response.data["fen"].split(" ")[1], "b")

    def test_illegal_move_returns_structured_error_and_does_not_mutate(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data["id"])
        original_fen = game.fen
        original_pgn = game.pgn
        move_url = reverse("game-move", kwargs={"pk": game.id})

        response = self.client.post(move_url, {"move_uci": "e2e5"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Illegal move")
        self.assertEqual(response.data["code"], "illegal_move")
        self.assertEqual(response.data["move_uci"], "e2e5")
        self.assertIn("e2e4", response.data["legal_moves"])

        game.refresh_from_db()
        self.assertEqual(game.fen, original_fen)
        self.assertEqual(game.pgn, original_pgn)

    def test_malformed_uci_returns_invalid_uci_error(self):
        response_data = self.create_game()
        move_url = reverse("game-move", kwargs={"pk": response_data["id"]})

        response = self.client.post(move_url, {"move_uci": "bad"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid UCI format")
        self.assertEqual(response.data["code"], "invalid_uci")

    def test_move_after_game_over_is_rejected(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data["id"])
        game.is_game_over = True
        game.save(update_fields=["is_game_over"])
        move_url = reverse("game-move", kwargs={"pk": game.id})

        response = self.client.post(move_url, {"move_uci": "e2e4"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Game is already over")
        self.assertEqual(response.data["code"], "game_over")

    def test_promotion_move_is_accepted_and_recorded(self):
        response_data = self.create_game()
        game = Game.objects.get(pk=response_data["id"])
        game.fen = "7k/P7/8/8/8/8/8/7K w - - 0 1"
        game.pgn = ""
        game.is_game_over = False
        game.winner = None
        game.save(update_fields=["fen", "pgn", "is_game_over", "winner"])

        move_url = reverse("game-move", kwargs={"pk": game.id})
        response = self.client.post(move_url, {"move_uci": "a7a8q"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("a8=Q", response.data["pgn"])
        self.assertTrue(response.data["fen"].startswith("Q6k/8/8/8/8/8/8/7K"))

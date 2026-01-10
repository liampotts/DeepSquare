import { useState, useEffect } from 'react'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import axios from 'axios'
import './App.css'

const API_Base = 'http://localhost:8001/api'

function App() {
  const [game, setGame] = useState(new Chess())
  const [gameId, setGameId] = useState(null)
  const [fen, setFen] = useState(game.fen())
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState("Select a mode to start")

  // Start a new game
  const startGame = async (blackPlayerType) => {
    setLoading(true)
    try {
      const response = await axios.post(`${API_Base}/games/`, {
        white_player_type: 'human',
        black_player_type: blackPlayerType
      })
      const newGameData = response.data
      setGameId(newGameData.id)

      const newGame = new Chess(newGameData.fen)
      setGame(newGame)
      setFen(newGame.fen())
      setStatus(`${newGameData.white_player_type} vs ${newGameData.black_player_type}`)
    } catch (error) {
      console.error("Error starting game", error)
      setStatus("Error starting game")
    }
    setLoading(false)
  }

  // Handle Move
  const onDrop = (sourceSquare, targetSquare) => {
    if (!gameId) return false

    // Attempt move locally to validate logic (optional)
    try {
      const tempGame = new Chess(game.fen())
      const move = tempGame.move({
        from: sourceSquare,
        to: targetSquare,
        promotion: 'q', // always promote to queen for simplicity
      })

      if (!move) return false // illegal

      // Make API call
      makeMove(move.uci)
      return true
    } catch (e) {
      return false
    }
  }

  const makeMove = async (moveUci) => {
    try {
      const response = await axios.post(`${API_Base}/games/${gameId}/move/`, {
        move_uci: moveUci
      })
      const gameData = response.data
      const newGame = new Chess(gameData.fen)
      setGame(newGame)
      setFen(newGame.fen())

      if (gameData.is_game_over) {
        setStatus(`Game Over! Winner: ${gameData.winner}`)
      }
    } catch (error) {
      console.error("Error making move", error)
      // If invalid, we should revert board. 
      // react-chessboard uses 'position' prop, so if we don't update 'fen', it snaps back.
      // But we optimistic update might have happened? 
      // Actually onDrop returning true makes piece move. 
      // If we don't update FEN state and key updates, it might be tricky. 
      // Simplest is to just force update game from previous state effectively reverting.
    }
  }

  return (
    <div className="app-container">
      <h1>DeepSquare Chess</h1>

      <div className="controls">
        <button onClick={() => startGame('human')} disabled={loading}>Play vs Friend</button>
        <button onClick={() => startGame('stockfish')} disabled={loading}>Play vs Stockfish</button>
      </div>

      <div className="status">{status}</div>

      <div className="board-container">
        <Chessboard
          position={fen}
          onPieceDrop={onDrop}
          boardWidth={600}
        />
      </div>
    </div>
  )
}

export default App

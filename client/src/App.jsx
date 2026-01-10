import { useState } from 'react'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import axios from 'axios'
import './App.css'

const API_Base = 'http://localhost:8001/api'

// Simple mapping for text-based icons or use images
const getPieceIcon = (pieceChar) => {
  const icons = {
    p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚'
  }
  return icons[pieceChar] || pieceChar
}

function App() {
  const [game, setGame] = useState(new Chess())
  const [gameId, setGameId] = useState(null)
  const [fen, setFen] = useState(game.fen())
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState("Select a mode to start")

  // Helper to count captured pieces
  const getCapturedPieces = () => {
    const history = game.history({ verbose: true })
    const captured = { w: [], b: [] } // w: pieces captured BY white (so black pieces)

    for (const move of history) {
      if (move.captured) {
        // move.color is who moved. If 'w' moved and captured, it captured a black piece ('b')
        // But store based on who captured it? Usually we show "White's captures" (black pieces)
        if (move.color === 'w') {
          captured.w.push(move.captured)
        } else {
          captured.b.push(move.captured)
        }
      }
    }
    return captured
  }

  const captures = getCapturedPieces()

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

      const newGame = new Chess()
      if (newGameData.pgn) {
        newGame.loadPgn(newGameData.pgn)
      } else {
        newGame.load(newGameData.fen)
      }
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
      const prevPgn = game.pgn()
      const prevFen = game.fen()
      const tempGame = new Chess()
      // Use PGN if available to keep history, otherwise FEN
      if (prevPgn) {
        tempGame.loadPgn(prevPgn)
      } else {
        tempGame.load(prevFen)
      }

      const move = tempGame.move({
        from: sourceSquare,
        to: targetSquare,
        promotion: 'q',
      })

      if (!move) return false // illegal

      // Optimistically update local board so the piece actually moves
      setGame(tempGame)
      setFen(tempGame.fen())

      // Make API call
      const promotion = move.promotion ? move.promotion : ''
      const moveUci = `${move.from}${move.to}${promotion}`
      makeMove(moveUci, { prevPgn, prevFen })
      return true
    } catch (e) {
      console.error(e)
      return false
    }
  }

  const makeMove = async (moveUci, prevState) => {
    try {
      const response = await axios.post(`${API_Base}/games/${gameId}/move/`, {
        move_uci: moveUci
      })
      const gameData = response.data
      const newGame = new Chess()
      if (gameData.pgn) {
        newGame.loadPgn(gameData.pgn)
      } else {
        newGame.load(gameData.fen)
      }
      setGame(newGame)
      setFen(newGame.fen())

      if (gameData.is_game_over) {
        setStatus(`Game Over! Winner: ${gameData.winner}`)
      }
    } catch (error) {
      console.error("Error making move", error)
      if (prevState) {
        const rollbackGame = new Chess()
        if (prevState.prevPgn) {
          rollbackGame.loadPgn(prevState.prevPgn)
        } else {
          rollbackGame.load(prevState.prevFen)
        }
        setGame(rollbackGame)
        setFen(rollbackGame.fen())
      }
    }
  }

  // Generate history rows
  // game.history({ verbose: true }) returns array of objects
  const history = game.history({ verbose: true })
  const historyRows = []
  for (let i = 0; i < history.length; i += 2) {
    historyRows.push({
      num: Math.floor(i / 2) + 1,
      white: history[i],
      black: history[i + 1] || null
    })
  }

  return (
    <div className="app-container">
      <h1 className="title">DeepSquare</h1>

      <div className="game-layout">
        {/* Left Panel: Controls */}
        <div className="glass-panel controls-panel">
          <h3>Game Mode</h3>
          <div className="mode-select">
            <button onClick={() => startGame('human')} disabled={loading}>
              Play vs Friend
            </button>
            <button onClick={() => startGame('stockfish')} disabled={loading}>
              Play vs Stockfish
            </button>
          </div>
          <div className="status">{status}</div>
        </div>

        {/* Center: Board */}
        <div className="board-wrapper">
          <Chessboard
            position={fen}
            onPieceDrop={onDrop}
            boardWidth={500}
            customDarkSquareStyle={{ backgroundColor: '#779556' }}
            customLightSquareStyle={{ backgroundColor: '#ebecd0' }}
            customBoardStyle={{
              borderRadius: '4px',
              boxShadow: '0 5px 15px rgba(0, 0, 0, 0.5)'
            }}
          />
        </div>

        {/* Right Panel: Move History & Captures */}
        <div className="glass-panel info-panel">
          <h3>Captures</h3>
          <div className="captures-container">
            <div className="capture-row">
              <span>White: </span>
              {captures.w.map((p, i) => <span key={i} className={`piece-icon black-piece`}>{getPieceIcon(p)}</span>)}
            </div>
            <div className="capture-row">
              <span>Black: </span>
              {captures.b.map((p, i) => <span key={i} className={`piece-icon white-piece`}>{getPieceIcon(p)}</span>)}
            </div>
          </div>

          <h3>Move History</h3>
          <div className="history-container">
            <table className="history-table">
              <tbody>
                {historyRows.map((row) => (
                  <tr key={row.num}>
                    <td className="move-num">{row.num}.</td>
                    <td className="white-move">{row.white.san}</td>
                    <td className="black-move">{row.black ? row.black.san : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {gameId && (
            <div style={{ marginTop: '1rem', borderTop: '1px solid #ffffff20', paddingTop: '1rem' }}>
              <small>Game ID: {gameId}</small>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App

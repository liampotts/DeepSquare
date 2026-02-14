import { useEffect, useMemo, useRef, useState } from 'react'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import axios from 'axios'
import './App.css'

const API_BASE = 'http://localhost:8001/api'

const PROMOTION_OPTIONS = ['q', 'r', 'b', 'n']
const STOCKFISH_ESTIMATED_ELO = '~2500 (0.5s/move)'
const PIECE_VALUES = {
  p: 1,
  n: 3,
  b: 3,
  r: 5,
  q: 9,
  k: 0,
}

const OPPONENT_PROFILE = {
  human: {
    title: 'Human Opponent',
    details: ['Another player controls the black pieces.'],
  },
  stockfish: {
    title: 'Stockfish Engine',
    details: [
      'Engine: Stockfish (UCI)',
      'Runtime: Local server binary',
      'Strength profile: ~0.5s search per move',
    ],
  },
}

const getOpponentProfile = (blackPlayerType) =>
  OPPONENT_PROFILE[blackPlayerType] || {
    title: blackPlayerType || 'Unknown Opponent',
    details: ['No additional details available.'],
  }

const getPieceIcon = (pieceChar) => {
  const icons = {
    p: '♟',
    n: '♞',
    b: '♝',
    r: '♜',
    q: '♛',
    k: '♚',
  }
  return icons[pieceChar] || pieceChar
}

const getMaterialScore = (chessGame) => {
  const board = chessGame.board()
  let score = 0

  for (const row of board) {
    for (const square of row) {
      if (!square) continue
      const value = PIECE_VALUES[square.type] || 0
      score += square.color === 'w' ? value : -value
    }
  }

  return score
}

const getPositionStrengthLabel = (score) => {
  if (score >= 3) return `White clearly better (+${score})`
  if (score >= 1) return `White slightly better (+${score})`
  if (score <= -3) return `Black clearly better (${score})`
  if (score <= -1) return `Black slightly better (${score})`
  return 'Roughly equal (0)'
}

const createGameFromSnapshot = (snapshot) => {
  const nextGame = new Chess()
  if (snapshot.prevPgn) {
    nextGame.loadPgn(snapshot.prevPgn)
  } else {
    nextGame.load(snapshot.prevFen)
  }
  return nextGame
}

const createGameFromServer = (gameData) => {
  const nextGame = new Chess()
  if (gameData.pgn) {
    try {
      nextGame.loadPgn(gameData.pgn)
    } catch {
      nextGame.load(gameData.fen)
    }
  } else {
    nextGame.load(gameData.fen)
  }
  return nextGame
}

function App() {
  const [game, setGame] = useState(new Chess())
  const [gameId, setGameId] = useState(null)
  const [fen, setFen] = useState(game.fen())
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('Select a mode to start')
  const [selectedSquare, setSelectedSquare] = useState(null)
  const [legalTargetSquares, setLegalTargetSquares] = useState([])
  const [pendingPromotion, setPendingPromotion] = useState(null)
  const [isSubmittingMove, setIsSubmittingMove] = useState(false)
  const [moveError, setMoveError] = useState(null)
  const [opponentProfile, setOpponentProfile] = useState(null)

  const gameRef = useRef(game)
  const gameIdRef = useRef(gameId)

  useEffect(() => {
    gameRef.current = game
  }, [game])

  useEffect(() => {
    gameIdRef.current = gameId
  }, [gameId])

  const clearSelection = () => {
    setSelectedSquare(null)
    setLegalTargetSquares([])
  }

  const syncLocalGame = (nextGame) => {
    setGame(nextGame)
    gameRef.current = nextGame
    setFen(nextGame.fen())
  }

  const getGameSnapshot = (chessGame) => ({
    prevPgn: chessGame.pgn(),
    prevFen: chessGame.fen(),
  })

  const getLegalMovesFromSquare = (chessGame, square) => {
    const legalMoves = chessGame.moves({ square, verbose: true })
    const targets = new Set(legalMoves.map((move) => move.to))
    return [...targets]
  }

  const selectSquare = (square) => {
    const currentGame = gameRef.current
    const piece = currentGame.get(square)
    if (!piece || piece.color !== currentGame.turn()) {
      clearSelection()
      return
    }

    setSelectedSquare(square)
    setLegalTargetSquares(getLegalMovesFromSquare(currentGame, square))
    setMoveError(null)
  }

  const hydrateFromServer = (gameData) => {
    const nextGame = createGameFromServer(gameData)
    syncLocalGame(nextGame)
    setOpponentProfile(getOpponentProfile(gameData.black_player_type))

    if (gameData.is_game_over) {
      setStatus(`Game Over! Winner: ${gameData.winner}`)
    }
  }

  const makeMove = async (moveUci, prevState, currentGameId = gameIdRef.current) => {
    if (!currentGameId) return

    setIsSubmittingMove(true)
    setMoveError(null)

    try {
      const response = await axios.post(`${API_BASE}/games/${currentGameId}/move/`, {
        move_uci: moveUci,
      })
      hydrateFromServer(response.data)
    } catch (error) {
      const rollbackGame = createGameFromSnapshot(prevState)
      syncLocalGame(rollbackGame)
      setMoveError(error.response?.data?.error || 'Error making move')
    } finally {
      setIsSubmittingMove(false)
    }
  }

  const executeMove = (sourceSquare, targetSquare, promotion = null) => {
    const currentGame = gameRef.current
    const activeGameId = gameIdRef.current

    if (!currentGame || !activeGameId) return false

    const prevState = getGameSnapshot(currentGame)
    const tempGame = createGameFromSnapshot(prevState)

    const moveInput = {
      from: sourceSquare,
      to: targetSquare,
    }

    if (promotion) {
      moveInput.promotion = promotion
    }

    const move = tempGame.move(moveInput)
    if (!move) return false

    syncLocalGame(tempGame)
    clearSelection()
    setPendingPromotion(null)

    const promotionSuffix = move.promotion || ''
    const moveUci = `${move.from}${move.to}${promotionSuffix}`
    void makeMove(moveUci, prevState, activeGameId)
    return true
  }

  const attemptMove = (sourceSquare, targetSquare) => {
    const activeGameId = gameIdRef.current
    const currentGame = gameRef.current

    if (!activeGameId || !currentGame || isSubmittingMove || currentGame.isGameOver()) {
      return false
    }

    const candidates = currentGame
      .moves({ verbose: true })
      .filter((move) => move.from === sourceSquare && move.to === targetSquare)

    if (candidates.length === 0) {
      setMoveError('Illegal move')
      return false
    }

    if (candidates.some((move) => move.promotion)) {
      setPendingPromotion({ sourceSquare, targetSquare })
      setMoveError(null)
      return false
    }

    return executeMove(sourceSquare, targetSquare)
  }

  const handlePieceDrop = ({ sourceSquare, targetSquare }) => {
    if (!sourceSquare || !targetSquare) return false
    return attemptMove(sourceSquare, targetSquare)
  }

  const handleSquareClick = ({ piece, square }) => {
    const currentGame = gameRef.current
    const activeGameId = gameIdRef.current

    if (!activeGameId || !currentGame || isSubmittingMove || currentGame.isGameOver() || pendingPromotion) {
      return
    }

    if (selectedSquare && legalTargetSquares.includes(square)) {
      attemptMove(selectedSquare, square)
      return
    }

    if (selectedSquare && square !== selectedSquare) {
      if (piece && piece.pieceType && piece.pieceType[0] === currentGame.turn()) {
        selectSquare(square)
        return
      }
      setMoveError('Illegal move')
      clearSelection()
      return
    }

    if (selectedSquare === square) {
      clearSelection()
      return
    }

    if (piece && piece.pieceType && piece.pieceType[0] === currentGame.turn()) {
      selectSquare(square)
      return
    }

    clearSelection()
  }

  const handlePromotionChoice = (promotion) => {
    if (!pendingPromotion) return
    executeMove(pendingPromotion.sourceSquare, pendingPromotion.targetSquare, promotion)
  }

  const handlePromotionCancel = () => {
    setPendingPromotion(null)
    clearSelection()
  }

  const startGame = async (blackPlayerType) => {
    setLoading(true)
    setMoveError(null)
    clearSelection()
    setPendingPromotion(null)

    try {
      const response = await axios.post(`${API_BASE}/games/`, {
        white_player_type: 'human',
        black_player_type: blackPlayerType,
      })

      const gameData = response.data
      setGameId(gameData.id)
      gameIdRef.current = gameData.id
      hydrateFromServer(gameData)
      setStatus(`${gameData.white_player_type} vs ${gameData.black_player_type}`)
    } catch (error) {
      console.error('Error starting game', error)
      setStatus('Error starting game')
      setMoveError(error.response?.data?.error || 'Failed to start game')
    } finally {
      setLoading(false)
    }
  }

  const captures = useMemo(() => {
    const history = game.history({ verbose: true })
    const captured = { w: [], b: [] }

    for (const move of history) {
      if (!move.captured) continue
      if (move.color === 'w') {
        captured.w.push(move.captured)
      } else {
        captured.b.push(move.captured)
      }
    }

    return captured
  }, [game])

  const historyRows = useMemo(() => {
    const history = game.history({ verbose: true })
    const rows = []

    for (let i = 0; i < history.length; i += 2) {
      rows.push({
        num: Math.floor(i / 2) + 1,
        white: history[i],
        black: history[i + 1] || null,
      })
    }

    return rows
  }, [game])

  const positionStrength = useMemo(() => {
    const score = getMaterialScore(game)
    return getPositionStrengthLabel(score)
  }, [game])

  const squareStyles = useMemo(() => {
    const styles = {}

    if (selectedSquare) {
      styles[selectedSquare] = {
        boxShadow: 'inset 0 0 0 4px rgba(255, 196, 0, 0.9)',
      }
    }

    for (const square of legalTargetSquares) {
      styles[square] = {
        ...(styles[square] || {}),
        background:
          'radial-gradient(circle at center, rgba(77, 187, 121, 0.7) 0%, rgba(77, 187, 121, 0.18) 60%, transparent 62%)',
      }
    }

    return styles
  }, [selectedSquare, legalTargetSquares])

  const canInteract = Boolean(gameId) && !isSubmittingMove && !game.isGameOver() && !pendingPromotion

  const boardOptions = {
    id: 'deepsquare-board',
    position: fen,
    onPieceDrop: handlePieceDrop,
    onSquareClick: handleSquareClick,
    squareStyles,
    boardStyle: {
      borderRadius: '4px',
      boxShadow: '0 5px 15px rgba(0, 0, 0, 0.5)',
    },
    darkSquareStyle: { backgroundColor: '#779556' },
    lightSquareStyle: { backgroundColor: '#ebecd0' },
    canDragPiece: ({ piece }) => {
      if (!canInteract) return false
      return piece?.pieceType?.[0] === game.turn()
    },
  }

  return (
    <div className="app-container">
      <h1 className="title">DeepSquare</h1>

      <div className="game-layout">
        <div className="glass-panel controls-panel">
          <h3>Game Mode</h3>
          <div className="mode-select">
            <button onClick={() => startGame('human')} disabled={loading || isSubmittingMove}>
              Play vs Friend
            </button>
            <button onClick={() => startGame('stockfish')} disabled={loading || isSubmittingMove}>
              Play vs Stockfish
            </button>
          </div>
          <div className="status">{status}</div>
          {opponentProfile ? (
            <div className="opponent-info">
              <div className="opponent-title">{opponentProfile.title}</div>
              {opponentProfile.details.map((detail) => (
                <div key={detail} className="opponent-detail">
                  {detail}
                </div>
              ))}
              {opponentProfile.title === 'Stockfish Engine' ? (
                <div className="opponent-metric">Estimated Elo: {STOCKFISH_ESTIMATED_ELO}</div>
              ) : null}
              <div className="opponent-metric">Position strength: {positionStrength}</div>
            </div>
          ) : null}
          {moveError ? <div className="status error-status">{moveError}</div> : null}
          {isSubmittingMove ? <div className="status info-status">Submitting move...</div> : null}
        </div>

        <div className="board-wrapper">
          <div className="board-shell">
            <Chessboard options={boardOptions} />
          </div>
        </div>

        <div className="glass-panel info-panel">
          <h3>Captures</h3>
          <div className="captures-container">
            <div className="capture-row">
              <span>White: </span>
              {captures.w.map((piece, index) => (
                <span key={`${piece}-${index}`} className="piece-icon black-piece">
                  {getPieceIcon(piece)}
                </span>
              ))}
            </div>
            <div className="capture-row">
              <span>Black: </span>
              {captures.b.map((piece, index) => (
                <span key={`${piece}-${index}`} className="piece-icon white-piece">
                  {getPieceIcon(piece)}
                </span>
              ))}
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
          {gameId ? (
            <div style={{ marginTop: '1rem', borderTop: '1px solid #ffffff20', paddingTop: '1rem' }}>
              <small>Game ID: {gameId}</small>
            </div>
          ) : null}
        </div>
      </div>

      {pendingPromotion ? (
        <div className="promotion-overlay" role="dialog" aria-modal="true" aria-label="Choose promotion piece">
          <div className="promotion-modal">
            <h3>Choose Promotion</h3>
            <div className="promotion-options">
              {PROMOTION_OPTIONS.map((piece) => (
                <button
                  key={piece}
                  type="button"
                  className="promotion-button"
                  data-promo={piece}
                  onClick={() => handlePromotionChoice(piece)}
                >
                  {getPieceIcon(piece)}
                </button>
              ))}
            </div>
            <button type="button" className="promotion-cancel" onClick={handlePromotionCancel}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default App

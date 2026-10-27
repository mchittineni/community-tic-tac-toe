"""Community tic-tac-toe, played through GitHub issues.

Each square in the README links to a pre-filled issue titled ``ttt|move|<team>|<cell>``
(or ``ttt|move|<team>|bot`` to let the bot play). The play workflow runs this script
with the issue's title and author, which validates the move, updates
``game/state.json``, rewrites the README section between the markers, and redraws
``assets/board.svg`` (the live preview other pages, like my profile, embed).

Exit codes: 0 = move played (commit the changes), 2 = move rejected (nothing to commit).
Either way, stdout is the markdown comment posted back on the issue.

Standard library only, so the workflow needs nothing beyond a Python runtime.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "game" / "state.json"
README_FILE = ROOT / "README.md"
BOARD_SVG = ROOT / "assets" / "board.svg"
START, END = "<!-- TICTACTOE:START -->", "<!-- TICTACTOE:END -->"

REPO = os.environ.get("GITHUB_REPOSITORY", "mchittineni/community-tic-tac-toe")
BOT = "TicTacToeBot"
TITLE = re.compile(r"^ttt\|move\|(x|o)\|([1-9]|bot)$")
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
MARK = {"x": "❌", "o": "⭕"}
RECENT_MOVES = 5
LEADERBOARD_SIZE = 10


class MoveError(Exception):
    """A move that can't be played; the message is shown to the player."""


def new_state() -> dict:
    return {
        "board": [""] * 9,
        "turn": "x",
        "last_mover": None,
        "last_result": None,
        "stats": {"moves": 0, "games": 0, "x_wins": 0, "o_wins": 0, "draws": 0},
        "players": [],
        "recent": [],
        "leaderboard": {},
    }


def other(team: str) -> str:
    return "o" if team == "x" else "x"


def outcome(board: list[str]) -> str | None:
    """'x' or 'o' for a win, 'draw' for a full board, None while the game is open."""
    for a, b, c in LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if all(board) else None


def minimax(board: list[str], player: str, me: str) -> int:
    result = outcome(board)
    if result == me:
        return 1
    if result == other(me):
        return -1
    if result == "draw":
        return 0
    scores = []
    for i in (i for i, cell in enumerate(board) if not cell):
        board[i] = player
        scores.append(minimax(board, other(player), me))
        board[i] = ""
    return max(scores) if player == me else min(scores)


def best_move(board: list[str], me: str, rng: random.Random | None = None) -> int:
    """A perfect move for ``me``, picked at random among equally good options."""
    rng = rng or random.Random()
    scored = []
    for i in (i for i, cell in enumerate(board) if not cell):
        board[i] = me
        scored.append((minimax(board, other(me), me), i))
        board[i] = ""
    top = max(score for score, _ in scored)
    return rng.choice([i for score, i in scored if score == top])


def play(state: dict, title: str, user: str, rng: random.Random | None = None) -> str:
    """Apply the move in ``title`` for ``user``. Returns the comment for the issue."""
    match = TITLE.match(title.strip())
    if not match:
        raise MoveError("That issue title isn't a valid move. Use the links in the README rather than editing the title.")
    team, target = match.groups()
    board = state["board"]

    if team != state["turn"]:
        raise MoveError(
            f"It's {MARK[state['turn']]}'s turn, so this {MARK[team]} move was skipped. "
            "Someone probably moved just before you; refresh the board and try again."
        )

    if target == "bot":
        cell, mover = best_move(board, team, rng), BOT
    else:
        cell, mover = int(target) - 1, user
        if board[cell]:
            raise MoveError(f"Square {target} is already taken. Refresh the board and pick an empty square.")
        if user == state["last_mover"]:
            raise MoveError(
                "You played the last move. Let someone else take this turn, "
                "or use the link to ask the bot to play it."
            )

    board[cell] = team
    state["last_mover"] = mover
    state["stats"]["moves"] += 1
    if user not in state["players"]:
        state["players"].append(user)
    who = f"{BOT} (asked by @{user})" if mover == BOT else f"@{user}"
    state["recent"] = [{"team": team, "cell": cell + 1, "user": user, "bot": mover == BOT}] + state["recent"]
    state["recent"] = state["recent"][:RECENT_MOVES]

    result = outcome(board)
    if result is None:
        state["turn"] = other(team)
        return f"{who} placed {MARK[team]} on square {cell + 1}. It's {MARK[state['turn']]}'s turn now. Thanks for playing!"

    stats = state["stats"]
    stats["games"] += 1
    if result == "draw":
        stats["draws"] += 1
        state["last_result"] = "The last game ended in a draw 🤝"
        message = f"{who} placed {MARK[team]} on square {cell + 1}, and the game is a draw 🤝"
    else:
        stats[f"{result}_wins"] += 1
        state["leaderboard"][mover] = state["leaderboard"].get(mover, 0) + 1
        winner = f"{BOT} 🤖" if mover == BOT else f"[@{mover}](https://github.com/{mover})"
        state["last_result"] = f"{MARK[result]} won the last game. Winning move by {winner} 🏆"
        message = f"{who} placed {MARK[team]} on square {cell + 1} and won the game for {MARK[result]} 🏆"

    # Fresh board straight away; the team that didn't open the last game opens the next.
    state["board"] = [""] * 9
    state["turn"] = "o" if stats["games"] % 2 else "x"
    state["last_mover"] = None
    return message + f"\n\nA new game has started, and {MARK[state['turn']]} goes first."


# ---------------------------------------------------------------------------
# README rendering
# ---------------------------------------------------------------------------


def issue_link(title: str) -> str:
    body = "Just press 'Submit new issue' without editing the title. The board updates in about 30 seconds."
    return f"https://github.com/{REPO}/issues/new?{urlencode({'title': title, 'body': body})}"


def badge(label: str, value: int, color: str) -> str:
    return f'<img src="https://img.shields.io/badge/{label.replace(" ", "%20")}-{value}-{color}?style=flat-square" alt="{label}: {value}" />'


def render(state: dict) -> str:
    turn, stats = state["turn"], state["stats"]
    rows = []
    for r in range(3):
        cells = []
        for c in range(3):
            i = r * 3 + c
            mark = state["board"][i]
            if mark:
                img = f'<img src="assets/{mark}.svg" width="84" alt="{mark.upper()}" />'
            else:
                img = (
                    f'<a href="{issue_link(f"ttt|move|{turn}|{i + 1}")}">'
                    f'<img src="assets/blank-{i + 1}.svg" width="84" alt="Play square {i + 1}" /></a>'
                )
            cells.append(f"    <td>{img}</td>")
        rows.append("  <tr>\n" + "\n".join(cells) + "\n  </tr>")

    lines = [
        START,
        '<div align="center">',
        "",
        "<p>",
        "  " + badge("Moves played", stats["moves"], "0284c7"),
        "  " + badge("Games completed", stats["games"], "4f46e5"),
        "  " + badge("Players", len(state["players"]), "9333ea"),
        "</p>",
        "",
        f"Everyone is welcome to play! **Click an empty square** to place the next mark. It's **{MARK[turn]}**'s turn.",
        "",
        "<table>",
        "\n".join(rows),
        "</table>",
        "",
        f"Tired of waiting? [Let the bot 🤖 play {MARK[turn]}]({issue_link(f'ttt|move|{turn}|bot')})",
        "",
    ]
    if state["last_result"]:
        lines += [state["last_result"], ""]
    lines += [
        f"❌ wins: **{stats['x_wins']}** · ⭕ wins: **{stats['o_wins']}** · Draws: **{stats['draws']}**",
        "",
        "</div>",
        "",
    ]

    if state["recent"]:
        lines += ["**⏰ Most recent moves**", "", "| Team | Square | Played by |", "| :--: | :----: | --------- |"]
        for move in state["recent"]:
            by = f"{BOT} 🤖 (asked by [@{move['user']}](https://github.com/{move['user']}))" if move["bot"] else (
                f"[@{move['user']}](https://github.com/{move['user']})"
            )
            lines.append(f"| {MARK[move['team']]} | {move['cell']} | {by} |")
        lines.append("")

    if state["leaderboard"]:
        top = sorted(state["leaderboard"].items(), key=lambda kv: (-kv[1], kv[0].lower()))[:LEADERBOARD_SIZE]
        lines += ["**🏆 Leaderboard: most game-winning moves**", "", "| Player | Wins |", "| ------ | :--: |"]
        for login, wins in top:
            name = f"{BOT} 🤖" if login == BOT else f"[@{login}](https://github.com/{login})"
            lines.append(f"| {name} | {wins} |")
        lines.append("")

    lines.append(END)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live preview image
# ---------------------------------------------------------------------------

SVG_TILE = '<rect x="{x}" y="{y}" width="112" height="112" rx="18" fill="#0f172a" stroke="#1e3a8a" stroke-width="3"/>'
SVG_X = '<path d="M{a} {b} {c} {d}M{c} {b} {a} {d}" stroke="#38bdf8" stroke-width="11" stroke-linecap="round"/>'
SVG_O = '<circle cx="{cx}" cy="{cy}" r="25" fill="none" stroke="#a78bfa" stroke-width="11"/>'
SVG_NUM = (
    '<text x="{cx}" y="{cy}" dy="0.35em" text-anchor="middle" font-family="Fira Code, ui-monospace, monospace" '
    'font-size="30" font-weight="600" fill="#334155">{n}</text>'
)


def render_svg(state: dict) -> str:
    """The whole board as one self-contained SVG, for pages that can only embed an image."""
    turn, stats = state["turn"], state["stats"]
    parts = []
    for i, mark in enumerate(state["board"]):
        x, y = 8 + (i % 3) * 120, 8 + (i // 3) * 120
        cx, cy = x + 56, y + 56
        parts.append(SVG_TILE.format(x=x, y=y))
        if mark == "x":
            parts.append(SVG_X.format(a=cx - 22, b=cy - 22, c=cx + 22, d=cy + 22))
        elif mark == "o":
            parts.append(SVG_O.format(cx=cx, cy=cy))
        else:
            parts.append(SVG_NUM.format(cx=cx, cy=cy, n=i + 1))
    next_mark = (
        SVG_X.format(a=110, b=386, c=126, d=402).replace('stroke-width="11"', 'stroke-width="5"')
        if turn == "x"
        else '<circle cx="118" cy="394" r="9" fill="none" stroke="#a78bfa" stroke-width="5"/>'
    )
    caption = " · ".join(
        f"{n} {word}{'' if n == 1 else 's'}"
        for n, word in ((stats["moves"], "move"), (stats["games"], "game"), (len(state["players"]), "player"))
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="376" height="440" viewBox="0 0 376 440">'
        "<title>Community tic-tac-toe: live board</title>"
        + "".join(parts)
        + next_mark
        + '<text x="138" y="394" dy="0.35em" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="17" '
        'font-weight="600" fill="#38bdf8">to move next</text>'
        f'<text x="188" y="426" text-anchor="middle" font-family="Segoe UI, Helvetica, Arial, sans-serif" '
        f'font-size="13" fill="#64748b">{caption}</text>'
        "</svg>\n"
    )


def update_readme(state: dict) -> None:
    text = README_FILE.read_text(encoding="utf-8")
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1:
        raise SystemExit(f"README is missing the {START} / {END} markers.")
    README_FILE.write_text(text[:start] + render(state) + text[end + len(END):], encoding="utf-8")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return new_state()


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    state = load_state()
    if "--render" in sys.argv:
        save_state(state)
        update_readme(state)
        BOARD_SVG.write_text(render_svg(state), encoding="utf-8")
        return 0

    title, user = os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_USER", "")
    try:
        message = play(state, title, user)
    except MoveError as err:
        print(f"⚠️ {err}")
        return 2
    save_state(state)
    update_readme(state)
    BOARD_SVG.write_text(render_svg(state), encoding="utf-8")
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

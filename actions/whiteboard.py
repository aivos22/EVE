"""
show_working: E.V.E. writes a worked answer on the whiteboard (ui/whiteboard.py)
and only says a short version out loud.

    sir:  "Eve, how do I solve 2x + 5 = 17?"
    Gemini calls show_working(subject="Solve 2x + 5 = 17",
                              maths=["2x + 5 = 17", "2x = 12"],
                              notes=["the question", "take 5 from both sides"],
                              answer="x = 6",
                              say_aloud="Take five off both sides, then halve it. x is six, sir.")
    -> the board writes the steps out, and she says the say_aloud line.

Works with look_at_screen too: "Eve, solve the question on my screen" makes
Gemini look first, then call this with the working.

The tool runs on the brain's background thread, but only the main (window)
thread may touch the HUD. So it doesn't draw anything itself: it sends a Qt
signal, and main.py connects that to the HUD, which writes on the board.

Test it alone (no Gemini; just prints what would be written):
    .venv\\Scripts\\python -m actions board
"""

import logging

from PySide6.QtCore import QObject, Signal

MAX_STEPS = 12

diary = logging.getLogger("eve")


class _Bridge(QObject):
    # (subject, [(maths, note), ...], answer). Qt carries it safely to the window's thread.
    write = Signal(str, list, str)


bridge = _Bridge()
_connected = False


def connect(write_on_board) -> None:
    """Called by main.py with the HUD's write_on_whiteboard."""
    global _connected
    bridge.write.connect(write_on_board)
    _connected = True


def show_working(subject: str, maths: list[str], notes: list[str], answer: str, say_aloud: str) -> dict:
    """
    Write a worked, step-by-step answer on sir's whiteboard, for any question
    where seeing the working helps: solving equations, rearranging, fractions,
    simultaneous equations, differentiation, physics or chemistry calculations,
    and "how do I solve this" or "show me how" questions, including ones on
    his screen (look_at_screen first, then this). Don't use it for quick sums
    like "what's seven times eight": just say those.

    Write the working the way a good teacher would on a board: one small
    step per line, starting with the question itself, as many lines as it
    needs but no more than 12.

    Args:
        subject: A short title for the board, e.g. "Solve 2x + 5 = 17".
        maths: The lines of working, in order, each in LaTeX without $ signs,
               e.g. ["2x + 5 = 17", "2x = 12", "x = \\frac{12}{2}"].
               Use \\frac{a}{b}, x^{2}, \\sqrt{x}, \\times, \\div, \\pi, \\theta.
               Words inside maths go in \\text{...}.
        notes: One short plain-English note per line of maths saying what was
               done, e.g. "take 5 from both sides". Same number as maths;
               use "" for a line that needs none.
        answer: The final answer in LaTeX, e.g. "x = 6". It's drawn in a box
                under the working, so don't repeat it as the last line of maths.
        say_aloud: What you say out loud: the method in a few words, then the
               answer, in one or two short spoken sentences ending with
               "sir", e.g. "Add the equations to get rid of y. x is three
               and y is one, sir." Always include the answer. Don't read the
               lines out; they're on the board.
    """
    lines = [str(line).strip() for line in (maths or []) if str(line).strip()][:MAX_STEPS]
    if not lines and not str(answer or "").strip():
        return {"error": "nothing to write: maths was empty"}
    notes = [str(note or "").strip() for note in (notes or [])]
    notes += [""] * (len(lines) - len(notes))   # fewer notes than lines: leave the rest blank
    steps = list(zip(lines, notes))
    say = str(say_aloud or "").strip() or "It's on the board, sir."
    if not _connected:   # testing from the command line: no HUD to write on
        return {"written": len(steps), "would_write": {"subject": subject, "steps": steps, "answer": answer},
                "say": say}
    bridge.write.emit(str(subject or "").strip(), steps, str(answer or "").strip())
    return {"written_on_whiteboard": f"{len(steps)} steps", "say": say}

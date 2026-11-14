"""
E.V.E.'s long-term memory: facts about sir that last between sessions.

Her conversation memory (in gemini_brain.py) is short-term: the last few
exchanges, gone when she closes. THIS is what she knows about you for good:
    "Sir is vegetarian."
    "Sir's sister is called Amy."
    "Sir is building E.V.E., a desktop assistant, in Python."

The facts are kept in data/memory.json, a plain text file you can open and
edit yourself (it stays on this PC; data/ is never uploaded to GitHub).

Each fact has a number, so she can update or forget a specific one:
    memory = LongTermMemory()
    memory.remember("Sir is vegetarian.")          # -> fact 1
    memory.remember("Sir eats fish now.", replaces=1)
    memory.forget(1)
"""

import json
import os
import shutil
import threading
from datetime import date

from paths import DATA_DIR

MEMORY_FILE = DATA_DIR / "memory.json"
MAX_FACTS = 200          # a safety limit; if reached, the oldest facts make room
MAX_FACT_LENGTH = 300    # characters; a fact should be one short sentence


class LongTermMemory:
    def __init__(self, path=MEMORY_FILE):
        self.path = path
        # A "lock" stops two threads changing the facts at the same moment
        # (the brain's tools run on a background thread).
        self._lock = threading.Lock()
        self.facts: list[dict] = self._load()

    # --- Reading --------------------------------------------------------

    def as_text(self) -> str:
        """All facts as numbered lines, for her to read, e.g. '1. Sir is vegetarian.'"""
        return "\n".join(f"{fact['id']}. {fact['fact']}" for fact in self.facts)

    def __len__(self) -> int:
        return len(self.facts)

    # --- Changing -------------------------------------------------------

    def remember(self, fact: str, replaces: int = 0) -> dict:
        """
        Save a fact. If `replaces` is a fact's number, that old fact is
        swapped for this one (e.g. sir has moved house). Returns what happened.
        """
        fact = " ".join(fact.split())[:MAX_FACT_LENGTH]   # tidy spaces, cap length
        if not fact:
            return {"error": "The fact was empty"}
        with self._lock:
            if replaces:
                old = self._find(replaces)
                if old is None:
                    return {"error": f"There is no fact number {replaces}"}
                old["fact"] = fact
                old["saved"] = date.today().isoformat()
                self._save()
                return {"updated": replaces, "fact": fact}
            # Already known (ignoring capitals)? Don't store it twice.
            for existing in self.facts:
                if existing["fact"].lower() == fact.lower():
                    return {"already_known": existing["id"]}
            new = {"id": self._next_id(), "fact": fact, "saved": date.today().isoformat()}
            self.facts.append(new)
            self.facts = self.facts[-MAX_FACTS:]   # keep only the newest MAX_FACTS
            self._save()
            return {"saved": new["id"], "fact": fact}

    def forget(self, number: int) -> dict:
        """Remove one fact by its number."""
        with self._lock:
            fact = self._find(number)
            if fact is None:
                return {"error": f"There is no fact number {number}"}
            self.facts.remove(fact)
            self._save()
            return {"forgotten": number, "fact": fact["fact"]}

    def forget_everything(self) -> int:
        """
        Remove every fact. Returns how many there were. A copy of the old
        file is kept as memory.backup.json, in case it was a mistake: to undo,
        rename it back to memory.json while E.V.E. is closed.
        """
        with self._lock:
            count = len(self.facts)
            if self.path.exists():
                shutil.copyfile(self.path, self.path.with_suffix(".backup.json"))
            self.facts = []
            self._save()
            return count

    # --- The file -------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("facts", [])
        except (OSError, ValueError):
            # A damaged file: keep a copy so nothing is lost, and start empty.
            self.path.replace(self.path.with_suffix(".damaged.json"))
            return []

    def _save(self) -> None:
        # Write to a temporary file, then swap it in, so a crash halfway
        # through can never leave a half-written (broken) memory file.
        temp = self.path.with_suffix(".writing")
        text = json.dumps({"facts": self.facts}, indent=2, ensure_ascii=False)
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, self.path)

    def _find(self, number: int) -> dict | None:
        return next((fact for fact in self.facts if fact["id"] == number), None)

    def _next_id(self) -> int:
        return max((fact["id"] for fact in self.facts), default=0) + 1


_shared: LongTermMemory | None = None


def get_memory() -> LongTermMemory:
    """The one shared memory, used by both her tools and her brain."""
    global _shared
    if _shared is None:
        _shared = LongTermMemory()
    return _shared


if __name__ == "__main__":
    # Show what's stored:  .venv\Scripts\python -m brain.memory
    memory = LongTermMemory()
    print(f"{len(memory)} facts in {memory.path}")
    print(memory.as_text() or "(nothing yet)")

"""Banter novelty check (W16): a repeated line is rerolled once, then replaced by the keyed line.

A line whose word set has Jaccard similarity of at least 0.5 with any of the trenchie's last 20
posted lines is a repeat. A repeat is rerolled once (the reroll is metered against the daily caps);
a second repeat is replaced by the sheet's keyed line for the moment, marked "repeat" so the feed
never pretends it was a fresh line. The card carries the last 3 posted lines. A line gets at most one
reply. Standard library only; no model call happens here: the caller supplies the generator.
"""

from collections import deque
import re

WINDOW = 20           # posted lines compared against
CARD_LINES = 3        # posted lines the card carries
REPEAT_LABEL = "repeat"
WORD = re.compile(r"[a-z0-9']+")


def words(text):
    return frozenset(WORD.findall(text.lower()))


def is_repeat_of(a, b):
    """Jaccard(a, b) >= 1/2, in integers: 2 * |a & b| >= |a | b|. Empty sets never repeat."""
    if not a or not b:
        return False
    return 2 * len(a & b) >= len(a | b)


class Voice:
    """One trenchie's posted-line memory, kept by the house runtime."""

    def __init__(self, name, keyed, window=WINDOW):
        if not keyed:
            raise ValueError("a keyed line is required for every moment the sheet names")
        self.name, self.keyed = name, dict(keyed)
        self.posted = deque(maxlen=window)
        self.replied = set()
        self.stats = {"posted": 0, "rerolls": 0, "keyed": 0, "repeats_posted": 0}

    def repeats(self, line):
        w = words(line)
        return any(is_repeat_of(w, words(old)) for old in self.posted)

    def card_lines(self):
        """The last three posted lines, oldest first, for the card the model reads."""
        return list(self.posted)[-CARD_LINES:]

    def post(self, generate, moment, on_reroll=None):
        """generate() returns one candidate line; on_reroll() is called before the one reroll.

        Returns {"text", "label", "source", "rerolled"}. label is None for a fresh line.
        """
        line, rerolled, source = generate(), 0, "model"
        if self.repeats(line):
            if on_reroll is not None:
                on_reroll()
            self.stats["rerolls"] += 1
            rerolled, source = 1, "reroll"
            line = generate()
            if self.repeats(line):
                line, source = self.keyed[moment], "keyed"
                self.stats["keyed"] += 1
        label = REPEAT_LABEL if source == "keyed" else None
        if source != "keyed" and self.repeats(line):
            self.stats["repeats_posted"] += 1
        self.posted.append(line)
        self.stats["posted"] += 1
        return {"text": line, "label": label, "source": source, "rerolled": rerolled}

    def may_reply(self, line_id):
        """A line gets at most one reply; the first asker wins."""
        if line_id in self.replied:
            return False
        self.replied.add(line_id)
        return True


def run_lines(sheet, generator, count=WINDOW, on_reroll=None):
    """Post `count` lines for one sheet; returns the numbers the W16 check prints."""
    voice = Voice(sheet["name"], sheet["keyed"])
    moments = sorted(sheet["keyed"])
    posted = [voice.post(generator, moments[i % len(moments)], on_reroll) for i in range(count)]
    # Measured after the fact, from the posted list alone: a fresh (unlabelled) line that repeats any of the
    # previous 20 posted lines. Not the Voice's own bookkeeping, which cannot see a miss by construction.
    texts = [p["text"] for p in posted]
    repeats = sum(1 for k, p in enumerate(posted) if p["label"] is None
                  and any(is_repeat_of(words(texts[k]), words(old)) for old in texts[max(0, k - WINDOW):k]))
    return {"sheet": sheet["name"], "lines": count, "repeats_posted": repeats,
            "rerolls": voice.stats["rerolls"], "keyed_lines": voice.stats["keyed"], "posted": posted}

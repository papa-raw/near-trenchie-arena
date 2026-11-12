"""The one public feed (F32, W17, B55): every line any trenchie posts, house or player, goes through post().

post() runs the banter guard on the line before anything stores it, so no producer can reach the feed
around the guard: a blocked line is stored as its emote, and with no block list every line is muted to
an emote and labelled "guard list missing" (B109). The raw text of a blocked or muted line is never kept;
the guard logs it by hash only.

Rate: at most one line per 10 s per trenchie (Pat, battle mode, superseding B55's 30 s), counted in sim ticks
(200 at 20 Hz), so it holds the same on a slow or paused host.

Emoji (battle mode, the persona emoji-set contract): a line may carry one emoji, picked by the speaker's AI from its own
set (`game.emoji`, else its temperament's default set). The rules live in near/lore/emoji.py; the feed only asks it,
so the feed, the persona checker and the creator cannot drift. A missing or invalid pick is the set's first emoji,
flagged `emoji_fallback`, never silent. A line may carry one reply, never an open conversation: a second reply to
the same line is refused, and a reply to a reply is refused.

Repeats: a house line whose words repeat one of that trenchie's last 20 house lines (the novelty check's
Jaccard >= 0.5) is refused as "repeat", whichever path produced it: a reflex line from its plan, its plan's own
say, or banter. A labelled line ("repeat", "autopilot") is posted, because its label already says it is not
fresh. A player's lines are not checked: its AI may repeat on purpose (a reflex with repeat: true).

The feed keeps the last 200 lines in memory; nothing is written to disk. Standard library only.
"""

from collections import deque

try:
    from . import guard as guard_mod
    from . import novelty
except ImportError:
    import guard as guard_mod
    import novelty

RATE_TICKS = 200                 # 10 s at 20 Hz (Pat, battle mode: one line per 10 s per fighter, superseding B55's 30 s)
KEEP = 200
MAX_CHARS = 140
SOURCES = ("house", "player")


def _emoji_rules():
    """near/lore/emoji.py, loaded by path like sheets.py loads the persona checker; None until it exists."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "lore" / "emoji.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("trenchie_lore_emoji", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EMOJI = _emoji_rules()


def _emoji(game, chosen):
    """The row's emoji fields, from the speaker's own set; {} when there is no game block or no rules module."""
    if game is None or _EMOJI is None:
        return {}
    return dict(_EMOJI.pick(game, chosen))


class PublicFeed:
    def __init__(self, guard, on_post=None, rate_ticks=RATE_TICKS, keep=KEEP, game_of=None):
        self.guard, self.on_post, self.rate = guard, on_post, rate_ticks
        self.game_of = game_of           # who -> the speaker's game block (for its emoji set), or None
        self.voice_emoji = {}            # who -> the emoji its AI last picked (a line or a plan), for lines it did not pick
        self.rows = deque(maxlen=keep)
        self.next_id = 1
        self.last_tick = {}
        self.house_words = {}            # who -> word sets of its last novelty.WINDOW house lines
        self.high_tick = -1              # the latest tick any line carried: a new arena's clock starts after it
        self.replied = set()
        self.reply_of = {}
        self.counts = {"posted": 0, "blocked": 0, "muted": 0, "refused": 0}

    @property
    def missing(self):
        return self.guard.missing

    def set_voice_emoji(self, who, emoji):
        """A plan's AI-picked emoji becomes the fighter's voice for the reflex lines that plan says (if it is in its set)."""
        game = self.game_of(who) if self.game_of else None
        picked = _emoji(game, emoji)
        if picked.get("emoji") and not picked.get("emoji_fallback"):
            self.voice_emoji[who] = picked["emoji"]

    def notice(self):
        return self.guard.notice()

    def post(self, who, text, *, source, tick, label=None, reply_to=None, emoji=None):
        """Guard, rate-limit and store one line. Returns the stored row, or {"refused": code, ...}."""
        if source not in SOURCES:
            raise ValueError("source is house or player")
        line = " ".join(str(text).split())[:MAX_CHARS]
        if not line:
            return self._refuse("empty")
        last = self.last_tick.get(who)
        if last is not None and tick - last < self.rate:
            return self._refuse("rate_limited", retry_after_s=-(-(self.rate - (tick - last)) // 20))
        said = novelty.words(line)
        recent = self.house_words.get(who, ()) if source == "house" and label is None else ()
        if any(novelty.is_repeat_of(said, old) for old in recent):
            return self._refuse("repeat")
        if reply_to is not None:
            if reply_to not in self.reply_of:
                return self._refuse("no_such_line")
            if self.reply_of[reply_to] is not None:
                return self._refuse("reply_to_a_reply")
            if reply_to in self.replied:
                return self._refuse("already_replied")
        checked = self.guard.check(line, who=who)
        muted = checked["blocked"] and checked["reason"] == "guard-list-missing"
        row = {"id": self.next_id, "tick": tick, "who": who, "text": checked["text"], "source": source,
               "label": guard_mod.MISSING_NOTICE if muted else label, "blocked": checked["blocked"] and not muted,
               "muted": muted, "reply_to": reply_to}
        game = self.game_of(who) if self.game_of else None
        if emoji is None and who in self.voice_emoji:   # no pick on this line (a reflex say): the AI's current emoji
            emoji, carried = self.voice_emoji[who], True
        else:
            carried = False
        row.update(_emoji(game, emoji))
        if row.get("emoji") and not row.get("emoji_fallback"):
            if carried:
                row["emoji_carried"] = True              # the AI picked it for this fighter's current plan or last line
            else:
                self.voice_emoji[who] = row["emoji"]
        self.next_id += 1
        if source == "house":
            self.house_words.setdefault(who, deque(maxlen=novelty.WINDOW)).append(said)
        self.last_tick[who] = tick
        self.high_tick = max(self.high_tick, tick)
        self.reply_of[row["id"]] = reply_to
        if reply_to is not None:
            self.replied.add(reply_to)
        self.rows.append(row)
        self.counts["posted"] += 1
        self.counts["muted" if muted else "blocked"] += checked["blocked"]
        if self.on_post is not None:
            self.on_post(dict(row))
        return dict(row)

    def _refuse(self, code, **extra):
        self.counts["refused"] += 1
        return {"refused": code, **extra}

    def since(self, after=0):
        """Public rows with an id above `after`, oldest first."""
        return [dict(r) for r in self.rows if r["id"] > after]

    def public(self, after=0):
        return {"guard": "missing" if self.missing else "loaded", "notice": self.notice(), "lines": self.since(after),
                "counts": dict(self.counts)}

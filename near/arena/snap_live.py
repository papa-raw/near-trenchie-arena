"""Line commands in, JSON-line battle events out; no model or model key enters the room."""
import json
import os
import select
import shlex
import stat
import sys
import time
from room.policy import BoundaryError

MAX_LINE = 16384
STANCES = frozenset(('flee','berserk','defend','loot','hold','follow-ally','hunt-weakest'))


class CommandError(ValueError):
    """A local refusal with a fix, before anything is signed or sent."""


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CommandError('Use each JSON key once; the order was not sent.')
        result[key] = value
    return result


def _fraction(value):
    raise CommandError('Use whole numbers in behaviours; the order was not sent.')


def parse_command(line):
    if len(line.encode('utf-8')) > MAX_LINE:
        raise CommandError('Shorten the command to at most 16384 bytes, then send it again.')
    line = line.strip()
    if not line:
        return None
    if line.startswith('{'):
        try:
            return 'behaviour', json.loads(line, object_pairs_hook=_pairs, parse_float=_fraction, parse_constant=_fraction)
        except json.JSONDecodeError:
            raise CommandError('Send one complete behaviour JSON object on one line.') from None
    if line in STANCES:
        return 'behaviour', {'v':1, 'stance':line}
    if line == 'leave':
        return 'leave', {'reason':'leave'}
    if line == 'state':
        return 'state', {}
    try:
        words = shlex.split(line)
    except ValueError:
        raise CommandError('Close the speech quotes: say "your line" [emoji].') from None
    if words and words[0] == 'say':
        if len(words) not in (2,3) or len(words) == 3 and words[2].isascii():
            raise CommandError('Put the speech line in quotes: say "your line" [emoji].')
        if not 1 <= len(words[1]) <= 140 or not words[1].isprintable():
            raise CommandError('Say one printable line of 1 to 140 characters.')
        return 'speech', {'text':words[1], 'emoji':words[2] if len(words) == 3 else None}
    raise CommandError('Send a behaviour JSON object, a stance, say "your line" [emoji], state, or leave.')


class InputLines:
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False

    def _line(self):
        if self.dropping:
            result = CommandError('Shorten the command to at most 16384 bytes, then send it again.')
        else:
            try:
                result = bytes(self.buffer).decode('utf-8')
            except UnicodeError:
                result = CommandError('Write commands as UTF-8 text, one per line.')
        self.buffer.clear()
        self.dropping = False
        return result

    def feed(self, data):
        lines = []
        for byte in data:
            if byte == 10:
                lines.append(self._line())
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE:
                    self.buffer.clear(); self.dropping = True
        return lines

    def eof(self):
        return [self._line()] if self.buffer or self.dropping else []


class LiveSession:
    def __init__(self, keeper, emit):
        self.keeper, self.emit = keeper, emit

    def command(self, line):
        try:
            if isinstance(line, CommandError):
                raise line
            command = parse_command(line)
        except CommandError as error:
            self.emit(dict(kind='refusal', code='bad_command', fix=str(error), sent=False))
            return
        if command is None:
            return
        kind, payload = command
        if kind == 'state':
            self.emit(dict(kind='state', **self.keeper.summary()))
            return
        try:
            receipt = self.keeper.client.control(kind, payload, life_id=self.keeper.life_id)
        except BoundaryError:
            if self.keeper.client._pending is not None:
                raise
            self.emit(dict(kind='refusal', code='bad_command', sent=False,
                           fix='Use bounded integer JSON: at most 16 levels and 256 entries per list, with ASCII keys.'))
            return
        if kind == 'leave':
            summary = 'Left the arena.' if receipt['state'] == 'accepted' else 'Leave refused; read state and retry.'
            self.keeper.stopping = receipt['state'] == 'accepted'
        else:
            summary = receipt['ack']['summary']
        self.emit(dict(kind='ack', receipt=receipt, summary=summary))

    def beat(self):
        for event in self.keeper.transport.poll(0.05):
            self.emit(event)
        self.keeper.tick()


def _input(path):
    if path is None:
        return sys.stdin.fileno(), False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        os.mkfifo(path, 0o600)
        info = os.lstat(path)
    if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid():
        raise CommandError('--fifo needs a named pipe owned by you; choose a new path.')
    descriptor = os.open(path, os.O_RDWR | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    info = os.fstat(descriptor)
    if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
        os.close(descriptor)
        raise CommandError('--fifo needs a private named pipe owned by you; chmod it to 600 or choose a new path.')
    return descriptor, True


def run_live(args, keeper_factory, *, refusal_fix, output=None):
    output = output or sys.stdout
    def emit(value):
        output.write(json.dumps(value, separators=(',', ':'), ensure_ascii=False) + '\n')
        output.flush()
    keeper, descriptor, own_descriptor = None, None, False
    status = 0
    try:
        if args.seconds < 0:
            raise CommandError('--seconds must be zero (until leave) or a positive whole number.')
        descriptor, own_descriptor = _input(args.fifo)
        keeper = keeper_factory(args)
        first = keeper.start(args.accept_terms)
        emit(dict(kind='session_ready', fighter_id=keeper.token, first_life=first, name_notice=keeper.ident.get('name_notice')))
        session, lines = LiveSession(keeper, emit), InputLines()
        end = time.monotonic() + args.seconds if args.seconds else None
        while not keeper.stopping and (end is None or time.monotonic() < end):
            session.beat()
            if descriptor is None or not select.select([descriptor], [], [], 0)[0]:
                continue
            chunk = os.read(descriptor, 4096)
            commands = lines.feed(chunk) if chunk else lines.eof()
            for command in commands:
                session.command(command)
                if keeper.stopping:
                    break
            if not chunk:
                descriptor = None  # A piped initial order may end; the live event stream keeps going.
    except KeyboardInterrupt:
        status = 130
        emit(dict(kind='session_ended', reason='interrupted', fix='The live connection is closing; rejoin to start a new session.'))
    except (ValueError, OSError, SystemExit) as error:
        status = 1
        code = getattr(error, 'code', None) or str(error)
        emit(dict(kind='refusal', code='live_stopped', fix=refusal_fix(str(code)) if str(code).isidentifier() else str(error),
                  summary='Live session stopped; do not assume an unanswered order applied.'))
    finally:
        if keeper is not None:
            keeper.stopping = True
            keeper.transport.close()
        if own_descriptor and descriptor is not None:
            os.close(descriptor)
    return status

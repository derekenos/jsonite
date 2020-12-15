
###############################################################################
# Exceptions
###############################################################################

class UnexpectedCharacter(Exception):
    def __init__(self, c, i):
        super().__init__(
            'Unexpected character "{}" at position {}'.format(c, i)
        )

###############################################################################
# Matchers
###############################################################################

class Matchers:
    OBJECT_OPEN = b'{'
    ARRAY_OPEN = b'['
    STRING_START = b'"'
    STRING_TERMINATOR = b'"'
    NULL_START = b'n'
    IS_NUMBER_START = lambda c: c == b'-' or c.isdigit()
    OBJECT_CLOSE = b'}'
    ARRAY_CLOSE = b']'
    KV_SEP = b':'
    ITEM_SEP = b','
    EOF = b''
    IS_NO_MATCH = lambda c: False

# Set derived matchers.
Matchers.OBJECT_KEY_START = Matchers.STRING_START
Matchers.IS_VALUE_START = lambda c: (
    c == Matchers.OBJECT_OPEN
    or c == Matchers.ARRAY_OPEN
    or c == Matchers.STRING_START
    or Matchers.IS_NUMBER_START(c)
    or c == Matchers.NULL_START
)
Matchers.IS_OBJECT_VALUE_START = lambda c: Matchers.IS_VALUE_START(c)
Matchers.IS_ARRAY_VALUE_START = lambda c: Matchers.IS_VALUE_START(c)
Matchers.IS_NEXT_OBJECT_KEY_START = \
    lambda c: c == Matchers.ITEM_SEP or c == Matchers.OBJECT_KEY_START
Matchers.IS_NEXT_ARRAY_VALUE_START = \
    lambda c: c == Matchers.ITEM_SEP or Matchers.IS_ARRAY_VALUE_START(c)

###############################################################################
# Events
###############################################################################

class Events:
    OBJECT_OPEN = 'OBJECT_OPEN'
    OBJECT_CLOSE = 'OBJECT_CLOSE'
    ARRAY_OPEN = 'ARRAY_OPEN'
    ARRAY_CLOSE = 'ARRAY_CLOSE'
    OBJECT_KEY = 'OBJECT_KEY'
    EOF = 'END_OF_FILE'
    ARRAY_VALUE_STRING = 'ARRAY_VALUE_STRING'
    ARRAY_VALUE_NUMBER = 'ARRAY_VALUE_NUMBER'
    ARRAY_VALUE_NULL = 'ARRAY_VALUE_NULL'
    OBJECT_VALUE_STRING = 'OBJECT_VALUE_STRING'
    OBJECT_VALUE_NUMBER = 'OBJECT_VALUE_NUMBER'
    OBJECT_VALUE_NULL = 'OBJECT_VALUE_NULL'
    STRING = 'STRING'
    NUMBER = 'NUMBER'
    NULL = 'NULL'

###############################################################################
# Helpers
###############################################################################

is_digit = lambda c: c.isdigit()
is_not_string_terminator = lambda c: c != Matchers.STRING_TERMINATOR

###############################################################################
# Parser
###############################################################################

class Parser:
    def __init__(self, stream):
        self.stream = stream
        # Store the current stream char number for reporting the position of
        # unexpected characters.
        self.char_num = 0
        # Store a place to stuff a character that we read from the stream but
        # need to put back for the next read. next_char() will pop this value
        # before reading again from the stream, thus providing a sort of 1-byte
        # lookahead mechanism.
        self.stuffed_char = None

    def next_char(self):
        # If there's a stuffed nonspace char, return that and do not increment
        # char_num.
        if self.stuffed_char is not None:
            c = self.stuffed_char
            self.stuffed_char = None
            return c
        # Return the next byte from the stream and increment char_num.
        c = self.stream.read(1)
        self.char_num += 1
        return c

    def next_nonspace_char(self):
        # Advance the stream past the next non-whitespace character and return
        # the character, or Matchers.EOF if the stream has been exhausted.
        while True:
            c = self.next_char()
            if c == Matchers.EOF:
                return Matchers.EOF
            if not c.isspace():
                return c

    def stuff_char(self, c):
        # Assert that stuffed_char is empty and write the character to it.
        if self.stuffed_char is not None:
            raise AssertionError
        self.stuffed_char = c

    def expect(self, matcher):
        # Assert that the next non-whitespace charater is as expected and
        # return both the character and the matcher that matched it.
        c = self.next_nonspace_char()
        # The expect_stack contains elements that are either a single matcher
        # or a tuple of matches in the format:
        #  ( <optional-matcher>, <mandatory-matcher> )
        # Iterate through all tuple-type matchers.
        while isinstance(matcher, tuple):
            optional, matcher = matcher
            # If the matcher doesn't look like a string (i.e. no 'decode'),
            # assume it's a function and call it, other test again the string.
            if ((not hasattr(optional, 'decode') and optional(c))
                or c == optional):
                # An optional matcher matched, so push the mandatory one back
                # onto the expect_stack.
                self.expect_stack.append(matcher)
                # Return the character and matched optional matcher.
                return c, optional
        # Either no optional matches were specified or none matched, so attempt
        # to match against the mandatory matcher.
        if (not hasattr(matcher, 'decode') and matcher(c)) or c == matcher:
            # Return the character and matched mandatory matcher.
            return c, matcher
        # The mandatory matcher failed, so raise UnexpectedCharacter.
        raise UnexpectedCharacter(c, self.char_num)

    def yield_while(self, pred):
        # Yield characters from the stream until testing them against the
        # specified predicate function returns False.
        while True:
            # Read the next character from the stream.
            c = self.next_char()
            # Check whether the character satisfies the predicate.
            if not pred(c):
                # The predicate has not been satisfied so stuff the last-read
                # character back and return.
                self.stuff_char(c)
                return
            # Yield the character.
            yield c

    def with_drain(self, event, gen):
        # Yield the specified (event, gen) pair and afterward, if necessary,
        # consume the generator to ensure that the stream read pointer is
        # advanced as expected.
        # Read the current char_num for later comparison to determine whether
        # any data was consumed from the generator.
        char_num = self.char_num
        yield event, gen
        if self.char_num == char_num and gen is not None:
            # char_num has not been incremented and gen is a generator, so
            # consume it.
            for _ in gen:
                pass

    def parse_string(self):
        # Yield characters from the stream up until the next string terminator
        # (i.e. '"') character.
        yield from self.yield_while(is_not_string_terminator)
        # Expect a string terminator to follow.
        self.expect(Matchers.STRING_TERMINATOR)

    def parse_number(self):
        # Yield characters from the stream up until the next non-number char.
        # Expect the first character to be a negative sign or digit.
        yield self.expect(lambda c: c == b'-' or c.isdigit())[0]
        # Expect one or more digits.
        yield from self.yield_while(is_digit)
        # Check to see if the next char is a decimal point.
        c = self.next_char()
        if c != b'.':
            # Not a decimal point so stuff it back and return.
            self.stuff_char(c)
            return
        # It is a decimal point.
        yield c
        # Expect the next character to be a digit.
        yield self.expect(is_digit)[0]
        # Yield any remaining digits.
        yield from self.yield_while(is_digit)

    def parse(self):
        self.expect_stack = [ Matchers.EOF, Matchers.IS_VALUE_START ]
        while True:
            for event_value in self.parse_next():
                if event_value is None:
                    return
                yield event_value

    def parse_next(self):
        c, match = self.expect(self.expect_stack.pop())

        if match == Matchers.EOF:
            # Char is an empty string which indicates that the input stream has
            # been exhausted.
            # Yield None to indicate that end-of-file has been reached.
            yield None
            return

        if match == Matchers.OBJECT_CLOSE:
            # Char is an object terminator (i.e. '}').
            yield Events.OBJECT_CLOSE
            # No context here for knowing what, if anything, should follow.
            return

        if match == Matchers.ARRAY_CLOSE:
            # Char is an array terminator (i.e. ']')
            yield Events.ARRAY_CLOSE
            # No context here for knowing what, if anything, should follow.
            return

        if match == Matchers.OBJECT_KEY_START:
            # Char is the expected object key's opening double-qoute.
            # Yield the object key string.
            yield from self.with_drain(Events.OBJECT_KEY, self.parse_string())
            # Expect a object key/value separator (i.e. ':') to follow.
            self.expect_stack.append(Matchers.KV_SEP)
            return

        if match == Matchers.KV_SEP:
            # Char is an object key / value separator (i.e. ':')
            # Expect an object value (e.g. string, number, null) to follow.
            self.expect_stack.append(Matchers.IS_OBJECT_VALUE_START)
            return

        if match == Matchers.IS_NEXT_OBJECT_KEY_START:
            # Char is an item separator (i.e. ',') in a post-object-value
            # context.
            # Expect an object value, item separator (thus accomodating
            # unlimited trailing commas), or object terminator to follow.
            self.expect_stack.append(
                (
                    Matchers.OBJECT_KEY_START,
                    (
                        Matchers.IS_NEXT_OBJECT_KEY_START,
                        self.expect_stack.pop()
                    )
                )
            )
            return

        if match == Matchers.IS_NEXT_ARRAY_VALUE_START:
            # Char is an item separator (i.e. ',') in a post-array-value
            # context.
            # Expect an array value, item separator (thus accomodating
            # unlimited trailing commas), or array terminator to follow.
            self.expect_stack.append(
                (
                    Matchers.IS_ARRAY_VALUE_START,
                    (
                        Matchers.IS_NEXT_ARRAY_VALUE_START,
                        self.expect_stack.pop()
                    )
                )
            )
            return

        # Having exhausted the above clauses, we find ourselves dealing with a
        # new value, either as a scalar or in the context of an array or object
        # value. Assert that this is so.
        if match not in (
                Matchers.IS_VALUE_START,
                Matchers.IS_OBJECT_VALUE_START,
                Matchers.IS_ARRAY_VALUE_START
            ):
            raise AssertionError(c, match, self.char_num)

        if c == Matchers.OBJECT_OPEN:
            # Char is an object initiator (i.e. '{')
            yield Events.OBJECT_OPEN
            # Expect an object key, item separator, or object terminator to
            # follow.
            self.expect_stack.append(
                (
                    Matchers.OBJECT_KEY_START,
                    (
                        Matchers.IS_NEXT_OBJECT_KEY_START,
                        Matchers.OBJECT_CLOSE
                    )
                )
            )
            return

        if c == Matchers.ARRAY_OPEN:
            # Char is an array initiator (i.e. '[')
            # Expect an array value, item separator, or array terminator to
            # follow.
            yield Events.ARRAY_OPEN
            self.expect_stack.append(
                (
                    Matchers.IS_ARRAY_VALUE_START,
                    (
                        Matchers.IS_NEXT_ARRAY_VALUE_START,
                        Matchers.ARRAY_CLOSE
                    )
                )
            )
            return

        if c == Matchers.STRING_START:
            # Char is a string initiator (i.e. '"')
            # Yield the event along with a string value parser/generator.
            if match == Matchers.IS_OBJECT_VALUE_START:
                event = Events.OBJECT_VALUE_STRING
            elif match == Matchers.IS_ARRAY_VALUE_START:
                event = Events.ARRAY_VALUE_STRING
            else:
                event = Events.STRING
            yield from self.with_drain(event, self.parse_string())

        elif Matchers.IS_NUMBER_START(c):
            # Char is a number initiator (i.e. '-' or a digit)
            # Yield the event along with a number value parser/generator.
            if match == Matchers.IS_OBJECT_VALUE_START:
                event = Events.OBJECT_VALUE_NUMBER
            elif match == Matchers.IS_ARRAY_VALUE_START:
                event = Events.ARRAY_VALUE_NUMBER
            else:
                event = Events.NUMBER
            # parse_number() is going to need this first character, so stuff it
            # back in.
            self.stuff_char(c)
            yield from self.with_drain(event, self.parse_number())

        elif c == Matchers.NULL_START:
            # Char is a null initiator (i.e. 'n')
            # Expect the next 3 chars to be 'ull' and yield the event.
            self.expect(b'u')
            self.expect(b'l')
            self.expect(b'l')
            if match == Matchers.IS_OBJECT_VALUE_START:
                yield Events.OBJECT_VALUE_NULL
            elif match == Matchers.IS_ARRAY_VALUE_START:
                yield Events.ARRAY_VALUE_NULL
            else:
                yield Events.NULL

        else:
            raise NotImplementedError(c)

        if match == Matchers.IS_ARRAY_VALUE_START:
            # We just yielded an array value.
            # Expect either an array item separator or array terminator to
            # follow.
            self.expect_stack.append(
                (Matchers.IS_NEXT_ARRAY_VALUE_START, self.expect_stack.pop())
            )
        elif match == Matchers.IS_OBJECT_VALUE_START:
            # We just yielded an object value.
            # Expect either an object item separator or object terminator to
            # follow.
            self.expect_stack.append(
                (Matchers.IS_NEXT_OBJECT_KEY_START, self.expect_stack.pop())
            )

    def convert(self, event, value):
        # Convert a parsed value to a Python type.
        if (event == Events.ARRAY_VALUE_NULL
            or event == Events.OBJECT_VALUE_NULL
            or event == Events.NULL):
            return None
        if (event == Events.ARRAY_VALUE_STRING
            or event == Events.OBJECT_VALUE_STRING
            or event == Events.STRING
            or event == Events.OBJECT_KEY):
            return b''.join(value)
        if (event == Events.ARRAY_VALUE_NUMBER
            or event == Events.OBJECT_VALUE_NUMBER
            or event == Events.NUMBER):
            return float(b''.join(value))
        raise NotImplementedError(event, value)

    def yield_paths(self, paths):
        # Yield ( <path>, <value-generator> ) tuples for all specified paths
        # that exist in the data.
        # paths must be an iterable of lists having the format:
        #   [ <object-key-or-array-index>, ... ]
        #
        # Track the indexes of the paths in paths to be yielded.
        unyielded_path_idxs = set(range(len(paths)))
        path = []
        for event_value in self.parse():
            if isinstance(event_value, tuple):
                event, value = event_value
            else:
                event, value  = event_value, None

            if event == Events.OBJECT_OPEN:
                if path and isinstance(path[-1], int):
                    path[-1] += 1
                path.append(b'.')
                continue

            elif event == Events.OBJECT_CLOSE:
                path.pop()
                continue

            elif event == Events.ARRAY_OPEN:
                if path and isinstance(path[-1], int):
                    path[-1] += 1
                path.append(-1)
                continue

            elif event == Events.ARRAY_CLOSE:
                path.pop()
                continue

            elif event == Events.OBJECT_KEY:
                path[-1] = b''.join(value)

            elif (event == Events.ARRAY_VALUE_STRING
                  or event == Events.ARRAY_VALUE_NUMBER
                  or event == Events.ARRAY_VALUE_NULL):
                path[-1] += 1
                for i in unyielded_path_idxs:
                    if path == paths[i]:
                        yield path, self.convert(event, value)
                        unyielded_path_idxs.remove(i)
                        break

            elif (event == Events.OBJECT_VALUE_STRING
                  or event == Events.OBJECT_VALUE_NUMBER
                  or event == Events.OBJECT_VALUE_NULL):
                for i in unyielded_path_idxs:
                    if path == paths[i]:
                        yield path, self.convert(event, value)
                        unyielded_path_idxs.remove(i)
                        break

            # Abort if all of the requested paths have been yielded.
            if len(unyielded_path_idxs) == 0:
                return

    def load(self):
        parse_gen = self.parse()
        # Initialize the value based on the first read.
        event_value = next(parse_gen)
        event, value = (event_value if isinstance(event_value, tuple)
                        else (event_value, None))
        # If it's a single scalar value, convert and return it.
        if (event == Events.STRING
            or event == Events.NUMBER
            or event == Events.NULL):
            return self.convert(event, value)

        # Read the initial container type.
        if event == Events.OBJECT_OPEN:
            root = {}
        elif event == Events.ARRAY_OPEN:
            root = []
        else:
            raise NotImplementedError(event)

        # Continue parsing.
        container_stack = []
        container = root
        key = None

        def open_container(_container):
            nonlocal container
            # Attach the new container to the one that's currently open.
            if type(container) is list:
                container.append(_container)
            else:
                container[key] = _container
            # Push the currently-open container onto the stack.
            container_stack.append(container)
            # Set the new container as the current.
            container = _container

        def close_container():
            nonlocal container
            container = container_stack.pop()

        for event_value in parse_gen:
            event, value = (event_value if isinstance(event_value, tuple)
                            else (event_value, None))
            if event == Events.ARRAY_OPEN:
                open_container([])
            elif event == Events.OBJECT_OPEN:
                open_container({})
            elif event == Events.ARRAY_CLOSE or event == Events.OBJECT_CLOSE:
                if len(container_stack) == 0:
                    # No more open containers, so stop parsing.
                    break
                close_container()
            elif (event == Events.ARRAY_VALUE_STRING
                  or event == Events.ARRAY_VALUE_NUMBER
                  or event == Events.ARRAY_VALUE_NULL):
                container.append(self.convert(event, value))
            elif event == Events.OBJECT_KEY:
                key = self.convert(event, value)
            elif (event == Events.OBJECT_VALUE_STRING
                  or event == Events.OBJECT_VALUE_NUMBER
                  or event == Events.OBJECT_VALUE_NULL):
                container[key] = self.convert(event, value)

        return root


###############################################################################
# Streaming UTF-8 Decoder
###############################################################################

STRICT, REPLACE, IGNORE = 0, 1, 2

class InvalidUTF8Encoding(Exception):
    def __init__(self, byte_num):
        super().__init__(
            self,
            'Invalid UTF-8 encoding at byte number: {}'.format(byte_num)
        )

class UTF8Decoder:
    REPLACEMENT_CHAR = '\ufffd'
    MAX_CODEPOINT = 0x10FFFF

    def __init__(self, stream, errors=STRICT):
        self.stream = stream
        self.byte_num = 0
        self.first_read = True
        self.errors = errors

    def read_one(self):
        c = self.stream.read(1)
        self.byte_num += 1

        if self.first_read:
            if not isinstance(c, bytes):
                raise AssertionError('UTF8Decoder requires a bytes stream')
            self.first_read = False

        if c == b'':
            raise StopIteration
        return c

    def __iter__(self):
        return self

    def error(self):
        if self.errors == STRICT:
            raise InvalidUTF8Encoding(self.byte_num)
        elif self.errors == REPLACE:
            return self.REPLACEMENT_CHAR
        else:
            return next(self)

    def __next__(self):
        # See: https://en.wikipedia.org/wiki/UTF-8#Encoding
        # Read the next char.
        byte = ord(self.read_one())
        # If the high bit is clear, return the single-byte char.
        if byte & 0b10000000 == 0:
            return chr(byte)
        # The high bit is set so char comprises multiple bytes.
        # Determine the number of bytes and init the codepoint with
        # the first byte.
        if byte & 0b11100000 == 0b11000000:
            # 2-byte char.
            bytes_remaining = 1
            codepoint = (byte & 0b00011111) << 6
        elif byte & 0b11110000 == 0b11100000:
            # 3-byte char.
            bytes_remaining = 2
            codepoint = (byte & 0b00001111) << 12
        elif byte & 0b11111000 == 0b11110000:
            # 4-byte char.
            bytes_remaining = 3
            codepoint = (byte & 0b00000111) << 18
        elif byte & 0b11111100 == 0b11111000:
            # 5-byte char.
            bytes_remaining = 4
            codepoint = (byte & 0b00000011) << 24
        elif byte & 0b11111110 == 0b11111100:
            # 6-byte char.
            bytes_remaining = 5
            codepoint = (byte & 0b00000001) << 30
        elif byte & 0b11000000 == 0b10000000:
            # Unexpected continuation.
            return self.error()
        else:
            # Some other unexpected condition.
            return self.error()

        # Read the remaining bytes, asserting that they're valid,
        # then shifting and ORing them with the codepoint.
        while bytes_remaining:
            try:
                byte = ord(self.read_one())
            except StopIteration:
                # Stream exhausted in the middle of a multi-byte char.
                self.error()
            if byte & 0b11000000 != 0b10000000:
                self.error()
            codepoint |= ((byte & 0b00111111) << ((bytes_remaining - 1) * 6))
            bytes_remaining -= 1

        # Python only supports codepoints up to U+10FFFF
        if codepoint > self.MAX_CODEPOINT:
            return self.REPLACEMENT_CHAR

        return chr(codepoint)

    def read(self, num_bytes):
        return ''.join(next(self) for _ in range(num_bytes))

"""
    project............: icb-irc
    description........: ICB-IRC proxy
    date...............: 01/2020
    copyright..........: Sebastian Fedrau

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
    OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
    ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
    OTHER DEALINGS IN THE SOFTWARE.
"""
import io

class Decoder:
    def __init__(self):
        self.__buffer = io.BytesIO()
        self.__listeners = []
        self.__crlf = bytearray((13, 10))

    def add_listener(self, listener):
        self.__listeners.append(listener)

    def remove_listener(self, listener):
        self.__listeners.remove(listener)

    def write(self, data):
        self.__buffer.write(data)
        self.__process__()

    def __process__(self):
        bytes = self.__buffer.getvalue()

        offset = (bytes.find(self.__crlf))

        if offset != -1:
            line = bytes[:offset].decode("utf-8").lstrip()

            if line:
                self.__process_line__(line.lstrip())

            rest = bytes[offset + 2:]

            self.__buffer = io.BytesIO(rest)

            if rest:
                self.__process__()

    def __process_line__(self, line):
        prefix, rest = "", line

        if line.startswith(":"):
            offset = line.find(" ")

            if offset != -1:
                prefix = line[:offset]
                rest = line[offset:].lstrip()
            else:
                prefix = line
                rest = ""

        offset, params = rest.find(" "), ""

        if offset == -1:
            command = rest
            params = []
        else:
            command = rest[:offset]
            params = Decoder.__split_params__(rest[offset:].lstrip())

        if command:
            for l in self.__listeners:
                l(prefix, command, params)

    @staticmethod
    def __split_params__(params):
        l = []

        rest = params

        while rest:
            if rest.startswith(":"):
                l.append(rest[1:])
                rest = ""
            else:
                offset = rest.find(" ")

                if offset == -1:
                    l.append(rest)
                    rest = ""
                else:
                    l.append(rest[:offset])
                    rest = rest[offset:].lstrip()

        return l

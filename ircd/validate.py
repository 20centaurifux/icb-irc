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
import re
from urllib.parse import urlparse

def has_valid_length(text, min_length, max_length):
    return len(text) >= min_length and len(text) <= max_length

NICK_MIN = 1
NICK_MAX = 12

def is_valid_nick(nick):
    return re.match(r"^[\w\-]{1,12}$", nick)

LOGINID_MIN = 1
LOGINID_MAX = 12

def is_valid_loginid(loginid):
    return re.match(r"^[A-Za-z0-9\-]{1,12}$", loginid)

GROUP_MIN = 1
GROUP_MAX = 12

def is_valid_group(group):
    return has_valid_length(group, GROUP_MIN, GROUP_MAX)

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
from dataclasses import dataclass, field
from typing import List
import copy
import core

@dataclass
class Config:
    server_hostname: str = "localhost"
    bindings: List[str] = field(default_factory=list)
    logging_verbosity: core.Verbosity = core.Verbosity.INFO
    icb_endpoint: str = "tcp://localhost:7326"

def transform_map(m):
    m = copy.deepcopy(m)

    try:
        m["logging_verbosity"] = core.Verbosity(m["logging_verbosity"])
    except KeyError: pass

    return m

def from_mapping(m):
    m = transform_map(m)

    return Config(**m)

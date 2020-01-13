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
import logging
import asyncio
import os.path
import getopt
import sys
import os
import socket
import traceback
from secrets import token_hex
import signal
import re
from dataclasses import dataclass
from textwrap import wrap
import core
import config
import config.json
import log
import irc
import url
import client
import ltd
import validate
import timer

@dataclass
class Session:
    nick: str = ""
    loginid: str = ""
    host: str = ""

    @property
    def clientid(self):
        return "%s!~%s@%s" % (self.nick, self.loginid, self.host)

class ListFromStatus(client.StatusParser):
    def __init__(self, group, list_type):
        super().__init__()

        self.__group = group
        self.__type = list_type

        self.__found_group = None

        self.on_found = lambda i: None
        self.on_end = lambda: None

    def begin(self, group):
        self.__found_group = group

    def found_invitation(self, invitation, is_address):
        if self.__type == "invitation":
            self.on_found(invitation)

    def found_talker(self, talker, is_address):
        if self.__type == "talker":
            self.on_found(talker)

    def end(self):
        self.on_end()

        if self.__found_group == self.__group:
            self.stop()

class FindUser(client.ListParser):
    def __init__(self, nick):
        super().__init__()

        self.__nick = nick
        self.__args = None

        self.on_found = lambda is_mod, nick, idle, loginid, host, status: None
        self.on_not_found = lambda: None

    def found_user(self, is_mod, nick, idle, loginid, host, status):
        if nick == self.__nick:
            self.__args = (is_mod, nick, idle, loginid, host, status)

            self.stop()

    def end(self):
        if self.__args:
            self.on_found(*self.__args)
        else:
            self.on_not_found()

class IRCServerProtocol(asyncio.Protocol, client.StateListener):
    def __init__(self, config, log, connections, icb_host="127.0.0.1", icb_port=7326):
        asyncio.Protocol.__init__(self)
        client.StateListener.__init__(self)

        self.__config = config
        self.__log = log
        self.__connections = connections
        self.__icb_host = icb_host
        self.__icb_port = icb_port
        self.__session_id = token_hex(20)
        self.__session = Session()
        self.__client = None
        self.__decoder = irc.Decoder()
        self.__shutdown = False
        self.__handlers = []
        self.__away_cache = {}

        self.__decoder.add_listener(self.__on_message__)

    def connection_made(self, transport):
        address = transport.get_extra_info("peername")

        self.__log.info("Client connected, session_id=%s, address=%s", self.__session_id, address[0])

        self.__connections[self.__session_id] = address
        self.__address = address[0]
        self.__transport = transport

        cipher = transport.get_extra_info("cipher")

        if cipher:
            self.__log.info("Cipher: %s", cipher)

    def data_received(self, data):
        if not self.__shutdown:
            try:
                self.__decoder.write(data)

            except:
                self.__log.warning(traceback.format_exc())

                self.__transport.close()

    def __abort__(self):
        self.__log.fatal(traceback.format_exc())

        loop = asyncio.get_running_loop()

        loop.stop()

    def connection_lost(self, ex):
        if ex:
            self.__log.info(ex)

        self.__shutdown__()

    def __shutdown__(self):
        self.__log.info("Closing session: '%s'", self.__session_id)

        try:
            self.__client.quit()
        except AttributeError:
            pass

        if self.__session_id in self.__connections:
            del self.__connections[self.__session_id]

        self.__transport.abort()

    """
        receive & handle IRC messages:
    """
    def __on_message__(self, prefix, command, params):
        self.__log.debug("Message received: prefix=%s, command=%s, params=%s", prefix, command, params)

        if not self.__client:
            self.__pre_login__(prefix, command, params)
        else:
            self.__post_login__(prefix, command, params)

    def __pre_login__(self, prefix, command, params):
        fn = None

        try:
            fn = getattr(self, "__%s_received_pre__" % command.lower())
        except AttributeError:
            pass

        if fn:
            fn(params)

            if self.__session.nick and self.__session.loginid:
                asyncio.create_task(self.__run_icb_client__(self.__session.loginid, self.__session.nick, "1", ""))

    def __nick_received_pre__(self, params):
        if len(params) != 1 or not validate.is_valid_nick(params[0]):
            self.__writeln__(":%s 432 :Erroneous nickname", self.__config.server_hostname)
        else:
            self.__session.nick = params[0]

    def __user_received_pre__(self, params):
        if not params or not validate.is_valid_loginid(params[0]):
            self.__die__(461, "No valid username found.")
        elif len(params) < 4:
            self.__die__(461, "No valid hostname found.")
        else:
            self.__session.loginid = params[0]
            self.__session.host = socket.getfqdn(self.__address)

    def __post_login__(self, prefix, command, params):
        fn = None

        try:
            fn = getattr(self, "__%s_received__" % command.lower())
        except:
            pass

        if fn:
            fn(params)

    def __ping_received__(self, params):
        self.__writeln__("PONG %s", self.__config.server_hostname)

    def __mode_received__(self, params):
        if len(params) >= 1:
            if params[0].startswith("#"):
                self.__channel_mode__(params[0][1:], params[1:])
            else:
                self.__user_mode__(params[0], params[1:])
        else:
            self.__writeln__(":%s 462 %s mode :Not enough Parameters.", self.__config.server_hostname, self.__session.nick)

    def __channel_mode__(self, channel, params):
        if channel == self.__client.state.group:
            if not params:
                self.__send_channel_mode__()
            elif len(params) == 1:
                q = params[0]

                if q == "+b":
                    self.__send_bans__()
                elif q == "+e":
                    self.__send_exceptions__()
                elif q == "+I":
                    self.__send_invitations__()
                else:
                    self.__writeln__(":%s 482 #%s :Cannot change mode over IRC protocol.", self.__config.server_hostname, channel)
        else:
            self.__writeln__(":%s 441 %s #%s :You're not in this channel.", self.__config.server_hostname, self.__session.nick, channel)

    def __user_mode__(self, user, params):
        if user == self.__session.nick:
            self.__writeln__(":%s 221 %s +i", self.__config.server_hostname, self.__session.nick)
        elif params:
            self.__writeln__(":%s 502 %s :Cannot change mode for other users.", self.__config.server_hostname, self.__session.nick)
        else:
            self.__writeln__(":%s 221 %s +i", self.__config.server_hostname, user)

    def __send_channel_mode__(self):
        flags = self.__map_group_status__(self.__client.state.group_status)

        self.__writeln__(":%s 324 %s #%s %s", self.__config.server_hostname, self.__session.nick, self.__client.state.group, flags)

    def __send_bans__(self):
        self.__writeln__(":%s 368 %s :End of BAN list", self.__config.server_hostname, self.__session.nick)

    def __send_exceptions__(self):
        self.__writeln__(":%s 349 %s :End of EXCEPTION list", self.__config.server_hostname, self.__session.nick)

    def __send_invitations__(self):
        self.__client.command("status")
        self.__client.ping()

        list_type = ""

        if self.__client.state.group_status[0] == "r":
            list_type = "invitation"
        elif self.__client.state.group_status[0] == "c":
            list_type = "talker"

        if list_type:
            p = ListFromStatus(self.__client.state.group, list_type)

            p.on_found = lambda n: self.__writeln__(":%s 346 %s #%s :%s", self.__config.server_hostname, self.__session.nick, self.__client.state.group, n)
            p.on_end = lambda: self.__writeln__(":%s 347 %s #%s :End of INVITATION list", self.__config.server_hostname, self.__session.nick, self.__client.state.group)

            self.__handlers.append(p)
        else:
            self.__writeln__(":%s 347 %s #%s :End of INVITATION list", self.__config.server_hostname, self.__session.nick, self.__client.state.group)

    def __channel_mode_changed__(self, old, new):
        old = self.__map_group_status__(old)[1:]
        new = self.__map_group_status__(new)[1:]

        for c in old:
            if not c in new:
                self.__writeln__(":%s MODE #%s -%s", self.__config.server_hostname, self.__client.state.group, c)

        for c in new:
            if not c in old:
                self.__writeln__(":%s MODE #%s +%s", self.__config.server_hostname, self.__client.state.group, c)

    def __moderator_changed__(self, old, new):
        if old:
            self.__writeln__(":%s MODE #%s -o %s", self.__config.server_hostname, self.__client.state.group, old)

        if new:
            self.__writeln__(":%s MODE #%s +o %s", self.__config.server_hostname, self.__client.state.group, new)

    def __who_received__(self, params):
        for p in params:
            if p != "o":
                self.__writeln__(":%s 315 %s %s :End of WHO list", self.__config.server_hostname, self.__session.nick, p)

    def __whois_received__(self, params):
        if len(params) > 0:
            p = FindUser(params[0])

            p.on_found = self.__send_whois__
            p.on_not_found = lambda: self.__writeln__(":%s 401 %s %s :No such nick.", self.__config.server_hostname, self.__session.nick, params[0])

            self.__handlers.append(p)

            self.__client.command("w")

    def __send_whois__(self, is_mod, nick, idle, loginid, host, status):
        self.__writeln__(":%s 311 %s %s %s %s * :%s", self.__config.server_hostname, self.__session.nick, nick, loginid, host, loginid)
        self.__writeln__(":%s 312 %s %s %s :ICB Proxy", self.__config.server_hostname, self.__session.nick, nick, self.__config.server_hostname)

        if is_mod:
            self.__writeln__(":%s 313 %s %s :Moderator", self.__config.server_hostname, self.__session.nick, nick)

        self.__writeln__(":%s 317 %s %s %d :seconds idle", self.__config.server_hostname, self.__session.nick, nick, idle)

        if "aw" in status:
            text = None

            if nick in self.__away_cache:
                m = self.__away_cache[nick]

                if m["timer"].elapsed() <= 120:
                    text = m["text"]
                else:
                    del self.__away_cache[nick]

            if text:
                self.__end_of_whois__(nick, text)
            else:
                p = client.AwayParser()

                p.on_away_found = lambda text: self.__end_of_whois__(nick, away_message=text, update_cache=True)

                self.__handlers.append(p)

                self.__client.command("beep", nick)
                self.__client.ping()
        else:
            self.__end_of_whois__(nick)

    def __end_of_whois__(self, nick, away_message=None, update_cache=False):
        if away_message:
            self.__writeln__(":%s 301 %s %s :%s", nick, self.__config.server_hostname, nick, away_message)

            if update_cache:
                self.__away_cache[nick] = {"timer": timer.Timer(), "text": away_message}

        self.__writeln__(":%s 318 %s %s: End of WHOIS", self.__config.server_hostname, self.__session.nick, nick)

    def __join_received__(self, params):
        if len(params) != 1:
            self.__writeln__(":%s ERROR :You can only join a single channel.", self.__config.server_hostname)
        elif (len(params[0]) < 2 or params[0][0] != "#") or not validate.is_valid_group(params[0][1:]):
            self.__writeln__("403 %s %s", self.__session.nick, params[0])
        else:
            self.__client.command("g", params[0][1:])

    def __nick_received__(self, params):
        if len(params) != 1 or not validate.is_valid_nick(params[0]):
            self.__writeln__(":%s 432 :Erroneous nickname", self.__config.server_hostname)
        else:
            self.__client.command("name", params[0])

    def __privmsg_received__(self, params):
        if params[0].startswith("#"):
            self.__open_message__(params[1])
        else:
            self.__private_message__(params[0], params[1])

    def __open_message__(self, message):
        for part in wrap(message, 200):
            e = ltd.Encoder("b")
            
            e.add_field_str(part, append_null=True)

            self.__client.send(e.encode())

    def __private_message__(self, receiver, message):
        for part in wrap(message, 200):
            e = ltd.Encoder("h")

            e.add_field_str("m")
            e.add_field_str("%s %s" % (receiver, message), append_null=True)

            self.__client.send(e.encode())

    def __topic_received__(self, params):
        self.__client.command("topic", params[1])

    def __quit_received__(self, params):
        self.__client.quit()

    """"
        receive & handle ICB messages:
    """
    async def __run_icb_client__(self, loginid, nick, group, password):
        try:
            self.__log.debug("Connecting to %s:%d.", self.__icb_host, self.__icb_port)

            self.__client = client.Client(self.__icb_host, self.__icb_port)

            self.__client.state.add_listener(self)

            connection_lost_f = await self.__client.connect()

            self.__client.login(loginid, nick, group, "", self.__address)

            msg_f = asyncio.ensure_future(self.__client.read())

            running = True

            while running:
                done, _ = await asyncio.wait([msg_f, connection_lost_f], return_when=asyncio.FIRST_COMPLETED)

                for task in done:
                    if task is msg_f:
                        t, f = task.result()

                        completed = []

                        for p in self.__handlers:
                            if not p.feed(t, f):
                                completed.append(p)

                        for p in completed:
                            self.__handlers.remove(p)

                        try:
                            if t == "j":
                                self.__welcome__()
                            elif t == "b":
                                self.__writeln__(":%s PRIVMSG #%s :%s", f[0], self.__client.state.group, f[1])
                            elif t == "c":
                                self.__writeln__(":%s PRIVMSG %s :%s", f[0], self.__client.state.nick, f[1])
                            elif t == "d":
                                self.__process_status_message__(f[0], f[1])
                            elif t == "e":
                                self.__process_error_message__(f[0])
                            elif t == "i":
                                self.__process_command_message__(f)
                        except:
                            self.__log.warning(traceback.format_exc())

                        msg_f = asyncio.ensure_future(self.__client.read())
                    elif task is connection_lost_f:
                        running = False

            msg_f.cancel()

            self.__log.debug("Disconnected from %s:%d.", self.__icb_host, self.__icb_port)

            self.__transport.close()
        except Exception as ex:
            self.__log.warning(traceback.format_exc())

    def __welcome__(self):
        self.__writeln__(":%s 001 %s :Welcome to the Internet Relay Network %s.", self.__config.server_hostname, self.__session.nick, self.__session.nick)
        self.__writeln__(":%s 002 %s :Your host is %s, running version v%s.", self.__config.server_hostname, self.__session.nick, self.__config.server_hostname, core.VERSION)
        self.__writeln__(":%s 004 %s :%s v%s oi npstiqC", self.__config.server_hostname, self.__session.nick, core.NAME, core.VERSION)
        self.__writeln__(":%s 375 %s :Message of the Day", self.__config.server_hostname, self.__session.nick)
        self.__writeln__(":%s 376 %s :End of MOTD", self.__config.server_hostname, self.__session.nick)
        self.__writeln__(":%s 221 %s +i", self.__config.server_hostname, self.__session.nick)

    def __process_status_message__(self, category, text):
        if category == "Register" and text.startswith("Nick already in use"):
            self.__die__(436, "%s :Nickname collision" % self.__session.nick)
        elif category == "FYI":
            self.__fyi_message__(text)
        elif category == "RSVP":
            self.__rsvp_message__(text)

    def __fyi_message__(self, text):
        m = re.match(r"You are invited to group (\w+)", text)

        if m:
            self.__writeln__(":%s INVITE %s #%s", self.__config.server_hostname, self.__session.nick, m.group(1))

    def __rsvp_message__(self, text):
        m = re.match(r"You can now talk in group (\w+)", text)

        invitation = None

        if m:
            invitation = m.group(1)
        else:
            m = re.match(r"You are invited to group (\w+)", text)

            if m:
                invitation = m.group(1)

        if invitation:
            self.__writeln__(":%s INVITE %s #%s", self.__config.server_hostname, self.__session.nick, invitation)

    def __process_error_message__(self, text):
        command, params = "ERROR", ":" + text

        try:
            code, params = self.__map_error_msg__(text)
            command = "%03d" % code
        except:
            pass

        self.__writeln__(":%s %s %s", self.__config.server_hostname, command, params)

    @staticmethod
    def __map_error_msg__(text):
        if text.startswith("You don't have administrative privileges"):
            return 481, ":" + text
        elif text.startswith("You aren't the moderator"):
            return 482, ":" + text
        elif text.startswith("Access denied."):
            return 465, ":" + text

    def __process_command_message__(self, fields):
        if not self.__client.state.joining and fields[0] == "co":
            self.__writeln__("NOTICE %s :%s", self.__session.nick, fields[1])

    """"
        client events:
    """
    def changed(self, name, old, new):
        if name == "group":
            self.__before_join__(old)
        elif name == "joining" and not new:
            self.__after_join__()
        elif not self.__client.state.joining:
            if name == "topic":
                self.__topic_changed__(new)
            elif name == "nick" and old:
                self.__nick__changed__(new)
            elif name == "group_status":
                self.__channel_mode_changed__(old, new)
            elif name == "moderator":
                self.__moderator_changed__(old, new)

    def __before_join__(self, current_channel):
        if current_channel:
            self.__writeln__(":%s PART :#%s", self.__session.clientid, current_channel)

    def __after_join__(self):
        self.__writeln__(":%s JOIN #%s", self.__session.clientid, self.__client.state.group)

        topic = self.__client.state.topic
        channel = self.__client.state.group
        status = self.__client.state.group_status
        
        if topic:
            self.__writeln__(":%s 332 %s #%s :%s", self.__config.server_hostname, self.__session.nick, channel, topic)
        else:
            self.__writeln__(":%s 331 #%s :Topic not set.", self.__config.server_hostname, channel)

        for nick in self.__client.state.members:
            visiblity = "="

            if "i" in status:
                visiblity = "@"
            elif "s" in status:
                visiblity = "*"

            user_flag = ""

            if nick == self.__client.state.moderator:
                user_flag = "@"

            self.__writeln__(":%s 353 %s %s #%s :%s%s", self.__config.server_hostname, self.__client.state.nick, visiblity, channel, user_flag, nick)

        self.__writeln__(":%s 366 %s #%s :End of NAMES list", self.__config.server_hostname, self.__client.state.nick, channel)

    def __topic_changed__(self, topic):
        self.__writeln__(":%s 332 %s #%s :%s", self.__config.server_hostname, self.__session.nick, self.__client.state.group, topic)

    def __nick__changed__(self, nick):
        self.__writeln__(":%s NICK %s", self.__session.clientid, nick)
        self.__session.nick = nick

    def member_added(self, nick, loginid):
        if not self.__client.state.joining and nick != self.__session.nick:
            self.__writeln__(":%s!~%s JOIN :#%s", nick, loginid, self.__client.state.group)

    def member_removed(self, nick, loginid):
        if not self.__client.state.joining and nick != self.__session.nick:
            self.__writeln__(":%s!~%s PART :#%s", nick, loginid, self.__client.state.group)

    def member_renamed(self, old, new, loginid):
        if not self.__client.state.joining and new != self.__session.nick:
            self.__writeln__(":%s!~%s NICK %s", old, loginid, new)

    def __writeln__(self, fmt, *args):
        self.__log.debug("=> %s" % fmt % args)

        self.__transport.write((fmt % args).encode("utf-8"))
        self.__transport.write(bytearray((13, 10)))

    def __die__(self, errcode, params):
        self.__writeln__(":%s %03d %s", self.__config.server_hostname, errcode, params)
        self.__shutdown = True

    @staticmethod
    def __map_group_status__(flags):
        control, visibility, volume = flags

        mapped = "+n"

        if control == "m":
            mapped = mapped + "t"
        elif control == "r":
            mapped = mapped + "ti"
        elif control == "c":
            mapped = mapped + "tC"

        if visibility == "s":
            mapped = "p"
        elif visibility == "i":
            mapped = "s"

        if volume == "q":
            mapped = mapped + "q"

        return mapped

class Server:
    def __init__(self, log, config):
        self.__log = log
        self.__connections = {}
        self.__servers = []
        self.__config = config

    async def run(self):
        loop = asyncio.get_running_loop()

        for addr in self.__config.bindings:
            self.__log.info("Found binding: %s", addr)

            binding = url.parse_server_address(addr)

            if binding["protocol"] == "tcp":
                self.__log.info("Listening on %s:%d (tcp)", binding["address"], binding["port"])

                server = await loop.create_server(lambda: IRCServerProtocol(self.__config,
                                                                            self.__log,
                                                                            self.__connections),
                                                                            binding["address"],
                                                                            binding["port"])

                self.__servers.append(server)

            elif binding["protocol"] == "tcps":
                self.__log.info("Listening on %s:%d (tcp/tls)", binding["address"], binding["port"])

                sc = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                sc.load_cert_chain(binding["cert"], binding["key"])

                server = await loop.create_server(lambda: IRCServerProtocol(self.__config,
                                                                            self.__log,
                                                                            self.__connections),
                                                                            binding["address"],
                                                                            binding["port"],
                                                                            ssl=sc)
            else:
                raise NotImplementedError("Unsupported protocol: %s", binding["protocol"])

        await asyncio.gather(*(map(lambda s: s.serve_forever(), self.__servers)))

    def close(self):
        self.__log.info("Stopping server.")

        for s in self.__servers:
            s.close()

async def run_service(opts):
    data_dir = opts.get("data_dir")

    mapping = config.json.load(opts["config"])
    preferences = config.from_mapping(mapping)

    logger = log.new_logger("ircd", preferences.logging_verbosity)

    logger.info("Starting server process with pid %d.", os.getpid())

    if os.name == "posix":
        loop = asyncio.get_event_loop()

        loop.add_signal_handler(signal.SIGINT, lambda: server.close())
        loop.add_signal_handler(signal.SIGTERM, lambda: server.close())

    try:
        server = Server(logger, preferences)

        await server.run()
    except asyncio.CancelledError:
        pass
    except:
        logger.warning(traceback.format_exc())

    logger.info("Server stopped.")

def get_opts(argv):
    options, _ = getopt.getopt(argv, 'c:', ['config='])

    m = {}

    for opt, arg in options:
        if opt in ('-c', '--config'):
            m["config"] = arg

    if not m.get("config"):
        raise getopt.GetoptError("--config option is mandatory")

    return m

if __name__ == "__main__":
    try:
        opts = get_opts(sys.argv[1:])

        asyncio.run(run_service(opts))

    except getopt.GetoptError as ex:
        print(str(ex))
    except:
        traceback.print_exc()

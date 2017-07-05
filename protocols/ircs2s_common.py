"""
ircs2s_common.py: Common base protocol class with functions shared by TS6 and P10-based protocols.
"""

import time
import re
from collections import defaultdict

from pylinkirc.classes import IRCNetwork, ProtocolError
from pylinkirc.log import log
from pylinkirc import utils

class IRCCommonProtocol(IRCNetwork):

    COMMON_PREFIXMODES = [('h', 'halfop'), ('a', 'admin'), ('q', 'owner'), ('y', 'owner')]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._caps = {}
        self._use_builtin_005_handling = False  # Disabled by default for greater security

    def post_connect(self):
        self._caps.clear()

    def validate_server_conf(self):
        """Validates that the server block given contains the required keys."""
        for k in self.conf_keys:
            assert k in self.serverdata, "Missing option %r in server block for network %s." % (k, self.name)

        port = self.serverdata['port']
        assert type(port) == int and 0 < port < 65535, "Invalid port %r for network %s" % (port, self.name)

    # TODO: these wrappers really need to be standardized
    def _get_SID(self, sname):
        """Returns the SID of a server with the given name, if present."""
        name = sname.lower()

        if name in self.servers:
            return name

        for k, v in self.servers.items():
            if v.name.lower() == name:
                return k
        else:
            return sname  # Fall back to given text instead of None

    def _get_UID(self, target):
        """Converts a nick argument to its matching UID. This differs from irc.nick_to_uid()
        in that it returns the original text instead of None, if no matching nick is found."""

        if target in self.users:
            return target

        target = self.nick_to_uid(target) or target
        return target

    @staticmethod
    def parse_args(args):
        """
        Parses a string or list of of RFC1459-style arguments, where ":" may
        be used for multi-word arguments that last until the end of a line.
        """
        if isinstance(args, str):
            args = args.split(' ')

        real_args = []
        for idx, arg in enumerate(args):
            if arg.startswith(':') and idx != 0:
                # ":" is used to begin multi-word arguments that last until the end of the message.
                # Use list splicing here to join them into one argument, and then add it to our list of args.
                joined_arg = ' '.join(args[idx:])[1:]  # Cut off the leading : as well
                real_args.append(joined_arg)
                break
            real_args.append(arg)

        return real_args

    @classmethod
    def parse_prefixed_args(cls, args):
        """Similar to parse_args(), but stripping leading colons from the first argument
        of a line (usually the sender field)."""
        args = cls.parse_args(args)
        args[0] = args[0].split(':', 1)[1]
        return args

    def _squit(self, numeric, command, args):
        """Handles incoming SQUITs."""

        split_server = self._get_SID(args[0])

        # Normally we'd only need to check for our SID as the SQUIT target, but Nefarious
        # actually uses the uplink server as the SQUIT target.
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test
        if split_server in (self.sid, self.uplink):
            raise ProtocolError('SQUIT received: (reason: %s)' % args[-1])

        affected_users = []
        affected_nicks = defaultdict(list)
        log.debug('(%s) Splitting server %s (reason: %s)', self.name, split_server, args[-1])

        if split_server not in self.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.name, split_server)
            return

        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.servers.copy()
        old_channels = self.channels.copy()

        # Cycle through our list of servers. If any server's uplink is the one that is being SQUIT,
        # remove them and all their users too.
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                # Recursively run SQUIT on any other hubs this server may have been connected to.
                args = self._squit(sid, 'SQUIT', [sid, "0",
                                   "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']

        for user in self.servers[split_server].users.copy():
            affected_users.append(user)
            nick = self.users[user].nick

            # Nicks affected is channel specific for SQUIT:. This makes Clientbot's SQUIT relaying
            # much easier to implement.
            for name, cdata in old_channels.items():
                if user in cdata.users:
                    affected_nicks[name].append(nick)

            log.debug('Removing client %s (%s)', user, nick)
            self._remove_client(user)

        serverdata = self.servers[split_server]
        sname = serverdata.name
        uplink = serverdata.uplink

        del self.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.name, affected_users)

        return {'target': split_server, 'users': affected_users, 'name': sname,
                'uplink': uplink, 'nicks': affected_nicks, 'serverdata': serverdata,
                'channeldata': old_channels}

    @staticmethod
    def parse_isupport(args, fallback=''):
        """
        Parses a string of capabilities in the 005 / RPL_ISUPPORT format.
        """

        if type(args) == str:
            args = args.split(' ')

        caps = {}
        for cap in args:
            try:
                # Try to split it as a KEY=VALUE pair.
                key, value = cap.split('=', 1)
            except ValueError:
                key = cap
                value = fallback
            caps[key] = value

        return caps

    @staticmethod
    def parse_isupport_prefixes(args):
        """
        Separates prefixes field like "(qaohv)~&@%+" into a dict mapping mode characters to mode
        prefixes.
        """
        prefixsearch = re.search(r'\(([A-Za-z]+)\)(.*)', args)
        return dict(zip(prefixsearch.group(1), prefixsearch.group(2)))

    def handle_error(self, numeric, command, args):
        """Handles ERROR messages - these mean that our uplink has disconnected us!"""
        raise ProtocolError('Received an ERROR, disconnecting!')

    def handle_pong(self, source, command, args):
        """Handles incoming PONG commands."""
        if source == self.uplink:
            self.lastping = time.time()

    def handle_005(self, source, command, args):
        """
        Handles 005 / RPL_ISUPPORT. This is used by at least Clientbot and ngIRCd (for server negotiation).
        """
        # ngIRCd:
        # <- :ngircd.midnight.local 005 pylink-devel.int NETWORK=ngircd-test :is my network name
        # <- :ngircd.midnight.local 005 pylink-devel.int RFC2812 IRCD=ngIRCd CHARSET=UTF-8 CASEMAPPING=ascii PREFIX=(qaohv)~&@%+ CHANTYPES=#&+ CHANMODES=beI,k,l,imMnOPQRstVz CHANLIMIT=#&+:10 :are supported on this server
        # <- :ngircd.midnight.local 005 pylink-devel.int CHANNELLEN=50 NICKLEN=21 TOPICLEN=490 AWAYLEN=127 KICKLEN=400 MODES=5 MAXLIST=beI:50 EXCEPTS=e INVEX=I PENALTY :are supported on this server

        # Regular clientbot, connecting to InspIRCd:
        # <- :millennium.overdrivenetworks.com 005 ice AWAYLEN=200 CALLERID=g CASEMAPPING=rfc1459 CHANMODES=IXbegw,k,FJLfjl,ACKMNOPQRSTUcimnprstz CHANNELLEN=64 CHANTYPES=# CHARSET=ascii ELIST=MU ESILENCE EXCEPTS=e EXTBAN=,ACNOQRSTUcmprsuz FNC INVEX=I :are supported by this server
        # <- :millennium.overdrivenetworks.com 005 ice KICKLEN=255 MAP MAXBANS=60 MAXCHANNELS=30 MAXPARA=32 MAXTARGETS=20 MODES=20 NAMESX NETWORK=OVERdrive-IRC NICKLEN=21 OVERRIDE PREFIX=(Yqaohv)*~&@%+ SILENCE=32 :are supported by this server
        # <- :millennium.overdrivenetworks.com 005 ice SSL=[::]:6697 STARTTLS STATUSMSG=*~&@%+ TOPICLEN=307 UHNAMES USERIP VBANLIST WALLCHOPS WALLVOICES WATCH=32 :are supported by this server

        if not self._use_builtin_005_handling:
            log.warning("(%s) Got spurious 005 message from %s: %r", self.name, source, args)
            return

        newcaps = self.parse_isupport(args[1:-1])
        self._caps.update(newcaps)
        log.debug('(%s) handle_005: self._caps is %s', self.name, self._caps)

        if 'CHANMODES' in newcaps:
            self.cmodes['*A'], self.cmodes['*B'], self.cmodes['*C'], self.cmodes['*D'] = \
                newcaps['CHANMODES'].split(',')
        log.debug('(%s) handle_005: cmodes: %s', self.name, self.cmodes)

        if 'USERMODES' in newcaps:
            self.umodes['*A'], self.umodes['*B'], self.umodes['*C'], self.umodes['*D'] = \
                newcaps['USERMODES'].split(',')
        log.debug('(%s) handle_005: umodes: %s', self.name, self.umodes)

        if 'CASEMAPPING' in newcaps:
            self.casemapping = newcaps.get('CASEMAPPING', self.casemapping)
            log.debug('(%s) handle_005: casemapping set to %s', self.name, self.casemapping)

        if 'PREFIX' in newcaps:
            self.prefixmodes = prefixmodes = self.parse_isupport_prefixes(newcaps['PREFIX'])
            log.debug('(%s) handle_005: prefix modes set to %s', self.name, self.prefixmodes)

            # Autodetect common prefix mode names.
            for char, modename in self.COMMON_PREFIXMODES:
                # Don't overwrite existing named mode definitions.
                if char in self.prefixmodes and modename not in self.cmodes:
                    self.cmodes[modename] = char
                    log.debug('(%s) handle_005: autodetecting mode %s (%s) as %s', self.name,
                              char, self.prefixmodes[char], modename)

        # https://defs.ircdocs.horse/defs/isupport.html
        if 'EXCEPTS' in newcaps:
            # Handle EXCEPTS=e or EXCEPTS fields
            self.cmodes['banexception'] = newcaps.get('EXCEPTS') or 'e'
            log.debug('(%s) handle_005: got cmode banexception=%r', self.name, self.cmodes['banexception'])

        if 'INVEX' in newcaps:
            # Handle INVEX=I, INVEX fields
            self.cmodes['invex'] = newcaps.get('INVEX') or 'I'
            log.debug('(%s) handle_005: got cmode invex=%r', self.name, self.cmodes['invex'])

        if 'NICKLEN' in newcaps:
            # Handle NICKLEN=number
            assert newcaps['NICKLEN'], "Got NICKLEN tag with no content?"
            self.maxnicklen = int(newcaps['NICKLEN'])
            log.debug('(%s) handle_005: got %r for maxnicklen', self.name, self.maxnicklen)

        if 'DEAF' in newcaps:
            # Handle DEAF=D, DEAF fields
            self.umodes['deaf'] = newcaps.get('DEAF') or 'D'
            log.debug('(%s) handle_005: got umode deaf=%r', self.name, self.umodes['deaf'])

        if 'CALLERID' in newcaps:
            # Handle CALLERID=g, CALLERID fields
            self.umodes['callerid'] = newcaps.get('CALLERID') or 'g'
            log.debug('(%s) handle_005: got umode callerid=%r', self.name, self.umodes['callerid'])

    def _send_with_prefix(self, source, msg, **kwargs):
        """Sends a RFC1459-style raw command from the given sender."""
        self.send(':%s %s' % (self._expandPUID(source), msg), **kwargs)

    def _expandPUID(self, uid):
        """
        Returns the nick for the given UID; this method helps support protocol modules that use
        PUIDs internally but must send nicks in the server protocol.
        """
        # TODO: stop hardcoding @ as separator
        if uid in self.users and '@' in uid:
            # UID exists and has a @ in it, meaning it's a PUID (orignick@counter style).
            # Return this user's nick accordingly.
            nick = self.users[uid].nick
            log.debug('(%s) Mangling target PUID %s to nick %s', self.name, uid, nick)
            return nick
        return uid

class IRCS2SProtocol(IRCCommonProtocol):
    COMMAND_TOKENS = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protocol_caps = {'can-spawn-clients', 'has-ts', 'can-host-relay',
                              'can-track-servers'}

        # Alias
        self.handle_squit = self._squit

    def handle_events(self, data):
        """Event handler for RFC1459-like protocols.

        This passes most commands to the various handle_ABCD() functions
        elsewhere defined protocol modules, coersing various sender prefixes
        from nicks and server names to UIDs and SIDs respectively,
        whenever possible.

        Commands sent without an explicit sender prefix will have them set to
        the SID of the uplink server.
        """
        data = data.split(" ")
        args = self.parse_args(data)

        sender = args[0]
        sender = sender.lstrip(':')

        # If the sender isn't in numeric format, try to convert it automatically.
        sender_sid = self._get_SID(sender)
        sender_uid = self._get_UID(sender)

        if sender_sid in self.servers:
            # Sender is a server (converting from name to SID gave a valid result).
            sender = sender_sid
        elif sender_uid in self.users:
            # Sender is a user (converting from name to UID gave a valid result).
            sender = sender_uid
        elif not (args[0].startswith(':')):
            # No sender prefix; treat as coming from uplink IRCd.
            sender = self.uplink
            args.insert(0, sender)

        if self.is_internal_client(sender) or self.is_internal_server(sender):
            log.warning("(%s) Received command %s being routed the wrong way!", self.name, command)
            return

        raw_command = args[1].upper()
        args = args[2:]

        log.debug('(%s) Found message sender as %s, raw_command=%r, args=%r', self.name, sender, raw_command, args)

        # For P10, convert the command token into a regular command, if present.
        command = self.COMMAND_TOKENS.get(raw_command, raw_command)
        if command != raw_command:
            log.debug('(%s) Translating token %s to command %s', self.name, raw_command, command)

        if command == 'ENCAP':
            # Special case for TS6 encapsulated commands (ENCAP), in forms like this:
            # <- :00A ENCAP * SU 42XAAAAAC :GLolol
            command = args[1]
            args = args[2:]
            log.debug("(%s) Rewriting incoming ENCAP to command %s (args: %s)", self.name, command, args)

        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # Unhandled command
            pass
        else:
            parsed_args = func(sender, command, args)
            if parsed_args is not None:
                return [sender, command, parsed_args]

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = self.to_lower(channel)
        if not self.is_internal_client(client):
            log.error('(%s) Error trying to part %r from %r (no such client exists)', self.name, client, channel)
            raise LookupError('No such PyLink client exists.')
        msg = "PART %s" % channel
        if reason:
            msg += " :%s" % reason
        self._send_with_prefix(client, msg)
        self.handle_part(client, 'PART', [channel])

    def _ping_uplink(self):
        """Sends a PING to the uplink.

        This is mostly used by PyLink internals to check whether the remote link is up."""
        if self.sid:
            self._send_with_prefix(self.sid, 'PING %s' % self.sid)

    def quit(self, numeric, reason):
        """Quits a PyLink client."""
        if self.is_internal_client(numeric):
            self._send_with_prefix(numeric, "QUIT :%s" % reason)
            self._remove_client(numeric)
        else:
            raise LookupError("No such PyLink client exists.")

    def message(self, numeric, target, text):
        """Sends a PRIVMSG from a PyLink client."""
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')

        # Mangle message targets for IRCds that require it.
        target = self._expandPUID(target)

        self._send_with_prefix(numeric, 'PRIVMSG %s :%s' % (target, text))

    def notice(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client or server."""
        if (not self.is_internal_client(numeric)) and \
                (not self.is_internal_server(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        # Mangle message targets for IRCds that require it.
        target = self._expandPUID(target)

        self._send_with_prefix(numeric, 'NOTICE %s :%s' % (target, text))

    def squit(self, source, target, text='No reason given'):
        """SQUITs a PyLink server."""
        # -> SQUIT 9PZ :blah, blah
        log.debug('(%s) squit: source=%s, target=%s', self.name, source, target)
        self._send_with_prefix(source, 'SQUIT %s :%s' % (target, text))
        self.handle_squit(source, 'SQUIT', [target, text])

    def topic(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink client."""
        if not self.is_internal_client(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send_with_prefix(numeric, 'TOPIC %s :%s' % (target, text))
        self.channels[target].topic = text
        self.channels[target].topicset = True

    def check_nick_collision(self, nick):
        """
        Nick collision checker.
        """
        uid = self.nick_to_uid(nick)
        # If there is a nick collision, we simply alert plugins. Relay will purposely try to
        # lose fights and tag nicks instead, while other plugins can choose how to handle this.
        if uid:
            log.info('(%s) Nick collision on %s/%s, forwarding this to plugins', self.name,
                     uid, nick)
            self.call_hooks([self.sid, 'SAVE', {'target': uid}])

    def handle_away(self, numeric, command, args):
        """Handles incoming AWAY messages."""
        # TS6:
        # <- :6ELAAAAAB AWAY :Auto-away
        # P10:
        # <- ABAAA A :blah
        # <- ABAAA A
        try:
            self.users[numeric].away = text = args[0]
        except IndexError:  # User is unsetting away status
            self.users[numeric].away = text = ''
        return {'text': text}

    def handle_invite(self, numeric, command, args):
        """Handles incoming INVITEs."""
        # TS6:
        #  <- :70MAAAAAC INVITE 0ALAAAAAA #blah 12345
        # P10:
        #  <- ABAAA I PyLink-devel #services 1460948992
        #  Note that the target is a nickname, not a numeric.

        target = self._get_UID(args[0])
        channel = self.to_lower(args[1])

        curtime = int(time.time())
        try:
            ts = int(args[2])
        except IndexError:
            ts = curtime

        ts = ts or curtime  # Treat 0 timestamps (e.g. inspircd) as the current time.

        return {'target': target, 'channel': channel, 'ts': ts}

    def handle_kill(self, source, command, args):
        """Handles incoming KILLs."""
        killed = args[0]
        # Depending on whether the IRCd sends explicit QUIT messages for
        # killed clients, the user may or may not have automatically been
        # removed from our user list.
        # If not, we have to assume that KILL = QUIT and remove them
        # ourselves.
        data = self.users.get(killed)
        if data:
            self._remove_client(killed)

        # TS6-style kills look something like this:
        # <- :GL KILL 38QAAAAAA :hidden-1C620195!GL (test)
        # What we actually want is to format a pretty kill message, in the form
        # "Killed (killername (reason))".

        try:
            # Get the nick or server name of the caller.
            killer = self.get_friendly_name(source)
        except KeyError:
            # Killer was... neither? We must have aliens or something. Fallback
            # to the given "UID".
            killer = source

        # Get the reason, which is enclosed in brackets.
        reason = ' '.join(args[1].split(" ")[1:])

        killmsg = "Killed (%s %s)" % (killer, reason)

        return {'target': killed, 'text': killmsg, 'userdata': data}

    def handle_part(self, source, command, args):
        """Handles incoming PART commands."""
        channels = self.to_lower(args[0]).split(',')

        for channel in channels:
            self.channels[channel].remove_user(source)
            try:
                self.users[source].channels.discard(channel)
            except KeyError:
                log.debug("(%s) handle_part: KeyError trying to remove %r from %r's channel list?", self.name, channel, source)

            try:
                reason = args[1]
            except IndexError:
                reason = ''

            # Clear empty non-permanent channels.
            if not (self.channels[channel].users or ((self.cmodes.get('permanent'), None) in self.channels[channel].modes)):
                del self.channels[channel]

        return {'channels': channels, 'text': reason}

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # TS6:
        # <- :70MAAAAAA PRIVMSG #dev :afasfsa
        # <- :70MAAAAAA NOTICE 0ALAAAAAA :afasfsa
        # P10:
        # <- ABAAA P AyAAA :privmsg text
        # <- ABAAA O AyAAA :notice text
        target = self._get_UID(args[0])

        # Coerse =#channel from Charybdis op moderated +z to @#channel.
        if target.startswith('='):
            target = '@' + target[1:]

        # We use lowercase channels internally, but uppercase UIDs.
        # Strip the target of leading prefix modes (for targets like @#channel)
        # before checking whether it's actually a channel.

        split_channel = target.split('#', 1)
        if len(split_channel) >= 2 and utils.isChannel('#' + split_channel[1]):
            # Note: don't mess with the case of the channel prefix, or ~#channel
            # messages will break on RFC1459 casemapping networks (it becomes ^#channel
            # instead).
            target = '#'.join((split_channel[0], self.to_lower(split_channel[1])))
            log.debug('(%s) Normalizing channel target %s to %s', self.name, args[0], target)

        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def handle_quit(self, numeric, command, args):
        """Handles incoming QUIT commands."""
        # TS6:
        # <- :1SRAAGB4T QUIT :Quit: quit message goes here
        # P10:
        # <- ABAAB Q :Killed (GL_ (bangbang))
        self._remove_client(numeric)
        return {'text': args[0]}

    def handle_time(self, numeric, command, args):
        """Handles incoming /TIME requests."""
        return {'target': args[0]}

    def handle_whois(self, numeric, command, args):
        """Handles incoming WHOIS commands.."""
        # TS6:
        # <- :42XAAAAAB WHOIS 5PYAAAAAA :pylink-devel
        # P10:
        # <- ABAAA W Ay :PyLink-devel

        # First argument is the server that should reply to the WHOIS request
        # or the server hosting the UID given. We can safely assume that any
        # WHOIS commands received are for us, since we don't host any real servers
        # to route it to.

        return {'target': self._get_UID(args[-1])}

    def handle_version(self, numeric, command, args):
        """Handles requests for the PyLink server version."""
        return {}  # See coremods/handlers.py for how this hook is used

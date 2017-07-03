"""
ngircd.py: PyLink protocol module for ngIRCd.
"""
##
# Server protocol docs for ngIRCd can be found at:
#     https://github.com/ngircd/ngircd/blob/master/doc/Protocol.txt
# and https://tools.ietf.org/html/rfc2813
##

import time
import re

from pylinkirc import utils, conf, __version__
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

S2S_BUFSIZE = 510

class NgIRCdProtocol(IRCS2SProtocol):
    def __init__(self, irc):
        super().__init__(irc)

        self.conf_keys -= {'sid', 'sidrange'}
        self.casemapping = 'rfc1459'

        # Track whether we've received end-of-burst from the uplink.
        self.has_eob = False

        self.uidgen = utils.PUIDGenerator("PUID")

    ### Commands

    def post_connect(self):
        self.send('PASS %s 0210-IRC+ PyLink|%s:LMoX' % (self.serverdata['sendpass'], __version__))
        self.send("SERVER %s 1 :%s" % (self.serverdata['hostname'],
                                       self.serverdata.get('serverdesc') or conf.conf['pylink']['serverdesc']));
        self.sid = self.serverdata['hostname']

    def spawn_client(self, nick, ident='null', host='null', realhost=None, modes=set(),
            server=None, ip='0.0.0.0', realname=None, ts=None, opertype='IRC Operator',
            manipulatable=False):
        """
        Spawns a new client with the given options.

        Note: No nick collision / valid nickname checks are done here; it is
        up to plugins to make sure they don't introduce anything invalid.

        Note 2: IP and realhost are ignored because ngIRCd does not send them.
        """
        server = server or self.sid
        if not self.is_internal_server(server):
            raise ValueError('Server %r is not a PyLink server!' % server)

        realname = realname or conf.conf['bot']['realname']

        uid = self.uidgen.next_uid(prefix=nick)
        userobj = self.users[uid] = User(nick, ts, uid, server, ident=ident, host=host, realname=realname,
                                         manipulatable=manipulatable, opertype=opertype)

        self.apply_modes(uid, modes)
        self.servers[server].users.add(uid)

        # <- :ngircd.midnight.local NICK GL 1 ~gl localhost 1 +io :realname
        self._send_with_prefix(server, 'NICK %s 1 %s %s 1 %s :%s' % (nick, ident, host, self.join_modes(modes), realname))
        return userobj


    def spawn_server(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        pass
        '''
        """
        Spawns a server off a PyLink server.

        * desc (server description) defaults to the one in the config.
        * uplink defaults to the main PyLink server.
        * SID is set equal to the server name for ngIRCd.

        Note: TS6 doesn't use a specific ENDBURST command, so the endburst_delay
        option will be ignored if given.
        """
        # -> :0AL SID test.server 1 0XY :some silly pseudoserver
        uplink = uplink or self.sid
        name = name.lower()

        desc = desc or self.serverdata.get('serverdesc') or conf.conf['bot']['serverdesc']

        if sid in self.servers:
            raise ValueError('A server named %r already exists!' % sid)

        if not self.is_internal_server(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)

        if not utils.isServerName(name):
            raise ValueError('Invalid server name %r' % name)


        self._send_with_prefix(uplink, 'SID %s 1 %s :%s' % (name, sid, desc))
        self.servers[sid] = Server(uplink, name, internal=True, desc=desc)
        return sid
        '''

    def join(self, client, channel):
        return

    def ping(self, *args):
        self.lastping = time.time()

    ### Handlers

    def handle_pass(self, source, command, args):
        """
        Handles phase one of the ngIRCd login process (password auth and version info).
        """
        # PASS is step one of server introduction, and is used to send the server info and password.
        # <- :ngircd.midnight.local PASS xyzpassword 0210-IRC+ ngIRCd|24~3-gbc728f92:CHLMSXZ PZ
        recvpass = args[0]
        if recvpass != self.serverdata['recvpass']:
            raise ProtocolError("RECVPASS from uplink does not match configuration!")

        assert 'IRC+' in args[1], "Linking to non-ngIRCd server using this protocol module is not supported"

    def handle_server(self, source, command, args):
        """
        Handles the SERVER command, used to introduce SID-less servers.
        """
        # <- :ngircd.midnight.local SERVER ngircd.midnight.local 1 :ngIRCd dev server
        servername = args[0].lower()
        serverdesc = args[-1]

        self.servers[servername] = Server(servername, servername, desc=serverdesc)

        if self.uplink is None:
            self.uplink = servername
            log.debug('(%s) Got %s as uplink', self.name, servername)
        else:
            # Only send the SERVER hook if this isn't the initial connection.
            return {'name': servername, 'sid': None, 'text': serverdesc}

    def handle_nick(self, source, command, args):
        # <- :ngircd.midnight.local NICK GL 1 ~gl localhost 1 +io :realname

        nick = args[0]
        ident = args[2]
        host = args[3]
        uid = self.uidgen.next_uid(prefix=nick)
        realname = args[-1]

        self.users[uid] = User(nick, int(time.time()), uid, source, ident=ident, host=host,
                               realname=realname)
        parsedmodes = self.parse_modes(uid, [args[5]])
        self.apply_modes(uid, parsedmodes)

    def handle_ping(self, source, command, args):
        if source == self.uplink:
            # Note: SID = server name here
            self._send_with_prefix(self.sid, 'PONG %s :%s' % (self.sid, args[-1]), queue=False)

            if not self.has_eob:
                # Treat the first PING we receive as end of burst.
                self.has_eob = True
                self.connected.set()

                # Return the endburst hook.
                return {'parse_as': 'ENDBURST'}


Class = NgIRCdProtocol

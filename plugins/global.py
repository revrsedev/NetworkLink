# global.py: Global Noticing Plugin

__authors__ = [("Ken Spencer", "Iota <ken@electrocode.net>")]
__version__ = "0.0.1"

from pylinkirc import conf, utils, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

def g(irc, source, args):
    """<message text>
    
    Sends out a Instance-wide notice.
    """
    permissions.checkPermissions(irc, source, ["global.global"])
    message = " ".join(args)
    message = message + " (sent by %s@%s)" % (irc.getFriendlyName(irc.called_by), irc.getFullNetworkName())
    for name, ircd in world.networkobjects.items():
        for channel in ircd.pseudoclient.channels:
            ircd.msg(channel, message)
        

utils.add_cmd(g, "global", featured=True)

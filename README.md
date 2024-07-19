# NetworkLink IRC Services

<!--
[![Latest stable release](https://img.shields.io/github/v/tag/jlu5/pylink?label=stable&color=1a1)](https://github.com/PyLink/PyLink/tree/master)
[![PyPI version](https://img.shields.io/pypi/v/pylinkirc.svg?maxAge=2592000)](https://pypi.python.org/pypi/pylinkirc/)
[![Docker image version](https://img.shields.io/docker/v/jlu5/pylink/latest?label=docker)](https://hub.docker.com/r/jlu5/pylink)
[![Supported Python versions](https://img.shields.io/badge/python-3.7%20and%20later-50e)](https://www.python.org/downloads/)
-->

NetworkLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a transparent server-side relayer between IRC networks.

2) a versatile framework for developing IRC services.

PyLink is licensed under the Mozilla Public License, version 2.0 ([LICENSE.MPL2](LICENSE.MPL2)). The [corresponding documentation](docs/) is licensed under the Creative Attribution-ShareAlike 4.0 International License. ([LICENSE.CC-BY-SA-4.0](LICENSE.CC-BY-SA-4.0))

## Getting help

**First, MAKE SURE you've read the [FAQ](docs/faq.md)!**

**When upgrading between major versions, remember to read the [release notes](RELNOTES.md) for any breaking changes!**

Please report any bugs you find to the [issue tracker](https://github.com/PyLink/PyLink/issues). Pull requests are likewise welcome.

## Installation

### Pre-requisites
* Python 3.7 or above - prefer the newest Python 3.x when available
* A Unix-like operating system: PyLink is actively developed on Linux only, so we cannot guarantee that things will work properly on other systems.

If you are a developer and want to help make PyLink more portable, patches are welcome.

### Installing from source

1) First, make sure the following dependencies are met:

    * Setuptools (`pip3 install setuptools`)
    * PyYAML (`pip3 install pyyaml`)
    * cachetools (`pip3 install cachetools`)
    * *For hashed password support*: Passlib >= 1.7.0 (`pip3 install passlib`)
    * *For Unicode support in Relay*: unidecode (`pip3 install Unidecode`)
    * *For extended PID file tracking (i.e. removing stale PID files after a crash)*: psutil (`pip3 install psutil`)

2) Clone the repository: `git clone https://github.com/PyLink/PyLink && cd PyLink`
    - Previously there was a *devel* branch for testing versions of NetworkLink - this practice has since been discontinued.

3) Install NetworkLink using `python3 setup.py install` (global install) or `python3 setup.py install --user` (local install)
    * Note: `--user` is a *literal* string; *do not* replace it with your username.
    *  **Whenever you switch branches or update PyLink's sources via `git pull`, you will need to re-run this command for changes to apply!**

### Installing via PyPI (stable branch only)

1) Make sure you're running the right pip command: on most distros, pip for Python 3 uses the command `pip3`.

2) Run `pip3 install pylinkirc` to download and install PyLink. pip will automatically resolve dependencies.

3) Download or copy https://github.com/PyLink/PyLink/blob/master/example-conf.yml for an example configuration.

## Configuration

1) Rename `example-conf.yml` to `pylink.yml` (or a similarly named `.yml` file) and configure your instance there.

2) Run `pylink` from the command line. PyLink will load its configuration from `pylink.yml` by default, but you can override this by running `pylink` with a config argument (e.g. `pylink mynet.yml`).

## Supported IRCds

These IRCds are frequently tested and well supported. If any issues occur, please file a bug on the issue tracker.

* [InspIRCd](http://www.inspircd.org/) (2.0 - 3.x) - module `inspircd`
    - Set the `target_version` option to `insp3` to target InspIRCd 3.x (default), or `insp20` to target InspIRCd 2.0 (legacy).
    - For vHost setting to work, `m_chghost.so` must be loaded. For ident and realname changing support, `m_chgident.so` and `m_chgname.so` must be loaded respectively.
    - Supported channel, user, and prefix modes are negotiated on connect, but hotloading modules that change these is not supported. After changing module configuration, it is recommended to SQUIT PyLink to force a protocol renegotiation.

* [UnrealIRCd](https://www.unrealircd.org/) (4.2.x - 5.0.x) - module `unreal`
    - Supported channel, user, and prefix modes are negotiated on connect, but hotloading modules that change these is not supported. After changing module configuration, it is recommended to SQUIT PyLink to force a protocol renegotiation.

### Clientbot

NetworkLink supports connecting to IRCds as a relay bot and forwarding users back as virtual clients, similar to Janus' Clientbot. This can be useful if the IRCd a network used isn't supported, or if you want to relay certain channels without fully linking with a network.

For Relay to work properly with Clientbot, be sure to load the `relay_clientbot` plugin in conjunction with `relay`.

Note: **Clientbot links can only be used as a leaf for Relay links - they CANNOT be used to host channels!** This means that Relay does not support having all your networks be Clientbot - in those cases you are better off using a classic relay bot, like [RelayNext for Limnoria](https://github.com/jlu5/SupyPlugins/tree/master/RelayNext).

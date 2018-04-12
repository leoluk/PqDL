#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

"""
PQdl is a tool that can download Pocket Queries from geocaching.com.
Pocket Queries that contain more than 500 caches won't be sent per mail, so you
need to do it by hand or with this script.
This script is written by leoluk.
Please look at www.leoluk.de/paperless-caching/pqdl for updates.

"""

__version__ = "0.3.3"
__status__ = "beta"
__author__ = "Leopold Schabel"

### pylint
# pylint: disable-msg=E1102, W0142
### endpylint

# stdlib imports

RAW_BASE_URL = "http%s://www.geocaching.com"
BASE_URL = RAW_BASE_URL % ""

import mechanize
import optparse
import cookielib
import os
import BeautifulSoup
import re
import sys
import random
import ConfigParser
import zipfile
import getpass
import fnmatch
import logging
import urllib2
import uuid
import webbrowser
import functools
import base64

from time import sleep

# Inits the default logger; I use a seperate logger for every part of the
# program. This allows some nicely formatted output
logging.basicConfig(stream=sys.stdout,
                    format="%(levelname)s - %(name)s -> %(message)s",
                    level=logging.DEBUG)

# I need a new level for HTTP debug as it generates so much output
# This lvel can only be used with logger.log(5, "message")
logging.addLevelName(5,'HTTPDEBUG')

def gdelay(odelay):
    """This method waits a random time if odelay == True.
    Please note this is best used with functools.partial
    """
    if odelay:
        logger = logging.getLogger('main.delay')
        logger.debug("Waiting random time")
        sleep(random.randint(500, 5000) / 1000)


def check_update(browser=True):
    """This method checks for new updates on a compatible update server."""

    updateserver = "http://update.leoluk.de"

    # Getting the logger for this method. I do this for every logical part of
    # the program, so it won't be commented later.

    logger = logging.getLogger('update')
    logger.info('Checking updates for PqDL...')

    # Building the URL to request. It contains the server name, the program and
    # the version string and a uuid.uuid1() for identification.
    # If the version is stable, the __status__-String is omitted
    # (this is required for the compairision on the server).

    url = "{server}/{program}/{version}/{uuid}".format(
        server=updateserver,
        program='pqdl',
        version='{version}{suffix}'.format(
            version=__version__,
            suffix=(('-'+__status__) if __status__ != 'stable' else '')
            ),
        uuid=str(uuid.uuid1())
        )

    # The entire update process will run in a catchall-try-except to not
    # interrupt the program. If an exception occurs, it will be printed
    # including a traceback.

    try:
        # Opening the URL that was built before
        request = urllib2.urlopen(url)
        # Making a new ConfigParser and feeding it with the request result
        parser = ConfigParser.ConfigParser()
        # urllib2.urlopen returns a file-like object, so I can do this:
        parser.readfp(request)

        def log_message(logger, message):
            """Generic code that prints a received message. Message string
            should be in this format:

            priority,message

            Parameters:
            logger -- a logging.Logger instance
            message -- the message

            If no priority found, it will use the plain message with priority
            20 as fallback.

            """

            data = message.split(',', 1)
            try:
                logger.log(int(data[0]), data[1])
            except ValueError:
                logger.info(message)

        # Parse the [Message] part of the update response

        if parser.has_section('Message'):
            logger = logging.getLogger('update.msg')
            if parser.has_option('Message', 'msg'):
                log_message(logger, parser.get('Message', 'msg'))
            if parser.has_option('Message', 'privmsg'):
                log_message(logger, parser.get('Message', 'privmsg'))

        # An update response has to contain a [Program] section.
        # (the [Message] is not required)

        if not parser.has_section('Program'):
            logger.error('Invalid update data: no header')
            return

        # Shortcut definition
        result = parser.get('Program', 'result')

        # Version check (the version check itself will be done on the server)
        if result == 'latest':
            logger.info("You are using the latest version")
            return # no more informations anyway
        elif result == 'future':
            logger.info("You are using a beta version")
            return #same as above
        elif result == 'new':
            # The first time the server gets a request from a specific
            # client (identified by the UUID) of a specific version, it
            # will send 'new', later it will send 'known'
            if browser:
                webbrowser.open_new_tab(parser.get('Program','url'))
            else:
                logger.info('Please update as soon as possible.')
        elif result == 'known':
            # Remind the user to update the script
            logger.warning("It is important to update PqDL!")
        else:
            # This should never happen
            logger.error("Server returned invalid result: %s" % result)

        # If the function is still running, a new version is available

        logger.info(
            "A newer version is available! Your version: {oldversion}, "
            "new version: {newversion}".format(oldversion="%s-%s" % (
                __version__, __status__),
                                    newversion=parser.get(
                                        'Program', 'version')))

        logger.info("More info on %s" % parser.get('Program', 'url'))

    except BaseException:
        # End of the catchall block, will print a traceback along with the
        # error message.
        logger.exception("Autoupdate on update.leoluk.de failed")


def rename(source, dest, *args, **kwargs):
    """os.rename with automatic output to the main logger. Will catch and
    handle all related errors and print a traceback.
    """
    logger = logging.getLogger('tool.rename')
    try:
        os.rename(source, dest, *args, **kwargs)
        logger.info("Renaming {0} to {1}".format(source, dest))
    except WindowsError:
        logger.exception('Renaming {0} to {1} failed'.format(source, dest))


def remove(path, *args, **kwargs):
    """os.remove with automatic output to the main logger. Will catch and
    handle all related errors and print a traceback.
    """
    logger = logging.getLogger('tool.remove')
    try:
        os.remove(path, *args, **kwargs)
        logger.debug("Removing %s" % path)
    except WindowsError:
        logger.exception('Removing %s failed' % path)

def optparse_setup():
    """Parsing options given to PqDL, should be called from main()"""
    desc = __doc__
    epilog = """This tool probably violates the Terms of Service by Groundspeak.
Please don't abuse it. If any argument (username, password, PQ names, ...)
contains spaces, put it into parantheses. """

    # custom usage string
    usage = ("%prog [-h] -u USERNAME -p PASSWORD [-o OUTPUTDIR] [options] "
             "[pq_1 pq_2 ...]")
    # optparse setup
    parser = optparse.OptionParser(description=desc,
                                   version="%%prog %s-%s"
                                   % (__version__, __status__),
                                   epilog=epilog,
                                   usage=usage)

    logger = logging.getLogger('cmdline')
    # Using an empty group as help text
    grp_prm = optparse.OptionGroup(parser, "Arguments", description=
"""Pass the names of the Pocket Queries you want to download as parameters
(pq_1 pq_2 ...). (case sensitive!) If none given, it will try to download all
of them. You can exlude PQs by adding # on the beginning of the name.
You need to specify the 'friendly name', the name, the date, the cache count or
the ID of a PQ. You can use UNIX-style wildcards (*, ?, [x], [!x]). Please run
with -d -l to get the friendly name or other parameters.""")

    parser.add_option_group(grp_prm)

    def print_help(*args, **kwargs):
        """Handler for print_help that does prints a newline after the text"""
        parser.print_help(*args, **kwargs)
        print '\n'

    # Core options
    parser.add_option('-u', '--username', help="Username on GC.com "
                      "(use parentheses if it contains spaces)")
    parser.add_option('-p', '--password', help="Password on GC.com "
                      "(use parentheses if it contains spaces), you will be "
                      "asked if you don't specify it (you can omit this!)")
    parser.add_option('--b64password', help="Base64-encoded password. This "
                      "should be used if you use a config file or store the "
                      "used command in a file instead of the normal password.")
    parser.add_option('--getb64', help="Output the used password as base64.",
                      default=False, action='store_true')
    parser.add_option('-o', '--outputdir', help="Output directory for "
                      "downloaded files (will be created if it doesn't exists "
                      "yet), will be set as default for other file parameters, "
                      "sets the working dir [default: %default]",
                      default=os.getcwd())
    parser.add_option('-r', '--remove', help="Remove downloaded files from "
                      "GC.com. WARNING: This deletes the files ONLINE! Consider"
                      " using the journal instead of this.", default=False,
                      action='store_true')
    parser.add_option('-n', '--nospecial', help="Ignore special Pocket Queries "
                      "that can't be removed like My Finds.", default=False,
                      action='store_true')
    parser.add_option('--noupdate', help="Skip the online update check. Please "
                      "make sure to check updates yourself!", default=False,
                      action='store_true')
    parser.add_option('--nobrowser', help="Don't open the browser on new "
                      "versions. The browser will be opened only once even "
                      "without that switch.", default=False,
                      action='store_true')
    parser.add_option('--noexit', help="Wait on the end of the program for a "
                      "keypress. USeful if you invoke the script from a GUI "
                      "like GSAK and you don't want it to close.", default=False
                      , action='store_true')
    parser.add_option('--allsecure', help="Use HTTPS for all requests.",
                      default=False,
                      action='store_true')
    parser.add_option('--loginsecure', help="Use HTTPS for login requests.",
                      default=False,
                      action='store_true')
    parser.add_option('--netdebug', help="For internal debugging. Do not use.",
                      default=False,
                      action='store_true')
    parser.add_option('--noini', help="Ignore pqdl.ini.", default=False
                      , action='store_true')
    parser.add_option('--ini', help="Custom settings file. Syntax see online "
                      "docs. If a file named pqdl.ini is found in the program "
                      "or output dir, it will be used automatically. If you "
                      "specify it using this option, it will be searched "
                      "in the output (-o) path.",
                      default="pqdl.ini")

    # ZIP options
    grp_zip = optparse.OptionGroup(parser, "ZIP options",
"""PqDL supports unzipping the Pocket Queries. They will be renamed
automatically after unzipping by this pattern:
Name-of-PQ_1234567_06-12-2010[_waypoints].gpx (-s will be used). Note: if you
want to your PQs with GSAK or pqloader, there's no need to unzip them!""")

    grp_zip.add_option('-z', '--unzip', help="Unzips and removes the "
                       "downloaded ZIP files.", default=False,
                       action='store_true')
    grp_zip.add_option('--keepzip', help="Do not remove unzipped files. "
                       "(to be used with -z)", default=False,
                       action='store_true')
    parser.add_option_group(grp_zip)

    # back to core
    parser.add_option('-s', '--singlefile', help="Overwrite existing files. "
                      "When using this option, there won't be any timestamps "
                      "added! (so just one file for every PQ in your DL folder)"
                      ", applies to unzip too", action="store_true", #
                      default=False)
    parser.add_option('-e', '--delay', help="Random delays between the requests"
                      , default=False, action='store_true')
    parser.add_option('-l', '--list', help="Do not download anything, "
                      "just list the files. Best to be used with -d.",
                      default=False, action='store_true')

    # Debug and logging options
    grp_dbg = optparse.OptionGroup(parser, "Logging options", """They are lots
of debug options. You should always use -d if the program doesn not exactly
does what it's supposed to do, they are lots of interesting debug outputs.
The other debug options are only needed for debugging special problems with
the parser. PLEASE ALWAYS USE -d IF YOU SEND ME A BUG REPORT!""")
    grp_dbg.add_option('-d', '--debug', help="Debug output, will set --loglevel"
                       " to DEBUG", default=False, action='store_true')
    grp_dbg.add_option('--ctl', help="Remove-CTL value, used for debugging very"
                       " special problems with -r (default: %default)",
                       default='search')
    grp_dbg.add_option('--logfile', help="Specify a filename if you want "
                       "logging to a file.")
    grp_dbg.add_option('--loglevel', help="Set the loglevel. Available (in "
                       "severity order): HTTPDEBUG, DEBUG, INFO, WARNING, "
                       "ERROR, CRITICAL. You usally only need HTTPDEBUG, DEBUG "
                       "or INFO. Default is %default. Overrides -d",
                       default='INFO', choices=('HTTPDEBUG', 'DEBUG', 'INFO',
                                                'WARNING', 'ERROR', 'CRITICAL'))
    grp_dbg.add_option('--logmode', help="Set the logfile access mode, append "
                       "or overwrite.", default='append', choices=('append',
                                                                   'overwrite'))
    grp_dbg.add_option('--pqsitefile', help="This will replace the PQ listing "
                       "download with a file. This will skip login and PQ site "
                       "fetch, but not the download of the PQs themselves. "
                       "If you want to skip that too, use -l.")
    parser.add_option_group(grp_dbg)

    # Journal and map file options
    grp_journal = optparse.OptionGroup(parser, "Journal and map options",
"""These are special options that will allow PqDL to remember which PQs have
already been downloaded. This is based on the PQ latest generation date, if the
PQ gets generated again, it will be downloaded.
The journal file is an .ini file (by default filestate.txt) that can be used
for the mappings too. The section for this feature is [Log].
"""
                                       )
    grp_journal.add_option('-j', '--journal', help="Create a download journal "
                           "file. Files downloaded while using -j there won't "
                           "be downloaded again (requires -j or --usejournal)",
                           default=False, action='store_true')
    grp_journal.add_option('--usejournal', help="Like -j, but in read-only "
                           "mode, it won't add new PQs or pqloader mappings to "
                           "the journal (-j or this one!)", default=False,
                           action='store_true')
    grp_journal.add_option('--resetjournal', help="Reset the log section of the"
                           " journal", default=False, action='store_true')
    grp_journal.add_option('--journalfile', help="Filename of journal file "
                           "[default: %default]", default="filestate.txt")
    parser.add_option_group(grp_journal)

    # GSAK options
    grp_map = optparse.OptionGroup(parser,
                                   "GSAK/pqloader file mappings options",
"""This is a feature made for those who use PqDL in conjunction with pqloader.
pqloader will take the first word in a PQs file name to decide in which database
the PQs will be saved. This feature allows you to add this prefix automatically
after downloading the PQs, so you don't longer need to rename your
PQs online! This feature will use an .ini file like -j (this can be the same
one, the default is filestate.txt too). In order to use this, you need to add
a new section [Map] to the .ini file and mappings like My-PQ-Name=PQ-Prefix
(one per line). You can use the name, friendlyname, date or ID, but no
wildcards yet."""
)

    grp_map.add_option('-m', '--mappings', help="Assign a GSAK Database for "
                       "pqloader to every PQ, requires journal", default=False,
                       action='store_true')
    grp_map.add_option('--mapfile', help="File that contains the mapping "
                       "section, default is the journal file. "
                       "[default: %default, or the custom journal file if set]."
                       " For usage examples look at the project site.",
                       default="filestate.txt", action='store_true')
    grp_map.add_option('--sep', help="Seperator for pqloader "
                       "[default: '%default']", default=" ",
                       action='store_true')
    parser.add_option_group(grp_map)

    # back to core
    parser.add_option('--myfinds', help="Trigger a My Finds Pocket Query if "
                      "possible (you'll most likely need to run this program "
                      "again if the PQ is not generated fast enough, so "
                      "consider using --myfinds with -l)", default=False,
                      action='store_true')
    opts, args = parser.parse_args()

    # Alternate way to set options, with a pqdl.ini that should be located
    # in the -o or the program file directory.

    if not opts.noini:

        oparse = ConfigParser.ConfigParser()
        # Multiple locations, it will prefer the first one
        oparse.read([
            opts.ini,
            os.path.join(opts.outputdir, 'pqdl.ini'),
            os.path.join(os.path.dirname(sys.argv[0]),'pqdl.ini')
        ])
        # [Options]
        # should contain key=value where key is a optparse name
        if oparse.has_section('Options'):
            for setting in oparse.items('Options'):
                setattr(opts, setting[0], setting[1])
        # [Arguments]
        # should contain randomkey=value where randomkey can be random, value
        # should be a valid argument.
        if oparse.has_section('Arguments'):
            for setting in oparse.items('Arguments'):
                args.append(setting[1])

    # Check if base64-encoded password is specified, if yes, replace the
    # password field with it.
    if opts.b64password:
        try:
            opts.password = base64.b64decode(opts.b64password)
        except ValueError:
            logger.error('Base64 password not valid!')

    # If no simulation, require username
    if not opts.username and not opts.pqsitefile:
        print_help()
        logger.critical("Please specify a username, I won't use mine :-)")
        sys.exit(1)

    # If mappings are used and the journal file has not the default value,
    # but the mapfile, overwrite the mapfile with the journalfile path.
    if (opts.mappings) and (opts.journalfile != 'filestate.txt') \
       and (opts.mapfile == 'filestate.txt'):
        opts.mapfile = opts.journalfile

    # If no simulation and password, request it.
    if not opts.password and not opts.pqsitefile:
        opts.password = getpass.getpass("\nPassword for %s: " % opts.username)
        print ''

    # The password should be available now, so let's check if the user
    # requested it encoded to base64.
    if opts.getb64:
        logger.info("Password as base64: %s",
                    base64.b64encode(opts.password))

    # Sorry, but read-write and read-only can't be used at the same time :)
    if opts.journal and opts.usejournal:
        print_help()
        logger.critical("You should decide if you want to write to the journal "
                        "file or not. Please use --usejournal *or* -j !")
        sys.exit(1)

    # If you don't unzip, the zip will be kept anyway.
    if opts.keepzip and not opts.unzip:
        print_help()
        logger.critical("You can't use --keepzip without -z (--unzip).")
        sys.exit(1)

    # Shortcut for debug logging
    if opts.debug:
        level = logging.DEBUG
    else:
        # Logging level mappings including the selfmade one (see above)
        levels = {
            'HTTPDEBUG': 5,
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
            }
        level = levels[opts.loglevel]

    logging.root.setLevel(level)

    # Assign the logfile to the root logger if specified and setup the logging
    if opts.logfile:
        filehandler = logging.FileHandler(opts.logfile,
                                          mode = ('a' if
                                                  opts.logmode == 'append'
                                                  else 'w'))
        filehandler.formatter = logging.Formatter(
            "%(module)s line %(lineno)d - %(asctime)s - %(levelname)s - \
            %(funcName)s - %(name)s - %(message)s")
        logging.root.addHandler(filehandler)

    return opts, args


class PqDLError(Exception):
    """Generic error for PqDL errors."""
    def __init__(self, value):
        Exception.__init__(self, value)
        self.value = value
    def __str__(self):
        return repr(self.value)


class LoginError(PqDLError):
    """Wrong password error."""
    pass

class PqBrowser(mechanize.Browser):
    """A mechanize.Browser() that provides additional GC.com access features."""

    def __init__(self):
        """Inits the mechanize browser class."""
        mechanize.Browser.__init__(self)
        # Get the logger
        self.logger = logging.getLogger('browser')
        # Various options
        cookiejar = cookielib.LWPCookieJar()
        self.set_cookiejar(cookiejar)
        self.set_handle_equiv(True)
        #self.set_handle_gzip(True)
        self.set_handle_redirect(True)
        self.set_handle_referer(True)
        self.set_handle_robots(False)
        # Follows refresh 0 but not hangs on refresh > 0
        #self.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(),
        #                      max_time=1)
        # Want debugging messages?
        #if debug:
        #    self.set_debug_http(True)
        #    self.set_debug_redirects(True)
        #    self.set_debug_responses(True)

        # User-Agent (this is cheating, ok?)
        self.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; '
        'en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1')]
        # Attributes that will be set from outer scope
        self.pqsimulate = False
        self.pqfile = None

    def login_gc(self, username, password, urlbase):
        """Login to GC.com site."""
        logger = logging.getLogger('browser.login')
        self.open("%s/login/default.aspx?RESET=Y"
                  % urlbase)
        #for f in self.forms():
        #   print f
        self.select_form(action="/account/login?RESET=Y")
        self.form['Username'] = username
        self.form['Password'] = password
        self.submit()
        response = self.response().read()
        logger.log(5, response)
        if not '/my/default.aspx' in response:

            logger.critical("Could not log in. Please check your password. "
                            "If your username or password contains spaces, "
                            "put it into parentheses!")
            sys.exit(1)

    def delete_pqs(self, chkid, ctl):
        """Deletes downloadable PQs with given ids."""

        logger = logging.getLogger('browser.delpq')
        self.open("%s/pocket/default.aspx" % BASE_URL)
        self.select_form(id="aspnetForm")
        self.form.set_all_readonly(False)
        self.form['ctl00$ContentBody$PQDownloadList$hidIds'] = (",".join(chkid)
                                                                + ",")
        self.form['__EVENTTARGET'] = ("ctl00$ContentBody$PQDownloadList$"
                                      "uxDownloadPQList$ctl%s$lnkDeleteSelected"
                                      % ctl)
        self.submit()
        logger.log(5, self.response().read())

    def trigger_myfinds(self):
        """Request a MyFinds-PocketQuery if available."""
        logger = logging.getLogger('browser.myfinds')
        try:
            logger.info("Trigger My Finds PQ...")
            self.open("%s/pocket/default.aspx" % BASE_URL)
            self.select_form(id="aspnetForm")
            self.form.set_all_readonly(False)
            self.form['ctl00$ContentBody$PQListControl1$btnScheduleNow'] = (
                "Add to Queue"
                )
            self.submit()
        except ValueError:
            logger.error("My Finds Pocket Query not available.")

    def find_ctl(self):
        """Find the current GC.com ctl value."""
        self.open("%s/pocket/default.aspx" % BASE_URL)
        response = self.response().read()
        isinstance(response, str)
        tmpl = ("javascript:__doPostBack('ctl00$ContentBody$PQDownloadList$"
                "uxDownloadPQList$ctl")
        ind = response.index(tmpl)+len(tmpl)
        return response[ind:ind+2]

    def get_link_db(self, special):
        """Gets the link DB. Requires login first!"""
        logger = logging.getLogger('browser.parser')
        if not self.pqsimulate:
            response = self.open(
                "%s/pocket/default.aspx" % BASE_URL).read()
            if not "/my/default.aspx" in response:
                logger.error("Invalid PQ site. Not logged in?")
        else:
            response = open(self.pqfile, 'r')
        #f = open('debug.txt')
        #response = f.read()

        soup = BeautifulSoup.BeautifulSoup(response)
        links = soup(id=re.compile("trPQDownloadRow"))

        logger.log(5, response)

        linklist = []
        for link in links:
            try:
                chkdelete = link.contents[1].contents[1]['value']
            except IndexError:
                if special:
                    chkdelete = 'myfinds'
                else:
                    logger.debug("MyFinds skipped because of -n" )
                    continue

            linklist.append({
                'type': 'normal',
                'index': link.contents[3].contents[0].strip().strip('.'),
                'url': link.contents[5].contents[3]['href'],
                'name': link.contents[5].contents[3].contents[0].strip(),
                'friendlyname': slugify(link.contents[5].contents[3].\
                                        contents[0].strip()),
                'size': link.contents[7].contents[0].strip(),
                'count': link.contents[9].contents[0].strip(),
                'date': link.contents[11].contents[0].strip().split(' ')[0].\
                                        replace('/','-'),
                #'preserve': link.contents[11].contents[0].split(' ',1)[1]\
                #[1:-1],
                'chkdelete': chkdelete,
            })

        return linklist

    def download_pq(self, link, filename, hook):
        """Retrieve a PQ from an URL and save it"""
        baseurl = 'http://www.geocaching.com'
        self.retrieve(baseurl+link, filename, hook)

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip())
    return re.sub('[-\s]+', '-', value)

def get_mapstr(mparser, link):
    """Searches a valid mapping for a PQ on the mapping config parser."""
    isinstance(mparser, ConfigParser.ConfigParser)
    logger = logging.getLogger('main.mapping.getstr')
    if mparser.has_section('Map'):
        for key in ('chkdelete', 'friendlyname', 'name', 'date', 'count'):
            if mparser.has_option('Map', link[key]):
                logger.debug("Map entry \"%s\" (%s) found for %s" % (link[key],
                                            key, link['friendlyname']))
                return mparser.get('Map', link[key])
        return ""
    else:
        return ""

def check_linkmatch(link, linklist):
    """Checks if a given link matches a link in the linklist."""
    result = False
    logger = logging.getLogger('main.linkmatch')
    for key in ('chkdelete', 'friendlyname', 'name', 'date', 'count'):
        for arg in linklist:
            if fnmatch.fnmatch(link[key], arg):
                logger.debug('"%s" matches "%s" as %s for %s' % (link[key],
                                            arg, key, link['friendlyname']))
                result = True
    return result

def main():
    """Main routine that contains the program logic."""
    ### Parsing options
    opts, args = optparse_setup()
    global BASE_URL
    BASE_URL = RAW_BASE_URL % ("s" if opts.allsecure else "")

    if opts.netdebug:
        import socks
        import socket
        socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", 1080)
        socket.socket = socks.socksocket

    browser = PqBrowser()
    excludes = []
    for arg in args:
        if arg[0] == '#':
            excludes.append(arg[1:])
            args.remove(arg)

    delay = functools.partial(gdelay, odelay=opts.delay)

    logger = logging.getLogger('main')

    if not opts.noupdate:
        check_update(opts.nobrowser)
    else:
        logger.info("Update check skipped. Please check for updates yourself!")

    if not os.path.exists(opts.outputdir):
        os.makedirs(opts.outputdir)

    logger.debug("mechanize %d.%d.%d; BeautifulSoup: %s; Filename: %s; "
                 "Python: %s" % (mechanize.__version__[0],
                                 mechanize.__version__[1],
                                 mechanize.__version__[2],
                                 BeautifulSoup.__version__,
                                 os.path.basename(sys.argv[0]),
                                 sys.version))


    ### Main program
    logger = logging.getLogger('main.login')
    if opts.pqsitefile:
        logger.info("Skipping login, simulation mode")
        browser.pqsimulate = True
        browser.pqfile = opts.pqsitefile
    else:
        logger.info("Logging in as {username}".format(username=opts.username))
        browser.login_gc(opts.username, opts.password,
                         RAW_BASE_URL % ("s" if (opts.loginsecure or
                                         opts.allsecure )
                                         else ""))
        delay()

    logger = logging.getLogger('main.linkdb')
    logger.info("Getting links")
    linklist = browser.get_link_db(not opts.nospecial)
    delay()
    os.chdir(opts.outputdir)
    if logger.getEffectiveLevel() <= 10:
        for link in linklist:
            logger.debug("Data for %s:" % link['friendlyname'])
            for field, data in link.iteritems():
                logger.debug('%s - %s: %s' % (link['friendlyname'], field,
                                              data))

    logger = logging.getLogger('main.linkdb.sync')

    if opts.journal or opts.usejournal:
        journal = True
        cparser = ConfigParser.RawConfigParser()
        cfiles = cparser.read([opts.journalfile])
        logger.debug("Journal: %s" % cfiles)
        if opts.resetjournal:
            logger.info("Resetting journal...")
            if cparser.has_section('Log'):
                cparser.remove_section('Log')
    else:
        journal = False

    if opts.mappings:
        mparser = ConfigParser.RawConfigParser()
        mfiles = mparser.read([opts.mapfile])
        logger.debug("Mappings: %s" %mfiles)

    if opts.myfinds:
        browser.trigger_myfinds()

    logger = logging.getLogger('main.select')
    logger.info("Selecting files")

    if (logger.getEffectiveLevel() > 10) and len(args):
        logger.info("NOTE: please enable debug (-d) if you want to see what "
                    "includes/excludes do or if they don't work as expected!")

    if linklist == []:
        logger.info("No valid Pocket Queries found online.")
        dllist = []
    else:
        if not len(args):
            logger.debug("No include arguments given, downloading all PQs.")
        dllist = []
        for link in linklist:
            assert isinstance(args, list)
            if journal:
                try:
                    if cparser.get('Log', link['chkdelete']) == link['date']:
                        logger.info('"{name}" skipped because {friendlyname} '
                                    'with date {date} has already been '
                                    'downloaded.'.format(**link))
                        continue
                except (ConfigParser.NoOptionError,
                        ConfigParser.NoSectionError):
                    pass
            if (check_linkmatch(link, excludes)):
                logger.info('"{name}" skipped because it is is exluded.'.
                            format(name=link['name']))
                continue
            if (check_linkmatch(link, args)) | (args == []):
                logger.info('"{name}" ({date}) will be downloaded'.
                            format(**link))
                dllist.append(link)
            else:
                logger.debug('"{name}" skipped because it is not in the '
                'arguments list.'.format(**link))
        if dllist == []:
            logger.info("All PQs skipped." if logger.getEffectiveLevel() <= 10
                        else "All PQs skipped. If you want to know why, "
                        "enable debug (-d)!")

    logger = logging.getLogger('main.download')
    logger.info("Downloading selected files")

    def _reporthook(count, blocksize, totalsize):
        """Local hook for mechanize.retrieve()"""
        percent = int(count*blocksize*100/totalsize)
        sys.stdout.write("\r  > %s%%" % (str(percent)))
        sys.stdout.flush()

    if opts.list:
        logger.info("Downloads skipped!")
        dllist = []
    for number, link in enumerate(dllist):
        if link['name'] != link['friendlyname']:
            logger.info('Downloading {0}/{1}: "{name}" (Friendly Name: '
                        '{friendlyname}) ({size}) [{date}]'.
                        format(number+1, len(dllist), **link))
        else:
            logger.info('Downloading {0}/{1}: "{name}" ({size}) [{date}]'.
                        format(number+1, len(dllist), **link))
        filename = '{friendlyname}.pqtmp'.format(**link)
        link['filename'] = filename
        delay()

        browser.download_pq(link['url'], filename, _reporthook)

        print('\r  > Done.')
        if journal:
            if not cparser.has_section('Log'):
                cparser.add_section('Log')
            cparser.set('Log', link['chkdelete'], link ['date'])
            cparser.set('Log', link['chkdelete'], link ['date'])

    delay()


    class FilenameDict(object):
        """A special dictionary for filename templates whose values depend on
        the parameters given to the constructor (link and suffix).

        """
        def __init__(self, link, suffix):
            """Inits the FilenameDict.

            link -- dictionary with link template values
            suffix -- the filename suffix, as example 'zip' or 'gpx'

            """
            self.suffix = suffix
            self.link = link
            self.base = self.single if opts.singlefile else self.basic

        basic = {
                'normal':'{mapstr}{chkdelete}_{friendlyname}_{date}',
                'myfinds':'{mapstr}MyFinds_{date}',
                'waypoints':('{mapstr}{chkdelete}_'
                             '{friendlyname}_{date}_waypoints')
                }

        single = {
                'normal':'{mapstr}{chkdelete}_{friendlyname}',
                'myfinds':'{mapstr}MyFinds',
                'waypoints':'{mapstr}{chkdelete}_{friendlyname}_waypoints'
                }

        def __getattr__(self, name):
            return "%s.%s" % (self.base[name].format(**self.link), self.suffix)



    logger = logging.getLogger('main.process')
    logger.info("Processing downloaded files")
    if dllist == []:
        logger.info("No downloads to process")
    for link in dllist:
        template = FilenameDict(link, 'zip')
        link['mapstr'] = (get_mapstr(mparser, link) + opts.sep if opts.mappings
                          else '')
        link['realfilename'] = template.normal
        if os.path.isfile(link['realfilename']):
            remove(link['realfilename'])
        rename(link['filename'], link['realfilename'])

    if opts.unzip:
        logger = logging.getLogger('main.unzip')
        logger.info("Unzipping the downloaded files")
        for link in dllist:
            template = FilenameDict(link,'gpx')
            logger.info("Unzipping {realfilename}".format(**link))

            zfile = zipfile.ZipFile(link['realfilename'])
            for info in zfile.infolist():
                isinstance(info, zipfile.ZipInfo)
                logger.debug("{filename} (size: {size})".
                             format(filename=info.filename,
                                    size=info.file_size))
                zfile.extract(info)

                if link['chkdelete'] == 'myfinds':
                    filename = template.myfinds
                else:
                    filename = template.normal
                if 'wpts' in info.filename:
                    filename = template.waypoints
                if info.filename != filename:
                    if os.path.isfile(filename):
                        remove(filename)
                    rename(info.filename, filename)

            zfile.close()

            if not opts.keepzip:
                remove(link['realfilename'])

    if opts.remove:
        logger = logging.getLogger('main.removegc')
        logger.info("Removing downloaded files from GC.com")
        rmlist = []
        if dllist == []:
            logger.info("No files to remove.")
        for link in dllist:
            if link['type'] == 'nodelete':
                logger.warning("MyFinds Pocket Query can't be removed. "
                               "If you want to exclude it in future runs, "
                               "use -n")
                continue
            rmlist.append(link['chkdelete'])
            logger.info(
                'Pocket Query "{name}" will be removed (ID: {chkdelete})'.
                format(**link))
        if rmlist != []:
            if opts.ctl != 'search':
                ctl = opts.ctl
            else:
                logger.debug("Searching CTL value...")
                ctl = browser.find_ctl()
                logger.debug("Found value %s" % ctl)
            logger.info("Sending removal request...")
            browser.delete_pqs(rmlist, ctl)
            logger.info("Removal request sent. If it didn't work, please report"
                        " this a bug. Groundspeak makes so many changes on "
                        "their site that this feature is broken from time "
                        "to time.")

    logger = logging.getLogger('main')
    if opts.journal:
        try:
            logger.debug("Writing journal file %s" % opts.journalfile)
            cfile = open(opts.journalfile, 'w')
            cparser.write(cfile)
        finally:
            cfile.close()

    if opts.noexit:
        raw_input('Press any key to exit.')

if __name__ == "__main__":
    logging.info("PQdl v%s (%s) by leoluk. Updates and help on "
                 "www.leoluk.de/paperless-caching/pqdl" ,
                 __version__, __status__)
    main()
    logging.info("Done")

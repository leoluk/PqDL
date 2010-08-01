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

"""PQdl is a tool that can download Pocket Queries from geocaching.com. 
Pocket Queries that contain more than 500 caches won't be sent per mail, so you 
need to do it by hand or with this script.
This script is written by leoluk. Please look at www.leoluk.de/paperless-caching/pqdl for updates.
"""

__version__ = "0.3.1-stable"

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
import codecs

from time import sleep

def error(msg):
    sys.stderr.write("\n%s: error: %s\n" % (os.path.basename(sys.argv[0]), msg)) 
    sys.exit(1)


def optparse_setup():
    """Parsing options given to PqDL"""
    desc = __doc__
    epilog = """This tool probably violates the Terms of Service by Groundspeak. 
Please don't abuse it. If any argument (username, password, PQ names, ...) contains spaces, put it into parantheses. """

    usage = "%prog [-h] -u USERNAME -p PASSWORD [-o OUTPUTDIR] [options] [pq_1 pq_2 ...]"

    parser = optparse.OptionParser(description=desc, version="%%prog %s" % __version__, epilog=epilog, usage=usage)
    
    grp_prm = optparse.OptionGroup(parser, "Arguments",description="""Pass the names of the Pocket Queries you want to download as parameters (pq_1 pq_2 ...). (case sensitive!) If none given, it will try to download all of them. You can exlude PQs by adding # on the beginning of the name. You need to specify the 'friendly name', the name, the date, the cache count or the ID of a PQ. You can use UNIX-style wildcards (*, ?, [x], [!x]). Please run with -d -l to get the friendly name or other parameters.""")
    
    parser.add_option_group(grp_prm)
    
    parser.add_option('-u', '--username', help="Username on GC.com (use parentheses if it contains spaces)")
    parser.add_option('-p', '--password', help="Password on GC.com (use parentheses if it contains spaces), you will be asked if you don't specify it (you can omit this!)")
    parser.add_option('-o', '--outputdir', help="Output directory for downloaded files (will be created if it doesn't exists yet), will be set as default for other file parameters, sets the working dir [default: %default]", default=os.getcwd())
    parser.add_option('-r', '--remove', help="Remove downloaded files from GC.com. WARNING: This deletes the files ONLINE! WARNING: This is broken from time to time, thanks go to Groundspeak!", default=False, action='store_true')
    parser.add_option('-n', '--nospecial', help="Ignore special Pocket Queries that can't be removed like My Finds.", default=False, action='store_true')
    
    grp_zip = optparse.OptionGroup(parser, "ZIP options", """PqDL supports unzipping the Pocket Queries. They will be renamed automatically after unzipping by this pattern: Name-of-PQ_1234567_06-12-2010[_waypoints].gpx (-s will be used). Note: if you want to your PQs with GSAK or pqloader, there's no need to unzip them!""")
    grp_zip.add_option('-z', '--unzip', help="Unzips and removes the downloaded ZIP files.", default=False, action='store_true')
    grp_zip.add_option('--keepzip', help="Do not remove unzipped files. (to be used with -z)", default=False, action='store_true')
    parser.add_option_group(grp_zip)
    
    parser.add_option('-s', '--singlefile', help="Overwrite existing files. When using this option, there won't be any timestamps added! (so just one file for every PQ in your DL folder), applies to unzip too", action="store_true", default=False)
    parser.add_option('-e', '--delay', help="Random delays between the requests", default=False, action='store_true') 
    parser.add_option('-l', '--list', help="Do not download anything, just list the files. Best to be used with -d.", default=False, action='store_true')
    
    grp_dbg = optparse.OptionGroup(parser, "Debug options", """They are lots of debug options. You should always use -d if the program doesn not exactly does what it's supposed to do, they are lots of interesting debug outputs. The other debug options are only needed for debugging special problems with the parser. PLEASE ALWAYS USE -d IF YOU SEND ME A BUG REPORT!""")
    grp_dbg.add_option('-d', '--debug', help="Debug output (RECOMMENDED)", default=False, action='store_true')
    grp_dbg.add_option('-t', '--httpdebug', help="HTTP header debug output, used for debugging fake requests", default=False, action='store_true')
    grp_dbg.add_option('--httpremovedebug', help="HTTP 'remove PQ' debug output, used when -r doesn't works", default=False, action='store_true')
    grp_dbg.add_option('--ignoreerrors', help="Ignore version errors", default=False, action='store_true')
    grp_dbg.add_option('--httpmaindebug', help="HTTP 'getPQ' debug output, used for debugging the main parser that gets the PQ site table", default=False, action='store_true')
    grp_dbg.add_option('--ctl', help="Remove-CTL value, used for debugging very special problems with -r (default: %default)", default='search')
    parser.add_option_group(grp_dbg)
    
    grp_journal = optparse.OptionGroup(parser, "Journal and map options","""These are special options that will allow PqDL to remember which PQs have already been downloaded. This is based on the PQ latest generation date, if the PQ gets generated again, it will be downloaded. The journal file is an .ini file (by default filestate.txt) that can be used for the mappings too. The section for this feature is [Log].""")    
    grp_journal.add_option('-j', '--journal', help="Create a download journal file. Files downloaded while using -j there won't be downloaded again (requires -j or --usejournal)", default=False, action='store_true')
    grp_journal.add_option('--usejournal', help="Like -j, but in read-only mode, it won't add new PQs or pqloader mappings to the journal (-j or this one!)", default=False, action='store_true')
    grp_journal.add_option('--resetjournal', help="Reset the log section of the journal", default=False, action='store_true')
    grp_journal.add_option('--journalfile', help="Filename of journal file [default: %default]", default="filestate.txt")
    parser.add_option_group(grp_journal)
    
    grp_map = optparse.OptionGroup(parser, "GSAK/pqloader file mappings options","""This is a feature made for those who use PqDL in conjunction with pqloader. pqloader will take the first word in a PQs file name to decide in which database the PQs will be saved. This feature allows you to add this prefix automatically after downloading the PQs, so you don't longer need to rename your PQs online! This feature will use an .ini file like -j (this can be the same one, the default is filestate.txt too). In order to use this, you need to add a new section [Map] to the .ini file and mappings like My-PQ-Name=PQ-Prefix (one per line). You can use the name, friendlyname, date or ID, but no wildcards yet.""")
    grp_map.add_option('-m', '--mappings', help="Assign a GSAK Database for pqloader to every PQ, requires journal", default=False, action='store_true')
    grp_map.add_option('--mapfile', help="File that contains the mapping section, default is the journal file. [default: %default, or the custom journal file if set]. For usage examples look at the project site.", default="filestate.txt", action='store_true')
    grp_map.add_option('--sep', help="Seperator for pqloader [default: '%default']", default=" ", action='store_true')
    parser.add_option_group(grp_map)

    
    #parser.add_option('--log', help="Make a logfile that will contain all output.")
    #parser.add_option('--logfile', help="Filename of the logfile [default: %default]", default="pqdl.log")
    
    parser.add_option('--myfinds', help="Trigger a My Finds Pocket Query if possible (you'll most likely need to run this program again if the PQ is not generated fast enough, so consider using --myfinds with -l)", default=False, action='store_true')
    pr, ar = parser.parse_args()


    if pr.username == None:
        parser.print_help()
        error("Please specify a username, I won't use mine :-)\n")

    if (pr.mappings) and (pr.journalfile != 'filestate.txt') and (pr.mapfile == 'filestate.txt'):
        pr.mapfile = pr.journalfile
    
    if pr.password == None:
        pr.password = getpass.getpass("Password for %s: " % pr.username)
        print ''
        
    if pr.journal and pr.usejournal:
        parser.print_help()
        error("You should decide if you want to write to the journal file or not. Please use --usejournal *or* -j !")

    if pr.keepzip and not pr.unzip:
        parser.print_help()
        error("You can't use --keepzip without -z (--unzip).")
        
    return pr, ar

def init_mechanize(debug):
    """Inits the mechanize browser."""
    br = mechanize.Browser()
    cj = cookielib.LWPCookieJar()
    br.set_cookiejar(cj)
    # Browser options
    br.set_handle_equiv(True)
    #br.set_handle_gzip(True)
    br.set_handle_redirect(True)
    br.set_handle_referer(True)
    br.set_handle_robots(False)
    # Follows refresh 0 but not hangs on refresh > 0
    br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=1)
    # Want debugging messages?
    if debug:
        br.set_debug_http(True)
        br.set_debug_redirects(True)
        br.set_debug_responses(True)
    # User-Agent (this is cheating, ok?)
    br.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1')]  
    return br

def delay():
    if odelay:
        sleep(random.randint(500,5000)/1000)
        

def login_gc(browser, username, password):
    """Login to GC.com site."""
    assert isinstance(browser, mechanize.Browser)
    browser.open("http://www.geocaching.com/login/default.aspx?RESET=Y&redir=http%3a%2f%2fwww.geocaching.com%2fpocket%2fdefault.aspx")
#    for f in browser.forms():
#        print f
    browser.select_form(name="aspnetForm")
    browser.form['ctl00$ContentBody$myUsername'] = username
    browser.form['ctl00$ContentBody$myPassword'] = password
    browser.submit()
    response = browser.response().read()
    #assert isinstance(response, str)
    if response.find('http://www.geocaching.com/my/') == -1:
        raise error("Could not log in. Please check your password.\nIf your username or password contains spaces, put it into parentheses!")

def delete_pqs(browser, chkid, debug, ctl):
    assert isinstance(browser, mechanize.Browser)
    browser.open("http://www.geocaching.com/pocket/default.aspx")
    browser.select_form(name="aspnetForm")
    browser.form.set_all_readonly(False)
    browser.form['ctl00$ContentBody$PQDownloadList$hidIds'] = ",".join(chkid) + ","
    browser.form['__EVENTTARGET'] = "ctl00$ContentBody$PQDownloadList$uxDownloadPQList$ctl%s$lnkDeleteSelected" % ctl
    browser.submit()
    if debug:
        print_section("HTTP REMOVE DEBUG")
        print "\n\n%s\n\n" % browser.response().read()

def trigger_myfinds(browser):
    assert isinstance(browser, mechanize.Browser)
    try:
        print "-> Trigger My Finds PQ..."
        browser.open("http://www.geocaching.com/pocket/default.aspx")
        browser.select_form(name="aspnetForm")
        browser.form.set_all_readonly(False)
        browser.form['ctl00$ContentBody$PQListControl1$btnScheduleNow'] = "Add to Queue"
        browser.submit()
    except ValueError:
        print "-> FAILURE: My Finds Pocket Query not available."
    #if debug:
        #print_section("HTTP MYFINDS DEBUG")
        #print "\n\n%s\n\n" % browser.response().read()        

def find_ctl(browser):
    assert isinstance(browser, mechanize.Browser)
    browser.open("http://www.geocaching.com/pocket/default.aspx")
    response = browser.response().read()
    isinstance(response, str)
    tmpl = "javascript:__doPostBack('ctl00$ContentBody$PQDownloadList$uxDownloadPQList$ctl"
    ind = response.index(tmpl)+len(tmpl)
    return response[ind:ind+2]
    

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip())
    return re.sub('[-\s]+', '-', value)

def getLinkDB(browser,special, debug, httpdebug):
    """Gets the link DB. Requires login first!"""
    response = browser.open("http://www.geocaching.com/pocket/default.aspx").read()
    #f = open('debug.txt')
    #response = f.read()
    if response.find("http://www.geocaching.com/my/") == -1:
        error("Invalid PQ site. Not logged in?")
    soup = BeautifulSoup.BeautifulSoup(response)
    links = soup(id=re.compile("trPQDownloadRow"))
    
    if httpdebug:
        print_section("DEBUG: PQ SITE")
        print "\n\n%s\n\n" % response

    linklist = []
    for link in links:
        try:
            linklist.append({
                'type': 'normal',
                'index': link.contents[3].contents[0].strip('.').strip(),
                'url': link.contents[5].contents[3]['href'],
                'name': link.contents[5].contents[3].contents[0].strip(),
                'friendlyname': slugify(link.contents[5].contents[3].contents[0].strip()),
                'size': link.contents[7].contents[0].strip(),
                'count': link.contents[9].contents[0].strip(),
                'date': link.contents[11].contents[0].strip().split(' ')[0].replace('/','-'),
                #'preserve': link.contents[11].contents[0].split(' ',1)[1][1:-1],
                'chkdelete': link.contents[1].contents[1]['value'],
            })
        except IndexError:
            if special:
                linklist.append({
                    'type': 'nodelete',
                    'index': link.contents[3].contents[0].strip('.').strip(),
                    'url': link.contents[5].contents[3]['href'],
                    'name': link.contents[5].contents[3].contents[0].strip(),
                    'friendlyname': slugify(link.contents[5].contents[3].contents[0].strip()),
                    'size': link.contents[7].contents[0].strip(),
                    'count': link.contents[9].contents[0].strip(),
                    'date': link.contents[11].contents[0].strip().split(' ')[0].replace('/','-'),
                    #'preserve': link.contents[11].contents[0].split(' ',1)[1][1:-1],
                    'chkdelete': 'myfinds',
                })
            else:
                if debug:
                    print "-> DEBUG: Pocket Query %s skipped because of -n\n" % slugify(link.contents[5].contents[2].contents[0])


    return linklist

def download_pq(link, filename, browser):
    def _reporthook(count, blockSize, totalSize):
        percent = int(count*blockSize*100/totalSize)
        sys.stdout.write("\r  > %s%%" % (str(percent)))
        sys.stdout.flush()

    baseurl = 'http://www.geocaching.com'
    isinstance(browser, mechanize.Browser)
    browser.retrieve(baseurl+link, filename, _reporthook)
    print '\r  > Done.\n'

def print_section(name):
    name = " %s " % name
    print name.center(50,'#') + '\n'

def get_mapstr(mparser, link, debug):
    isinstance(mparser, ConfigParser.ConfigParser)
    if mparser.has_section('Map'):
        for key in ('chkdelete', 'friendlyname', 'name', 'date', 'count'):
            if mparser.has_option('Map',link[key]):
                if debug:
                    print "-> DEBUG: Map entry \"%s\" (%s) found for %s" % (link[key], key, link['friendlyname'])
                return mparser.get('Map',link[key])
        return ""
    else:
        return ""
 
def check_linkmatch(link, linklist, debug):
    result = False
    for key in ('chkdelete', 'friendlyname', 'name', 'date', 'count'):
        for arg in linklist:
            if fnmatch.fnmatch(link[key],arg):
                if debug:
                    print '-> DEBUG: "%s" matches "%s" as %s for %s' % (link[key], arg, key, link['friendlyname'])
                result = True
    return result

def main():
    ### Parsing options
    print "-> PQdl v%s by leoluk. Updates and help on www.leoluk.de/paperless-caching/pqdl\n" % (__version__)
    opts, args = optparse_setup()
    browser = init_mechanize(opts.httpdebug)
    excludes = []
    for arg in args:
        if arg[0] == '#':
            excludes.append(arg[1:])
            args.remove(arg)
     
    global odelay
        
    odelay = opts.delay
    
    if not os.path.exists(opts.outputdir):
        os.makedirs(opts.outputdir)
        
    if opts.debug:
        print "-> DEBUG: mechanize %d.%d.%d; BeautifulSoup: %s; Filename: %s; \n-> DEBUG: Python: %s \n" % (mechanize.__version__[0], mechanize.__version__[1], mechanize.__version__[2], BeautifulSoup.__version__, os.path.basename(sys.argv[0]), sys.version)

    #if mechanize.__version__[1] < 2:
        #if opts.ignoreerrors:
            #print "-> IMPORTANT: Please use the most recent version of mechanize. The version you are running is too old. Use it on your own risk. If it doesn't works, just upgrade it."
        #else:
            #error("Please use the most recent version of mechanize. The version you are running is too old.")
        
    ### Main program
    print "-> LOGGING IN as %s" % opts.username
    login_gc(browser,opts.username, opts.password)
    delay()
    print "-> GETTING LINKS\n" 
    linklist = getLinkDB(browser, not opts.nospecial, opts.debug, opts.httpmaindebug)
    delay()
    os.chdir(opts.outputdir)
    if opts.debug:
        print_section("DEBUG - LINK DATABASE")
        for link in linklist:
            for field, data in link.iteritems():
                print '%s: %s' % (field, data)
            print ''      
    
    if opts.journal or opts.usejournal:
        journal = True
        cparser = ConfigParser.RawConfigParser()
        cfiles = cparser.read([opts.journalfile])
        if opts.debug:
            print "-> DEBUG: Journal: %s" % cfiles
        if opts.resetjournal:
            print "-> Resetting journal...\n"
            if cparser.has_section('Log'):
                cparser.remove_section('Log')
        print '\n'
    else:
        journal = False
    
    if opts.mappings:
        mparser = ConfigParser.RawConfigParser()
        mfiles = mparser.read([opts.mapfile])
        if opts.debug:
            print "-> DEBUG: Mappings: %s" %mfiles
        print '\n'
        
    if opts.myfinds:
        trigger_myfinds(browser)
        print ''
        
    print_section("SELECTING FILES")
    if linklist == []:
        print "No valid Pocket Queries found. (try -d)"
        dllist = []
    else:
        if args == []:
            print "No arguments given, downloading all PQs.\n"
        dllist = []
        for link in linklist:
            assert isinstance(args, list)
            if journal:
                try:
                    if cparser.get('Log',link['chkdelete']) == link['date']:
                        if opts.debug:
                            print "-> DEBUG: \"%s\" skipped because %s with date %s has already been downloaded." % (link['name'],link['friendlyname'], link['date'])
                        continue
                except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
                    pass
            if (check_linkmatch(link, excludes, opts.debug)):
                if opts.debug:
                    print "-> DEBUG: \"%s\" skipped because %s is exluded." % (link['name'],link['friendlyname'])
                continue
            if (check_linkmatch(link, args, opts.debug)) | (args == []):
                print '-> "%s" (%s) will be downloaded' % (link['name'], link['date'])
                dllist.append(link)
            else:
                if opts.debug:
                    print "-> DEBUG: \"%s\" skipped because %s is not in the arguments list." % (link['name'],link['friendlyname'])
        if dllist == []:
            print "All PQs skipped. Use -d to see why." if not opts.debug else "\nAll PQs skipped."
    print '\n'

    print_section("DOWNLOADING SELECTED FILES")
    if opts.list:
        print "Downloads skipped!\n"
        dllist = []
    for n, link in enumerate(dllist):
        if link['name'] != link['friendlyname']:
            print '>>> Downloading %d/%d: "%s" (Friendly Name: %s) (%s) [%s]' % (n+1, len(dllist), link['name'], link['friendlyname'], link['size'], link['date'])
        else:
            print '>>> Downloading %d/%d: "%s" (%s) [%s]' % (n+1, len(dllist), link['name'], link['size'], link['date'])
        filename = '%s.pqtmp' % (link['friendlyname'])
        link['filename'] = filename
        delay()
        download_pq(link['url'],filename, browser)
        if journal:
            if not cparser.has_section('Log'):
                cparser.add_section('Log')
            cparser.set('Log',link['chkdelete'],link ['date'])
            cparser.set('Log',link['chkdelete'],link ['date'])

    delay()
    print_section("PROCESSING DOWNLOADED FILES")
    if dllist == []:
        print "No downloads to process. (try -d)\n"
    for link in dllist:
        mapstr = get_mapstr(mparser, link, opts.debug) + opts.sep if opts.mappings else ""
        link['realfilename'] = ('%s%s_%s.zip' % (mapstr, link['friendlyname'],link['date']) if not opts.singlefile else '%s%s.zip' % (mapstr, link['friendlyname']))
        print "%s -> %s" % (link['filename'],link['realfilename'])
        if os.path.isfile(link['realfilename']):
            os.remove(link['realfilename'])
        os.rename(link['filename'],link['realfilename'])

    if opts.unzip:
        print '\n'
        print_section("UNZIPPING THE DOWNLOADED FILES")
        for link in dllist:
            print "-> Unzipping %s" % link['realfilename']
            if opts.debug:
                print "-> DEBUG:"
            zfile = zipfile.ZipFile(link['realfilename'])
            for info in zfile.infolist():
                isinstance(info, zipfile.ZipInfo)
                if opts.debug:
                    print "%s (size: %s)" % (info.filename, info.file_size)
                zfile.extract(info)
                mapstr = get_mapstr(mparser, link, opts.debug) + opts.sep if opts.mappings else ""
                if link['chkdelete'] == 'myfinds':
                    filename = "%sMyFinds_%s.gpx" % (mapstr, link['date'])
                else:
                    filename = "%s%s_%s_%s.gpx" % (mapstr, link['friendlyname'],link['chkdelete'],link['date'])
                if info.filename.find('wpts') > 0:
                    filename = "%s%s_%s_%s_waypoints.gpx" % (mapstr, link['friendlyname'],link['chkdelete'],link['date'])
                if os.path.isfile(filename):
                    os.remove(filename)
                if opts.debug:
                    print "%s -> %s" % (info.filename, filename)
                os.rename(info.filename, filename)
            
            zfile.close()
            
            if not opts.keepzip:
                if opts.debug:
                    print "Removing %s..." % link['realfilename']
                os.remove(link['realfilename'])
            if opts.debug:
                print ''
    
    if opts.remove:
        print '\n'
        print_section("REMOVE DOWNLOADED FILES FROM GC.COM")
        rmlist = []
        if dllist == []:
            print "No files to remove.\n"
        for link in dllist:
            if link['type'] == 'nodelete':
                print "MyFinds Pocket Query can't be removed. If you want to exclude it in future runs, use -n\n"
                continue
            rmlist.append(link['chkdelete'])
            print "Pocket Query \"%s\" will be removed (ID: %s)." % (link['name'], link['chkdelete'])
        if rmlist != []:
            print "\n-> REMOVING POCKET QUERIES..."
            if opts.ctl != 'search':
                ctl = opts.ctl
            else:
                print "\n-> Searching CTL value..."
                ctl = find_ctl(browser)
                if opts.debug:
                    print "-> DEBUG: found value %s" % ctl
            print "\n-> Sending removal request..."
            delete_pqs(browser, rmlist, opts.httpremovedebug, ctl)
            print "\n-> Removal request sent. If it didn't work, please report this a bug.\n  Groundspeak makes so many changes on their site that this feature is broken from time to time."
        
        # REPICKLE
        
    if opts.journal:
        try:
            if opts.debug:
                print "\n-> DEBUG: writing journal file %s" % opts.journalfile
            cfile = open(opts.journalfile, 'w')
            cparser.write(cfile)
        finally:
            cfile.close()

if __name__ == "__main__":
    main()


#!/usr/bin/env python
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

"""PQdl is a little tool that can download Pocket Queries from geocaching.com. 
Pocket Queries that contain more than 500 caches won't be sent per mail, so you 
need to do it by hand or with this script.
This script is written by leoluk. Please look at www.leoluk.de/paperless-caching/pqdl
"""

import mechanize
import optparse
import cookielib
import os
from BeautifulSoup import BeautifulSoup
import re
import sys
import zipfile
import atexit
#from termcolor import colored as color
#from colorama import init, Fore, Style

def colored(string, color):
    return string

def reset_colorama():
    print Style.DIM

#atexit.register(reset_colorama)
#init()

def error(msg):
    sys.stderr.write(colored("\n%s: error: %s\n",'red') % (os.path.basename(sys.argv[0]), str(msg)))
    sys.exit(1)


def optparse_setup():
    """Parsing options given to PqDL"""
    desc = __doc__
    epilog = """Pass the names of the Pocket Queries you want to download as
parameters (pq_1 pq_2 ...). If none given, it will try to 
download all of them. (IMPORTANT: the Pocket Queries needs to be zipped!)
When not using -s, it will add timestamps to the filename of every downloaded file according to the "Last Generated" dates on the PQ site.
This tool probably violates the Terms of Service by Groundspeak. 
Please don't abuse it."""
       
    #usage = "%prog [-h] -u USERNAME -p PASSWORD [-o OUTPUTDIR] [-r] [-w] [-z [-k]] [pq_1 pq_2 ...]"

    parser = optparse.OptionParser(description=desc, version="%prog 0.1", epilog=epilog)
    parser.add_option('-u', '--username', help="Username on GC.com")
    parser.add_option('-p', '--password', help="Password on GC.com")
    parser.add_option('-o', '--outputdir', help="Output directory for downloaded files [default: %default]", default=os.getcwd())
    #parser.add_option('-r', '--remove', help="Remove downloaded files from GC.com. WARNING: This deleted the files ONLINE!", default=False, action='store_true')
    parser.add_option('-s', '--singlefile', help="Overwrite existing files. When using this option, there won't be any timestamps added! (so just one file for every PQ in your DL folder)", action="store_true", default=False)
    #parser.add_option('-z', '--unzip', help="Unzip the downloaded ZIP files and delete the originals.", action="store_true", default=False)
    #parser.add_option('-k', '--keepzip', help="Do not delete the original ZIP files (to be used with -z)", default=False, action='store_true')
    parser.add_option('-d', '--debug', help="Debug output, interesting, try it out!", default=False, action='store_true')
    parser.add_option('-t', '--httpdebug', help="HTTP debug output", default=False, action='store_true')
    parser.add_option('-l', '--list', help="Skip download", default=False, action='store_true')
    #parser.add_option('-c', '--colored', help="Colored ouput", default=False, action='store_true')
    pr, ar = parser.parse_args()

    
    
    if pr.username == None:
        parser.print_help()
        error("Please specify a username, I won't use mine :-)\n")

    if pr.password == None:
        parser.print_help()
        error("Nice try, but sorry, I won't guess your password.\n")

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
        raise error("Could not log in. Please check your password.")

def delete_pq(browser, chkid):
    browser.open("http://www.geocaching.com/pocket/default.aspx")
    browser.select_form(name="aspnetForm")
    
def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip())
    return re.sub('[-\s]+', '-', value)
    
def getLinkDB(browser):
    """Gets the link DB. Requires login first!"""
    response = browser.open("http://www.geocaching.com/pocket/default.aspx").read()
    if response.find("http://www.geocaching.com/my/") == -1:
        error("Invalid PQ site. Not logged in?")
    soup = BeautifulSoup(response)
    links = soup(id=re.compile("trPQDownloadRow"))
    
    linklist = []
    for link in links:
        linklist.append({
            'index': link.contents[3].contents[0].strip('.'),
            'url': link.contents[5].contents[2]['href'],
            'name': link.contents[5].contents[2].contents[0],
            'size': link.contents[7].contents[0],
            'count': link.contents[9].contents[0],
            'date': link.contents[11].contents[0].split(' ')[0].replace('/','-'),
            'nextgen': link.contents[11].contents[0].split(' ',1)[1][1:-1],
            'chkdelete': link.contents[1].contents[0]['value'],
        })
        
    return linklist
    
def download_pq(link, filename, browser):
    def _reporthook(count, blockSize, totalSize):
        percent = int(count*blockSize*100/totalSize)
        sys.stdout.write("\r  %s %s" % (colored('>','red'),colored(str(percent)+'%','red')))
        sys.stdout.flush()

    baseurl = 'http://www.geocaching.com/'
    isinstance(browser, mechanize.Browser)
    browser.retrieve(baseurl+link, filename, _reporthook)
    print '\r  %s %s\n' % (colored('>','cyan'), colored('Done.','green'))
    
def print_section(name):
    name = " %s " % name
    print colored(name.center(50,'#') + '\n', 'yellow')
    
def main():
    print colored("\n-> PQdl by leoluk. Updates on ",'cyan')+colored('www.leoluk.de/paperless-caching/pqdl\n','red')
    opts, args = optparse_setup()
    browser = init_mechanize(opts.httpdebug)
    print "-> LOGGING IN"
    login_gc(browser,opts.username, opts.password)
    print "-> GETTING LINKS\n" 
    linklist = getLinkDB(browser)
    os.chdir(opts.outputdir)
    if opts.debug:
        print_section("DEBUG - LINK DATABASE")
        for link in linklist:
            for field, data in link.iteritems():
                print '%s %s' % (colored(field,'grey')+':', data)
            print '\n'      
        
    print_section("SELECTING FILES")
    if args == []:
        print colored("No arguments given, downloading all PQs.\n",'grey')
    dllist = []
    for link in linklist:
        assert isinstance(args, list)
        if (args.count(link['name'])) | (args == []):
            print "-> %s will be downloaded" % colored(link['name'],'green')
            dllist.append(link)
        else:
            if opts.debug:
                print "-> DEBUG: %s skipped because arguments are not empty but %s is not included." % (colored(link['name'],'red'),link['name'])
    print '\n'
    
    print_section("DOWNLOADING SELECTED FILES")
    if opts.list:
        print "Downloads skipped!\n"
        dllist = []
    filelist = []
    for n, link in enumerate(dllist):
        print colored(">>> Downloading %d/%d (ID %s): %s (%s) [%s]", 'red') % (n+1, len(dllist), link['index'], link['name'], link['size'], link['date'])
        filename = '%s.pqtmp' % (link['name'])
        link['filename'] = filename
        download_pq(link['url'],filename, browser)  
    
    print_section("PROCESSING DOWNLOADED FILES")
    if dllist == []:
        print "No downloads to process.\n"
    for link in dllist:
        link['name'] = slugify(link['name'])
        link['realfilename'] = ('%s_%s.zip' % (link['name'],link['date']) if not opts.singlefile else '%s.zip' % (link['name']))
        print "%s -> %s" % (link['filename'],link['realfilename'])
        if os.path.isfile(link['realfilename']):
            os.remove(link['realfilename'])
        os.rename(link['filename'],link['realfilename'])

if __name__ == "__main__":
    main()
    #print Style.DIM
    

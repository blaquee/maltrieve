# Copyright 2013 Kyle Maxwell
# Includes code from mwcrawler, (c) 2012 Ricardo Dias. Used under license.

# Maltrieve - retrieve malware from the source

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/

import urllib2
import logging
import argparse
import tempfile
import re
import hashlib
import os
import sys
import datetime
import xml.etree.ElementTree as ET
import itertools
import mimetools
import mimetypes
import urllib
import json
from MultiPartForm import *
from threading import Thread 
from Queue import Queue

from bs4 import BeautifulSoup

from malutil import *

NUMTHREADS = 4
hashes = set()
pasturls = set()
now = datetime.datetime.now()

def get_malware(q,dumpdir):
    while True:
        url = q.get()
        logging.info("Fetched URL %s from queue", url)
        mal = get_URL(url)
        if mal:
            malfile=mal.read()
            md5 = hashlib.md5(malfile).hexdigest()
            # Is this a big race condition problem?
            if md5 not in hashes:
                logging.info("Found file %s at URL %s", md5, url)
                logging.debug("Going to put file in directory %s", dumpdir)
                # store the file and log the data
                with open(os.path.join(dumpdir, md5), 'wb') as f:
                    f.write(malfile)
                    logging.info("Stored %s in %s", md5, dumpdir)
                hashes.add(md5)
                pasturls.add(url)
		if args.cuckoo:
		    f = open(os.path.join(dumpdir, md5), 'rb')
		    form = MultiPartForm()
		    form.add_file('file', md5, fileHandle=f)
		    request = urllib2.Request('http://localhost:8090/tasks/create/file')
		    request.add_header('User-agent', 'Maltrieve')
		    body = str(form)
		    request.add_header('Content-type', form.get_content_type())
		    request.add_header('Content-length', len(body))
		    request.add_data(body)
		    response = urllib2.urlopen(request).read()
		    responsedata = json.loads(response)
		    logging.info("Submitted %s to cuckoo, task ID %s", md5, responsedata["task_id"])
        q.task_done()

def get_XML_list(url,q):
    malwareurls = []
    descriptions = []

    tree = get_XML(url)
    if tree:
        descriptions = tree.findall('channel/item/description')

    for d in descriptions:
        logging.info('Parsing description %s', d.text)
        url = d.text.split(' ')[1].rstrip(',')
        if url == '-':
            url = d.text.split(' ')[4].rstrip(',')
        url = re.sub('&amp;','&',url)
        if not re.match('http',url):
            url = 'http://'+url
        malwareurls.append(url)

    for url in malwareurls:
        push_malware_URL(url,q)

def push_malware_URL(url,q):
    url = url.strip()
    if url not in pasturls:
        q.put(url)

def main():
    malq = Queue()

    parser = argparse.ArgumentParser()
#   parser.add_argument("-t", "--thug", help="Enable thug analysis", action="store_true")
    parser.add_argument("-p", "--proxy", 
                        help="Define HTTP proxy as address:port")
    parser.add_argument("-d", "--dumpdir", 
                        help="Define dump directory for retrieved files")
    parser.add_argument("-l", "--logfile", 
                        help="Define file for logging progress")
    parser.add_argument("-c", "--cuckoo",
			help="Enable cuckoo analysis", action="store_true") 
    global args 
    args = parser.parse_args()

    if args.logfile:
        logging.basicConfig(filename=args.logfile, level=logging.DEBUG, 
                            format='%(asctime)s %(thread)d %(message)s', 
                            datefmt='%Y-%m-%d %H:%M:%S')
    else:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(thread)d %(message)s', 
                            datefmt='%Y-%m-%d %H:%M:%S')

    # Enable thug support 
    # https://github.com/buffer/thug
    # TODO: rewrite and test
    '''
    try:
        if args.thug:
            loadthug()
    except Exception as e:
        logging.warning('Could not enable thug (%s)', e)
    '''

    if args.proxy:
        proxy = urllib2.ProxyHandler({'http': args.proxy})
        opener = urllib2.build_opener(proxy)
        urllib2.install_opener(opener)
        logging.info('Using proxy %s', args.proxy)
        my_ip = urllib2.urlopen('http://whatthehellismyip.com/?ipraw').read()
        logging.info('External sites see %s',my_ip)

    # http://stackoverflow.com/questions/14574889/verify-directory-write-privileges
    if args.dumpdir:
        try:
            d = tempfile.mkdtemp(dir=args.dumpdir)
            dumpdir=args.dumpdir
        except Exception as e:
            logging.error('Could not open %s for writing (%s), using default', 
                          dumpdir, e)
            dumpdir = '/tmp/malware'
        else:
            os.rmdir(d)
    else:
        dumpdir = '/tmp/malware'

    logging.info('Using %s as dump directory', dumpdir)

    if os.path.exists('hashes.obj'):
        with open('hashes.obj','rb') as hashfile:
            hashes = pickle.load(hashfile)

    if os.path.exists('urls.obj'):
        with open('urls.obj', 'rb') as urlfile:
            pasturls = pickle.load(urlfile)

    for i in range(NUMTHREADS):
        worker = Thread(target=get_malware, args=(malq,dumpdir,))
        worker.setDaemon(True)
        worker.start()
    
    get_XML_list('http://www.malwaredomainlist.com/hostslist/mdl.xml',malq)
    get_XML_list('http://malc0de.com/rss',malq)
    
    # TODO: wrap these in a function
    for url in get_URL('http://vxvault.siri-urz.net/URL_List.php'):
        if re.match('http', url):
            push_malware_URL(url,malq)
    
    sacourtext=get_URL('http://www.sacour.cn/showmal.asp?month=%d&year=%d' % 
                  (now.month, now.year)).read()
    for url in re.sub('\<[^>]*\>','\n',sacourtext).splitlines():
        push_malware_URL(url,malq)
    
    # appears offline
    # minotaur(parse('http://minotauranalysis.com/malwarelist-urls.aspx'))
    # appears offline
    # malwarebl(parse('http://www.malwareblacklist.com/mbl.xml'))
    
    malq.join()

    with open('hashes.obj','wb') as hashfile:
        pickle.dump(hashfile, hashes)

    with open('urls.obj', 'wb') as urlfile:
        pickle.dump(urlfile, pasturls)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()

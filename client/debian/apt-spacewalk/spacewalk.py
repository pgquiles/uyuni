#!/usr/bin/python -u
#
# Very early prototype of apt-transport-spacewalk
#
# Author:  Simon Lukasik <xlukas08 [at] stud.fit.vutbr.cz>
# Date:    2011-01-01
# License: GPLv2
#
#

import sys
import re
import hashlib

import warnings
warnings.filterwarnings("ignore", message="the md5 module is deprecated; use hashlib instead")
sys.path.append("/usr/share/rhn/")

from urlparse import urlparse
from rhn.connections import HTTPConnection, HTTPSConnection
from up2date_client import config
from up2date_client import rhnChannel
from up2date_client import up2dateAuth
from up2date_client import up2dateErrors



class pkg_acquire_method:
    """
    This is slightly modified python variant of apt-pkg/acquire-method.
    It is a skeleton class that implements only very basic of apt methods
    functionality.
    """
    __eof = False

    def __init__(self):
        print "100 Capabilities\nVersion: 1.0\nSingle-Instance: true\n\n",

    def __get_next_msg(self):
        """
        Apt uses for communication with its methods the text protocol similar
        to http. This function parses the protocol messages from stdin.
        """
        if self.__eof:
            return None
        result = {};
        line = sys.stdin.readline()
        if not line:
            self.__eof = True
            return None
        s = line.split(" ", 1)
        result['_number'] = int(s[0])
        result['_text'] = s[1].strip()

        while not self.__eof:
            line = sys.stdin.readline()
            if not line:
                self.__eof = True
                return result
            if line == '\n':
                return result
            s = line.split(":", 1)
            result[s[0]] = s[1].strip()

    def __dict2msg(self, msg):
        """Convert dictionary to http like message"""
        result = ""
        for item in msg.keys():
            if msg[item] != None:
                result += item + ": " + msg[item] + "\n"
        return result

    def status(self, **kwargs):
        print "102 Status\n%s\n" % self.__dict2msg(kwargs),

    def uri_start(self, msg):
        print "200 URI Start\n%s\n" % self.__dict2msg(msg),

    def uri_done(self, msg):
        print "201 URI Done\n%s\n" % self.__dict2msg(msg),

    def uri_failure(self, msg):
        print "400 URI Failure\n%s\n" % self.__dict2msg(msg),

    def run(self):
        """Loop through requests on stdin"""
        while True:
            msg = self.__get_next_msg()
            if msg == None:
                return 0
            if msg['_number'] == 600:
                try:
                    self.fetch(msg)
                except Exception, e:
                    self.fail(e.__class__.__name__ + ": " + str(e))
                except up2dateErrors.Error, e:
                    self.fail(e.__class__.__name__ + ": " + str(e))
            else:
                return 100



def get_ssl_ca_cert(up2date_cfg):
    if not (up2date_cfg.has_key('sslCACert') and up2date_cfg['sslCACert']):
       raise BadSslCaCertConfig

    ca_certs = up2date_cfg['sslCACert']
    if type(ca_certs) == list:
        return ca_certs
    return [ca_certs]



class spacewalk_method(pkg_acquire_method):
    """
    Spacewalk acquire method
    """
    up2date_cfg = None
    login_info = None
    current_url = None
    svr_channels = None
    http_headers = None
    base_channel = None
    conn = None
    not_registered_msg = 'This system is not registered with the spacewalk server'

    def fail(self, message = not_registered_msg):
        self.uri_failure({'URI': self.uri,
                          'Message': message})


    def __load_config(self):
        if self.up2date_cfg == None:
            self.up2date_cfg = config.initUp2dateConfig()
            self.up2date_server = urlparse(self.up2date_cfg['serverURL'])
        # TODO: proxy settings


    def __login(self):
        if self.login_info == None:
            self.status(URI = self.uri, Message = 'Logging into the spacewalk server')
            self.login_info = up2dateAuth.getLoginInfo()
            if not self.login_info:
                raise up2date_client.AuthenticationError(self.not_registered_msg)
            self.status(URI = self.uri, Message = 'Logged in')


    def __init_channels(self):
        if self.svr_channels == None:
            self.svr_channels = rhnChannel.getChannelDetails()
            for channel in self.svr_channels:
                if channel['parent_channel'] == '':
                    self.base_channel = channel['label']


    def __init_headers(self):
        if self.http_headers == None:
            rhn_needed_headers = ['X-RHN-Server-Id',
                                  'X-RHN-Auth-User-Id',
                                  'X-RHN-Auth',
                                  'X-RHN-Auth-Server-Time',
                                  'X-RHN-Auth-Expire-Offset']
            self.http_headers = {};
            for header in rhn_needed_headers:
                if not self.login_info.has_key(header):
                    raise up2date_client.AuthenticationError(
                        "Missing required login information %s" % (header))
                self.http_headers[header] = self.login_info[header]
            self.http_headers['X-RHN-Transport-Capability'] = 'follow-redirects=3'


    def __make_conn(self):
        if self.conn == None:
            if self.up2date_server.scheme == 'http' \
                or self.up2date_cfg['useNoSSLForPackages'] == 1:
                self.conn = HTTPConnection(self.up2date_server.netloc)
            else:
                self.conn = HTTPSConnection(self.up2date_server.netloc,
                    trusted_certs=get_ssl_ca_cert(self.up2date_cfg))


    def __transform_document(self, document):
        """Transform url given by apt to real spacewalk url"""
        document = document.replace('dists/channels:/main/', 
                'dists/channels:/' + self.base_channel  + '/', 1)
        document = re.sub('/binary-[\d\w]*/', '/repodata/', document, 1)
        document = document.replace('dists/channels:/', '/XMLRPC/GET-REQ/', 1)
        return document


    def fetch(self, msg):
        """
        Fetch the content from spacewalk server to the file.

        Acording to the apt protocol msg must contain: 'URI' and 'Filename'.
        Other possible keys are: 'Last-Modified', 'Index-File', 'Fail-Ignore'
        """
        self.uri = msg['URI']
        self.uri_parsed = urlparse(msg['URI'])
        self.filename = msg['Filename']

        self.__load_config()
        if self.uri_parsed.netloc != self.up2date_server.netloc:
            return self.fail()
        self.__login()
        self.__init_channels()

        document = self.__transform_document(self.uri_parsed.path)

        self.__init_headers()
        self.__make_conn()

        self.conn.request("GET", "/" + document, headers = self.http_headers)
        self.status(URI = self.uri, Message = 'Waiting for headers')

        res = self.conn.getresponse()
        if res.status != 200:
            self.uri_failure({'URI': self.uri,
                              'Message': str(res.status) + '  ' + res.reason,
                              'FailReason': 'HttpError' + str(res.status)})
            while True:
                data = res.read(4096)
                if not len(data): break
            res.close()
            return

        self.uri_start({'URI': self.uri,
                        'Size': res.getheader('content-length'),
                        'Last-Modified': res.getheader('last-modified')})

        f = open(self.filename, "w")
        hash_sha256 = hashlib.sha256()
        hash_md5 = hashlib.md5()
        while True:
            data = res.read(4096)
            if not len(data):
                break
            hash_sha256.update(data)
            hash_md5.update(data)
            f.write(data)
        res.close()
        f.close()

        self.uri_done({'URI': self.uri,
                       'Filename': self.filename,
                       'Size': res.getheader('content-length'),
                       'Last-Modified': res.getheader('last-modified'),
                       'MD5-Hash': hash_md5.hexdigest(),
                       'MD5Sum-Hash': hash_md5.hexdigest(),
                       'SHA256-Hash': hash_sha256.hexdigest()})


    def __del__(self):
        if self.conn:
            self.conn.close()



if __name__ == '__main__':
    method = spacewalk_method()
    ret = method.run()
    sys.exit(ret)


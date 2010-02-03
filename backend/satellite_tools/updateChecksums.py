#!/usr/bin/python
#
# Copyright (c) 2008--2009 Red Hat, Inc.
#
# Authors: Pradeep Kilambi
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#
#

import sys
import os
import time
import shutil

sys.path.append('/usr/share/rhn')

from optparse import Option, OptionParser
from common import rhnLib, rhnLog, initLOG, CFG, initCFG
from spacewalk.common import rhn_rpm
from server.rhnLib import parseRPMFilename, get_package_path
from server import rhnSQL
from server.rhnServer import server_packages
from satellite_tools.progress_bar import ProgressBar

initCFG('server.satellite')
initLOG(CFG.LOG_FILE, CFG.DEBUG)

OPTIONS = None
debug = 0
verbose = 0

options_table = [
    Option("-v", "--verbose",       action="count",
        help="Increase verbosity"),
    Option("-d", "--db",            action="store",
        help="DB string to connect to"),
    Option(   "--debug",            action="store_true",
        help="logs the debug information to a log file"),
]


def main():
    global options_table, debug
    parser = OptionParser(option_list=options_table)

    (options, args) = parser.parse_args()

    if args:
        for arg in args:
            sys.stderr.write("Not a valid option ('%s'), try --help\n" % arg)
        sys.exit(-1)

    if options.verbose:
        verbose = 1

    if options.debug:
        debug = 1

    if not options.db:
        sys.stderr.write("--db not specified\n")
        sys.exit(1)

    print "Connecting to %s" % options.db
    rhnSQL.initDB(options.db)

    process_package_data()



_get_needed_pkgs_query = """
   select P.id, P.path, CV.checksum_type, CV.checksum
   from rhnPackage P left join
        rhnPackageKeyAssociation PA on PA.package_id = P.id inner join
        rhnChecksumView CV on CV.id = P.checksum_id
   where PA.key_id is null
"""


def process_package_data():
    global verbose, debug

    if debug:
        Log = rhnLog.rhnLog('/var/log/rhn/update-packages.log', 5)

    _get_path_sql = rhnSQL.prepare(_get_needed_pkgs_query)

    _get_path_sql.execute()
    pkgs = _get_path_sql.fetchall_dict()

    if not pkgs:
        # Nothing to change
        return
    if verbose: print "Processing %s packages" % len(pkgs)
    pb = ProgressBar(prompt='standby: ', endTag=' - Complete!', \
                     finalSize=len(pkgs), finalBarLength=40, stream=sys.stdout)
    pb.printAll(1)
    skip_list = []
    i = 0
    for pkg in pkgs:
        pb.addTo(1)
        pb.printIncrement()
        path =  pkg['path']

        full_path = os.path.join(CFG.MOUNT_POINT, path)
        checksum_type = pkg['checksum_type']
        checksum = pkg['checksum']

        if not os.path.exists(full_path):
            skip_list.append(full_path)
            Log.writeMessage("File not %s found" % (full_path))
            continue

        try:
            hdr = rhn_rpm.get_package_header(filename=full_path)
        except:
            rhnSQL.commit()
            raise

        # Process gpg key ids
        server_packages.processPackageKeyAssociations(hdr, checksum_type, checksum)
        if debug: Log.writeMessage("gpg key info updated from %s" % new_abs_path )
        i = i + 1
        # we need to break the transaction to smaller pieces
        if i % 1000 == 0:
            rhnSQL.commit()
    pb.printComplete()
    # All done, final commit
    rhnSQL.commit()
    sys.stderr.write("Transaction Committed! \n")
    if verbose: print " Skipping %s packages, paths not found" % len(skip_list)
    return


if __name__ == '__main__':
    main()


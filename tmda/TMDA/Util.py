# -*- python -*-
#
# Copyright (C) 2001-2007 Jason R. Mastaler <jason@mastaler.com>
#
# This file is part of TMDA.
#
# TMDA is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.  A copy of this license should
# be included in the file COPYING.
#
# TMDA is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with TMDA; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA

"""General purpose functions."""


from io import StringIO
import pickle
import email
import email.utils
import fnmatch
import os
import subprocess
from subprocess import PIPE, STDOUT # Make these available in Util
import re
import socket
import stat
import sys
import tempfile
import textwrap
import time
import optparse

from .Errors import ConfigError


MODE_EXEC = 0o1
MODE_READ = 0o4
MODE_WRITE = 0o2
POSIX_NAME_MAX = 255                    # maximum length of a file name


def gethostname():
    """The host name"""
    hostname = os.environ.get('TMDAHOST') or \
               os.environ.get('QMAILHOST') or \
               os.environ.get('MAILHOST')
    if not hostname:
        hostname = socket.getfqdn()
    return hostname


def urlsplit(urlstring, scheme='', allow_fragments=True):
    '''Modified urlsplit that handles IPv6 addresses.'''
    from urllib.parse import urlsplit

    result = urlsplit(urlstring, scheme, allow_fragments)
    if '[' in result.netloc:
        return IP6SplitResult(result)
    return result

class IP6SplitResult(object):
    '''Result type for urlsplit when the URL uses an IPv6 address. This is
    intended to be compatible with the regular urlsplit result, but beware of
    subtle differences. For example, this is not derived from tuple. Indexing
    and unpacking are supported, however.'''
    # Host matcher matches IP-literal in RFC3986, but it's not very strict and
    # doesn't match IPvFuture addresses. It does match addresses that use the
    # IPv4 dotted-quad format for the last 32 bits.
    _host_matcher = re.compile(r'\[([\da-fA-F:.]+)\]')

    def __init__(self, result):
        self._result = result

        # urlsplit gets hostname and port wrong. Replace them. Everything else
        # is looked up in self._result.
        self.hostname = self._host_matcher.search(result.netloc).group(1)

        if ']:' in result.netloc:
            self.port = int(result.netloc.split(']:', 1)[1])
        else:
            self.port = None

    def __getattr__(self, name):
        return getattr(self._result, name)

    # Special method lookup doesn't go through __getattr__ (or
    # through __getattribute__).
    def __getitem__(self, key):
        return self._result[key]

    def __repr__(self):
        return repr(self._result)


def getfullname():
    """The user's personal name.  Default is an empty value."""
    fullname = os.environ.get('TMDANAME') or \
               os.environ.get('QMAILNAME') or \
               os.environ.get('NAME') or \
               os.environ.get('MAILNAME')
    if not fullname:
        import pwd
        fullname = pwd.getpwuid(os.getuid())[4]
        if fullname:
            fullname = fullname.split(',')[0]
    return fullname


def getusername():
    """The user name"""
    username = os.environ.get('TMDAUSER') or \
               os.environ.get('QMAILUSER') or \
               os.environ.get('USER') or \
               os.environ.get('LOGNAME')
    if not username:
        import pwd
        username = pwd.getpwuid(os.getuid())[0]
    if not username:
        username = '<unknown>'
    return username


def getuid(username):
    """Return username's numerical user ID."""
    import pwd
    return pwd.getpwnam(username)[2]


def getgid(username):
    """Return username's numerical group ID."""
    import pwd
    return pwd.getpwnam(username)[3]


def gethomedir(username):
    """Return the home directory of username."""
    import pwd
    return pwd.getpwnam(username)[5]


def getgrouplist(username):
    """Read through the group file and calculate the group access
    list for the specified user.  Return a list of group ids."""
    import grp
    # calculate the group access list
    gids = [i[2] for i in grp.getgrall() if username in i[-1]]
    # include the base gid
    gids.insert(0, getgid(username))
    return gids


def getfilemode(path):
    """Return the octal number of the bit pattern for the file
    permissions on path."""
    statinfo = os.stat(path)
    mode = stat.S_IMODE(statinfo[stat.ST_MODE])
    #mode = int(oct(mode))
    return mode


def getfileuid(path):
    """Return the numerical UID of the user owning the file in path."""
    statinfo = os.stat(path)
    return statinfo[stat.ST_UID]


def issticky(path):
    """Return True if the sticky bit is set on path.  Generally only
    appropriate for directories."""
    statinfo = os.stat(path)
    return statinfo[stat.ST_MODE] & stat.S_ISVTX


def getvdomainprepend(address, vdomainsfile):
    ret_prepend = ''
    if os.path.exists(vdomainsfile):
        fp = open(vdomainsfile, 'r')
        # Parse the virtualdomains control file; see qmail-send(8) for
        # syntax rules.  All this because qmail doesn't store the original
        # envelope recipient in the environment.
        u, d = address.split('@', 1)
        #ousername = u.lower()
        odomain = d.lower()
        for line in fp.readlines():
            vdomain_match = 0
            line = line.strip().lower()
            # Comment or blank line?
            if line == '' or line[0] in '#':
                continue
            vdomain, prepend = line.split(':', 1)
            # domain:prepend
            if vdomain == odomain:
                vdomain_match = 1
            # .domain:prepend (wildcard)
            elif vdomain[:1] == '.' and odomain.find(vdomain) != -1:
                vdomain_match = 1
            # user@domain:prepend
            else:
                try:
                    if vdomain.split('@', 1)[1] == odomain:
                        vdomain_match = 1
                except IndexError:
                    pass
            if vdomain_match:
                ret_prepend = prepend
                break
        fp.close()
    return ret_prepend


def getvuserhomedir(user, domain, script):
    """Return the home directory of a qmail virtual domain user."""
    cmd = "%s %s %s" % (script, user, domain)
    fpin = os.popen(cmd)
    vuserhomedir = fpin.read()
    fpin.close()
    return vuserhomedir.strip()


def getuserparams(login):
    "Return a user's home directory, UID, & GID."
    import pwd
    stats = pwd.getpwnam(login)
    return (stats[5], stats[2], stats[3])


def RunTask(Args):
    """Run a program the "hard way" so we don't lose our UID."""

    # Open a pipe between the parent and a child process
    Read, Write = os.pipe()
    if not os.fork():
        # Child writes only and can close the reader
        os.close(Read)

        # Capture the STDOUT and stick it in the pipe
        os.dup2(Write, 1)

        # Launch the program
        os.execv(Args[0], Args)

    # Parent reads only and can close the writer
    os.close(Write)

    # Capture contents of pipe
    Read = os.fdopen(Read)
    RetVal = Read.readlines()
    Read.close()

    return RetVal


def seconds(timeout):
    """Translate the defined timeout interval into seconds."""
    match = re.match("^([0-9]+)([YMwdhms])$", timeout)
    if not match:
        raise ValueError('Invalid timeout value: ' + timeout)
    (num, unit) = match.groups()
    unit_secs = {'Y': 60*60*24*365,  # years
                 'M': 60*60*24*30,   # months
                 'w': 60*60*24*7,    # weeks
                 'd': 60*60*24,      # days
                 'h': 60*60,         # hours
                 'm': 60,            # minutes
                 's': 1              # seconds
                }
    return int(num) * unit_secs[unit]


def format_timeout(timeout):
    """Return a human readable translation of the timeout interval."""
    match = re.match("^([0-9]+)([YMwdhms])$", timeout)
    if not match:
        return timeout
    (num, unit) = match.groups()
    from . import Defaults
    timeout = num + " " + Defaults.TIMEOUT_UNITS[unit]
    if int(num) == 1:
        timeout = timeout[:-1]
    return timeout


def unixdate(timesecs=None):
    """Return a date string in the format of the UNIX `date' command.  e.g,

    Thu Dec 27 17:54:04 MST 2001

    timesecs is optional, and if not given, the current time is used.
    """
    if not timesecs:
        timesecs = time.time()
    timetuple = time.localtime(timesecs)
    tzname = time.tzname[timetuple[-1]]
    asctime_list = time.asctime(timetuple).split()
    asctime_list.insert(len(asctime_list)-1, tzname)
    return ' '.join(asctime_list)


def make_msgid(timesecs=None, pid=None):
    """Return an rfc2822 compliant Message-ID: string, composed of
    seconds since the epoch in UTC + process id + 'TMDA' + FQDN. e.g:

    <1016659379.10104.TMDA@nightshade.la.mastaler.com>

    timesecs is optional, and if not given, the current time is used.

    pid is optional, and if not given, the current process id is used.
    """
    if not timesecs:
        timesecs = time.time()
    if not pid:
        from . import Defaults
        pid = Defaults.PID
    idhost = os.environ.get('TMDAIDHOST') or \
             os.environ.get('QMAILIDHOST') or \
             gethostname()
    idtag = os.environ.get('TMDAIDTAG') or 'TMDA'
    msgid = '<%s.%s.%s@%s>' % (int(timesecs), pid, idtag, idhost)
    return msgid


def make_date(timesecs=None):
    """Return an RFC 2822 compliant Date string relative to the local
    timezone.  e.g,

    Tue, 02 Mar 2004 15:55:05 +1300

    timesecs is optional, and if not given, the current time is used.
    """
    if timesecs is None:
        timesecs = time.time()
    return email.utils.formatdate(timesecs, localtime=True)


def file_to_list(filename):
    """Process and then append each line of file to list."""
    result = []
    for line in open(filename, encoding='utf-8'):
        line = line.strip()
        # Comment or blank line?
        if line == '' or line[0] in '#':
            continue
        line = line.expandtabs().split('#')[0].strip()
        result.append(line)
    return result


def runcmd(cmd, instr=None, stdout=None, stderr=None):
    """Run a command, wait for it to complete, and return a tuple of
    (return value, stdout text, stderr text). instr is a string to
    pass as input. stdout and stderr can take the same forms as their
    subprocess.Popen equivalents.
    """
    use_shell = False
    if isinstance(cmd, str):
        use_shell = True

    process = subprocess.Popen(cmd, stdin=PIPE, stdout=stdout, stderr=stderr,
                               shell=use_shell)
    if type(instr) == str:
        instr = bytes(instr, 'utf-8')
    (stdoutdata, stderrdata) = process.communicate(instr)

    return (process.returncode, stdoutdata, stderrdata)


def runcmd_checked(cmd, instr=None, stdout=None, stderr=None):
    """Version of runcmd that doesn't return the exit code or
    signal, but raises an exception for errors and signals.
    """
    (r, stdoutdata, stderrdata) = runcmd(cmd, instr, stdout, stderr)
    if r > 0:
        raise Exception('command %r exited with error %d' % (cmd, r))
    if r < 0:
        raise Exception('command %r exited with signal %d' % (cmd, -r))

    return (stdoutdata, stderrdata)


def writefile(contents, fullpathname):
    """Simple function to write contents to a file."""
    if os.path.exists(fullpathname):
        raise IOError(fullpathname + ' already exists')
    with open(fullpathname, 'w') as f:
        f.write(contents)


def append_to_file(s, fullpathname):
    """Append a string to a text file if it isn't already in there."""
    bare = bytes(s.expandtabs().split('#')[0].strip().lower(), 'utf-8')
    if os.path.exists(fullpathname):
        for inline in open(fullpathname, 'rb'):
            line = inline.strip().lower()
            # Comment or blank line?
            if line[:1] in [ b'', b'#']:
                continue
            line = line.expandtabs()
            line = line.split(b'#', 1)[0]
            line = line.strip()
            if bare == line:
                # Already there
                return
    with open(fullpathname, 'a+') as f:
        f.write(s.strip() + '\n')


def pager(str):
    """Display a string using a UNIX text pager such as less or more."""
    pager = os.environ.get('PAGER')
    if pager is None:
        # try to locate less or more if $PAGER is not set
        for prog in ('less', 'more'):
            path = os.popen('which ' + prog).read()
            if path != '':
                pager = path
                break
    try:
        os.popen(pager, 'w').write(str)
    except IOError:
        return


def normalize_sender(sender):
    """Return a normalized version of the given sender address for use
    in ~/.tmda/responses.

    - Any / characters are replaced with : to prevent creation of files
      outside the directory.
    - Spaces are replaced with underscores.
    - The address is lowercased.
    - Truncate sender at 233 chars to insure the full filename
    (including time, pid, and two dots) fits within the POSIX limit of
    255 chars for a filename.
    """
    sender = sender.replace(' ', '_')
    sender = sender.replace('/', ':')
    sender = sender.lower()
    return sender[:POSIX_NAME_MAX - 22]


def confirm_append_address(xp, rp):
    """
    xp is an address from the ``X-Primary-Address'' header.
    rp is the envelope sender address.

    Compare the two addresses, and return the address appropriate for
    CONFIRM_APPEND based on the PRIMARY_ADDRESS_MATCH setting.
    """
    if not xp:
        return rp
    if '@' not in rp or '@' not in xp:
        return rp
    from . import Defaults
    rpl = rp.lower()
    xpl = xp.lower()
    rplocal, rphost = rpl.split('@', 1)
    rpdomain = '.'.join(rphost.split('.')[-2:])
    rpusername = rplocal.split(Defaults.RECIPIENT_DELIMITER)[0]
    xplocal, xphost = xpl.split('@', 1)
    xpdomain = '.'.join(xphost.split('.')[-2:])
    xpusername = xplocal.split(Defaults.RECIPIENT_DELIMITER)[0]
    match = Defaults.PRIMARY_ADDRESS_MATCH

    tests = {1: lambda: False,
             2: lambda: xpusername == rpusername and xphost == rphost,
             3: lambda: xpusername == rpusername and xpdomain == rpdomain,
             4: lambda: xphost == rphost,
             5: lambda: xpdomain == rpdomain,
             6: lambda: True
             }
    return xp if tests[match] else rp

"""
    if match == 0:
        # never a match
        return rp
    if match == 1:
        # only identical addresses match
        if xpl == rpl:
            return xp
    if match == 2:
        # usernames and hostnames must match
        if xpusername == rpusername and xphost == rphost:
            return xp
    if match == 3:
        # usernames and domains must match
        if xpusername == rpusername and xpdomain == rpdomain:
            return xp
    if match == 4:
        # hostnames must match
        if xphost == rphost:
            return xp
    if match == 5:
        # domains must match
        if xpdomain == rpdomain:
            return xp
    if match == 6:
        # always a match
        return xp
    return rp
"""

def msg_from_file(fp, fullParse=False, isBytes=False):
    """Read a file and parse its contents into a Message object model.
    Replacement for email.message_from_file().

    We use the HeaderParser subclass instead of Parser to avoid trying
    to parse the message body, instead setting the payload to the raw
    body as a string.  This is faster, and also helps us avoid
    problems trying to parse spam with broken MIME bodies."""
    from email.parser import Parser, HeaderParser, BytesParser, BytesHeaderParser
    parsers = ((HeaderParser, Parser), (BytesHeaderParser, BytesParser))
    parser = parsers[int(isBytes)][int(fullParse)]
    return parser().parse(fp)

def msg_as_string(msg, maxheaderlen=False, mangle_from_=False, unixfrom=False):
    """A more flexible replacement for Message.as_string().  The default
    is a textual representation of the message where the headers are
    not wrapped, From is not escaped, and a leading From_ line is not
    added.

    msg is an email.message.Message object.

    maxheaderlen specifies the longest length for a non-continued
    header.  Disabled by default.  RFC 2822 recommends 78.

    mangle_from_ escapes any line in the body that begins with "From"
    with ">".  Useful when writing to Unix mbox files.  Default is
    False.

    unixfrom forces the printing of the envelope header delimiter.
    Default is False."""
    from email import generator
    fp = StringIO()
    #if hasattr(msg, 'header_parsed') and msg.header_parsed:
    #    genclass = Generator.HeaderParsedGenerator
    #else:
         #genclass = Generator.Generator
    genclass = generator.Generator
    g = genclass(fp, mangle_from_=mangle_from_, maxheaderlen=maxheaderlen)
    g.flatten(msg, unixfrom=unixfrom)
    return fp.getvalue()


def sendmail(msgstr, envrecip, envsender):
    """Send e-mail via direct SMTP, or by opening a pipe to the
    sendmail program.

    msgstr is an rfc2822 message as a string.

    envrecip is the envelope recipient address.

    envsender is the envelope sender address.
    """
    from . import Defaults
    # Sending mail with a null envelope sender address <> is not done
    # the same way across the different supported MTAs, nor across the
    # two mail transports (SMTP and /usr/sbin/sendmail).
    #
    # The most common method is to use the string '<>'.  There are two
    # exceptions where an empty string must be used instead.
    #
    # 1) When running qmail/courier and using the sendmail transport.
    # qmail munges the envelope sender address into <"<>"@domain.dom
    # if "sendmail -f <>" is used.
    #
    # 2) When running Postfix and using the sendmail transport.
    # Old versions of Postfix apparently also have trouble with
    # "sendmail -f <>", though Postfix 2.0.x does not.
    if envsender == '':
        envsender = '<>'
    if envsender == '<>' and \
           Defaults.MAIL_TRANSFER_AGENT in ('postfix', 'qmail') and \
           Defaults.MAIL_TRANSPORT == 'sendmail':
        envsender = ''
    if Defaults.MAIL_TRANSPORT == 'sendmail':
        # You can avoid the shell by passing a tuple of arguments as
        # the command instead of a string.  This will cause the
        # subprocess.Popen() code to execvp() "/usr/bin/sendmail" with
        # these arguments exactly, with no trip through any shell.
        cmd = (Defaults.SENDMAIL_PROGRAM, '-i',
               '-f', envsender, '--', envrecip)
        runcmd_checked(cmd, msgstr)
    elif Defaults.MAIL_TRANSPORT == 'smtp':
        from . import SMTP
        server = SMTP.Connection()
        server.sendmail(envsender, envrecip, msgstr)
        server.quit()
    else:
        raise ConfigError("Invalid MAIL_TRANSPORT method: " + Defaults.MAIL_TRANSPORT)


def _str(s):
    if type(s) == bytes:
        return s.decode('utf8', 'ignore')
    return s


def decode_header(s):
    """Accept a possibly encoded message header as a string, and
    return a decoded string if it can be decoded.

    JRM: email.header has a decode_header method, but it returns a
    list of decoded pairs, one for each part of the header, which is
    an awkward interface IMO, especially when the header contains a
    mix of encoded and non-encoded parts.
    """
    if s is None: # No such header.
        return _str(s)
    try:
        from email import header
        return ' '.join(_str(pair[0]) for pair in header.decode_header(s))
    except email.errors.HeaderParseError:
        return _str(s)


def headers_as_list(msg):
    """Return a list containing the entire set of header lines, in the
    order in which they were read."""
    return ['%s: %s' % (k, v) for k, v in msg.items()]


def headers_as_raw_string(msg):
    """Return the headers as a raw (undecoded) string."""
    msgtext = msg_as_string(msg)
    idx = msgtext.index('\n\n')
    return msgtext[:idx+1]


def headers_as_string(msg):
    """Return the (decoded) message headers as a string.  If the
    sequence can't be decoded, punt and return a raw (undecoded)
    string instead."""
    try:
        hdrstr = '\n'.join(['%s: %s' %
                            (k, decode_header(v)) for k, v in msg.items()])
    except email.errors.HeaderParseError:
        hdrstr = headers_as_raw_string(msg)
    return hdrstr


def body_as_raw_string(msg):
    """Return the body as a raw (undecoded) string."""
    msgtext = msg_as_string(msg)
    idx = msgtext.index('\n\n')
    return msgtext[idx+2:]



def rename_headers(msg, old, new):
    """Rename all occurances of a message header in a Message object.

    msg is an email.message.Message object.

    old is name of the header to rename.

    new is the new name of the header
    """
    if old in msg:
        for pair in msg._headers:
            if pair[0].lower() == old.lower():
                index = msg._headers.index(pair)
                msg._headers[index] = (new, '%s' % pair[1])


def add_headers(msg, headers):
    """Add headers to a Message object.

       msg is an email.message.Message object.

       headers is a dictionary of headers and values.
       """
    if headers:
        # no idea why this is done in sorted order
        for k in sorted(headers.keys()):
            del msg[k]
            msg[k] = headers[k]


def purge_headers(msg, headers):
    """Purge headers from a Message object.

       msg is an email.message.Message object.

       headers is a list of headers.
       """
    if headers:
        for h in headers:
            del msg[h]


def build_cdb(filename):
    """Build a cdb file from a text file."""
    import cdb
    try:
        cdbname = filename + '.cdb'
        tempfile.tempdir = os.path.dirname(filename)
        tmpname = os.path.split(tempfile.mktemp())[1]
        cdb = cdb.cdbmake(cdbname, cdbname + '.' + tmpname)
        for line in file_to_list(filename):
            key, value = (line.split() + [''])[:1]
            cdb.add(key.lower(), value)
        cdb.finish()
    except:
        return False
    return True


def build_dbm(filename):
    """Build a DBM file from a text file."""
    import dbm
    import glob
    try:
        dbmpath, dbmname = os.path.split(filename)
        dbmname += '.db'
        tempfile.tempdir = dbmpath
        tmpname = tempfile.mktemp()
        db = dbm.open(tmpname, 'n')
        for line in file_to_list(filename):
            key, value = (line.split() + [''])[:1]
            db[key.lower()] = value
        db.close()
        for f in glob.glob(tmpname + '*'):
            (tmppath, tmpname) = os.path.split(tmpname)
            newf = f.replace(tmpname, dbmname)
            newf = os.path.join(tmppath, newf)
            os.rename(f, newf)
    except:
        return False
    return True


def pickleit(object, file, proto=2):
    """Store object in a pickle file.

    Optional 'proto' specifies which data storage format to use.
    Possible integer values include:

    0 (original ASCII protocol and is backwards compatible with
    earlier versions of Python)

    1 (old binary format which is also compatible with earlier
    versions of Python)

    2 (a more effecient binary format introduced in Python 2.3)

    -1 (always choose the highest protocol version available)

    default is 2, since we must support Python 2.3 and above.
    """
    tempfile.tempdir = os.path.dirname(file)
    tmpname = tempfile.mkstemp()[1]
    fp = open(tmpname, 'wb')
    pickle.dump(object, fp, proto)
    fp.close()
    os.rename(tmpname, file)
    return


def unpickle(file):
    """Retrieve and return object from file."""
    fp = open(file, 'rb')
    object = pickle.load(fp)
    fp.close()
    return object


def db_insert(db, insert_sql, params):
    """Insert (using the 'insert_sql' SQL) an address into a SQL DB."""
    dbmodule = sys.modules[db.__module__]
    DatabaseError = getattr(dbmodule, 'DatabaseError')
    cursor = db.cursor()
    try:
        try:
            cursor.execute(insert_sql, params)
            db.commit()
        except DatabaseError:
            pass
    finally:
        cursor.close()


def findmatch(list, addrs):
    """Determine whether any of the passed e-mail addresses match a
    Unix shell-style wildcard pattern contained in list.  The
    comparison is case-insensitive.  Also, return the second half of
    the string if it exists (for exp and ext addresses only)."""
    for address in addrs:
        if address:
            address = address.lower()
            for p in list:
                stringparts = p.split()
                p = stringparts[0]
                # Handle special @=domain.dom syntax.
                try:
                    at = p.rindex('@')
                    atequals = p[at+1] == '='
                except (ValueError, IndexError):
                    atequals = None
                if atequals:
                    p1 = p[:at+1] + p[at+2:]
                    p2 = p[:at+1] + '*.' + p[at+2:]
                    match = (fnmatch.fnmatch(address,p1)
                             or fnmatch.fnmatch(address,p2))
                else:
                    match = fnmatch.fnmatch(address,p)
                if match:
                    try:
                        return stringparts[1]
                    except IndexError:
                        return 1


def wraptext(text, column=70):
    """Wrap and fill the text to the specified column width."""
    wrapper = textwrap.TextWrapper(width=column, break_long_words=False)
    return wrapper.fill(text)


def maketext(templatefile, vardict):
    """Make some text from a template file.

    templatefile can either be an absolute pathname starting with an /
    or ~ (e.g, /usr/local/packages/tmda/templates/bounce.txt) or a
    relative pathname (e.g, bounce.txt).

    Given a relative pathname, several locations are scanned for
    templatefile, in the following order:

    1. The directory specified by tmda-filter's `-t' option.
    2. Defaults.TEMPLATE_DIR_MATCH_SENDER (if true)
    3. Defaults.TEMPLATE_DIR_MATCH_RECIPIENT (if true)
    4. Defaults.TEMPLATE_DIR
    5. ../templates/
    6. The package/RPM template directories.

    The first match found stops the search.  In this way, you can
    specialize templates at the desired level, or, if you use only the
    default templates, you don't need to change anything.

    Once the templatefile is found, string substitution is performed
    by interpolation in `localdict'.

    Based on code from Mailman
    <URL:http://www.gnu.org/software/mailman/mailman.html>
    Copyright (C) 1998,1999,2000,2001 by the Free Software Foundation, Inc.,
    and licensed under the GNU General Public License version 2.
    """
    from . import Defaults
    foundit = None
    if templatefile.startswith('~'):
        templatefile = os.path.expanduser(templatefile)
    if templatefile.startswith('/') and os.path.exists(templatefile):
        foundit = templatefile
    if foundit is None:
        # Calculate the locations to scan.
        searchdirs = []
        searchdirs.append(os.environ.get('TMDA_TEMPLATE_DIR'))
        if Defaults.TEMPLATE_DIR:
            tdirs = []
            if Defaults.TEMPLATE_DIR_MATCH_SENDER:
                sender = os.environ.get('SENDER').lower()
                tdirs = [sender]
                _, domainpart = (sender.split('@', 1) + [''])[:2]
                if domainpart:
                    domainparts = domainpart.split('.')
                    for i in range(len(domainparts)):
                        tdirs.append('.'.join(domainparts[i:]))
            if Defaults.TEMPLATE_DIR_MATCH_RECIPIENT:
                recipient = os.environ.get('TMDA_RECIPIENT').lower()
                tdirs.append(recipient)

                recippart, domainpart = (recipient.split('@', 1) + [''])[:2]
                delim = Defaults.RECIPIENT_DELIMITER

                recipparts = recippart.split(delim)
                for i in range(len(recipparts), step=-1):
                    tdirs.append(delim.join(recipparts[:i]) + "@" + domainpart)

                if domainpart:
                    domainparts = domainpart.split('.')
                    for i in range(len(domainparts)):
                        tdirs.append('.'.join(domainparts[i:]))

            searchdirs += [ os.path.join(Defaults.TEMPLATE_DIR, d) for d in tdirs ]
            searchdirs.append(Defaults.TEMPLATE_DIR)
        searchdirs.append(os.path.join(Defaults.PARENTDIR, 'templates'))
        searchdirs.append(os.path.join(sys.prefix, 'share/tmda'))
        searchdirs.append('/etc/tmda/')
        # Start scanning.
        for d in searchdirs:
            if not d: continue
            filename = os.path.join(d, templatefile)
            if os.path.exists(filename):
                foundit = filename
                break

    if foundit is None:
        raise IOError("Can't find " + templatefile)

    template = open(foundit, 'r').read()
    localdict = Defaults.__dict__.copy()
    localdict.update(vardict)
    text = template % localdict
    return text


def filter_match(filename, recip, sender=None):
    """Check if the give e-mail addresses match lines in filename."""
    from . import Defaults
    from . import FilterParser
    filter = FilterParser.FilterParser(Defaults.DB_CONNECTION)
    filter.read(filename)
    (actions, matchline) = filter.firstmatch(recip, [sender])
    # print the results
    checking_msg = 'Checking ' + filename
    print(checking_msg)
    print('-' * len(checking_msg))
    if recip:
        print('To:',recip)
    if sender:
        print('From:',sender)
    print('-' * len(checking_msg))
    if actions:
        print('MATCH:', matchline)
    else:
        print('Sorry, no matching lines.')


def CanRead( file, uid = None, gid = None, raiseError = 1 ):
    try:
        return CanMode( file, MODE_READ, uid, gid )
    except IOError:
        if not raiseError:
            return 0
        else:
            pass


def CanWrite( file, uid = None, gid = None, raiseError = 1 ):
    try:
        return CanMode( file, MODE_WRITE, uid, gid )
    except IOError:
        if not raiseError:
            return 0
        else:
            pass


def CanExec( file, uid = None, gid = None, raiseError = 1 ):
    try:
        return CanMode( file, MODE_EXEC, uid, gid )
    except IOError:
        if not raiseError:
            return 0
        else:
            pass


def CanMode( file, mode = MODE_READ, uid = None, gid = None ):
    try:
        fstat = os.stat( file )
    except:
        raise IOError("'%s' does not exist" % file)
    if uid is None:
        uid = os.geteuid()
    if gid is None:
        gid = os.getegid()
    needuid = fstat[4]
    needgid = fstat[5]
    filemod = fstat[0] & 0o777
    if uid == 0:
        # Root always wins.
        return 1
    elif filemod & mode:
        return 1
    elif filemod & ( mode * 0o10 ) and needgid == gid:
        return 1
    elif filemod & ( mode * 0o100 ) and needuid == uid:
        return 1
    else:
        return 0


class DevnullOutput:
    def write(self, msg): pass
    def flush(self): pass
    def __repr__(self):
        return ""


class StringOutput:
    def __init__(self):
        self.__content = ""
    def write(self, msg):
        if msg != "":
            self.__content += "%s" % msg
    def flush(self):
        self.__content = ""
    def __repr__(self):
        return self.__content


class Debugable(object):
    def __init__(self, outputObject = DevnullOutput() ):
        self.DEBUGSTREAM = outputObject
        if self.DEBUGSTREAM is DevnullOutput:
            self.level = 0
        else:
            self.level = 1

    def debug(self, msg, level = 1):
        if self.level >= level:
            self.DEBUGSTREAM.write(msg + '\n')

    def set_debug(self, level = 1):
        self.level = level

    def set_nodebug(self):
        self.level = 0


class HelpFormatter(optparse.IndentedHelpFormatter):
    '''
    The available formatters in optparse cannot preserve formatting. This makes
    tables (for example) impossible to format properly.

    This class is a help formatter that preserves empty lines and lines that
    begin with whitespace. Other lines are re-wrapped as usual.
    '''
    _dont_wrap = re.compile(r'^(\s|$)')

    @classmethod
    def _wrap(cls, text, width):
        def do_wrappable():
            if wrappable:
                result.extend(textwrap.wrap('\n'.join(wrappable), width))
                wrappable[:] = []

        lines = text.split('\n')
        wrappable = []
        result = []
        for line in lines:
            if cls._dont_wrap.match(line):
                do_wrappable()
                result.append(line)
            else:
                wrappable.append(line)

        do_wrappable()
        return result

    # format_option is taken (slightly modified) from optparse.py in Python 2.6
    # under the following license.
    #
    # Copyright (c) 2001-2006 Gregory P. Ward.  All rights reserved.
    # Copyright (c) 2002-2006 Python Software Foundation.  All rights reserved.
    #
    # Redistribution and use in source and binary forms, with or without
    # modification, are permitted provided that the following conditions are
    # met:
    #
    #   * Redistributions of source code must retain the above copyright
    #     notice, this list of conditions and the following disclaimer.
    #
    #   * Redistributions in binary form must reproduce the above copyright
    #     notice, this list of conditions and the following disclaimer in the
    #     documentation and/or other materials provided with the distribution.
    #
    #   * Neither the name of the author nor the names of its
    #     contributors may be used to endorse or promote products derived from
    #     this software without specific prior written permission.
    #
    # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
    # IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
    # TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
    # PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR
    # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
    # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
    # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
    # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
    # LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
    # NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
    # SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
    def format_option(self, option):
        result = []
        opts = self.option_strings[option]
        opt_width = self.help_position - self.current_indent - 2
        if len(opts) > opt_width:
            opts = "%*s%s\n" % (self.current_indent, "", opts)
            indent_first = self.help_position
        else:                       # start help on same line as opts
            opts = "%*s%-*s  " % (self.current_indent, "", opt_width, opts)
            indent_first = 0
        result.append(opts)
        if option.help:
            help_text = self.expand_default(option)
            help_lines = self._wrap(help_text, self.help_width)
            result.append("%*s%s\n" % (indent_first, "", help_lines[0]))
            result.extend(["%*s%s\n" % (self.help_position, "", line)
                           for line in help_lines[1:]])
        elif opts[-1] != "\n":
            result.append("\n")
        return "".join(result)

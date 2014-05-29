from __future__ import unicode_literals

import logging
import shutil
import sys
import tarfile
import tempfile
import os
import platform
import re
import sqlite3
import string
import subprocess

import reprounzip.common
from reprounzip.common import FILE_WDIR
from reprounzip.utils import find_all_links


def shell_escape(s):
    if any(c in s for c in string.whitespace + '$\\"\''):
        return '"%s"' % (s.replace('\\', '\\\\')
                          .replace('"', '\\"')
                          .replace('$', '\\$'))
    else:
        return s


def rb_escape(s):
    return "'%s'" % (s.replace('\\', '\\\\')
                      .replace("'", "\\'"))


def load_config(pack):
    tmp = tempfile.mkdtemp(prefix='reprozip_')
    try:
        # Loads info from package
        tar = tarfile.open(pack, 'r:*')
        f = tar.extractfile('METADATA/version')
        version = f.read()
        f.close()
        if version != b'REPROZIP VERSION 1\n':
            sys.stderr.write("Unknown pack format\n")
            sys.exit(1)
        tar.extract('METADATA/config.yml', path=tmp)
        tar.close()
        configfile = os.path.join(tmp, 'METADATA/config.yml')
        ret = reprounzip.common.load_config(configfile)
    finally:
        shutil.rmtree(tmp)

    return ret


def list_directories(pack):
    tmp = tempfile.mkdtemp(prefix='reprozip_')
    try:
        tar = tarfile.open(pack, 'r:*')
        tar.extract('METADATA/trace.sqlite3', path=tmp)
        database = os.path.join(tmp, 'METADATA/trace.sqlite3')
        tar.close()
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        executed_files = cur.execute(
                '''
                SELECT name
                FROM opened_files
                WHERE mode = ?
                ''',
                (FILE_WDIR,))
        result = set(n for (n,) in executed_files)
        cur.close()
        conn.close()
        return result
    finally:
        shutil.rmtree(tmp)


class AptInstaller(object):
    def __init__(self, binary):
        self.bin = binary

    def install(self, packages, assume_yes=False):
        # Installs
        options = []
        if assume_yes:
            options.append('-y')
        returncode = subprocess.call([self.bin, 'install'] +
                                     options +
                                     [pkg.name for pkg in packages])
        if returncode != 0:
            return returncode

        # Checks package versions
        pkgs_dict = dict((pkg.name, pkg) for pkg in packages)
        p = subprocess.Popen(['dpkg-query',
                              '--showformat=${Package;-50}\t${Version}\n',
                              '-W'] +
                             [pkg.name for pkg in packages],
                             stdout=subprocess.PIPE)
        try:
            for l in p.stdout:
                fields = l.split()
                if len(fields) == 2:
                    name = fields[0].decode('ascii')
                    pkg = pkgs_dict.pop(name)
                    version = fields[1].decode('ascii')
                    if pkg.version != version:
                        sys.stderr.write("Warning: version %s of %s was "
                                         "installed, instead of %s\n" % (
                                             version, name, pkg.version))
                    logging.info("Installed %s %s (original: %s)" % (
                                 name, version, pkg.version))
        finally:
            p.wait()
        if pkgs_dict:
            sys.stderr.write("Error: some packages could not be installed:\n")
            for pkg in pkgs_dict.keys():
                sys.stderr.write("    %s\n" % pkg)
        assert p.returncode == 0

    def update_script(self):
        return '%s update' % self.bin

    def install_script(self, packages):
        return '%s install -y %s' % (self.bin,
                                     ' '.join(pkg.name for pkg in packages))


def select_installer(pack, runs):
    # Identifies current distribution
    distribution = platform.linux_distribution()[0].lower()

    orig_distribution = runs[0]['distribution'][0].lower()

    # Checks that the distributions match
    if set([orig_distribution, distribution]) == set(['ubuntu', 'debian']):
        # Packages are more or less the same on Debian and Ubuntu
        sys.stderr.write("Warning: Installing on %s but pack was generated on "
                         "%s\n" % (
                             distribution.capitalize(),
                             orig_distribution.capitalize()))
    elif orig_distribution != distribution:
        sys.stderr.write("Error: Installing on %s but pack was generated on %s"
                         "\n" % (
                             distribution.capitalize(),
                             orig_distribution.capitalize()))
        sys.exit(1)

    # Selects installation method
    if distribution == 'ubuntu':
        installer = AptInstaller('apt-get')
    elif distribution == 'debian':
        installer = AptInstaller('aptitude')
    else:
        sys.stderr.write("Your current distribution, \"%s\", is not "
                         "supported\n" % distribution.capitalize())
        sys.exit(1)

    return installer


def select_box(runs):
    distribution, version = runs[0]['distribution'][0].lower()
    architecture = runs[0]['architecture']

    if architecture not in ('i686', 'x86_64'):
        sys.stderr.write("Error: unsupported architecture %s\n" % architecture)

    # Ubuntu
    if distribution == 'ubuntu':
        if version != '12.04':
            sys.stderr.write("Warning: using Ubuntu 12.01 'Precise' instead "
                             "of '%s'\n" % version)
        if architecture == 'i686':
            return 'hashicorp/precise32'
        else:  # architecture == 'x86_64':
            return 'hashicorp/precise64'

    # Debian
    elif distribution != 'debian':
        sys.stderr.write("Warning: unsupported distribution %s, using Debian"
                         "\n" % distribution)
    if distribution == 'debian' and version != '7':
        sys.stderr.write("Warning: using Debian 7 'Jessie' instead of '%s'"
                         "\n" % version)
    if architecture == 'i686':
        return 'remram/debian-7.5-i386'
    else:  # architecture == 'x86_64':
        return 'remram/debian-7.5-amd64'


def installpkgs(args):
    pack = args.pack[0]

    # Loads config
    runs, packages, other_files = load_config(pack)

    installer = select_installer(pack, runs)

    # Installs packages
    r = installer.install(packages, assume_yes=args.assume_yes)
    if r != 0:
        sys.exit(r)


def makedir(path):
    if not os.path.exists(path):
        makedir(os.path.dirname(path))
        try:
            os.mkdir(path)
        except OSError:
            pass


def create_chroot(args):
    pack = args.pack[0]
    target = args.target[0]
    if os.path.exists(target):
        sys.stderr.write("Error: Target directory exists\n")
        sys.exit(1)

    # Loads config
    runs, packages, other_files = load_config(pack)

    os.mkdir(target)
    root = os.path.abspath(os.path.join(target, 'root'))
    os.mkdir(root)

    # Checks that everything was packed
    packages_not_packed = [pkg for pkg in packages if not pkg.packfiles]
    if packages_not_packed:
        sys.stderr.write("Error: According to configuration, some files were "
                         "left out because they belong to the following "
                         "packages:\n")
        sys.stderr.write(''.join('    %s\n' % pkg
                                 for pkg in packages_not_packed))
        sys.stderr.write("Will copy files from HOST SYSTEM\n")
        for pkg in packages_not_packed:
            for ff in pkg.files:
                for f in find_all_links(ff.path):
                    if not os.path.exists(f):
                        sys.stderr.write("Missing file %s (from package %s)"
                                         "\n" % (f, pkg.name))
                    dest = f
                    if dest[0] == '/':
                        dest = dest[1:]
                    dest = os.path.join(root, dest)
                    makedir(os.path.dirname(dest))
                    if os.path.islink(f):
                        os.symlink(os.readlink(f), dest)
                    else:
                        shutil.copy(f, dest)

    # Unpacks files
    tar = tarfile.open(pack, 'r:*')
    if any('..' in m.name for m in tar.getmembers()):
        sys.stderr.write("Error: Tar archive contains invalid pathnames\n")
        sys.exit(1)
    members = [m for m in tar.getmembers() if m.name.startswith('DATA/')]
    for m in members:
        m.name = m.name[5:]
    tar.extractall(root, members)
    tar.close()

    # Copies /bin/sh + dependencies
    fmt = re.compile(r'^\t(?:[^ ]+ => )?([^ ]+) \([x0-9a-z]+\)$')
    p = subprocess.Popen(['ldd', '/bin/sh'], stdout=subprocess.PIPE)
    try:
        for l in p.stdout:
            l = l.decode('ascii')
            m = fmt.match(l)
            f = m.group(1)
            if not os.path.exists(f):
                continue
            dest = f
            if dest[0] == '/':
                dest = dest[1:]
            dest = os.path.join(root, dest)
            makedir(os.path.dirname(dest))
            shutil.copy(f, dest)
    finally:
        p.wait()
    assert p.returncode == 0
    makedir(os.path.join(root, 'bin'))
    shutil.copy('/bin/sh', os.path.join(root, 'bin/sh'))

    # Makes sure all the directories used as working directories exist
    # (they already do if files from them are used, but empty directories do
    # not get packed inside a tar archive)
    for directory in list_directories(pack):
        makedir(os.path.join(root, directory[1:]))

    # Writes start script
    with open(os.path.join(target, 'script.sh'), 'w') as fp:
        fp.write('#!/bin/sh\n\n')
        for run in runs:
            cmd = "cd %s && " % shell_escape(run['workingdir'])
            # FIXME : Use exec -a or something if binary != argv[0]
            cmd += ' '.join(
                    shell_escape(a)
                    for a in [run['binary']] + run['argv'][1:])
            fp.write('chroot --userspec=1000 %s /bin/sh -c %s\n' % (
                     shell_escape(root),
                     shell_escape(cmd)))

    print("Experiment set up, run %s to start" % (
          os.path.join(target, 'script.sh')))


def create_vagrant(args):
    pack = args.pack[0]
    target = args.target[0]
    if os.path.exists(target):
        sys.stderr.write("Error: Target directory exists\n")
        sys.exit(1)

    # Loads config
    runs, packages, other_files = load_config(pack)

    installer = select_installer(pack, runs)
    box = select_box(runs)

    os.mkdir(target)

    # Writes setup script
    with open(os.path.join(target, 'setup.sh'), 'w') as fp:
        fp.write('#!/bin/sh\n\n')
        # Makes sure the start script is executable
        fp.write('chmod +x script.sh\n\n')
        # Updates package sources
        fp.write(installer.update_script())
        fp.write('\n')
        # Installs necessary packages
        fp.write(installer.install_script(packages))
        fp.write('\n\n')
        # TODO : Compare package versions (painful because of sh)
        # Untar
        fp.write('cd /\n')
        fp.write('tar zxf /vagrant/experiment.rpz --strip=1 %s\n' % ' '.join(
                 shell_escape(f.path) for f in other_files))

    # Copies pack
    shutil.copyfile(pack, os.path.join(target, 'experiment.rpz'))

    # Writes start script
    with open(os.path.join(target, 'script.sh'), 'w') as fp:
        fp.write('#!/bin/bash\n\n')
        for run in runs:
            fp.write('cd %s\n' % shell_escape(run['workingdir']))
            # FIXME : Use exec -a or something if binary != argv[0]
            fp.write('%s\n' % ' '.join(
                     shell_escape(a)
                     for a in [run['binary']] + run['argv'][1:]))

    # Writes Vagrant file
    with open(os.path.join(target, 'Vagrantfile'), 'w') as fp:
        # Vagrant header and version
        fp.write('# -*- mode: ruby -*-\n'
                 '# vi: set ft=ruby\n\n'
                 'VAGRANTFILE_API_VERSION = "2"\n\n'
                 'Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|\n')
        # Selects which box to install
        fp.write('  config.vm.box = "%s"\n' % box)
        # Run the setup script on the virtual machine
        fp.write('  config.vm.provision "shell", path: "setup.sh"\n')

        fp.write('end\n')

    if not target:
        target_dir = './'
    elif target.endswith('/'):
        target_dir = target
    else:
        target_dir = target + '/'
    print("Vagrantfile ready\n"
          "Create the virtual machine by running 'vagrant up' from %s\n"
          "Then, ssh into it (for example using 'vagrant ssh') and run "
          "'sh script.sh'" % target_dir)

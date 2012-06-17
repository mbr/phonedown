#!/usr/bin/env python

import argparse
import os
from itertools import cycle
from multiprocessing import Pool, cpu_count, Queue
from Queue import Empty
import signal
import subprocess
import sys

from mutagen.flac import FLAC
from mutagen import File


status_queue = Queue()


def folder(v):
    if not os.path.exists(v):
        raise ValueError('Does not exist: %s' % v)

    if not os.path.isdir(v):
        raise ValueError('Not a directory: %s' % v)

    return os.path.abspath(v)

parser = argparse.ArgumentParser()
parser.add_argument('source_folder', type=folder)
parser.add_argument('dest_folder', type=folder)
parser.add_argument('-e', '--extensions', nargs='+', default=['.flac'])
parser.add_argument('-p', '--pool-size', type=int,
                    default=2 * cpu_count())
parser.add_argument('lame_options', nargs=argparse.REMAINDER)
parser.add_argument('--no-mp3gain', action='store_false', dest='apply_mp3gain',
                    default=True)
parser.add_argument('--lame', default='lame')
parser.add_argument('--flac', default='flac')
parser.add_argument('--mp3gain', default='mp3gain')


def convert_file(args, full_path):
    try:
        rel_path = os.path.relpath(full_path, args.source_folder)
        base, ext = os.path.splitext(rel_path)
        out_path = os.path.join(args.dest_folder, base + '.mp3')

        lame_options = args.lame_options or ['--preset', 'standard', '-h']

        metadata = FLAC(full_path)

        try:
            os.makedirs(os.path.dirname(out_path))
        except OSError, e:
            if e.errno != 17:
                raise  # only raise if not "file exists" error

        flac_p = subprocess.Popen([args.flac, '-s', '-d', '--stdout',
                                  full_path],
                                  stdout=subprocess.PIPE,
                                  preexec_fn=ignore_sigint)
        lame_cmd = [args.lame] + lame_options + ['--quiet', '-', out_path]
        lame_p = subprocess.Popen(lame_cmd, stdin=flac_p.stdout,
                                  preexec_fn=ignore_sigint)

        flac_p.wait()
        lame_p.wait()

        # now apply gain
        if args.apply_mp3gain:
            mp3gain_cmd = [args.mp3gain, '-q', '-T', '-r', out_path]

            subprocess.check_call(mp3gain_cmd, stdout=open('/dev/null', 'wb'))

        # finally, correct the tags
        id3data = File(out_path, easy=True)
        for attr in ('title', 'artist', 'album', 'date',
                     'genre', 'tracknumber'):
            id3data[attr] = metadata.get(attr)
        id3data.save()
    except Exception, e:
        status_queue.put('ERROR: %r (%s)' % (e, out_path))
        if os.path.exists(out_path):
            os.unlink(out_path)
    else:
        status_queue.put('OK: %s' % out_path)


def list_files(args):
    for dirpath, dirnames, filenames in os.walk(args.source_folder):
        for fn in filenames:
            full_path = os.path.join(dirpath, fn)
            root, ext = os.path.splitext(full_path)
            if not ext in args.extensions:
                # ignore unknown extensions
                continue

            yield args, full_path


def _convert_file_args(args):
    return convert_file(*args)


def ignore_sigint():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


if __name__ == '__main__':
    args = parser.parse_args()

    print "Converting from %s to %s" % (args.source_folder, args.dest_folder)
    print "Pool size", args.pool_size

    pool = Pool(args.pool_size, ignore_sigint)
    total = 0

    try:
        res = pool.map_async(_convert_file_args, list_files(args))

        for c in cycle(('-', '\\', '|', '/')):
            sys.stdout.write(c)
            sys.stdout.flush()
            res.wait(0.1)
            sys.stdout.write('\b')
            try:
                while True:
                    sys.stdout.write(status_queue.get_nowait())
                    sys.stdout.write('\n')
                    sys.stdout.flush()
            except Empty:
                pass

            if res.ready():
                break

    except KeyboardInterrupt:
        print >>sys.stderr, "exiting..."
        pool.terminate()
        pool.join()
        print "done"

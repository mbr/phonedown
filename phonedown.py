#!/usr/bin/env python

import argparse
import os
from itertools import cycle
from multiprocessing import Pool, cpu_count, Queue
from queue import Empty
import signal
import subprocess
import sys

import click
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
parser.add_argument('-p', '--pool-size', type=int, default=1 + cpu_count())
parser.add_argument('lame_options', nargs=argparse.REMAINDER)
parser.add_argument('--no-mp3gain',
                    action='store_false',
                    dest='apply_mp3gain',
                    default=True)
parser.add_argument('--no-skip',
                    action='store_false',
                    dest='skip_existing',
                    default=True)
parser.add_argument('--lame', default='lame')
parser.add_argument('--flac', default='flac')
parser.add_argument('--mp3gain', default='mp3gain')


def get_out_path(args, full_path):
    rel_path = os.path.relpath(full_path, source_folder)
    base, ext = os.path.splitext(rel_path)
    out_path = os.path.join(dest_folder, base + '.mp3')

    return out_path


def convert_file(args, full_path):
    try:
        out_path = get_out_path(args, full_path)

        lame_options = args.lame_options or ['--preset', 'standard', '-h']

        metadata = FLAC(full_path)

        try:
            os.makedirs(os.path.dirname(out_path))
        except OSError as e:
            if e.errno != 17:
                raise  # only raise if not "file exists" error

        flac_p = subprocess.Popen(
            [args.flac, '-s', '-d', '--stdout', full_path],
            stdout=subprocess.PIPE,
            preexec_fn=ignore_sigint)
        lame_cmd = [args.lame] + lame_options + ['--quiet', '-', out_path]
        lame_p = subprocess.Popen(lame_cmd,
                                  stdin=flac_p.stdout,
                                  preexec_fn=ignore_sigint)

        flac_p.wait()
        lame_p.wait()

        # now apply gain
        if args.apply_mp3gain:
            mp3gain_cmd = [args.mp3gain, '-q', '-T', '-r', '-k', out_path]

            subprocess.check_call(mp3gain_cmd, stdout=open('/dev/null', 'wb'))

        # finally, correct the tags
        id3data = File(out_path, easy=True)
        for attr in ('title', 'artist', 'album', 'date', 'genre',
                     'tracknumber'):
            id3data[attr] = metadata.get(attr)
        id3data.save()
    except Exception as e:
        status_queue.put(('ERROR', full_path, str(e)))
        if os.path.exists(out_path):
            os.unlink(out_path)
    else:
        status_queue.put(('OK', full_path, out_path))


def list_files(source_folder, skip_existing, extensions):
    for dirpath, dirnames, filenames in os.walk(source_folder):
        for fn in filenames:
            full_path = os.path.join(dirpath, fn)
            root, ext = os.path.splitext(full_path)
            if ext not in extensions:
                # ignore unknown extensions
                continue

            if args.skip_existing and\
               os.path.exists(get_out_path(args, full_path)):
                continue

            yield args, full_path


def _convert_file_args(args):
    return convert_file(*args)


def ignore_sigint():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class PhoneDown(object):
    def __init__(self, source_folder, dest_folder, extensions, pool_size,
                 apply_mp3gain, skip_existing, lame, flac, mp3gain):
        # FIXME: lame_options
        lame_options = []

        sizes = {}
        total_size = 0
        bytes_processed = 0

        for _, full_path in list_files(args):
            filesize = os.stat(full_path).st_size
            sizes[full_path] = filesize
            total_size += filesize

        print("Converting from %s to %s" % (source_folder, dest_folder))

        if not sizes:
            print("Nothing to be done")
            sys.exit(0)

        print("Using %d workers to process %.2fM" %
              (args.pool_size, total_size / (1024 * 1024)))

        pool = Pool(args.pool_size, ignore_sigint)

        try:
            res = pool.map_async(_convert_file_args, list_files(args))
            # pbar = progressbar.ProgressBar(widgets=[
            #     'Encoding: ', progressbar.AnimatedMarker(), progressbar.Percentage(
            #     ), ' ', progressbar.Bar(marker='*'), ' ', progressbar.ETA(
            #     ), ' ', progressbar.FileTransferSpeed()
            # ],
            #                                maxval=total_size).start()

            for c in cycle(('-', '\\', '|', '/')):
                res.wait(0.1)
                try:
                    while True:
                        status, filename, info = status_queue.get_nowait()
                        if 'ERROR' == status:
                            print("ERROR: %s (%s)" % (info, filename),
                                  file=sys.stderr)

                        bytes_processed += sizes[filename]
                        # pbar.update(bytes_processed)
                except Empty:
                    pass

                if res.ready():
                    # pbar.finish()
                    break

                # pbar.update()

        except KeyboardInterrupt:
            print("exiting...", file=sys.stderr)
            pool.terminate()
            pool.join()
            print("done", file=sys.stderr)


@click.command()
@click.argument('source_folder')
@click.argument('dest_folder')
@click.option('--extensions',
              '-e',
              multiple=True,
              default=('.flac', ),
              help='Extension of files to convert, may be given multiple '
              'times (default: .flac)')
@click.option('--pool-size',
              '-p',
              type=int,
              default=1 + cpu_count(),
              help='Number of worker processes (default: # cores + 1)')
@click.option('--mp3gain/--no-mp3gain',
              'apply_mp3gain',
              default=True,
              help='Enable/disable mp3 gain (default: enabled)')
@click.option('--skip/--no-skip',
              'skip_existing',
              default=True,
              help='Skip already processed files (default: enabled)')
@click.option('--lame',
              default='lame',
              help='Override lame binary (default: "lame")')
@click.option('--flac',
              default='flac',
              help='Override flac binary (default: "flac")')
@click.option('--mp3gain',
              default='mp3gain',
              help='Override mp3gain binary (default: "mp3gain")')
def cli(*args, **kwargs):
    PhoneDown(*args, **kwargs).run()


if __name__ == '__main__':
    cli()

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


def ignore_sigint():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class PhoneDown(object):
    def __init__(self, source_folder, dest_folder, extensions, pool_size,
                 apply_mp3gain, skip_existing, lame, flac, mp3gain):
        self.lame_options = []

        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.extensions = extensions
        self.pool_size = pool_size
        self.apply_mp3gain = apply_mp3gain
        self.skip_existing = skip_existing

        self.lame = lame
        self.flac = flac
        self.mp3gain = mp3gain

    def list_files(self):
        for dirpath, dirnames, filenames in os.walk(self.source_folder):
            for fn in filenames:
                full_path = os.path.join(dirpath, fn)
                root, ext = os.path.splitext(full_path)
                if ext not in self.extensions:
                    # ignore unknown extensions
                    continue

                if self.skip_existing and os.path.exists(self.get_out_path(
                        full_path)):
                    continue

                yield full_path

    def get_out_path(self, full_path):
        rel_path = os.path.relpath(full_path, self.source_folder)
        base, ext = os.path.splitext(rel_path)
        out_path = os.path.join(self.dest_folder, base + '.mp3')

        return out_path

    def convert_file(self, full_path):
        try:
            out_path = self.get_out_path(full_path)
            lame_options = self.lame_options or ['--preset', 'standard', '-h']

            metadata = FLAC(full_path)

            try:
                os.makedirs(os.path.dirname(out_path))
            except OSError as e:
                if e.errno != 17:
                    raise  # only raise if not "file exists" error

            flac_p = subprocess.Popen(
                [self.flac, '-s', '-d', '--stdout', full_path],
                stdout=subprocess.PIPE,
                preexec_fn=ignore_sigint)
            lame_cmd = [self.lame] + lame_options + ['--quiet', '-', out_path]
            lame_p = subprocess.Popen(lame_cmd,
                                      stdin=flac_p.stdout,
                                      preexec_fn=ignore_sigint)

            flac_p.wait()
            lame_p.wait()

            # now apply gain
            if self.apply_mp3gain:
                mp3gain_cmd = [self.mp3gain, '-q', '-T', '-r', '-k', out_path]

                subprocess.check_call(mp3gain_cmd,
                                      stdout=open('/dev/null', 'wb'))

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

    def run(self):
        sizes = {}
        total_size = 0
        bytes_processed = 0

        for full_path in self.list_files():
            filesize = os.stat(full_path).st_size
            sizes[full_path] = filesize
            total_size += filesize

        print("Converting from %s to %s" % (self.source_folder,
                                            self.dest_folder))

        if not sizes:
            print("Nothing to be done")
            sys.exit(0)

        print("Using %d workers to process %.2fM" %
              (self.pool_size, total_size / (1024 * 1024)))

        pool = Pool(self.pool_size, ignore_sigint)

        try:
            res = pool.map_async(self.convert_file, self.list_files())
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
@click.argument('source_folder',
                type=click.Path(exists=True,
                                dir_okay=True,
                                file_okay=False))
@click.argument('dest_folder', type=click.Path(dir_okay=True, file_okay=False))
@click.option('--extensions',
              '-e',
              multiple=True,
              default=['.flac'],
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

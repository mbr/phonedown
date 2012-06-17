Phonedown
*********

This is a small tool that converts my .flac collection to small MP3s suitable
for copying onto the non-expandable memory of my phone (where it gets
  afterwards via `Dropbox <http://dropbox.com>`_.

It uses the lame, flac and mp3gain commandline utilities and the libraries
``progressbar`` and ``mutagen``.

Features:

* Speedy (using ``multiprocessing`` to parallelize work)
* skips already converted tracks
* hard-normalizes mp3 volumes through mp3gain
* lame options fully configurable

Example usage:
--------------
::

    $ phonedown.py path/to/flac/folder output/folder

If your music library is rather large, you may want to alter some `LAME
<http://lame.sourceforge.net/>`_ options:

::

    $ phonedown.py path/to/flac/folder output/folder --preset medium

Try ``phonedown.py --help`` for more options.

#!/bin/sh
set -e
set -x
make
#scp art.py amahl.fi:~/news.amahl.fi/art.py
#scp zh-news/zh-articles.css amahl.fi:~/news.amahl.fi/zh-news/zh-articles.css
rsync -azivcR --skip-compress=jpg/webp/png/gif/mp4/gz/bz2 -e ssh --rsync-path=~/bin/rsync $(cat rsync.lst) amahl.fi:~/news.amahl.fi/


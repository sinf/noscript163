#!/bin/sh
if [ -z "$UPLOAD_STUFF_TO" ]; then
	echo "Set UPLOAD_STUFF_TO environment variable (sshhost:/path/to/dir)"
	exit 1
fi
set -e
set -x
ND=z
make
#scp art.py $UPLOAD_STUFF_TO/art.py
#scp $ND/zh-articles.css $UPLOAD_STUFF_TO/$ND/zh-articles.css
rsync -azivcR --skip-compress=jpg/webp/png/gif/mp4/gz/bz2 -e ssh --rsync-path=~/bin/rsync $(cat rsync.lst) $UPLOAD_STUFF_TO/


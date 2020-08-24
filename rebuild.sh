#!/bin/sh
set -x
ND=z

find $ND -maxdepth 2 -type f -name '[0-9]*.xhtml' -delete
find $ND/????-??/ -type f -name '*.html' -delete
#rm -rf $ND/????-??/img
#rm -rf $ND/????-??/img0
rm -f $ND/last.xhtml $ND/$ND.db
rm -f $ND/*.xhtml

c=""
if [ -f local.json ]; then c="-clocal.json"; fi

for f in $(echo $ND/news_* | tr ' ' '\n' | sort -n); do
	./art.py -f -m "$f" "$c" $*
done


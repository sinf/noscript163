#!/bin/sh
set -x
ND=z
rm -f $ND/last.xhtml $ND/zh-news.db $ND/*.xhtml $ND/*.xhtml.gz
c=''
if [ -f local.json ]; then c=-clocal.json; fi
if [ -f config.json ]; then c=-cconfig.json; fi
./art.py $c -f -r $*


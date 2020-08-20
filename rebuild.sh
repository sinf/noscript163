#!/bin/sh
set -x

find zh-news -maxdepth 2 -type f -name '[0-9]*.xhtml' -delete
find zh-news/????-??/ -type f -name '*.html' -delete
#rm -rf zh-news/????-??/img
#rm -rf zh-news/????-??/img0
rm -f zh-news/last.xhtml zh-news/zh-news.db
rm -f zh-news/*.xhtml

c=""
if [ -f local.json ]; then c="-clocal.json"; fi

for f in $(echo zh-news/news_* | tr ' ' '\n' | sort -n); do
	./art.py -f -m "$f" "$c" $*
done


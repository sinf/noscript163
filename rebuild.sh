#!/bin/sh
set -x

find zh-news -maxdepth 2 -type f -name '[0-9]*.xhtml' -delete
find zh-news/????-??/ -type f -name '*.html' -delete
#rm -rf zh-news/????-??/img
#rm -rf zh-news/????-??/img0
rm -f zh-news/last.xhtml zh-news/zh-news.db

for f in $(echo zh-news/news_* | tr ' ' '\n' | sort -n); do
	./art.py -f -m "$f" $*
done


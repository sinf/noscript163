.PHONY: all clean clean-img distclean view

all: news.tar.bz2

news.tar.bz2: zh-articles.css art.py
	tar cjvf $@ $^

%.css: %.scss
	sass $< --sourcemap=none -E utf-8 --unix-newlines -C -t compact $@
	cp -lfv $@ zh-news/zh-articles.css

clean:
	find zh-news/ \( -name '[0-9]+.html' -o -name '*.xhtml' -o -name '*.gz' \) -delete -print
	find zh-news/ -mindepth 2 -type f -name '*.html' -delete -print
	rm -fv zh-news/zh-news.db

view:
	firefox ./zh-news/last.xhtml

clean-img:
	rm -rfv zh-news/*/img

distclean:
	rm -rv zh-news


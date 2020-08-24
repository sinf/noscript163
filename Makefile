.PHONY: all clean clean-img distclean view testsetup

ND:=z

all: news.tar.bz2

news.tar.bz2: $(ND)/zh-articles.css art.py
	tar cjvf $@ $^

$(ND)/%.css: %.scss
	sass $< --sourcemap=none -E utf-8 --unix-newlines -C -t compact $@

view:
	firefox ./$(ND)/last.xhtml

distclean:
	rm -rv $(ND)


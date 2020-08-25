.PHONY: all distclean view re re-img dirs update

ND:=z

all: $(ND)/zh-articles.css

release.tar.bz2: $(ND)/zh-articles.css $(ND)/favicon.gif art.py local.json
	tar cjvf $@ $^

$(ND)/%.css: %.scss
	sass $< --sourcemap=none -E utf-8 --unix-newlines -C -t compact $@

view:
	firefox ./$(ND)/last.xhtml

distclean:
	rm -rv $(ND)

re:
	rm -f $(ND)/zh-news.db $(ND)/*.xhtml $(ND)/*.xhtml.gz
	./art.py -c config.json -f -r

re-img:
	rm -f $(ND)/zh-news.db $(ND)/*.xhtml $(ND)/*.xhtml.gz
	rm -rf $(ND)/????-??/img
	./art.py -c config.json -f -r -R

update:
	./art.py -c config.json -f


.PHONY: all nuke view re re-img push

ifeq ($(UPLOAD_STUFF_TO),'')
$(error "Set UPLOAD_STUFF_TO environment variable (sshhost:/path/to/www)")
endif

ND:=z
DISTFILES:=$(addprefix $(ND),zh-articles.css favicon.gif) art.py

all: $(ND)/zh-articles.css

release.tar.bz2: $(DISTFILES)
	tar cjvf $@ $^

$(ND)/%.css: %.scss
	sass $< --sourcemap=none -E utf-8 --unix-newlines -C -t compact $@

view:
	firefox ./$(ND)/main.xhtml

nuke:
	rm -rv $(ND)

re:
	rm -f $(ND)/zh-news.db $(ND)/*.xhtml $(ND)/*.xhtml.gz
	./art.py -c config.json -f -r

re-img:
	rm -f $(ND)/zh-news.db $(ND)/*.xhtml $(ND)/*.xhtml.gz
	rm -rf $(ND)/????-??/img
	./art.py -c config.json -f -r -R

push: $(DISTFILES)
	rsync -azivcR --skip-compress=jpg/webp/png/gif/mp4/gz/bz2 -e ssh --rsync-path=~/bin/rsync $(DISTFILES) $(UPLOAD_STUFF_TO)/

push1: art.py
	scp art.py $(UPLOAD_STUFF_TO)/art.py


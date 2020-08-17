#!/usr/bin/env python2.7
#-*- encoding: utf-8 -*-
from __future__ import print_function

# Chinese news article aggregator script
# downloads articles, removes javascript etc.. crap
# and outputs a reformatted static news website
# Licensed under GPL v3
# Arho Mahlamaki, 2020

cfg={
# local filesystem path where things are stored
	'WEB_ROOT':'.',

# filename (under WEB_ROOT/ARTICLES/)
# of a copy of the most recent index page
	'LAST_PAGE_ALIAS':'last.xhtml',

#	relative to WEB_ROOT
# index files are called WEB_ROOT/ARTICLES/idx%d.html
# and articles:
# WEB_ROOT/ARTICLES/YYYY-MM/(*.xhtml,*.webp)
	'ARTICLES':'zh-news',

# url that returns to front page or whatever
	'BACK':'/main.html',

# how many articles per index page
	'INDEX_BATCH':20,

# if we want to keep source images (may eat up server hdd)
	'SAVE_IMG_SRC':False,

# if we want .html articles
	'SAVE_HTML':True,

# if we want .html.gz articles
	'SAVE_HTML_GZ':True,

# if we want to write info .txt for later re-downloading of higher resolution image
	'SAVE_IMG_INFO':True,

# all index documents include this in their <head>
	'HEAD_INDEX': u'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Type" content="application/xhtml+xml;charset=UTF-8"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, shrink-to-fit=no"/>
<link rel="stylesheet" type="text/css" href="zh-articles.css"/>
'''.encode('utf-8'),

# and all article documents include this
	'HEAD_ARTICLE': u'''<html lang="zh">
<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Type" content="application/html;charset=UTF-8"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, shrink-to-fit=no"/>
<link rel="stylesheet" type="text/css" href="../zh-articles.css"/>
'''.encode('utf-8'),
}

import urllib2
import re
import json
import os
import time
import sqlite3
import xml.etree.ElementTree as ET

def the_dir(path):
	wr=os.environ.get('WEB_ROOT',cfg['WEB_ROOT'])
	return os.path.join(wr, path)

def art_dir(path):
	return os.path.join(cfg['ARTICLES'],path)

def the_art_dir(path):
	return the_dir(art_dir(path))

def GET(url):
	print('GET', url)
	agent='Mozilla/5.0 (Windows NT 6.1; Win64; x64)'
	req=urllib2.Request(url,headers={'User-Agent':agent})
	r = urllib2.urlopen(req)
	html=r.read()
	r.close()
	return html

def make_dir(d):
	if len(d) and not os.path.isdir(d):
		print('Create directory:', d)
		os.makedirs(d)

def cached(path, func):
	make_dir(os.path.dirname(path))
	if os.path.exists(path):
		print('use cached:',path)
		with open(path,'rb') as f:
			data=f.read()
	else:
		data=func()
		with open(path,'wb') as f:
			f.write(data)
	return data

def scanJ(html, r):
	m=re.search(r, html, re.M|re.I)
	if m is None:
		raise Exception('failed to parse main page, regex'+r)
	return json.loads(m.group(1))

def S(x):
	if type(x) is unicode:
		return x.encode('utf-8')
	return x

class Article:
	def __init__(self, item):
		""" item needs to have
		link : url to some .html file
		ptime : YYYY-MM-DD HH:MM:SS
		title or docid (optional)
		digest (optional)
		"""
		self.j=item
		self.docid=S(self.j['docid'])
		self.src_url = S(item['link'])
		if '?' in self.src_url:
			self.src_url = self.src_url[:self.src_url.find('?')]
		self.title=S(item.get('title',self.docid))
		# digest: truncated description
		self.desc=S(item.get('digest','no description'))
		self.origin=S(u'3g.163.com 手机网易网')
		self.bname=self.docid+'.html'
		self.date=time.strptime(item['ptime'], '%Y-%m-%d %H:%M:%S')
		self.dir_ym = time.strftime('%Y-%m',self.date)
		self.dstdir_r = art_dir(self.dir_ym)
		self.dstdir=the_dir(self.dstdir_r)
		self.dstpath=os.path.join(self.dstdir,self.bname)
		# how this is addressed from index pages
		self.idx_url = self.dir_ym + '/' + self.bname
		self.back_url=None
	
	def exists(self):
		return os.path.exists(self.dstpath)
	
	def fix_img(self,m):
		src=m.group(1)
		data_src=m.group(2)
		tailer=m.group(3)
		if src.startswith('javascript:'):
			print('rejecting javascript img hack:', src)
			return ''
		bn=os.path.basename(src)
		if bn[-4:].lower() not in ('.jpg','.gif','.png'):
			print('rejecting image because of unknown suffix:', bn[-4:])
			return ''
		org=os.path.join(self.dstdir, 'img0', bn)
		bn2=re.sub('(\..{1,4})$','.webp',bn)
		dst=os.path.join(self.dstdir, 'img', bn2)
		url=os.path.join('img', bn2)
		if not os.path.exists(dst):
			make_dir(os.path.dirname(dst))
			cached(org, lambda: GET(src))
			os.system('convert '+org+" -resize 400000@ -quality 25 "+dst)
			if not cfg['SAVE_IMG_SRC']:
				os.remove(org)
			if cfg['SAVE_IMG_INFO']:
				with open(org+'.txt','w') as f:
					f.write(src+'\n')
					f.write(data_src+'\n')
					f.write(tailer+'\n')
			print('Write image', dst)
		s='<img src="' + url + '"/>'
		if '<script' not in tailer:
			s += tailer
		return s
	
	def fetch(self):
		make_dir(self.dstdir)
		self.src_html=cached(self.dstpath+'.in', \
			lambda:GET(self.src_url))
	
	def write_html(self):
		html=self.src_html

		de=re.search('<meta\s+name="description"\s+content="([^"]+)"\s*/?>', html)
		if de is not None:
			# upgrade to the real description
			self.desc=de.group(1)

		# dig out the article
		m=re.search('<article[^>]*>.*</article>', html, re.I|re.S)
		if m is None:
			print('failed to get article', self.docid)
			return None

		body=m.group(0)

		# preserve image tags
		body=re.sub('<a href="(.*?)">\s*<img.*?data-src="(.*?)"\s*>(.*?)</a>', lambda m: self.fix_img(m), body, flags=re.M|re.S)

		# todo: video
		body=re.sub('<div class="video">.*?</div>','',body, flags=re.M|re.S)
		
		# cheap attempt at minifying it
		body=re.sub('[ \t]+',' ',body)
		body=re.sub('[ \t]*[\n\r]+[ \t]*','\n',body)

		# remove Notice: the content..NetEase..blahblah
		body=re.sub('<p>特别声明.*?</p>','',body)
		body=re.sub('<p class="statement-en".*?</p>','',body)

		# safety
		noscript='<!--SCRIPT REMOVED-->'
		body=re.sub('<\s*script.*?script\s*/?>',noscript,body)
		body=re.sub('<\s*script.*',noscript,body)

		print('write article:', self.dstpath)

		s=self.header()
		s+=body
		s+=self.footer()
		s=S(s)

		if cfg['SAVE_HTML']:
			with open(self.dstpath,'wb') as f:
				f.write(s)
		if cfg['SAVE_HTML_GZ']:
			import gzip
			with gzip.open(self.dstpath+'.gz','wb') as f:
				f.write(s)
	
	def header(self):
		h=cfg['HEAD_ARTICLE'] \
+ '<title>' + self.title +'</title>\n' \
+ '<meta name="description" content="' \
+ self.desc + '"/>\n' \
+ '</head>\n<body>\n'
		h+=self.make_back_url()
		return h
	
	def make_back_url(self):
		if not self.back_url:
			return ''
		h='<nav>'
		h+='<a class="zh-ret" href="'+self.back_url+'">'
		h+='Return to index'
		h+='</a>\n'
		h+='</nav>'
		return h

	def footer(self):
		return self.make_back_url()+'</body>\n</html>\n'

class IndexPage:
	def __init__(self, basename):
		title=time.strftime('Chinese news %Y-%m-%d')
		self.sib_url=basename
		self.filepath=the_art_dir(basename)
		self.next=None
		self.prev=None
		self.ns='{http://www.w3.org/1999/xhtml}'
		self.et=ET.ElementTree( \
		ET.fromstring(cfg['HEAD_INDEX']+\
	'<title>' + title + '''</title>
<meta name="author" content="ArhoM"/>
<meta name="description" content="Aggregated script-free chinese news"/>
</head><body>
<nav><ul>
<li><a href="'''+cfg['BACK']+'''">Main site</a></li>
<li><a href="'''+cfg['LAST_PAGE_ALIAS']+'''">Most recent</a></li>
<li><a class="prev" href="#">Previous page</a></li>
<li><a class="next" href="#">Next page</a></li>
</ul></nav>
<div class="main-content"></div>
<nav><ul>
<li><a href="'''+cfg['BACK']+'''">Main site</a></li>
<li><a href="'''+cfg['LAST_PAGE_ALIAS']+'''">Most recent</a></li>
<li><a class="prev" href="#">Previous page</a></li>
<li><a class="next" href="#">Next page</a></li>
</ul></nav>
<br/><br/><br/>
</body></html>'''))
		self.load()
		self.body=self.et.find(".//"+self.ns+"body")
		if self.body is None:
			raise Exception('oops. no body')
		print('Index page',self.filepath,'(%d)'%self.count())
	
	def load(self):
		if os.path.exists(self.filepath):
			self.et=ET.parse(self.filepath)
			return True
		return False
	
	def count(self):
		# namespace crap always works differently. fuckin xpath
		a=self.et.findall(".//"+self.ns+"div[@class='article-ref']")
		b=self.body.findall(".//div[@class='article-ref']")
		c=self.body.findall(".//"+self.ns+"div[@class='article-ref']")
		return max((len(a),len(b),len(c)))
	
	def has(self, url):
		return self.body.find(".//div[@class='article-ref']//a[@class='local'][@href='"+url+"']") is not None
	
	def store(self, art):
		if self.has(art.idx_url):
			print('Index already has', art.idx_url)
			return
		code=\
'<div class="article-ref">\n' +\
'<a class="local" href="'+art.idx_url+'">\n' +\
'<h2 class="title">' + art.title + '</h2>\n' +\
'<p class="desc">' + art.desc + '</p>\n' +\
'</a>\n' +\
'<span class="date">'+ time.strftime('%Y-%m-%d %H:%M:%S',art.date)+ '</span>\n' +\
'<a class="origin" href="'+art.src_url+'">Source: '+art.origin+'</a>\n'+\
'</div>'
		a=ET.fromstring(code)
		pgc=self.body.find(self.ns+"div[@class='main-content']")
		assert pgc is not None
		pgc.append(a)
		print('Index page',self.filepath,'(%d)'%self.count())
	
	def set_ref(self, c, url):
		aa=self.body.findall('.//'+self.ns+"a[@class='"+c+"']")
		assert aa is not None
		assert len(aa) > 0
		if aa is not None:
			for a in aa:
				a.attrib['href'] = url
	
	def save(self, r=1):
		if self.count() < 1:
			return
		if self.prev:
			self.prev.set_ref('next',self.sib_url)
			self.set_ref('prev',self.prev.sib_url)
			if r>0:
				self.prev.save(r-1)
		print('Write index page',self.filepath)
		with open(self.filepath,'w') as f:
			f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
			f.write('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n')
			self.et.write(f,encoding='utf-8', xml_declaration=False)

			#default_namespace='{http://www.w3.org/1999/xhtml}')

class Indexer:
	def __init__(self):
		sq_path=the_art_dir('zh-news.db')
		make_dir(os.path.dirname(sq_path))
		self.sq = sqlite3.connect(sq_path)
		self.sq.text_factory = str #utf hack
		self.sqc = self.sq.cursor()
		self.sqc.execute( \
'CREATE TABLE IF NOT EXISTS articles \
(date TEXT, title TEXT, desc TEXT, html_path TEXT, src_url TEXT, origin TEXT)')
		self.sqc.execute( \
'CREATE TABLE IF NOT EXISTS indexes \
(id INTEGER PRIMARY KEY, date TEXT, html_path TEXT)')
		rows = self.sqc.execute( \
'SELECT * FROM indexes ORDER BY id DESC LIMIT 2;'\
			).fetchall()
		if rows is None or len(rows)==0:
			self.next_id = 1
			self.page=None
			self.new_page()
		else:
			self.next_id = rows[0][0] + 1
			self.page = IndexPage(rows[0][2])
			if len(rows)>1:
				prev=IndexPage(rows[1][2])
				prev.next=self.page
				self.page.prev=prev
	
	def new_page(self):
		i=self.next_id
		p=str(i)+'.xhtml'
		prev=self.page
		self.page = IndexPage(p)
		if prev:
			prev.next=self.page
			self.page.prev=prev
		self.next_id += 1
		self.sqc.execute('INSERT INTO indexes VALUES (?,?,?)', (i, time.strftime('%Y-%m-%d'), p))
		self.sq.commit()
	
	def put(self, art):
		self.sqc.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', (
			time.strftime('%Y-%m-%d %H:%M:%S',art.date),
			art.title,
			art.desc,
			art.idx_url,
			art.src_url,
			art.origin,
		))
		self.sq.commit()
		self.page.store(art)
		if self.page.count() >= cfg['INDEX_BATCH']:
			self.page.save()
			self.new_page()

	def done(self):
		self.page.save()
		self.sqc.close()
		self.sq.commit()
	
	def article_back_ref(self):
		return '../' + self.page.sib_url

def main():
	
	ET.register_namespace('','http://www.w3.org/1999/xhtml')

	fp_url='https://3g.163.com/touch/news/'
	fp_cache=the_art_dir(time.strftime('news_163-%Y-%m-%d.html'))
	frontpage = cached(fp_cache, lambda u=fp_url:GET(u))

	# Fetch single-line json array from front page
	# difference between topicData and channelData?
	#topicData = scanJ(frontpage, r'^ *var *topicData *= *(.*);$')
	chanData = scanJ(frontpage, r'^ *var *channelData *= *(.*);$')
	items=[]

	items+=chanData['listdata']['data']
	#items+=chanData['topdata']['data']
	#for cat,xx in topicData['data'].items(): items+=xx;

	idx = Indexer()

	for item in items:
		assert type(item) is dict
		if False:
			print()
			for z in 'ptime','title','digest','link','type','docid', 'category', 'channel':
				print(z,item.get(z,None))

		link=item['link'].lower()
		if not link.endswith('.html') \
			and not link.endswith('.xhtml') \
			and not link.endswith('.html') \
			and not link.endswith('.cgi') \
			and not link.endswith('.php'):
			art=Article(item)
			if not art.exists():
				print('Process:',item['link'])
				art.fetch()
				art.back_url = idx.article_back_ref()
				art.write_html()
				idx.put(art)
	
	idx.done()

	p=the_art_dir(cfg['LAST_PAGE_ALIAS'])
	if os.path.exists(p):
		os.remove(p)
	if os.path.exists(idx.page.filepath):
		os.link(idx.page.filepath, p)
		print(p,'=>',idx.page.filepath)

if __name__=="__main__":
	main()


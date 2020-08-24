#!/usr/bin/env python2.7
#-*- encoding: utf-8 -*-
from __future__ import print_function
"""
Why 2.7? The web hosting service I use has it, that's why. Unicode problems ahead.

# Chinese article aggregator script

In the server's crontab I have put the command:
	0 0,4,8,12,16,20 * * * /path/to/art.py -c /path/to/config.json 2>&1 | tee -a /path/to/log.log
And so this script will just keep appending more articles each day.
It generates a tree of documents and images in zh-news/
All command line options are meant for testing

Relevant files
WEB_ROOT/ARTICLES/MASTER_INDEX        master index. links to index pages
WEB_ROOT/ARTICLES/[NUMBER].xhtml      index pages. links to articles
WEB_ROOT/ARTICLES/YYYY-MM/*.html      articles
WEB_ROOT/ARTICLES/YYYY-MM/img/*.webp  articles' images
WEB_ROOT/ARTICLES/zh-articles.css     one style for all pages
WEB_ROOT/ARTICLES/favicon.gif
WEB_ROOT/ARTICLES/zh-news.db          sqlite3 for searching stuff

Temporary files
WEB_ROOT/ARTICLES/YYYY-MM/img0/*      articles' original large images
*.in , *.in.gz                        original articles pages
*.skip

"""

# This dict is appended from -c FILEPATH.json specified on command line
cfg={
# local filesystem path where things are stored
	'WEB_ROOT':'.',

# relative to WEB_ROOT
	'ARTICLES':'zh-news',

# filename (under WEB_ROOT/ARTICLES/)
# of a hardlink to the most recent index page
	'LAST_PAGE_ALIAS':'last.xhtml',

# contains links to index pages
	'MASTER_INDEX':'main.xhtml',

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

# save PID to this file (comment if don't want)
	'PID_FILE':'/tmp/news-aggregator.pid',

# enable delays to keep server CPU usage low
	'NICE':True,

# paths to external programs
	'CONVERT':'convert',
	'CPULIMIT':'cpulimit',

# all index documents include this in their <head>
	'HEAD_INDEX': u'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Type" content="application/xhtml+xml;charset=UTF-8"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, shrink-to-fit=no"/>
<meta name="keywords" content="china,news,chinese,cctv,新闻,中国,article,read,recent,learn,study"/>
<meta name="robots" content="index,follow"/>
<meta name="author" content="ArhoM"/>
<link rel="stylesheet" type="text/css" href="zh-articles.css"/>
<link rel="icon" href="favicon.gif"/>
'''.encode('utf-8'),

# and all article documents include this
	'HEAD_ARTICLE': u'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Type" content="application/html;charset=UTF-8"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, shrink-to-fit=no"/>
<link rel="stylesheet" type="text/css" href="../zh-articles.css"/>
<link rel="icon" href="../favicon.gif"/>
'''.encode('utf-8'),

	'GET_163':True,
	'GET_CCTV':True,

# Upper limit how many articles to download from one source in 1h (or however often this script is called)
	'MAX_DL':50,
}

import traceback
import urllib2
import re
import json
import os
import sys
import time
import sqlite3
import xml.etree.ElementTree as ET
import argparse
import gzip

def should_terminate():
	# to kill the program (when started by another user) use PID_FILE and delete it
	return 'PID_FILE' in cfg and not os.path.exists(cfg['PID_FILE'])

def try_remove(x):
	try:
		os.remove(x)
		print('Removed',x)
	except:
		pass

def try_link(x,y):
	if os.path.exists(x):
		try_remove(y)
		os.link(x, y)
		print(y,'=>',x)

def be_nice():
	if cfg['NICE']:
		time.sleep(5)

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

def cached(path, func, opn=open):
	if os.path.exists(path):
		print('use cached:',path)
		with opn(path,'rb') as f:
			data=f.read()
	else:
		make_dir(os.path.dirname(path))
		data=func()
		print('Write cached copy:', path)
		with opn(path,'wb') as f:
			f.write(data)
	return data

def cached_gz(path, func):
	path+='.gz'
	return cached(path, func, gzip.open)

def scanJ(html, r):
	m=re.search(r, html, flags=re.M|re.I|re.U)
	if m is None:
		raise Exception('failed to parse main page, regex'+r)
	return json.loads(m.group(1))

def S(x):
	if type(x) is unicode:
		return x.encode('utf-8')
	return str(x)

def discard_url_params(url):
	i=url.find('?')
	return url[:i] if i>=0 else url

def check_ext(url,valid):
	u=discard_url_params(url).lower()
	for ext in valid:
		if u.endswith(ext):
			return True
	return False

def write_html_files(path, func):
	if cfg['SAVE_HTML']:
		with open(path,'wb') as f:
			func(f)
	if cfg['SAVE_HTML_GZ']:
		with gzip.open(path+'.gz','wb') as f:
			func(f)

def have_html_files(path):
	return (not cfg.get('REBUILD_HTML',False)) \
		and ((not cfg.get('SAVE_HTML',True)) or os.path.exists(path)) \
		and ((not cfg.get('SAVE_HTML_GZ',True)) or os.path.exists(path+'.gz'))
	
def shell_cmd(cmd):
	if cfg['NICE']:
		cmd=cfg['CPULIMIT']+' -q -l 15 -- '+cmd
	print(cmd)
	os.system(cmd)
	be_nice()

class ImgError(Exception):
	pass

class Img:
	def __init__(self, dstdir, src):
		if should_terminate():
			raise ImportError('program kill switch')
		if 'javascript:' in src:
			raise ImgError('javascript img hack: '+src)
		bn=os.path.basename(src)
		no_suf=re.sub(r'(\..{1,5})$','',bn)
		if not check_ext(bn,('.jpg','.jpeg','.gif','.png','.webp')):
			raise ImgError('unknown suffix: '+bn[-4:])
		self.path_org=os.path.join(dstdir, 'img0', bn)
		self.path_webp=os.path.join(dstdir, 'img', no_suf+'.webp')
		self.path_jpg=os.path.join(dstdir, 'img', no_suf+'.jpg')
		self.url_src=src
		self.url_webp='img/'+no_suf+'.webp'
		self.url_jpg='img/'+no_suf+'.jpg'
		rebuild=cfg.get('REBUILD_IMAGES',False)
		if not os.path.exists(self.path_jpg) or rebuild:
			make_dir(os.path.dirname(self.path_org))
			make_dir(os.path.dirname(self.path_jpg))
			try:
				cached(self.path_org, lambda: GET(src))
			except KeyboardInterrupt as e:
				raise e
			except:
				raise ImgError('FAILED to get image:', src)
			shell_cmd(cfg['CONVERT']+' '+self.path_org+" -fuzz 1% -trim +repage -resize '500000@>' -quality 40 -sampling-factor 4:2:0 "+self.path_jpg)
			if not cfg['SAVE_IMG_SRC']:
				try_remove(self.path_org)
		# webp is nice. but HDD space cost $$ and don't want duplicate images
	
	def tag(self, alt='', cl=''):
		code='\n<!-- source: '+self.url_src+'-->\n'
		if os.path.exists(self.path_webp):
			code+='<object'+cl+' type="image/webp"'+' data="'+self.url_webp+'">'
			if os.path.exists(self.path_jpg):
				code+='<img'+cl+alt+' src="'+self.url_jpg+'"/>'
			else:
				pass # could insert message about unsupported webp
			code+='</object>\n'
		else:
			if os.path.exists(self.path_jpg):
				code+='<img'+cl+alt+' src="'+self.url_jpg+'"/>\n'
			else:
				pass # could insert message about missing image
		return code

class Article:

	def setup(self, item):
		""" set self. docid, src_url, title, desc, origin """
		assert False

	def scan_article_content(self, html):
		"""
		Cut out article html (to be regex filtered) from a full webpage
		Return string. Or return None to indicate the page was bad
		"""
		assert False

	def __init__(self, item):
		self.setup(item)

		# Article subclass .setup() shall set these:
		assert type(self.docid) is str
		assert type(self.src_url) is str
		assert type(self.title) is str
		assert type(self.desc) is str
		assert type(self.origin) is str

		self.date=item['article_date_py_']
		self.bname=self.docid+'.html'
		self.dir_ym = time.strftime('%Y-%m',self.date)
		self.dstdir_r = art_dir(self.dir_ym)
		self.dstdir=the_dir(self.dstdir_r)
		self.dstpath=os.path.join(self.dstdir,self.bname)

		# idx_url: how this article is addressed from index pages
		self.idx_url = self.dir_ym + '/' + self.bname
		self.back_url=None
	
	def exists(self):
		return have_html_files(self.dstpath)
	
	def filter_img163(self, attr, cl):
		""" Reformat <img ...attr...> tag
		attr: string (xx="yy" zz="ww" ...)
		cl: string (class="blabhblah ...")
		"""
		ds=re.search(r'data-src="([^"]+)"', attr)
		ds=ds if ds is not None else re.search(r'src="([^"]+)"', attr)
		if ds is None:
			return ''
		src_url=ds.group(1)
		if 'javascript:' in src_url.lower():
			#print('dropping weird img:', whole)
			return '<!-- IMG REMOVED -->'
		if src_url.startswith('//'):
			# CCTV images
			src_url = 'http:' + src_url
		try:
			im=Img(self.dstdir, src_url)
		except ImgError as e:
			print('Image rejected.', e.message)
			return '<!-- FAILED IMG CONVERSION, IMG REMOVED -->'
		alt=re.search(r'alt="([^"]+)"', attr)
		alt='' if alt is None else ' '+alt.group(0)
		return im.tag(alt=alt, cl=cl)
	
	def filter_a163(self, attr, cl):
		url=''
		ref=re.search(r'href="([^"]+)"', attr)
		if ref is not None:
			url=ref.group(1).strip().lower()
			url=discard_url_params(url)
		Js='javascript:' in url
		Ds='data-src' in attr
		http=url.startswith('http://')
		https=url.startswith('https://')
		ext_ok=check_ext(url,('.html','.htm','.xht','.xhtml','.cgi','.php')) #,'.png','.jpg','.jpeg','.gif','.webp'))
		if Js or Ds or (not http and not https) or not ext_ok:
			#print('dropping weird link:', whole)
			return '<a><!-- LINK "' + url + '" -->'
		return str('<a href="' + cl + url + '">')
	
	def filter_tag(self, x):
		whole=x.group(0)
		if whole=='<!--SCRIPT REMOVED-->':
			return whole
		tag=x.group(1).strip().strip('/').lower()
		attr=x.group(2).strip().strip('/').replace('\n',' ')
		start_slash='/' if x.group(1).startswith('/') else ''
		end_slash='/' if x.group(2).endswith('/') else ''

		if tag not in ('p','h1','h2','h3','h4','h5','h6',
			'strong','em','table','th','tr','td','blockquote',
			'b','i','small','br','hr','img',
			'ul','li','ol','a','section','figure','figcaption',
			'sub','sup','tt','u','big','center','pre','q'):
			#print('dropping extra tag:', whole)
			return ''
			return '<!-- TAG: ' + tag + ' -->'

		cl=''
		if len(attr)>0:
			cl=re.search(r'class="[-_a-zA-Z0-9]+"', attr)
			cl='' if cl is None else ' '+cl.group(0)
			Id=re.search(r'id="[-_a-zA-Z0-9]+"', attr)
			Id='' if Id is None else ' '+Id.group(0)
			cl=Id+cl
			if tag == 'img':
				return self.filter_img163(attr, cl)
			if tag == 'a':
				return self.filter_a163(attr, cl)

		nl = '\n' if start_slash=='/' else ''
		return str('<' + start_slash + tag + cl + end_slash + '>' + nl)
	
	def have_src_page(self):
		return os.path.exists(self.dstpath+'.in.gz')
	
	def fetch(self):
		make_dir(self.dstdir)
		self.src_html=cached_gz(self.dstpath+'.in', \
			lambda:GET(self.src_url))
	
	def is_poisoned(self):
		return os.path.exists(self.dstpath+'.skip')
	
	def mark_poisoned(self):
		open(self.dstpath+'.skip','w').close()
		print('flag as poisoned:', self.dstpath)
	
	def write_html(self):
		html=self.src_html

		de=re.search(r'<meta\s+name="description"\s+content="([^"]+)"\s*/?>', html)
		if de is not None:
			# upgrade to the real description
			self.desc=de.group(1)

		# dig out the article
		body = self.scan_article_content(html)
		if body is None:
			return False

		# safety
		noscript='<!--SCRIPT REMOVED-->'
		f=re.S|re.U|re.M|re.I
		body=re.sub(r'<script>.*?</script>',noscript,body,flags=f)
		body=re.sub(r'<\s*script.*?>.*?</\s*script\s*>',noscript,body,flags=f)
		body=re.sub(r'<\s*script.*?/>',noscript,body,flags=f)
		body=re.sub(r'<\s*script.*',noscript,body,flags=f)

		# remove Notice: the content..NetEase..blahblah
		body=re.sub(r'<p>特别声明.*?</p>','',body,flags=re.S)
		body=re.sub(r'<p class="statement-en".*?</p>','',body,flags=re.S)

		try:
			# only keep some tags
			body=re.sub(r'<\s*([^ >]*)\s*([^>]*)>', lambda x: self.filter_tag(x), body, flags=re.M|re.S|re.U)
		except ImportError:
			# manual termination
			return False

		# not sure whats up with these non-links
		body=re.sub('<p>https?://[^<]*</p>', \
			lambda x: '<!-- '+x.group(0)+' -->\n', \
			body, flags=re.M|re.S)

		# cheap attempt at minifying it
		# remove useless links
		body=re.sub('<a>(.*?)</a>',lambda x: x.group(1), body, flags=re.S)
		# empty tags like <span></span> ...
		body=re.sub('<([a-zA-Z]+)>\s*</\1>','', body, flags=re.M|re.S|re.U)
		#body=re.sub('\xe3\x80\x80',' ',html)
		body=re.sub('[ \t]+',' ',body)
		body=re.sub(' *\n+ *','\n',body,flags=re.M)
		body=re.sub(' *\n+ *','\n',body,flags=re.M)

		print('write article:', self.dstpath)

		s=self.header()
		s+='<div class="main-content">\n'
		s+=body
		s+='</div>\n'
		s+=self.footer()
		s=S(s)

		write_html_files(self.dstpath, lambda f,s=s: f.write(s))
		return True
	
	def header(self):
		h=cfg['HEAD_ARTICLE'] \
+ '<title>' + self.title +'</title>\n' \
+ '<meta name="description" content="' \
+ self.desc + '"/>\n' \
+ '</head>\n<body id="art_body">\n'
		h+=self.make_back_url()
		return h
	
	def make_back_url(self, org=True):
		if not self.back_url:
			return ''
		h='<nav>'
		h+='<a class="zh-ret" href="'+self.back_url+'">'
		h+=u'Return 返回'.encode('utf-8')
		h+='</a>\n'
		if org:
			xx=u'Source 原文'.encode('utf-8')
			h+='<a href="'+self.src_url+'">'+xx+'</a>\n'
		h+='</nav>'
		return h

	def footer(self):
		s=self.make_back_url(org=True)
		s+='</body>\n</html>\n'
		return s

class Article163(Article):

	def setup(self, item):
		""" item needs to have
		link : url to some .html file
		ptime_py : python datetime
		title or docid (optional)
		digest (optional)
		"""
		self.docid=S(item['docid'])
		self.src_url = discard_url_params(S(item['link']))
		self.title=S(item.get('title',self.docid))
		# digest: truncated description
		self.desc=S(item.get('digest','no description'))
		self.origin=S(u'3g.163.com 手机网易网')
	
	def scan_article_content(self, html):
		""" Works for 163 """

		# dig out the article
		m=re.search(r'<article[^>]*>(.*)</article>', html, flags=re.I|re.S)
		if m is None:
			print('failed to get article body', self.docid)
			return None

		art_tag=m.group(0)[:100]
		if 'type="imgnews"' in art_tag or 'class="topNews"' in art_tag:
			print('rejecting clickbait trash compilation')
			self.mark_poisoned()
			return None

		body=m.group(1)
		return body

class ArticleCCTV(Article):

	def setup(self, item):
		self.docid=S(item['id'])
		self.src_url = discard_url_params(S(item['url']))
		self.title=S(item.get('title',self.docid))
		self.desc=S(item.get('brief','no description'))
		self.origin=S(u'news.cctv.com')

	def scan_article_content(self, html):

		# body (some fake articles don't have it)
		b=re.search(r'<!--repaste\.body\.begin-->(.*?)<!--repaste\.body\.end-->', html, flags=re.I|re.S)
		if b is None:
			print('failed to get article body')
			self.mark_poisoned()
			return None

		# optional title
		t=re.search('r<!--repaste\.title\.begin-->(.*?)<!--repaste\.title\.end-->', html, flags=re.I|re.S)
		if t is None:
			t=re.search('"og:title" content="([^"]+)"', html, flags=re.I|re.S|re.M)

		# optional editor
		z=re.search('r<div class="zebian">(.*?)</div>', html, flags=re.I|re.S|re.M)

		body=''
		if t is not None:
			body+='<h1>'+t.group(1)+'</h1>'
		body+=b.group(1)
		if z is not None:
			body+='<p class="editor">'+z.group(1)+'</p>'
		return body

#	def filter_tag(self, x):
# todo

class IndexPage:
	def __init__(self, seq_id, basename):
		title=time.strftime('News %Y-%m-%d')
		self.seq_id=seq_id
		self.sib_url=basename
		self.filepath=the_art_dir(basename)
		self.next=None
		self.prev=None
		self.ns='{http://www.w3.org/1999/xhtml}'
		head_code=cfg['HEAD_INDEX']+\
	'<title>' + title + '''</title>
<meta name="description" content="News, no scripts"/>
</head><body id="subIdx">
''' + self.nav() + '''
<div class="main-content"></div>
''' + self.nav() + '''
<br/><br/><br/>
</body></html>'''
		self.et=ET.ElementTree(ET.fromstring(head_code))
		self.load()
		self.body=self.find2(self.et, ".//body")
		if self.body is None:
			raise Exception('oops. body not found. xpath failed')
		print('Index page initialized',self.filepath,'(%d)'%self.count())

	def find2(self, el, xpath):
		# find2: stupid workaround to a stupid schrodinger's namespace problem
		x=el.find(xpath)
		if x is None:
			x=el.find(xpath.replace('//','//'+self.ns))
		return x
	
	def nav(self):
		return '''<nav><ul>
<li><a href="./'''+cfg['MASTER_INDEX']+'''">Index</a></li>
<li><a href="./'''+cfg['LAST_PAGE_ALIAS']+'''">Most recent</a></li>
<li><a class="prev" href="#">Previous page</a></li>
<li><a class="next" href="#">Next page</a></li>
</ul></nav>'''
	
	def load(self):
		if os.path.exists(self.filepath):
			self.et=ET.parse(self.filepath)
			return True
		return False

	def article_container(self):
		pgc=self.find2(self.body, ".//div[@class='main-content']")
		assert pgc is not None
		return pgc
	
	def count(self):
		return len(self.article_container().getchildren())
	
	def get_date_str(self):
		c=self.article_container()
		d=self.find2(c, ".//span[@class='date']")
		return d.text
	
	def is_full(self):
		return self.count() >= cfg['INDEX_BATCH']
	
	def _date_of(self, x):
		d=self.find2(x, ".//span[@class='date']")
		return time.strptime(d.text, '%Y-%m-%d %H:%M:%S')
	
	def sort(self):
		# newest articles first
		c=self.article_container()
		c[:]=sorted(c[:], key=lambda x: self._date_of(x), reverse=True)

	def has(self, url):
		a=self.body.find(".//div[@class='article-ref']//a[@class='local'][@href='"+url+"']")
		b=self.body.find(".//"+self.ns+"div[@class='article-ref']//"+self.ns+"a[@class='local'][@href='"+url+"']")
		return (a is not None) or (b is not None)
	
	def store(self, art):
		if self.has(art.idx_url):
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
		self.article_container().insert(0,a)
		print('Index page appended',self.filepath,'(%d)'%self.count())
	
	def set_ref(self, c, url):
		aa=self.body.findall(".//a[@class='"+c+"']")
		aa+=self.body.findall(".//"+self.ns+"a[@class='"+c+"']")
		for a in aa:
			a.attrib['href'] = url
	
	def write_xhtml(self, f):
		f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
		f.write('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n')
		self.et.write(f,encoding='utf-8', xml_declaration=False)
	
	def save(self, sqc, r=1):
		if self.count() < 1:
			print('empty index page. not saving')
			return
		self.sort()
		if self.count()>0: # get_date_str fail if count==0
			i=self.seq_id
			d=self.get_date_str()
			sqc.execute('UPDATE indexes SET date = ? WHERE id = ?', (d,i))
		if self.prev is None:
			print(self.filepath+': previous page not set')
		else:
			print(self.filepath+': previous page = ', self.prev.filepath)
			self.prev.set_ref('next',self.sib_url if self.is_full() else '#')
			self.set_ref('prev',self.prev.sib_url)
			if r>0:
				self.prev.save(sqc, r-1)
		print('Write index page',self.filepath)
		write_html_files(self.filepath, lambda f,s=self: s.write_xhtml(f))

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
			print('This will be the first page in the database')
			self.next_id = 1
			self.page=None
			self.new_page()
		else:
			self.next_id = rows[0][0] + 1
			self.page = IndexPage(rows[0][0], rows[0][2])
			if len(rows)>1:
				print('got previous row', rows[1])
				self.page.prev=IndexPage(rows[1][0], rows[1][2])
				self.page.prev.next=self.page
	
	def last_full_page(self):
		p=self.page
		if p.prev is not None and not p.is_full():
			p=p.prev
		return p
	
	def total_count(self):
		r=self.sqc.execute('SELECT COUNT(*) FROM articles')
		return r.fetchone()[0]
	
	def write_master_index_(self, f):
		f.write(cfg['HEAD_INDEX'])
		f.write('''<title>News, no scripts</title>
<meta name="description" content="News, no scripts"/>
</head><body id="mainIdx">
''')
		f.write('<a class="recent" href="'\
+cfg['LAST_PAGE_ALIAS']+'">&gt;&gt;&gt; Enter &lt;&lt;&lt;</a><br/>\n')
		f.write(u'''<div class="introd"><div lang="en">
<h1>About</h1>
<p>Hey. I study chinese. I read their news. But chinese news apps and websites suck! They're slow and put a heavy burden on phone's battery. That's why I made this service. Here you can read chinese news served fast from Europe. No javascript, no ads, just news.</p>
</div>
<div lang="zh">
<h1>介绍</h1>
<p>你好。我是一个喜欢学中文的西方人，为了提高我的中文水平，我经常看中国的新闻。但是中国网站和APP都很慢，而且它们运行的javascript让我手机掉电特别快。为了解决这个问题，我创建了这个新闻网站。它每天自动下载中国网站上的新闻，移除之中的垃圾，然后保存到位于欧洲的服务器，这样在欧洲的读者会得到更好的使用体验。</p>
</div>
<a href="https://github.com/sinf/noscript163">Github project page</a>
</div>
'''.encode('utf-8'))
		f.write('<div class="all"><h1>Archive</h1>\n')
		f.write('<h2>Total articles: '+str(self.total_count())+'</h2>\n')
		s = self.sqc.execute( \
'SELECT * FROM indexes ORDER BY id DESC;')
		rows = s.fetchall()
		if rows is not None and len(rows)>0:
			date = None
			for i,d,html_path in rows:
				d=d[:10] # YYYY-MM-DD; drop the rest
				if d != date:
					if date is not None:
						f.write('</div>')
					date=d
					f.write('<div class="d">'+d+'<br/>\n')
				f.write('<a href="'+html_path+'">')
				f.write(str(i))
				f.write('</a>\n')
			f.write('</div>')
		else:
			f.write('No articles yet\n')
		f.write('</div></body></html>\n')
	
	def write_master_index(self):
		write_html_files(
			the_art_dir(cfg['MASTER_INDEX']),
			lambda f: self.write_master_index_(f))
	
	def new_page(self):
		i=self.next_id
		p=str(i)+'.xhtml'
		self.next_id += 1
		tmp=self.page
		self.page = IndexPage(i, p)
		print('start editing a new page:', self.page.filepath)
		if tmp is not None:
			print('previous page was', tmp.filepath)
			tmp.next = self.page
			self.page.prev = tmp
		d=time.strftime('%Y-%d-%m %H:%M:%S')#placeholder time
		self.sqc.execute('INSERT INTO indexes VALUES (?,?,?)', (i, d, p))
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
		if self.page.count() >= cfg['INDEX_BATCH']:
			self.page.save(self.sqc)
			self.new_page()
		self.page.store(art)

	def done(self):
		self.page.save(self.sqc)
		self.sq.commit()
		self.write_master_index()
		self.sqc.close()
		self.sq.commit()
	
	def article_back_ref(self):
		return '../' + self.page.sib_url

def get_mainpage(url, cache_prefix, args):
	if len(args.mainpage)>0:
		# src file specified on command line
		src_path=args.mainpage[0]
		src_bn=os.path.basename(src_path)
		print('Using', src_path, 'as the front page')
		if src_bn.startswith(cache_prefix):
			opn=open
			if src_bn.endswith('.gz'):
				opn=gzip.open
			with opn(src_path,'rb') as f:
				frontpage=f.read()
		else:
			# some other news source deals with the file
			return None
	else:
		p=the_art_dir(time.strftime( \
			cache_prefix + '-%Y-%m-%d-%H.html'))
		frontpage = cached_gz(p, lambda u=url:GET(u))
	assert type(frontpage) is str
	return frontpage

def parse_date_ymdhms(x):
	t = x.encode('utf-8') if type(x) is unicode else str(x)
	return time.strptime(t,'%Y-%m-%d %H:%M:%S')

def pull_163(args):
	url='https://3g.163.com/touch/news/'
	prefix='news_163'
	frontpage=get_mainpage(url, prefix, args)
	if frontpage is None:
		return []
	# Fetch single-line json array from front page
	# difference between topicData and channelData?
	#topicData = scanJ(frontpage, r'^\s*var\s+topicData\s*=\s*({.*});$')
	chanData = scanJ(frontpage, r'^\s*var\s+channelData\s*=\s*({.*});$')
	items=[]
	items+=chanData['listdata']['data']
	for xx in chanData['topdata']['data']:
		assert type(xx) is dict
		assert 'ptime' in xx
		items+=[xx]
	for it in items:
		it['article_class_py_'] = Article163
		it['article_date_py_'] = parse_date_ymdhms(it['ptime'])
	return items

def pull_cctv(args):
	url='http://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/news_1.jsonp'
	prefix='news_cctv'
	news_1=get_mainpage(url, prefix, args)
	if news_1 is None:
		return []
	try:
		news_json=json.loads(news_1[5:-1], encoding='utf-8')
	except Exception, err:
		print('Failed to parse CCTV json')
		print('json', news_1[:10], '...', news_1[-10:])
		print('json (inner)', news_1[5:10], '...', news_1[-10:-1])
		traceback.print_exc()
		sys.exit(1)
	items=[]
	for it in news_json['data']['list']:
		it['article_class_py_'] = ArticleCCTV
		it['article_date_py_'] = parse_date_ymdhms(it['focus_date'])
		items += [it]
	return items

def n_most_recent(items, n):
	items = sorted(items, key=lambda it: it['article_date_py_'])
	if n >= 0:
		for it in items[n:]:
			it['__skipDL'] = True
	return items

def main():

	ap=argparse.ArgumentParser()
	ap.add_argument('-m', '--mainpage', nargs=1, default=[], help="Specify filename of main page (.html or .html.gz)")
	ap.add_argument('-a', '--articles', nargs='*', default=[], help="Only consider article URLs that end with any string listed here")
	ap.add_argument('-f', '--fuck-it', action='store_true',help="Disable CPU saving (for testing)")
	ap.add_argument('-c', '--conf', nargs=1, default=[None],help="Load JSON config from this filepath")
	ap.add_argument('-r', '--rebuild-html', action='store_true',help="Rebuild HTML files")
	ap.add_argument('-R', '--rebuild-images', action='store_true',help="Rebuild HTML and image files")
	ap.add_argument('-I', '--rebuild-index-only', action='store_true',help="Skip rebuilding articles")
	ap.add_argument('-n', '--no-fetch', action='store_true',help="Just rebuild mainpage without downloading anything")
	args=ap.parse_args()

	print('\nNews article archiver & reformatter started')
	print('Time:', time.strftime('%Y-%d-%m %H:%M:%S'))

	if args.conf[0] is not None:
		print('reading config', args.conf[0])
		with open(args.conf[0],'r') as f:
			tmp=json.load(f)
			cfg.update(tmp)

	if args.rebuild_html: cfg['REBUILD_HTML']=True;
	if args.rebuild_images: cfg['REBUILD_IMAGES']=True;

	T_START=time.time()
	print('My PID is', os.getpid())
	if 'PID_FILE' in cfg:
		try:
			with open(cfg['PID_FILE'],'w') as f:
				f.write(str(os.getpid()))
		except KeyboardInterrupt:
			return
		except:
			print('!! Failed to write', cfg['PID_FILE'])
			del cfg['PID_FILE']
	
	os.nice(19) # be nice
	os.environ['PATH'] = cfg.get('PATH_PREPEND','') + os.environ['PATH']

	if args.fuck_it:
		cfg['NICE']=False
	
	ET.register_namespace('','http://www.w3.org/1999/xhtml')
	items = []

	if not args.no_fetch:
		n=int(cfg.get('MAX_DL',50))
		if cfg['GET_163']:
			print('Fetch 163...')
			items += n_most_recent(pull_163(args), n)
		if cfg['GET_CCTV']:
			print('Fetch CCTV...')
			items += n_most_recent(pull_cctv(args), n)

	idx = Indexer()
	sq = idx.sq

	rebuild_index_only=\
		cfg.get('REBUILD_HTML',False) \
		and args.rebuild_index_only

	revisit_html=\
		args.rebuild_html or args.rebuild_images
	
	items = n_most_recent(items, -1)

	print('Fetching articles... (%d)' % len(items))
	for item in items:
		assert type(item) is dict
		assert 'article_class_py_' in item
		assert 'article_date_py_' in item

		cl_init=item['article_class_py_']
		art=cl_init(item)

		if len(args.articles)>0:
			# if specific paths were listed in command line
			# check if article matches any. skip otherwise
			tmp=discard_url_params(art.src_url).lower()
			ok=False
			for a in args.articles:
				if tmp.endswith(a.lower()):
					ok=True
					break
			if not ok:
				continue

		if item.get('__skipDL',False) and not art.have_src_page():
			continue

		print(art.src_url)

		if check_ext(art.src_url, ('.shtml', '.html','.xhtml','.cgi','.php')):
			if should_terminate():
				break
			if (revisit_html or not art.exists()) \
			and not art.is_poisoned():
				print('Process:',art.src_url)
				while True:
					try:
						art.fetch()
					except KeyboardInterrupt:
						break
					except:
						print('Failed to GET')
						break
					art.back_url = idx.article_back_ref()
					if rebuild_index_only or art.write_html():
						idx.put(art)
					be_nice()
					break

		if should_terminate():
			break
	
	idx.done()

	p=the_art_dir(cfg['LAST_PAGE_ALIAS'])
	last=idx.last_full_page()
	try_link(last.filepath, p)
	try_link(last.filepath+'.gz', p+'.gz')
	
	T_END=time.time()
	T_TOT=T_END-T_START
	print('Operation took', '%.0f min %.0f s' % (T_TOT/60,T_TOT%60), 'seconds')

if __name__=="__main__":
	try:
		main()
	finally:
		if 'PID_FILE' in cfg:
			try_remove(cfg['PID_FILE'])


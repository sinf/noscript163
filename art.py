#!/usr/bin/env python2.7
#-*- encoding: utf-8 -*-
from __future__ import print_function
import sys
PYTHON2=sys.version_info[0]<3

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
WEB_ROOT/ARTICLES/head.db             HEAD requests cached here
*.in , *.in.gz                        original articles pages
*.skip

"""

# This dict is appended from -c FILEPATH.json specified on command line
cfg={
# local filesystem path where things are stored
	'WEB_ROOT':'.',

# relative to WEB_ROOT
	'ARTICLES':'z',

# filename (under WEB_ROOT/ARTICLES/) of a hardlink to the most recent index page
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

# save PID to this file (comment if don't want)
	'PID_FILE':'/tmp/news-aggregator.pid',

# enable delays to keep server CPU usage low
	'NICE':True,

# paths to external programs
	'CONVERT':'convert',
	'CPULIMIT':'cpulimit',
# 'PATH_PREPEND' : '/path/to/your/bin:'

	'XHTML_HEADER': '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">
''',
	'HTML_HEADER':'<!DOCTYPE html>\n<html lang="zh">\n',

# only used by make_head_tag()
	'HEAD_CODE' : u'''<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Type" content="application/xhtml+xml;charset=UTF-8"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, shrink-to-fit=no"/>
<meta name="keywords" content="china,news,chinese,cctv,新闻,中国,article,read,recent,learn,study"/>
<meta name="author" content="ArhoM"/>
<style type="text/css">html{background-color:#324A8B;color:white;}a,a:visited{color:white;}</style>
<link rel="stylesheet" type="text/css" href="@@zh-articles.css"/>
<link rel="icon" href="@@favicon.gif"/>
''',

	'GET_163':True,
	'GET_CCTV':True,
	'GET_SINA':True,

# Upper limit how many articles to download from one source in 1h (or however often this script is called)
	'MAX_DL':50,

# don't want to get altered content or denied so we're lying about this
	'USER_AGENT':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36',
}

import traceback
import subprocess
import re
import json
import os
import sys
import time
import sqlite3
import xml.etree.ElementTree as ET
import argparse
import gzip
import atexit
from base64 import encodestring as b64encode

if PYTHON2:
	from urllib2 import Request, urlopen, URLError
	from cStringIO import StringIO
	from httplib import InvalidURL
	def S(x): return x.encode('utf-8') if type(x) is unicode else str(x) ;
	def B(x): return S(x) ;
	# in python 2.x we use str, no unicode
	# all strings that may have non-ascii in them we pass through S()
else:
	from io import StringIO
	from urllib.request import Request, urlopen, URLError
	class InvalidURL(Exception): pass ;
	def unicode(x): return x;
	def S(x): return x.decode('utf-8') if type(x) is bytes else x ;
	def B(x): return x.encode('utf-8') if type(x) is str else x ;

class KillSwitchEx(Exception):
	pass

def make_head_tag(url_prefix=''):
	return S(cfg['HEAD_CODE'].replace('@@',url_prefix))

def check_kill_switch():
	# to kill the program (when started by another user) use PID_FILE and delete it
	if 'PID_FILE' in cfg and not os.path.exists(cfg['PID_FILE']):
		raise KillSwitchEx()

def try_remove(x):
	try:
		os.remove(x)
		print('Removed',x)
	except OSError:
		pass

def try_link(x,y):
	if os.path.exists(x):
		try_remove(y)
		os.link(x, y)
		print(y,'=>',x)

def be_nice(s=3):
	if cfg['NICE']:
		for i in range(s):
			check_kill_switch()
			time.sleep(1)

def the_dir(path):
	wr=os.environ.get('WEB_ROOT',cfg['WEB_ROOT'])
	return os.path.join(wr, path)

def art_dir(path):
	return os.path.join(cfg['ARTICLES'],path)

def the_art_dir(path):
	return the_dir(art_dir(path))

def GET(url):
	print('GET', url)
	agent=cfg['USER_AGENT']
	req=Request(url,headers={'User-Agent':agent})
	r = urlopen(req)
	html=r.read()
	r.close()
	return html

def HEAD(url):
	print('HEAD', url)
	agent=cfg['USER_AGENT']
	req=Request(url,headers={'User-Agent':agent})
	req.get_method = lambda: 'HEAD'
	r = urlopen(req)
	nfo = r.info()
	r.close()
	return nfo

HEAD_sq_conn=None
HEAD_sq_cur=None

def HEAD_sq_cleanup():
	global HEAD_sq_conn
	global HEAD_sq_cur
	HEAD_sq_cur.close()
	HEAD_sq_conn.commit()
	HEAD_sq_conn.close()

def HEAD_date(url):
	global HEAD_sq_conn
	global HEAD_sq_cur
	if HEAD_sq_conn is None:
		HEAD_sq_conn = sqlite3.connect(the_art_dir('head.db'))
		HEAD_sq_cur = HEAD_sq_conn.cursor()
		HEAD_sq_cur.execute( \
'CREATE TABLE IF NOT EXISTS head (url TEXT UNIQUE, date TEXT)')
		atexit.register(HEAD_sq_cleanup)
	sqc = HEAD_sq_cur
	row = sqc.execute('SELECT date FROM head WHERE url = ?',(url,)).fetchone()
	try:
		if row is not None and len(row)>0:
			d=row[0]
		else:
			d=HEAD(url)['Date']
			sqc.execute('INSERT INTO head VALUES (?,?)',(url,d))
		ts=time.strptime(d, '%a, %d %b %Y %H:%M:%S GMT')
		be_nice(1)
	except KeyboardInterrupt as e:
		raise e
	except KillSwitchEx as e:
		raise e
	except:
		ts=time.localtime()
		traceback.print_exc()
		print('Failed to query', url)
	return ts

def htmlspecialchars(s):
	s=S(s)
	for a,b in (
		("&","&amp;"),('"',"&quot;"),("<","&lt;"),(">","&gt;")
		): s=s.replace(a,b);
	return s

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

def discard_url_params(url):
	i=url.find('?')
	return url[:i] if i>=0 else url

def suffix_split(path):
	i=path.rfind('.')
	return (path,'') if i<0 else (path[:i],path[i:])

def check_ext(url,valid):
	u=discard_url_params(url).lower()
	for ext in valid:
		if u.endswith(ext):
			return True
	return False

def have_html_files(path):
	return (not cfg.get('REBUILD_HTML',False)) \
		and ((not cfg.get('SAVE_HTML',True)) or os.path.exists(path)) \
		and ((not cfg.get('SAVE_HTML_GZ',True)) or os.path.exists(path+'.gz'))
	
def shell_cmd(args):
	if cfg['NICE']:
		args=[cfg['CPULIMIT']]+' -q -l 15 -- '.split()+args
	print(' '.join(args))
	ret=subprocess.call(args)
	be_nice(2)
	return ret

class ImgError(Exception):
	pass

class Img:
	def __init__(self, dstdir, src):
		check_kill_switch()
		if 'javascript:' in src.lower():
			raise ImgError('javascript img hack: '+src)
		if 'ERROR' in src:
			# cctv put an error message in URL. WHY!?
			raise ImgError('this... '+src)
		bn=os.path.basename(src)
		no_suf, suf = suffix_split(bn)
		if suf not in ('', '.jpg','.jpeg','.gif','.png','.webp'):
			# gotta reject some obvious non-images
			raise ImgError('unknown suffix: '+suf)
		self.path_org=os.path.join(dstdir, 'img0', bn)
		self.path_webp=os.path.join(dstdir, 'img', no_suf+'.webp')
		self.path_jpg=os.path.join(dstdir, 'img', no_suf+'.jpg')
		self.url_src=src
		self.url_webp='img/'+no_suf+'.webp'
		self.url_jpg='img/'+no_suf+'.jpg'
		rebuild=cfg.get('REBUILD_IMAGES',False)
		if self.is_poisoned():
			raise ImgError('poisoned')
		if 'REBUILD_AFTER' in cfg and os.path.exists(self.path_jpg):
			t0=cfg['REBUILD_AFTER']
			if time.localtime(os.stat(self.path_jpg).st_mtime) > t0:
				rebuild=True
		if not os.path.exists(self.path_jpg) or rebuild:
			make_dir(os.path.dirname(self.path_jpg))
			try:
				cached(self.path_org, lambda: GET(src))
			except KeyboardInterrupt as e:
				raise e
			except KillSwitchEx as e:
				raise e
			except (URLError, InvalidURL, ValueError) as ex:
				traceback.print_exc()
				raise ImgError('FAILED to get image: '+src)
			if shell_cmd([cfg['CONVERT'],self.path_org+"[0]"] \
+ "-fuzz 1% -trim +repage".split() \
+ ['-resize', '560x2000>'] \
+ "-quality 40 -sampling-factor 4:2:0".split() \
+ [self.path_jpg]) == 0:
				# convert success

				# but check for 1x1 image
				try:
					if (subprocess.check_output([cfg['CONVERT'],'-format','%wx%h',
						self.path_jpg, 'info:']).strip() == '1x1'):
							print('1x1 image')
							self.mark_poisoned()
							raise ImgError('poisoned')
				except subprocess.CalledProcessError:
					pass

				if not cfg['SAVE_IMG_SRC']:
					try_remove(self.path_org)
			else:
				# remove potentially broken output file. but keep original
				try_remove(self.path_jpg)
				raise ImgError('FAILED to convert image: '+src)
		# webp is nice. but HDD space cost $$ and don't want duplicate images
	
	def is_poisoned(self):
		return os.path.exists(self.path_jpg+'.skip')
	
	def mark_poisoned(self):
		open(self.path_jpg+'.skip','w').close()
	
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
				code+='<!-- file not found -->\n'
		return code

class Article:

	frontpage_url=None
	frontpage_file_prefix=None
	origin=None

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
		
		self.src_url = discard_url_params(S(item['url']))
		self.docid = S(item['docid'])
		self.title = S(item.get('title',self.docid))
		self.desc = S(item.get('desc',''))
		assert type(self.origin) is str

		assert type(item['article_date_py_']) is time.struct_time
		self.date=item['article_date_py_']
		self.bname=self.docid+'.html'
		self.dir_ym = time.strftime('%Y-%m',self.date)
		self.dstdir_r = art_dir(self.dir_ym)
		self.dstdir=the_dir(self.dstdir_r)
		self.dstpath=os.path.join(self.dstdir,self.bname)
		self.dstpath_r=os.path.join(self.dstdir_r, self.bname)

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
			print(e)
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
		self.src_html=S(cached_gz(self.dstpath+'.in', \
			lambda:GET(self.src_url)))
	
	def is_poisoned(self):
		p=os.path.exists(self.dstpath+'.skip')
		if p: try_remove(self.dstpath+'.in.gz');
		return p
	
	def mark_poisoned(self):
		open(self.dstpath+'.skip','w').close()
		print('flag as poisoned:', self.dstpath)
	
	def write_html(self, f):
		de=re.search( \
r'<meta\s+name="description"\s+content="([^"]+)"\s*/?>', self.src_html)
		if de is not None:
			# upgrade to the real description
			self.desc=de.group(1)

		# dig out the article
		body = self.scan_article_content(self.src_html)
		if body is None:
			return False

		body = self.rectify(body)

		f.write(S(self.header()))
		f.write('<div class="main-content">\n')
		f.write(S(body))
		f.write('</div>\n')
		f.write(S(self.footer()))
		return True
	
	def rectify(self, body):
		""" Cleans up source htmls with regex """

		# some comments contain broken html so delete them first
		body=re.sub(r'<!--(.*?)-->','',body,flags=re.S)

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

		# filter_tag only keeps some tags (<p>,<span>,<img>, ..)
		# also converts images (takes forever)
		body=re.sub(r'<\s*([^ >]*)\s*([^>]*)>', lambda x: self.filter_tag(x), body, flags=re.M|re.S|re.U)

		# not sure whats up with these non-links
		body=re.sub('<p>\s*https?://[^<]*</p>', \
			lambda x: '<!-- '+x.group(0)+' -->\n', \
			body, flags=re.M|re.S|re.U)

		# cheap attempt at minifying it
		# remove useless links (usually filter_tag removed the href)
		body=re.sub('<a>(.*?)</a>',lambda x: x.group(1), body, flags=re.S)
		# empty tags like <span></span> ...
		body=re.sub('<([a-zA-Z]+)>\s*</\1>','', body, flags=re.M|re.S|re.U)
		# plz tell me WTF they doing with these spaces. css does margin better
		body=body.replace('\xe3\x80\x80',' ')
		body=re.sub('[ \t]+',' ',body)
		body=re.sub(' *\n+ *','\n',body,flags=re.M)
		body=re.sub(' *\n+ *','\n',body,flags=re.M)

		return body
	
	def header(self):
		h=cfg['HTML_HEADER'] \
+ make_head_tag('../') \
+ '<title>' + self.title +'</title>\n' \
+ '<meta name="description" content="' + self.desc + '"/>\n' \
+ '<meta name="robots" content="index,nofollow,noimageindex"/>\n' \
+ '</head>\n<body id="art_body">\n'
		h+=self.make_back_url()
		return h
	
	def make_back_url(self, org=True):
		if not self.back_url:
			return ''
		h='<nav>'
		h+='<a class="zh-ret" href="'+self.back_url+'">'
		h+=S(u'Return 返回')
		h+='</a>\n'
		if org:
			xx=S(u'Source 原文')
			uu=S(self.src_url)
			h+='<a class="article-src" href="'+uu+'">'+xx+'</a>\n'
		h+='</nav>'
		return h

	def footer(self):
		s=self.make_back_url(org=True)
		s+='</body>\n</html>\n'
		return s

"""
class ArticleXXXXX(Article):

	frontpage_url='https://xxxxx'
	frontpage_file_prefix='news_xxx'
	origin=S(u'xxxxxx.com 中文字')
	
	def scan_article_content(self, html):
		if error_happened(html):
			# may try again sometime
			return None
		body=re.search(html).group(x)
		if is_garbage(body):
			# ban forever
			self.mark_poisoned()
			return None
		return body
	
	def parse_frontpage(html):
		items=[]
		for x in re.findall(expr, html):
			items+=[{
				'url' : 'http://whatever',
				'docid' : some_unique_id_string, #maybe get from filename
				'title' : optional,
				'desc' : optional,

				# optional performance boost
				'article_date_py_' : parse_time(x['xx_date_field']),
			}]
"""

class Article163(Article):

	frontpage_url='https://3g.163.com/touch/news/'
	frontpage_file_prefix='news_163'
	origin=S(u'3g.163.com 手机网易网')

	def scan_article_content(self, html):
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

	@staticmethod
	def parse_frontpage(frontpage):
		items=[]
		# Fetch single-line json array from front page
		# difference between topicData and channelData?
		#topicData = scanJ(frontpage, r'^\s*var\s+topicData\s*=\s*({.*});$')
		chanData = scanJ(frontpage, r'^\s*var\s+channelData\s*=\s*({.*});$')
		items+=chanData['listdata']['data']
		for xx in chanData['topdata']['data']:
			items+=[xx]
		items_out = []
		for it in items:
			try:
				items_out += [{
					'docid' : it['docid'],
					'url'   : it['link'],
					'article_date_py_' : parse_date_ymdhms(it['ptime']),
					'title' : it.get('title',''),
					'desc'  : it.get('digest',''), #digest: truncated description
				}]
			except KeyboardInterrupt as e:
				raise e
			except:
				traceback.print_exc()
		return items_out

class ArticleCCTV(Article):

	frontpage_url='http://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/news_1.jsonp'
	frontpage_file_prefix='news_cctv'
	origin=S(u'news.cctv.com')

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

	@staticmethod
	def parse_frontpage(news_1):
		try:
			news_json=json.loads(news_1[5:-1], encoding='utf-8')
		except Exception as ex:
			print('Failed to parse CCTV json')
			print('json', news_1[:10], '...', news_1[-10:])
			print('json (inner)', news_1[5:10], '...', news_1[-10:-1])
			traceback.print_exc()
			return []
		items=[]
		for it in news_json['data']['list']:
			if '/PHOA' in it['url']:
				continue
			items += [{
				'docid' : it['id'],
				'url'   : it['url'],
				'title' : it.get('title',it['id']),
				'desc'  : it.get('brief',''),
				'article_date_py_' : parse_date_ymdhms(it['focus_date']),
			}]
		return items

class ArticleSina(Article):
	frontpage_url='https://news.sina.com.cn/'
	frontpage_file_prefix='news_sina'
	origin=S(u'news.sina.com.cn 新浪网')

	def scan_article_content(self, html):
		b=re.search(r'<div class="article" id="article">(.*?)</div>\s*<!-- 正文 end -->', html, flags=re.S|re.M|re.U)
		if b is None:
			print('failed to get article body')
			self.mark_poisoned()
			return None
		t=re.search(r'<h1 class="main-title">([^<]+)</h1>', html)
		code=''
		if t is not None:
			code+='<h1>'+t.group(1)+'</h1>\n'
		code+=b.group(1)
		return code

	@staticmethod
	def parse_frontpage(mainpage):
		p=re.search(\
r'<!-- 新闻中心要闻区 begin -->(.*?)<!-- 新闻中心要闻区 end -->', \
			mainpage, flags=re.S|re.M)
		if p is None:
			# TODO flag as poisoned
			return []
		# only want few items and yaowen supposedly has the relevant ones
		yaowen=p.group(1)
		items=[]
		for hl in re.findall( \
r'href="(https?://news.sina.[^"]+\.[xs]?html)"[^>]*>([^<]{3,300})<', \
		yaowen, flags=re.S|re.M):
			assert type(hl) is tuple
			url=hl[0]
			title=hl[1]
			di=re.sub(r'.*/(.*)\.[a-zA-Z]+$',lambda x: x.group(1),url)
			assert '/' not in di
			assert '.' not in di
			try:
				items+=[{
					'url' : url,
					'title' : title,
					'docid' : di,
				}]
			except KeyboardInterrupt as e:
				raise e
			except:
				pass
		return items

class IndexPage:
	def __init__(self, seq_id, basename):
		title=time.strftime('News %Y-%m-%d')
		self.seq_id=seq_id
		self.sib_url=basename
		self.filepath=the_art_dir(basename)
		self.next=None
		self.prev=None
		self.ns='{http://www.w3.org/1999/xhtml}'
		head_code=cfg['XHTML_HEADER'] + make_head_tag() + \
'<title>' + title + '''</title>
<meta name="description" content="News, no scripts"/>
<meta name="robots" content="index,follow"/>
</head><body id="subIdx">
''' + self.nav() + '''
<div class="main-content"></div>
''' + self.nav() + '''
<br/><br/><br/>
</body></html>'''
		self.et=ET.ElementTree(ET.fromstring(head_code))
		self.load()
		self.body=self.find2(self.et, ".//body")
		self.modified=False
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
		return len(self.article_container())
	
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
		org=c[:]
		c[:]=sorted(c[:], key=lambda x: self._date_of(x), reverse=True)
		if c[:] != org:
			self.modified=True

	def has(self, url):
		a=self.body.find(".//div[@class='article-ref']//a[@class='local'][@href='"+url+"']")
		b=self.body.find(".//"+self.ns+"div[@class='article-ref']//"+self.ns+"a[@class='local'][@href='"+url+"']")
		return (a is not None) or (b is not None)
	
	def store(self, art):
		if self.has(art.idx_url):
			return False
		self.modified=True
		code=\
'<div class="article-ref">\n' +\
'<a class="local" href="'+art.idx_url+'">\n' +\
'<h2 class="title">' + htmlspecialchars(art.title) + '</h2>\n' +\
'<p class="desc">' + htmlspecialchars(art.desc) + '</p>\n' +\
'</a>\n' +\
'<span class="date">'+ time.strftime('%Y-%m-%d %H:%M:%S',art.date)+ '</span>\n' +\
'<a class="origin" href="'+art.src_url+'">Source: '+htmlspecialchars(art.origin)+'</a>\n'+\
'</div>'
		a=ET.fromstring(code)
		self.article_container().insert(0,a)
		print('Index page appended',self.filepath,'(%d)'%self.count())
		return True
	
	def set_ref(self, c, url):
		aa=self.body.findall(".//a[@class='"+c+"']")
		aa+=self.body.findall(".//"+self.ns+"a[@class='"+c+"']")
		for a in aa:
			if a.attrib['href'] != url:
				a.attrib['href'] = url
				self.modified=True
	
	def write_xhtml(self, f):
		f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n')
		self.et.write(f, encoding=['unicode','utf-8'][PYTHON2], \
			xml_declaration=False)
	
	def save(self, out_file, sqc):
		if self.count() < 1:
			print('empty index page. not saving')
			return False
		self.sort()
		if (not cfg.get('REBUILD_HTML',False)) \
		and (not self.modified) \
		and have_html_files(self.filepath):
			print("page wasn't modified. not saving")
			return False
		if self.count()>0: # get_date_str fail if count==0
			i=self.seq_id
			d=self.get_date_str()
			sqc.execute('UPDATE indexes SET date = ? WHERE id = ?', (d,i))
		if self.prev is not None:
			print(self.filepath+': previous page = ', self.prev.filepath)
			self.prev.set_ref('next',self.sib_url if self.is_full() else '#')
			self.set_ref('prev',self.prev.sib_url)
		self.write_xhtml(out_file)
		return True

class Indexer:
	def __init__(self):
		sq_path=the_art_dir('zh-news.db')
		make_dir(os.path.dirname(sq_path))
		self.sq = sqlite3.connect(sq_path)
		self.sq.text_factory = str #utf hack
		self.sqc = self.sq.cursor()
		if cfg.get('REBUILD_HTML',False):
			self.sqc.execute('DROP TABLE IF EXISTS articles')
			self.sqc.execute('DROP TABLE IF EXISTS indexes')
		self.sqc.execute( \
'CREATE TABLE IF NOT EXISTS articles \
(date TEXT, title TEXT, desc TEXT, html_path TEXT, src_url TEXT UNIQUE, origin TEXT, idx_fn TEXT)')
		self.sqc.execute( \
'CREATE TABLE IF NOT EXISTS indexes \
(id INTEGER PRIMARY KEY, date TEXT, html_path TEXT UNIQUE)')
		atexit.register(self.done_sq)
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
		# new files are renamed and moved over old files at the end
		self.renames = []
	
	def last_full_page(self):
		p=self.page
		if p.prev is not None and not p.is_full():
			p=p.prev
		return p
	
	def total_count(self):
		q=self.sqc.execute('SELECT DISTINCT html_path FROM articles')
		rows=q.fetchall()
		if rows is None:
			return 0
		n=0
		for r in rows:
			p=the_art_dir(r[0])
			if (os.path.exists(p) or os.path.exists(p+'.gz')) \
			and not (os.path.exists(p+'.skip')):
				n+=1
		return n
	
	def has_url(self, u):
		return self.sqc.execute('SELECT EXISTS(SELECT 1 FROM articles WHERE src_url = ? LIMIT 1)', (u,)).fetchone()[0] == 1

	def write_html_files(self, path, func):
		if (not cfg['SAVE_HTML']) or (not cfg['SAVE_HTML_GZ']):
			return False
		io = StringIO()
		if func(io) is False:
			io.close()
			return False
		content = B(io.getvalue())
		io.close()
		path_wip = path + '.wip'
		path_gz = path + '.gz'
		path_gz_wip = path + '.gz.wip'
		print('Write:', path+'[.gz].wip')
		if cfg['SAVE_HTML']:
			self.renames += [(path_wip, path)]
			with open(path_wip,'wb') as f: f.write(content);
		if cfg['SAVE_HTML_GZ']:
			self.renames += [(path_gz_wip, path_gz)]
			with gzip.open(path_gz_wip,'wb') as f: f.write(content);
		return True
	
	def write_master_index_(self, f):
		f.write(cfg['XHTML_HEADER'])
		f.write(make_head_tag())
		f.write('''<title>News, no scripts</title>
<meta name="description" content="News, no scripts"/>
<meta name="robots" content="index,follow"/>
</head><body id="mainIdx">
''')
		f.write('<a class="recent bling" href="'\
+cfg['LAST_PAGE_ALIAS']+'">&gt;&gt;&gt; Enter &lt;&lt;&lt;</a><br/>\n')
		f.write('<div class="main-content">')
		f.write(S(u'''<div class="introd">
<div lang="en">
<h1>About</h1>
<p>Hey. I study chinese. I read their news. But chinese websites and apps put a heavy burden on phone's battery. That's why I made this service. Here you can read chinese news served fast from Europe. No javascript, no ads, just news.</p>
</div>
<div lang="zh">
<h1>介绍</h1>
<p>你好。我是一个喜欢学中文的芬兰人，我经常看中国的新闻。但是从欧洲打开中国的网站很慢，而且它们运行的javascript让我手机掉电特别快。为了解决这个问题，我创建了这个网站。它简单的让大家看中国网站的新闻，但是在欧洲的读者会有更通畅的使用体验。</p>
</div>
<a href="https://github.com/sinf/noscript163">Github project page</a>
'''))
		if 'FEEDBACK_ADDR' in cfg:
			f.write('<a id="feedback"></a>\n')
			f.write("""<script>
/* I know. But just 3 lines for basic anti-spam */
var fbm=document.getElementById('feedback');
fbm.innerText='Send me feedback';
fbm.href=atob('""")
			f.write(b64encode(cfg['FEEDBACK_ADDR']).strip())
			f.write("');\n</script>\n")
		f.write('</div>\n') #end .introd
		f.write('<div class="all"><h1>Archive</h1>\n')
		f.write('<h2>Total articles: '+str(self.total_count())+'</h2>\n')
		s = self.sqc.execute( \
'SELECT * FROM indexes ORDER BY date DESC;')
		rows = s.fetchall()
		if rows is not None and len(rows)>0:
			date = None
			for i,d,html_path in sorted(rows, key=lambda r:r[1][:10], reverse=True):
				d=d[:10] # YYYY-MM-DD; drop the rest
				if d != date:
					if date is not None:
						f.write('</div>')
					date=d
					f.write('<div class="d"><div class="date">'+d+'</div>\n')
				f.write('<a href="'+html_path+'">')
				f.write(str(i))
				f.write('</a>\n')
			f.write('</div>')
		else:
			f.write('No articles yet\n')
		f.write('</div></div></body></html>\n')
	
	def write_master_index(self):
		p=the_art_dir(cfg['MASTER_INDEX'])
		return \
			self.write_html_files(p, lambda f: self.write_master_index_(f))
	
	def write_index_page(self):
		p1=self.page
		ok=self.write_html_files(p1.filepath, lambda f: p1.save(f, self.sqc))
		if ok:
			# update previous page because the navbutton needs a new link
			p0=p1.prev
			if p0 is not None:
				self.write_html_files(p0.filepath,lambda f: p0.save(f,self.sqc))
		return ok
	
	def write_article(self, art):
		return \
			self.write_html_files(art.dstpath, lambda f: art.write_html(f))
	
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
		if self.page.count() >= cfg['INDEX_BATCH']:
			self.write_index_page()
			self.new_page()
		try:
			self.sqc.execute('INSERT INTO articles VALUES (?,?,?,?,?,?)', (
				time.strftime('%Y-%m-%d %H:%M:%S',art.date),
				art.title,
				art.desc,
				art.idx_url,
				art.src_url,
				art.origin,
			))
		except sqlite3.IntegrityError as e:
			traceback.print_exc()
			print('src_url:', art.src_url)
			print('html_path:', art.dstpath)
			print('checking other records..')
			rows=self.sqc.execute('SELECT * FROM articles WHERE html_path = ?', art.dstpath)
			print(rows.fetchall())
			raise e
		self.page.store(art)
	
	def done_sq(self):
		self.sqc.close()
		self.sq.commit()
		self.sq.close()
	
	def overwrite_files(self):
		print('*** Moving new files over old files')
		for old,new in self.renames:
			if os.path.exists(old):
				bak=new+'.bak'
				if os.path.exists(bak): os.remove(bak) ;
				if os.path.exists(new): os.rename(new,bak) ;
				os.rename(old,new)
				print(old,'=>',new)
	
	def done(self):
		self.write_index_page()
		self.sq.commit()
		self.write_master_index()
		self.overwrite_files()
	
	def article_back_ref(self):
		return '../' + self.page.sib_url

def get_mainpages(url, cache_prefix, args):
	if cfg.get('REBUILD_HTML',False):
		# If rebuilding, skip download. Read all available old cached files
		d_in=the_art_dir('in')
		for src_bn in os.listdir(d_in):
			src_path=os.path.join(d_in, src_bn)
			ok=True
			if len(args.mainpage)>0:
				ok=False
				for p in args.mainpage:
					if os.path.basename(p)==src_bn:
						ok=True
						break
			if ok and src_bn.startswith(cache_prefix):
				print('Read front page:', src_path)
				opn=gzip.open if src_bn.endswith('.gz') else open
				with opn(src_path,'rb') as f:
					frontpage=f.read()
				yield frontpage
			# else: some other news source deals with the file
	else:
		# Update. Download the frontpage once and store to file
		p=the_art_dir('in/'+time.strftime( \
			cache_prefix + '-%Y-%m-%d-%H.html'))
		frontpage = S(cached_gz(p, lambda u=url:GET(u)))
		yield frontpage

def parse_date_ymdhms(x):
	return time.strptime(S(x),'%Y-%m-%d %H:%M:%S')

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
	ap.add_argument('-A', '--rebuild-after', nargs=1, type=lambda s: time.strptime(s, '%Y-%m-%d/%H:%M'), default=None)
	ap.add_argument('-I', '--rebuild-index-only', action='store_true',help="Skip rebuilding articles")
	ap.add_argument('-M', '--rebuild-mainpage', action='store_true',help='Rebuild main page and quit')
	ap.add_argument('-C', '--check-images', action='store_true')
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
	if args.rebuild_after: cfg['REBUILD_AFTER']=args.rebuild_after

	T_START=time.time()
	print('My PID is', os.getpid())
	if 'PID_FILE' in cfg:
		if os.path.exists(cfg['PID_FILE']):
			print('Another process maybe running, aborting')
			print('If not, delete', cfg['PID_FILE'], 'and try again')
			return
		try:
			with open(cfg['PID_FILE'],'w') as f:
				f.write(str(os.getpid()))
			atexit.register(lambda: try_remove(cfg['PID_FILE']))
		except:
			print('!! Failed to write', cfg['PID_FILE'])
			del cfg['PID_FILE']
	
	os.nice(19) # be nice
	os.environ['PATH'] = cfg.get('PATH_PREPEND','') + os.environ['PATH']

	if args.fuck_it:
		cfg['NICE']=False
	
	ET.register_namespace('','http://www.w3.org/1999/xhtml')
	items = []

	idx = Indexer()
	if args.rebuild_mainpage:
		idx.write_master_index()
		idx.overwrite_files()
		return
	
	sources = [
		('GET_163', Article163),
		('GET_CCTV', ArticleCCTV),
		('GET_SINA', ArticleSina),
	]
	for enb_key, cl in sources:
		if not cfg.get(enb_key,True):
			continue
		for page_content in get_mainpages(\
		cl.frontpage_url, cl.frontpage_file_prefix, args):
			try:
				tmp = cl.parse_frontpage(page_content)
				if tmp is None:
					continue
				for it in tmp:
					assert 'url' in it
					assert 'docid' in it
					it['article_class_py_'] = cl
					if 'article_date_py_' not in it:
						it['article_date_py_'] = HEAD_date(it['url'])
				tmp = n_most_recent(tmp, int(cfg.get('MAX_DL',50)))
				items += tmp
			except AssertionError as e:
				traceback.print_exc()
				print('class', str(cl))
				return
			except KeyboardInterrupt:
				return
			except KillSwitchEx:
				return
			except (URLError, InvalidURL, ValueError) as ex:
				traceback.print_exc()
				print('Failed to get source', cl.origin)

	rebuild_index_only = args.rebuild_index_only
	revisit_html = args.rebuild_html or args.rebuild_images

	article_whitelist=None
	if len(args.articles)>0:
		article_whitelist=set(x.lower() for x in args.articles)
	
	items = n_most_recent(items, -1)

	print('Processing articles... (%d)' % len(items))
	for item in items:
		cl_init=item['article_class_py_']
		art=cl_init(item)

		if idx.has_url(art.src_url):
			continue

		if article_whitelist is not None:
			# if specific paths were listed in command line
			# check if article matches any. skip otherwise
			no_suf_bn=suffix_split(art.src_url.lower().split('/')[-1])[0]
			if no_suf_bn not in article_whitelist:
				continue

		# n_most_recent sets __skipDL for items that should be ignored
		# so after changing MAX_DL:
		# items that were already downloaded can be rebuilt
		# but new extra items won't be downloaded.
		if item.get('__skipDL',False) and not art.have_src_page():
			continue

		print(art.src_url)

		if check_ext(art.src_url, ('.shtml', '.html','.xhtml','.cgi','.php')):
			if (revisit_html or not art.exists()) \
			and not art.is_poisoned():
				print('Process:',art.src_url)
				try:
					check_kill_switch()
					art.fetch()
					art.back_url = idx.article_back_ref()
					if args.check_images is True:
						with open('/dev/null','w') as f:
							art.write_html(f)
					else:
						if rebuild_index_only or idx.write_article(art):
							idx.put(art)
					be_nice(2)
				except KeyboardInterrupt as e:
					raise e
				except KillSwitchEx:
					break
				except (URLError, InvalidURL, ValueError) as ex:
					traceback.print_exc()
					# continue

		try:
			check_kill_switch()
		except KillSwitchEx:
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
	except KeyboardInterrupt:
		pass
	except KillSwitchEx:
		print('Aborted because PID file was removed')


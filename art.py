#!/usr/bin/env python2.7
#-*- encoding: utf-8 -*-
from __future__ import print_function

# Chinese article aggregator script
# generates a tree of documents and images

cfg={
# local filesystem path where things are stored
	'WEB_ROOT':'.',

# filename (under WEB_ROOT/ARTICLES/)
# of a hardlink to the most recent index page
	'LAST_PAGE_ALIAS':'last.xhtml',

# contains links to index pages
	'MASTER_INDEX':'main.xhtml',

#	relative to WEB_ROOT
# index files are called WEB_ROOT/ARTICLES/idx%d.html
# and articles:
# WEB_ROOT/ARTICLES/YYYY-MM/(*.xhtml,*.webp)
	'ARTICLES':'zh-news',

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
}

import urllib2
import re
import json
import os
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
		time.sleep(10)

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
	m=re.search(r, html, re.M|re.I|re.U)
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
		cmd=cfg['CPULIMIT']+' -q -l 5 -- '+cmd
	print(cmd)
	os.system(cmd)
	be_nice()

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
		""" item needs to have
		link : url to some .html file
		ptime_py : python datetime
		title or docid (optional)
		digest (optional)
		"""
		self.setup(item)
		assert type(self.docid) is str
		assert type(self.src_url) is str
		assert type(self.title) is str
		assert type(self.desc) is str
		assert type(self.origin) is str

		self.date=item['ptime_py_']
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
	
	def shrink_img(self, src):
		""" Accepts a source URL. Downloads the image, recompresses to webp, saves. Teturns url for a local document """
		if should_terminate():
			raise ImportError('program kill switch')
		if 'javascript:' in src:
			print('rejecting javascript img hack:', src)
			return None
		bn=os.path.basename(src)
		no_suf=re.sub(r'(\..{1,5})$','',bn)
		if not check_ext(bn,('.jpg','.jpeg','.gif','.png','.webp')):
			print('rejecting image because of unknown suffix:', bn[-4:])
			return None
		org=os.path.join(self.dstdir, 'img0', bn)
		dst=os.path.join(self.dstdir, 'img', no_suf+'.webp')
		url=os.path.join('img', no_suf+'.webp')
		rebuild=cfg.get('REBUILD_IMAGES',False)
		if not os.path.exists(dst) or rebuild:
			make_dir(os.path.dirname(dst))
			try:
				cached(org, lambda: GET(src))
			except:
				print('FAILED to get image:', src)
				return None
			shell_cmd(cfg['CONVERT']+' '+org+" -fuzz 1% -trim +repage -resize '500000@>' -quality 30 "+dst)
			if not cfg['SAVE_IMG_SRC']:
				try_remove(org)
			if cfg['SAVE_IMG_INFO']:
				with open(org+'.txt','w') as f:
					f.write(src+'\n')
			print('Write image', dst)
		fallback=os.path.join(self.dstdir, 'img', no_suf+'.jpg')
		if os.path.exists(dst) and (rebuild or not os.path.exists(fallback)):
			# make a fallback JPG. save CPU: downscale the already downscaled image
			shell_cmd(cfg['CONVERT']+' '+dst+" -fuzz 1% -trim +repage -resize '200000@>' -quality 40 "+fallback)
		return url
	
	def filter_img163(self, attr, cl):
		""" Reformat <img ...attr...> tag
		attr: string (xx="yy" zz="ww" ...)
		cl: string (class="blabhblah ...")
		"""
		ds=re.search(r'data-src="([^"]+)"', attr)
		ds=ds if ds is not None else re.search(r'src="([^"]+)"', attr)
		if ds is None or 'javascript:' in ds.group(1).lower():
			#print('dropping weird img:', whole)
			return '<!-- IMG REMOVED -->'
		src_url=ds.group(1)
		url=self.shrink_img(src_url)
		if url is None:
			return '<!-- FAILED IMG CONVERSION, IMG REMOVED -->'
		alt=re.search(r'alt="([^"]+)"', attr)
		alt='' if alt is None else ' '+alt.group(0)
		return str('\n<object' + cl + ' type="image/webp"' + ' data="' + url \
			+ '"><img' + cl + alt + ' src="' + url[:-4] + 'jpg"/></object>\n')
	
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
	
	def fetch(self):
		make_dir(self.dstdir)
		self.src_html=cached_gz(self.dstpath+'.in', \
			lambda:GET(self.src_url))
	
	def is_poisoned(self):
		return os.path.exists(self.dstpath+'.skip')
	
	def mark_poisoned(self):
		open(self.dstpath+'.skip','w').close()
	
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
		body=re.sub(r'<script>.*?</script>',noscript,body,flags=re.S|re.U|re.M)
		body=re.sub(r'<\s*script.*?>.*?</\s*script\s*>',noscript,body,flags=re.S|re.U|re.M)
		body=re.sub(r'<\s*script.*?/>',noscript,body,flags=re.S|re.U|re.M)
		body=re.sub(r'<\s*script.*',noscript,body,flags=re.S|re.U|re.M)

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
		body=re.sub('<a>(.*?)</a>',lambda x: x.group(1), body, flags=re.S)
		body=re.sub('<span>\s*</span>','', body, flags=re.M)
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

class Article163(Article):

	def setup(self, item):
		self.docid=S(item['docid'])
		self.src_url = discard_url_params(S(item['link']))
		self.title=S(item.get('title',self.docid))
		# digest: truncated description
		self.desc=S(item.get('digest','no description'))
		self.origin=S(u'3g.163.com 手机网易网')
	
	def scan_article_content(self, html):
		""" Works for 163 """

		# dig out the article
		m=re.search(r'<article[^>]*>(.*)</article>', html, re.I|re.S)
		if m is None:
			print('failed to get article', self.docid)
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
		pass
	def scan_article_content(self, html):
		pass

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
<meta name="author" content="ArhoM"/>
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
<li><a href="'''+cfg['MASTER_INDEX']+'''">Index</a></li>
<li><a href="'''+cfg['LAST_PAGE_ALIAS']+'''">Most recent</a></li>
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
	
	def write_master_index_(self, f):
		f.write(cfg['HEAD_INDEX'])
		f.write('''<title>News, no scripts</title>
<meta name="author" content="ArhoM"/>
<meta name="description" content="News, no scripts"/>
</head><body id="mainIdx">
''')
		f.write('<a class="recent" href="'\
+cfg['LAST_PAGE_ALIAS']+'">&gt;&gt;&gt; Enter &lt;&lt;&lt;</a><br/>\n')
		f.write(u'''<div class="introd"><div lang="en">
<h1>About</h1>
<p>To improve my chinese I read chinese news. But news apps and websites suck! They drain battery with ads, have long latency and random junk, track the user and have broken HTTPS. This service solves those problems. It downloads news each day and reformats them into static HTML without javascript. Images are compressed to 5% of the original size. So far it only supports one site, 163.com. I will add more later.</p>
</div>
<div lang="zh">
<h1>介绍</h1>
<p>为了提高我的中文，我会偶尔看看中国的新闻网站。可是你们网站太慢了。装满了那么多javascript垃圾我手机的电池要着火了！服务器遥远，有广告，有跟踪曲奇，有长城，https有毛病。为了解决这些问题，我编程了这个服务。它每天几次下载新闻，移除script垃圾，把单纯的文章写成简单不变的html。它把图片数据微缩到5%的大小。在欧洲看我的网页应该比原来的网页快很多。目前只有一个新闻来源，163.com。你如果觉得这服务有用，可以给我建议接下来加什么来源。</p>
</div></div>
'''.encode('utf-8'))
		f.write('<div class="all"><h1>Archive</h1>\n')
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

def main():

	ap=argparse.ArgumentParser()
	ap.add_argument('-m', '--mainpage', nargs=1, default=[])
	ap.add_argument('-f', '--fuck-it', action='store_true')
	ap.add_argument('-c', '--conf', nargs=1, default=[None])
	ap.add_argument('-r', '--rebuild-html', action='store_true')
	ap.add_argument('-R', '--rebuild-images', action='store_true')
	ap.add_argument('-I', '--rebuild-index-only', action='store_true')
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
		except:
			print('!! Failed to write', cfg['PID_FILE'])
			del cfg['PID_FILE']
	
	os.nice(19) # be nice
	os.environ['PATH'] = '/home4/wlmrnkbl/bin:' + os.environ['PATH']

	if args.fuck_it:
		cfg['NICE']=False
	
	ET.register_namespace('','http://www.w3.org/1999/xhtml')

	if len(args.mainpage)>0:
		print('Using', args.mainpage[0], 'as the front page')
		opn=open
		if args.mainpage[0].endswith('.gz'):
			opn=gzip.open
		with opn(args.mainpage[0],'rb') as f:
			frontpage=f.read()
	else:
		fp_url='https://3g.163.com/touch/news/'
		fp_cache=the_art_dir(time.strftime('news_163-%Y-%m-%d-%H.html'))
		frontpage = cached_gz(fp_cache, lambda u=fp_url:GET(u))
	
	# regex error: frontpage was accidentally .gz (mislabeled file extension)

	# Fetch single-line json array from front page
	# difference between topicData and channelData?
	#topicData = scanJ(frontpage, r'^\s*var\s+topicData\s*=\s*({.*});$')
	chanData = scanJ(frontpage, r'^\s*var\s+channelData\s*=\s*({.*});$')
	items=[]

	items+=chanData['listdata']['data']

	for xx in chanData['topdata']['data']:
		assert type(xx) is dict
		items+=[xx]

	idx = Indexer()
	sq = idx.sq

	rebuild_index_only=\
		cfg.get('REBUILD_HTML',False) \
		and args.rebuild_index_only

	for item in items:
		assert type(item) is dict
		if False:
			print()
			for z in 'ptime','title','digest','link','type','docid', 'category', 'channel':
				print(z,item.get(z,None))

		item['ptime_py_'] = time.strptime(item['ptime'],'%Y-%m-%d %H:%M:%S')
		link=item['link']

		if check_ext(link, ('.html','.xhtml','.cgi','.php')):
			art=Article163(item)
			if should_terminate():
				break
			if not art.exists() and not art.is_poisoned():
				print('Process:',link)
				art.fetch()
				art.back_url = idx.article_back_ref()
				if rebuild_index_only or art.write_html():
					idx.put(art)
				be_nice()

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


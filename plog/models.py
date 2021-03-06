__all__ = ('Comment', 'Commenter', 'CommentForm', 'Post', 'PostForm', 'TagCloud', 'UploadsForm')

from datetime import datetime
from HTMLParser import HTMLParser
import re
from pytz import timezone, utc

from flask import request
from gridfs import GridFS
from mongoengine import *

import wtforms
from wtforms import validators

from plog import app, db
from plog.utils import randstring

uploads = GridFS(db)

boundary = re.compile(r'\s')
nopunc = re.compile(r'[^a-z0-9]')

class TagCloud(Document):
    tag = StringField(primary_key=True)
    count = IntField()
    updated = DateTimeField()

    meta = {
        'allow_inheritance': False,
        'indexes': [
            {'fields': ['count', 'tag']},
        ],
    }

    @staticmethod
    def get(sizes=6):
        tags = [t for t in TagCloud.objects(count__gt=0).order_by('tag')]
        if tags == []:
            return tags

        least = min(t.count for t in tags)
        most = max(t.count for t in tags)
        range = max(most - least, 1)
        scale = float(min(range, sizes))
        for t in tags:
            t.bucket = sizes - int(round(scale * (t.count - least) / range))
            t.bucket = max(1, min(t.bucket, sizes))

        return tags


class Commenter(Document):
    cookie = StringField(primary_key=True)
    author = StringField()
    email = StringField()

    meta = {'allow_inheritance': False}

    def __init__(self, *args, **kwargs):
        super(Commenter, self).__init__(*args, **kwargs)
        if self.cookie is None:
            self.cookie = randstring()
        self.when = datetime.utcnow()

class Comment(EmbeddedDocument):
    author = StringField(required=True)
    email = StringField(required=True)
    body = StringField(required=True)
    approved = BooleanField()
    when = DateTimeField()

    meta = {'allow_inheritance': False}

    def __init__(self, *args, **kwargs):
        super(Comment, self).__init__(*args, **kwargs)
        if self.when is None:
            self.when = datetime.utcnow()

class Post(Document):
    pubdate = DateTimeField(required=True)
    updated = DateTimeField()
    published = BooleanField(default=True)

    title = StringField(required=True)
    slug = StringField(required=True, unique=True)

    blurb = StringField(required=True)
    body = StringField(required=False)

    tags = ListField(StringField())

    comments = ListField(EmbeddedDocumentField(Comment))

    _words = ListField(StringField())

    meta = {
        'allow_inheritance': False,
        'indexes': [
            {'fields': ['published', '_words', 'pubdate']},
            {'fields': ['published', 'slug', 'pubdate']},
        ],
    }

    def __init__(self, *args, **kwargs):
        super(Post, self).__init__(*args, **kwargs)

        # perform timezone conversion to UTC;
        # if datetime fields don't have a timezone,
        # assume they are in site_tz's timezone
        site_tz = timezone(app.config.get('TIMEZONE', 'US/Eastern'))
        if self.pubdate is not None and self.pubdate.tzinfo is None:
            self.pubdate = self.pubdate.replace(tzinfo=utc).astimezone(site_tz)

    def save(self, set_updated=True):
        words = set(boundary.split(self.title.lower()))
        words.update(boundary.split(self.blurb.lower()))
        words.update(boundary.split(self.body.lower()))
        words = set(nopunc.sub('', word) for word in words)
        self._words = list(words)

        # perform timezone conversion to UTC;
        # if datetime fields don't have a timezone,
        # assume they are in site_tz's timezone
        site_tz = timezone(app.config.get('TIMEZONE', 'US/Eastern'))

        # pubdate is required
        if self.pubdate.tzinfo is None:
            self.pubdate = site_tz.localize(self.pubdate)
        self.pubdate = self.pubdate.astimezone(utc).replace(tzinfo=None)

        if set_updated:
            self.updated = datetime.utcnow()
        super(Post, self).save()

class CommaListField(wtforms.TextField):

    def _value(self):
        if self.data:
            return ', '.join(self.data)
        else:
            return ''

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = [x.strip() for x in valuelist[0].split(',')]
            self.data = [x for x in self.data if x != '']
        else:
            self.data = []

class PostForm(wtforms.Form):
    title = wtforms.TextField(label='Title', validators=[validators.Required()])
    slug = wtforms.TextField(label='Slug')

    tags = CommaListField()

    pubdate = wtforms.DateTimeField(label='Date', format='%Y-%m-%d %H:%M')
    published = wtforms.BooleanField(label='Published', default=False)
    blurb = wtforms.TextAreaField(label='Blurb', validators=[validators.Required()])
    body = wtforms.TextAreaField(label='Body')

    @property
    def known_tags(self):
        return [t.tag for t in TagCloud.objects.order_by('tag').only('tag')]

    def images_to_add(self):
        newuploads = re.findall(r'\[[^\]]+\]\(([^\)]+)\)', self.blurb.data)
        newuploads.extend(re.findall(r'\[[^\]]+\]\(([^\)]+)\)', self.body.data))

        newuploads = [u[len('/uploads/'):] for u in newuploads if u.startswith('/uploads/')]

        return set(newuploads) - set(uploads.list())

class UploadForm(wtforms.Form):
    filename = wtforms.HiddenField()
    file = wtforms.FileField()

class UploadsForm(wtforms.Form):
    enctype = ' enctype="multipart/form-data"'
    uploads = wtforms.FieldList(wtforms.FormField(UploadForm))

    def __init__(self, images=None, *args, **kwargs):
        super(UploadsForm, self).__init__(*args, **kwargs)

        if not kwargs.get('formdata'):
            for image in images or []:
                self.uploads.append_entry({'filename': image})

        for filename, field in zip(images, self.uploads):
            field.label = filename
            field.file.label = ''


class NoHTML(object):
    """Validator that uses :func:`~jinja2.escape` to ensure that no HTML
    is permitted in the field's value.
    """

    class HTMLChecker(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.passed = True
        def handle_starttag(self, tags, attrs):
            self.passed = False
        def handle_endtag(self, tags):
            self.passed = False
        @classmethod
        def check(cls, html_string):
            h = cls()
            h.feed(html_string)
            return h.passed

    def __call__(self, form, field):
        if not isinstance(field.data, (str, unicode)):
            return
        if not self.HTMLChecker.check(unicode(field.data)):
            raise validators.ValidationError('HTML is not permitted')

class CommentForm(wtforms.Form):
    author = wtforms.TextField(label='Your Name', validators=[validators.Required(), NoHTML()])
    email = wtforms.TextField(
        label='Email',
        validators=[validators.Required(), validators.Email()],
        description='Never displayed')
    body = wtforms.TextAreaField(
        description='No HTML, but feel free to use <a href="http://daringfireball.net/projects/markdown/">Markdown</a>',
        validators=[validators.Required(), NoHTML()])

    def __init__(self, formdata=None, *args, **kwargs):
        super(CommentForm, self).__init__(formdata, *args, **kwargs)

        self.commenter = None
        if 'plogcmt' in request.cookies:
            self.commenter = Commenter.objects(cookie=request.cookies['plogcmt']).first()
            if self.commenter and formdata is None:
                del self.email
                self.author.data = self.commenter.author

    def validate(self):
        if self.commenter:
            self.email.data = self.commenter.email

        return super(CommentForm, self).validate()

